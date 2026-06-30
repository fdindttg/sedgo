import requests
import time
import logging
import hmac
import hashlib
import json
import os
import tempfile
import traceback
import subprocess
import threading
import base64
import mimetypes
import pathlib
import shutil
from datetime import datetime
from sqlalchemy.orm import Session
from database import (
    Channel, Endpoint, EndpointType, TaskRecord, TaskStatus, BatchTask, PointsRecord, PointsType,
    VideoSegment, VideoComposition
)
from services.point_service import (
    calculate_tokens_cost, calculate_points_cost,
    consume_points, earn_points, get_active_config
)
from services.subscription_service import get_active_subscription
from services.auth_service import decrypt_value
from services.concurrency_service import (
    acquire_concurrency_token, release_concurrency_token,
    check_concurrency_limit, ConcurrencyLimitError
)
from config import PUBLIC_BASE_URL
from services.error_utils import translate_error, is_real_person_error

# Seedance单段视频最大时长（秒）
# 根据 BytePlus 文档：
# - 2.0 版本最长单个时长是 15 秒
# - 1.5 和 1.0 版本最长单个时长是 12 秒
SEEDANCE_2_0_MAX_DURATION = 15
SEEDANCE_1_X_MAX_DURATION = 15

# 支持真人素材（r2v）功能的模型列表
R2V_SUPPORTED_MODELS = {
    'dreamina-seedance-2-0-260128',
    'dreamina-seedance-2-0-20128',
    'dreamina-seedance-2-0-fast',
}

def get_model_max_duration(model: str) -> int:
    """根据模型名称判断最大单段时长
    
    Args:
        model: 模型名称，如 'seedance-1.0', 'dreamina-seedance-2-0-fast', 'seedance-1.5' 等
    
    Returns:
        最大单段时长（秒）
    """
    if not model:
        return SEEDANCE_1_X_MAX_DURATION
    
    model_lower = model.lower()
    
    # 2.0 版本模型
    if '2.0' in model_lower or 'seedance2' in model_lower or 'dreamina-seedance-2' in model_lower:
        return SEEDANCE_2_0_MAX_DURATION
    
    # 1.5 和 1.0 版本模型（默认）
    return SEEDANCE_1_X_MAX_DURATION

def is_r2v_supported(model: str | list) -> bool:
    """检查模型是否支持真人转视频（r2v）功能
    
    Args:
        model: 模型名称、接入点ID、模型列表（list）或 JSON 字符串
    
    Returns:
        True 如果模型支持 r2v，False 否则
    """
    if not model:
        logger.info(f"[DEBUG] is_r2v_supported: model is empty")
        return False
    
    logger.info(f"[DEBUG] is_r2v_supported: input model='{model}', type={type(model)}")
    
    # 如果是字符串，尝试解析为 JSON 列表
    if isinstance(model, str):
        try:
            import json
            parsed = json.loads(model)
            if isinstance(parsed, list):
                logger.info(f"[DEBUG] is_r2v_supported: parsed JSON to list: {parsed}")
                return is_r2v_supported(parsed)
        except (json.JSONDecodeError, TypeError) as e:
            logger.info(f"[DEBUG] is_r2v_supported: not valid JSON, error={e}")
            # 不是 JSON，继续作为字符串处理
            pass
    
    # 如果是列表，检查列表中的任何模型是否支持 r2v
    if isinstance(model, list):
        logger.info(f"[DEBUG] is_r2v_supported: checking list of {len(model)} models")
        for m in model:
            logger.info(f"[DEBUG] is_r2v_supported: checking model '{m}' in list")
            if is_r2v_supported(m):
                return True
        logger.info(f"[DEBUG] is_r2v_supported: no supported model found in list")
        return False
    
    model_lower = str(model).lower()
    logger.info(f"[DEBUG] is_r2v_supported: checking single model '{model_lower}'")
    
    # 检查是否在支持列表中
    for supported_model in R2V_SUPPORTED_MODELS:
        if supported_model.lower() in model_lower or model_lower in supported_model.lower():
            logger.info(f"[DEBUG] is_r2v_supported: matched supported model '{supported_model}'")
            return True
    
    # 检查是否是 2.0 版本模型（通常支持 r2v）
    if '2.0' in model_lower or 'seedance2' in model_lower or 'dreamina-seedance-2' in model_lower:
        logger.info(f"[DEBUG] is_r2v_supported: matched 2.0 version pattern")
        return True
    
    # 检查是否是 real_human/portrait/real_people 模型（专门支持真人素材）
    if 'real_human' in model_lower or 'portrait' in model_lower or 'real_people' in model_lower:
        logger.info(f"[DEBUG] is_r2v_supported: matched real people model pattern")
        return True
    
    logger.info(f"[DEBUG] is_r2v_supported: no match found, returning False")
    return False

logger = logging.getLogger(__name__)


def _resolve_media_url(url: str) -> str:
    """Convert local /static/uploads/ paths to base64 data URLs for BytePlus API."""
    if not url or not url.startswith("/static/uploads/"):
        return url
    local_path = pathlib.Path(url.lstrip("/"))
    if not local_path.exists():
        return url
    mime = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    data = base64.b64encode(local_path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"

def _trim_audio(audio_path: str, target_duration: float) -> str | None:
    """用 ffmpeg 将音频裁剪到 target_duration 秒，返回裁剪后的文件路径，失败返回 None"""
    ffmpeg = _get_ffmpeg_exe()
    src = pathlib.Path(audio_path)
    trimmed = src.parent / f"trimmed_{src.stem}.mp3"
    try:
        cmd = [
            ffmpeg, "-y", "-i", str(src),
            "-t", str(round(target_duration, 2)),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(trimmed),
        ]
        result_sub = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result_sub.returncode == 0 and trimmed.exists():
            logger.info(f"[trim_audio] {src.name} trimmed from {_get_video_duration(str(src)):.1f}s to {target_duration}s")
            return str(trimmed)
        logger.error(f"[trim_audio] ffmpeg failed: {result_sub.stderr[-300:]}")
        return None
    except Exception as e:
        logger.error(f"[trim_audio] error: {e}")
        return None


def _call_volcengine_api(ak: str, sk: str, action: str, body: dict) -> dict:
    """Call Volcengine Universal API (ark service) with AK/SK signing.
    Falls back to canonical module-level credentials on failure."""
    from routers.asset_library import _call_api as _asset_call_api
    from routers.asset_library import set_asset_credentials as _set_creds
    from volcengine.base.Request import Request
    from volcengine.Credentials import Credentials
    from volcengine.auth.SignerV4 import SignerV4
    _FALLBACK_AK = ""
    _FALLBACK_SK = ""
    use_ak = ak if ak else _FALLBACK_AK
    use_sk = sk if sk else _FALLBACK_SK
    if not use_ak or not use_sk:
        logger.warning(f"[asset] _call_volcengine_api called without valid AK/SK, falling back to module-level credentials")
        return _asset_call_api(action, body)
    body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
    r = Request()
    r.method = "POST"
    r.host = "open.ap-southeast-1.byteplusapi.com"
    r.path = "/"
    r.query = {"Action": action, "Version": "2024-01-01"}
    r.body = body_bytes
    r.headers = {"Host": "open.ap-southeast-1.byteplusapi.com", "Content-Type": "application/json"}
    SignerV4.sign(r, Credentials(use_ak, use_sk, "ark", "ap-southeast-1"))
    resp = requests.post(
        "https://open.ap-southeast-1.byteplusapi.com/",
        headers=r.headers, params=r.query, data=body_bytes, timeout=30
    )
    if not resp.ok:
        logger.warning(f"[asset] API call failed ({resp.status_code}), retrying with fallback credentials: {resp.text[:200]}")
        return _asset_call_api(action, body)
    return resp.json()


def _upload_to_asset_library(local_url: str, api_key: str, ak: str, sk: str,
                              group_id: str, project_name: str, api_base_url: str,
                              public_base_url: str = "",
                              asset_type: str = "Image") -> str | None:
    """Upload a local file (image/video) to BytePlus asset library.

    Flow:
      1. Resolve public URL (via public_base_url, else Files API)
      2. Call CreateAsset (AK/SK) with that URL + group_id → get asset Id
      3. Poll GetAsset until Active
      Returns asset URI string like 'asset://asset-xxx', or None on failure.
    """
    # Ensure module-level asset credentials are set for fallback paths
    from routers.asset_library import set_asset_credentials
    set_asset_credentials(ak, sk)

    # Resolve local path
    local_path = local_url.lstrip("/") if local_url.startswith("/") else local_url
    file_path = pathlib.Path(local_path)

    # 如果本地文件不存在但有 public_base_url，跳过本地检查直接用公网URL
    if not file_path.exists() and not (public_base_url and local_url.startswith("/")):
        logger.warning(f"[asset] File not found: {file_path}")
        return None

    # Auto-create group if none provided (only AIGC type is supported by API)
    if not group_id:
        try:
            g = _call_volcengine_api(ak, sk, "CreateAssetGroup", {
                "Name": "真人肖像默认组",
                "GroupType": "AIGC",
                "ProjectName": project_name,
            })
            group_id = (g.get("Result") or {}).get("Id") or g.get("Id", "")
            if group_id:
                logger.info(f"[asset] Auto-created asset group: {group_id}")
            else:
                logger.error(f"[asset] CreateAssetGroup returned no Id: {g}")
                return None
        except Exception as e:
            try:
                logger.error(f"[asset] CreateAssetGroup error: {e}, response={e.response.text[:500] if hasattr(e, 'response') else 'N/A'}")
            except Exception:
                logger.error(f"[asset] CreateAssetGroup error: {e}")
            return None

    # Step 1: resolve a publicly accessible URL for CreateAsset
    # Prefer Files API upload over public_base_url (direct web URL), since BytePlus server may not be able to access external URLs
    _effective_public_base = public_base_url or PUBLIC_BASE_URL
    
    # Try Files API first
    public_url = None
    try:
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        base = api_base_url.rstrip("/")
        if not base.endswith("/api/v3"):
            base = base + "/api/v3"
        files_url = f"{base}/files"
        with open(file_path, "rb") as f:
            resp = requests.post(
                files_url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (file_path.name, f, mime)},
                data={"purpose": "user_data"},
                timeout=300,
            )
        if resp.status_code == 200:
            file_obj = resp.json()
            public_url = file_obj.get("url") or file_obj.get("data", {}).get("url", "")
            if not public_url:
                file_id = file_obj.get("id") or file_obj.get("file_id")
                if file_id:
                    for poll_i in range(15):
                        time.sleep(2)
                        try:
                            detail_url = f"{files_url}/{file_id}"
                            poll_resp = requests.get(detail_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
                            if poll_resp.status_code == 200:
                                detail = poll_resp.json()
                                st = (detail.get("status") or "").lower()
                                logger.info(f"[asset] Files API poll {poll_i+1}: id={file_id}, status={st}")
                                if st == "ready":
                                    public_url = detail.get("url") or (detail.get("data") or {}).get("url", "")
                                    if public_url:
                                        logger.info(f"[asset] File ready, url={public_url[:120]}...")
                                        break
                                elif st in ("failed", "error"):
                                    logger.error(f"[asset] Files API file {file_id} failed")
                                    break
                        except Exception as poll_err:
                            logger.warning(f"[asset] Files API poll error: {poll_err}")
                if not public_url:
                    logger.error(f"[asset] Files API returned no URL: {json.dumps(file_obj)}")
            else:
                logger.info(f"[asset] File uploaded to Files API, url={public_url[:120]}...")
        else:
            logger.error(f"[asset] Files API upload failed {resp.status_code}: {resp.text[:1000]}")
            public_url = None
    except Exception as e:
        logger.error(f"[asset] Files API upload error: {e}, traceback=traceback.format_exc()")
        public_url = None
    
    # NOTE: Do NOT fall back to public_base_url because BytePlus server cannot access external URLs
    # If Files API failed, return None immediately
    if not public_url:
        logger.error(f"[asset] Files API upload failed and no fallback available for {file_path}")
        return None

    # Step 2: CreateAsset — use the passed-in AK/SK for signing
    try:
        logger.info(f"[asset] CreateAsset: AssetType={asset_type}, URL={public_url[:80]}, GroupId={group_id}")
        result = _call_volcengine_api(ak, sk, "CreateAsset", {
            "GroupId": group_id,
            "URL": public_url,
            "AssetType": asset_type,
            "Name": file_path.name,
            "ProjectName": project_name,
            "Moderation": {
                "Strategy": "Skip"
            },
        })
        asset_id = (result.get("Result") or {}).get("Id") or result.get("Id")
        if not asset_id:
            err = (result.get("Result") or result).get("ResponseMetadata", {}).get("Error", {}) or result.get("ResponseMetadata", {}).get("Error", {})
            logger.error(f"[asset] CreateAsset failed: AssetType={asset_type}, error={err}")
            return None
        logger.info(f"[asset] CreateAsset succeeded: {asset_id}")
    except Exception as e:
        resp_text = e.response.text[:500] if hasattr(e, 'response') else 'N/A'
        logger.error(f"[asset] CreateAsset error: AssetType={asset_type}, error={e}, response={resp_text}")
        return None

    # Step 3: poll GetAsset until Active (max 60s)
    for attempt in range(30):
        time.sleep(2)
        try:
            info = _call_volcengine_api(ak, sk, "GetAsset", {
                "Id": asset_id,
                "ProjectName": project_name,
            })
            status = ((info.get("Result") or info).get("Status") or info.get("Status") or "").lower()
            logger.info(f"[asset] GetAsset {asset_id} status={status} (attempt {attempt+1})")
            if status == "active":
                return f"asset://{asset_id}"
            if status == "failed":
                err_info = (info.get("Result") or info).get("Error", {})
                err_code = err_info.get("Code", "")
                err_msg = err_info.get("Message", "")
                logger.error(f"[asset] Asset {asset_id} failed: {err_code} - {err_msg}")
                raise ValueError(translate_error(err_msg or f"素材处理失败({err_code})"))
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[asset] GetAsset poll error: {e}")

    logger.error(f"[asset] Asset {asset_id} did not become Active within timeout")
    return None



# 轮询计数器（简单的全局轮询实现）
channel_round_robin_counter = 0


def get_active_channels(db: Session) -> list[Channel]:
    """获取所有活跃的渠道列表"""
    return db.query(Channel).filter(Channel.is_active == True).order_by(Channel.priority.desc()).all()


def get_channel_with_round_robin(db: Session) -> Channel | None:
    """使用轮询策略获取下一个渠道"""
    global channel_round_robin_counter
    channels = get_active_channels(db)
    
    if not channels:
        return None
    
    # 简单轮询：按索引循环选择
    channel = channels[channel_round_robin_counter % len(channels)]
    channel_round_robin_counter += 1
    
    return channel


def get_active_channel(db: Session) -> Channel | None:
    """获取活跃渠道（使用轮询策略）"""
    return get_channel_with_round_robin(db)


def get_endpoint_for_model(db: Session, channel: Channel, model_name: str) -> Endpoint | None:
    """根据模型名获取对应的接入点"""
    # 根据模型名匹配接入点的 models 列表
    endpoint = db.query(Endpoint).filter(
        Endpoint.channel_id == channel.id,
        Endpoint.is_active == True,
        Endpoint.models != None
    ).filter(
        Endpoint.models.any(model_name)
    ).first()
    if endpoint:
        return endpoint
    
    # 3. 查找默认接入点
    endpoint = db.query(Endpoint).filter(
        Endpoint.channel_id == channel.id,
        Endpoint.is_default == True,
        Endpoint.is_active == True
    ).first()
    if endpoint:
        return endpoint
    
    # 4. 查找普通类型的接入点
    endpoint = db.query(Endpoint).filter(
        Endpoint.channel_id == channel.id,
        Endpoint.type == "default",
        Endpoint.is_active == True
    ).first()
    if endpoint:
        return endpoint
    
    # 5. 返回第一个可用的接入点
    return db.query(Endpoint).filter(
        Endpoint.channel_id == channel.id,
        Endpoint.is_active == True
    ).first()


def generate_signature(ak: str, sk: str, timestamp: str, method: str = "POST", path: str = "/api/v3/contents/generations/tasks", body: str = "") -> str:
    """生成BytePlus签名
    
    BytePlus签名格式通常包含：
    - HTTP方法
    - 请求路径
    - 查询参数（可选）
    - 请求体（可选）
    - 时间戳
    - AK/SK
    """
    # 构建签名字符串
    # 格式: METHOD\nPATH\nQUERY\nBODY\ntimestamp\nak
    query = ""  # 查询参数
    
    sign_str = f"{method}\n{path}\n{query}\n{body}\n{timestamp}\n{ak}"
    signature = hmac.new(sk.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    return signature


def test_endpoint(db: Session, channel_id: int, endpoint_id: int = None) -> dict:
    """测试渠道或接入点的连通性"""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        return {"success": False, "error": "Channel not found"}
    
    # 构建请求头
    headers = {"Content-Type": "application/json"}
    timestamp = str(int(time.time()))
    
    # 如果指定了接入点，测试特定接入点
    if endpoint_id:
        endpoint = db.query(Endpoint).filter(
            Endpoint.id == endpoint_id,
            Endpoint.channel_id == channel_id
        ).first()
        if not endpoint:
            return {"success": False, "error": "Endpoint not found"}
        
        test_url = endpoint.endpoint_url or channel.api_base_url
        test_model = endpoint.endpoint_id
        endpoint_name = endpoint.endpoint_name
    else:
        # 测试渠道级别
        test_url = channel.api_base_url
        test_model = "test"
        endpoint_name = "Channel Default"
    
    # 构建请求路径
    api_path = "/api/v3/contents/generations/tasks"
    
    # 发送测试请求
    try:
        # 构建测试任务payload
        payload = {
            "model": test_model,
            "content": [{"type": "text", "text": "test"}],
            "generate_audio": False,
            "ratio": "16:9",
            "duration": 1,
            "resolution": "360p",
            "watermark": True,
            "test": True,
        }
        
        import json
        body_str = json.dumps(payload)
        
        # 构建请求头 - 支持 AK/SK 认证
        headers = {"Content-Type": "application/json"}
        
        if channel.ak_encrypted and channel.sk_encrypted:
            try:
                ak = decrypt_value(channel.ak_encrypted)
                sk = decrypt_value(channel.sk_encrypted)
                signature = generate_signature(ak, sk, timestamp, "POST", api_path, body_str)
                headers["X-Token-Ak"] = ak
                headers["X-Token-Timestamp"] = timestamp
                headers["X-Token-Signature"] = signature
            except Exception as e:
                return {"success": False, "error": f"Failed to decrypt credentials: {str(e)}"}
        elif channel.api_key_encrypted:
            api_key = decrypt_value(channel.api_key_encrypted)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        else:
            return {"success": False, "error": "No credentials configured for channel"}
        
        full_url = f"{test_url.rstrip('/')}{api_path}"
        res = requests.post(full_url, headers=headers, json=payload, timeout=30)
        result = res.json()
        
        if res.status_code == 200 and "id" in result:
            return {
                "success": True,
                "message": "Endpoint test successful",
                "endpoint": endpoint_name,
                "task_id": result.get("id"),
                "latency": res.elapsed.total_seconds() * 1000
            }
        else:
            return {
                "success": False,
                "message": "Endpoint test failed",
                "endpoint": endpoint_name,
                "error": result.get("message", str(res.status_code)),
                "latency": res.elapsed.total_seconds() * 1000
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}",
            "endpoint": endpoint_name
        }


def create_task_with_channel(db: Session, user_id: int, task_config: dict, channel: Channel, points: int) -> TaskRecord | None:
    """使用指定渠道创建任务（内部函数）"""
    endpoint_id = task_config.get("model")
    
    # 添加调试日志
    logger.info(f"[DEBUG create_task_with_channel] task_config received: {task_config}")
    logger.info(f"[DEBUG create_task_with_channel] use_real_people in task_config: {task_config.get('use_real_people')}")
    
    if not endpoint_id:
        logger.warning(f"No endpoint_id provided in task config")
        return None
    
    endpoint = db.query(Endpoint).filter(
        Endpoint.endpoint_id == endpoint_id,
        Endpoint.channel_id == channel.id,
        Endpoint.is_active == True
    ).first()
    
    if not endpoint:
        logger.warning(f"Channel {channel.name} has no endpoint with id {endpoint_id}")
        return None

    # 如果需要使用真人素材，检查用户选择的接入点是否支持 r2v
    if task_config.get("use_real_people"):
        from database import EndpointType

        # 检查当前接入点是否支持 r2v
        current_models = endpoint.models or []
        if is_r2v_supported(current_models):
            logger.info(f"[DEBUG] User-selected endpoint {endpoint_id} supports r2v, using it")
        else:
            # 当前接入点不支持 r2v，尝试寻找支持 r2v 的接入点作为降级
            found_ep = None

            # 1. 首先尝试寻找包含 2.0 版本模型的视频接入点
            eps = db.query(Endpoint).filter(
                Endpoint.channel_id == channel.id,
                Endpoint.is_active == True,
                Endpoint.type == EndpointType.VIDEO
            ).all()

            for ep in eps:
                ep_models = ep.models or []
                if is_r2v_supported(ep_models):
                    found_ep = ep
                    break

            # 2. 如果找到支持 r2v 的接入点，使用它（降级）
            if found_ep:
                logger.info(f"[DEBUG] User-selected endpoint {endpoint_id} does not support r2v. Falling back to r2v-supported endpoint: {found_ep.endpoint_id}")
                endpoint = found_ep
                endpoint_id = found_ep.endpoint_id
            else:
                logger.warning(f"[DEBUG] User-selected endpoint {endpoint_id} does not support r2v and no fallback endpoint available")
                raise ValueError(f"Endpoint '{endpoint_id}' does not support real person (r2v) feature. Please select an endpoint with 2.0 version models in the dropdown.")

    # 先构建请求体
    content = [{"type": "text", "text": task_config.get("prompt", "")}]
    # 根据 BytePlus Ark SDK 示例，参考图片需要添加 role: "reference_image" 属性
    # 参考：https://docs.byteplus.com/en/docs/ModelArk/2333589

    # 公共参数
    _use_real = task_config.get("use_real_people")
    _portrait_group_id = task_config.get("portrait_group_id") or channel.portrait_group_id or ""
    _project_name = channel.project_id or task_config.get("project_name", "default")
    _public_base_url = channel.public_base_url or ""
    _api_key = decrypt_value(channel.api_key_encrypted) if channel.api_key_encrypted else ""
    _ak = decrypt_value(channel.ak_encrypted) if channel.ak_encrypted else ""
    _sk = decrypt_value(channel.sk_encrypted) if channel.sk_encrypted else ""
    _api_base = channel.api_base_url or "https://ark.ap-southeast.bytepluses.com/api/v3"

    def _try_upload_to_asset(url: str, asset_type: str) -> str | None:
        """尝试上传到素材库。真人模式失败抛异常，非真人模式失败返回 None。"""
        if not (_ak and _sk):
            if _use_real:
                raise ValueError("真人素材模式需要渠道配置 AK/SK")
            logger.warning(f"[asset] No AK/SK configured, cannot upload {asset_type} to asset library: {url}")
            return None
        try:
            result = _upload_to_asset_library(
                url, _api_key, _ak, _sk,
                _portrait_group_id, _project_name,
                _api_base, _public_base_url,
                asset_type=asset_type,
            )
            if result:
                logger.info(f"[asset] Uploaded {asset_type} to asset library: {result}")
                return result
            elif _use_real:
                raise ValueError(f"{asset_type}上传到素材库失败，无法在真人素材模式下继续: {url}")
            else:
                logger.warning(f"[asset] {asset_type} asset upload returned None, falling back to direct URL: {url}")
                return None
        except ValueError:
            raise
        except Exception as e:
            if _use_real:
                raise ValueError(f"{asset_type}上传到素材库失败: {e}") from e
            logger.warning(f"[asset] {asset_type} asset upload error, falling back to direct URL: {e}")
            return None

    # 参考图片
    for img_url in (task_config.get("reference_images") or []):
        asset_uri = None
        if img_url.startswith("/static/uploads/") and (_use_real or (_ak and _sk)):
            asset_uri = _try_upload_to_asset(img_url, "Image")
        if not asset_uri:
            resolved_img = _resolve_media_url(img_url)
        else:
            resolved_img = asset_uri
        content.append({
            "type": "image_url",
            "image_url": {"url": resolved_img},
            "role": "reference_image"
        })

    # 参考音频（Seedance 2.0 要求音频必须走素材库，不能直传 URL）
    for aud_url in (task_config.get("reference_audios") or []):
        asset_uri = None
        if aud_url.startswith("/static/uploads/") and (_ak and _sk):
            asset_uri = _try_upload_to_asset(aud_url, "Audio")
        if not asset_uri:
            resolved_aud = _resolve_media_url(aud_url)
        else:
            resolved_aud = asset_uri
        target_dur = task_config.get("duration_seconds", 15)
        if not asset_uri and aud_url.startswith("/static/uploads/"):
            local_audio = pathlib.Path(aud_url.lstrip("/"))
            if local_audio.exists():
                dur = _get_video_duration(str(local_audio))
                if dur > target_dur:
                    trimmed_path = _trim_audio(str(local_audio), target_dur)
                    if trimmed_path:
                        if _ak and _sk:
                            asset_uri = _try_upload_to_asset(trimmed_path, "Audio")
                        if not asset_uri:
                            resolved_aud = _resolve_media_url(trimmed_path)
                        try:
                            os.remove(trimmed_path)
                        except Exception:
                            pass
        content.append({"type": "audio_url", "audio_url": {"url": resolved_aud.replace('`','').strip()}, "role": "reference_audio"})

    # 参考视频（Seedance 2.0 要求视频必须走素材库，不能直传 URL）
    for vid_url in (task_config.get("reference_videos") or []):
        asset_uri = None
        if vid_url.startswith("/static/uploads/") and (_ak and _sk):
            asset_uri = _try_upload_to_asset(vid_url, "Video")
        if not asset_uri:
            resolved = vid_url
            if resolved.startswith("/") and _public_base_url:
                resolved = f"{_public_base_url.rstrip('/')}/{resolved.lstrip('/')}"
        else:
            resolved = asset_uri
        content.append({"type": "video_url", "video_url": {"url": resolved.replace('`','').strip()}, "role": "reference_video"})

        # 校验：音频参考不能是唯一的参考输入
    audios = task_config.get("reference_audios") or []
    images = task_config.get("reference_images") or []
    videos = task_config.get("reference_videos") or []
    if audios and not images and not videos:
        raise ValueError("音频参考必须配合至少一张图片或一段视频使用")

# 使用接入点ID作为模型参数（BytePlus API要求使用接入点ID）
    model = endpoint.endpoint_id
    logger.info(f"[DEBUG] Using endpoint ID as model: {model}")

    payload = {
        "model": model,
        "content": content,
        "generate_audio": False if (task_config.get("reference_audios") or []) else task_config.get("generate_audio", True),
        "ratio": task_config.get("ratio", "16:9"),
        "duration": task_config.get("duration_seconds", 5),
        "resolution": task_config.get("resolution", "720p"),
        "watermark": task_config.get("watermark", False),
    }

    # 真人素材参数支持
    # 根据 BytePlus 文档：https://docs.byteplus.com/en/docs/ModelArk/2333589
    if task_config.get("use_real_people"):
        # 检查接入点的模型列表是否支持真人转视频（r2v）功能
        models = endpoint.models
        logger.info(f"[DEBUG] use_real_people=True detected")
        logger.info(f"[DEBUG] Endpoint ID: '{endpoint_id}'")
        logger.info(f"[DEBUG] Models type: {type(models)}")
        logger.info(f"[DEBUG] Models value: {models}")
        logger.info(f"[DEBUG] Models repr: {repr(models)}")
        
        # 如果 models 列表为空或为 None，尝试从 endpoint_id 来推断
        if not models or (isinstance(models, list) and len(models) == 0):
            logger.info(f"[DEBUG] Models list is empty, trying endpoint_id instead")
            supported = is_r2v_supported(endpoint_id)
        else:
            supported = is_r2v_supported(models)
        
        if not supported:
            logger.info(f"[DEBUG] r2v NOT supported")
            raise ValueError(f"Endpoint '{endpoint_id}' does not support real person (r2v) feature. Please use an endpoint with 2.0 version models like 'dreamina-seedance-2-0-260128'.")
        else:
            logger.info(f"[DEBUG] r2v IS supported")
        
        # 必须添加 use_real_people 参数到 payload
        payload["use_real_people"] = True
        logger.info(f"Adding use_real_people=True to payload for real person mode")
        # 虚拟人/真人素材参数
        if task_config.get("avatar_id"):
            payload["avatar_id"] = task_config["avatar_id"]
        if task_config.get("asset_library_id"):
            payload["asset_library_id"] = task_config["asset_library_id"]
        if task_config.get("real_human_portrait_id"):
            payload["real_human_portrait_id"] = task_config["real_human_portrait_id"]
        if task_config.get("action_id"):
            payload["action_id"] = task_config["action_id"]
        if task_config.get("background_id"):
            payload["background_id"] = task_config["background_id"]
        if task_config.get("voice_id"):
            payload["voice_id"] = task_config["voice_id"]

    # 精细化字幕擦除功能
    # 根据文档：https://bytedance.larkoffice.com/docx/FG9AdmjyDoTRugxYsMWci956nwd
    if task_config.get("subtitle_removal"):
        payload["subtitle_removal"] = {
            "enable": True,
            "mode": task_config.get("subtitle_removal_mode", "accurate"),  # accurate: 精细化模式
        }

    # 构建请求头 - 支持 AK/SK 认证
    headers = {"Content-Type": "application/json"}
    timestamp = str(int(time.time()))
    api_path = "/api/v3/contents/generations/tasks"
    
    import json
    body_str = json.dumps(payload)
    
    # 文生视频只使用 API Key 认证（AK/SK 仅用于素材上传）
    if channel.api_key_encrypted:
        try:
            api_key = decrypt_value(channel.api_key_encrypted)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
                logger.info(f"Channel {channel.name} - Using API Key authentication for video generation: Key={api_key[:10]}...")
            else:
                error_msg = f"API Key for channel '{channel.name}' is empty after decryption. Please reconfigure in admin panel."
                logger.error(error_msg)
                raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"Failed to decrypt API Key for channel '{channel.name}'. This usually happens when SD_SECRET_KEY has changed. Please reconfigure API Key in admin panel. Error: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    else:
        error_msg = f"Channel '{channel.name}' has no API Key configured. Video generation requires API Key. Please configure in admin panel."
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        api_url = channel.task_url or (channel.api_base_url.rstrip('/') + '/contents/generations/tasks')
        logger.info(f"Channel {channel.name} - Sending request to: {api_url}")
        logger.info(f"Channel {channel.name} - Request headers: {dict(headers)}")
        logger.info(f"Channel {channel.name} - Request payload keys: {list(payload.keys())}")
        
        res = requests.post(api_url, headers=headers, json=payload, timeout=30)
        
        logger.info(f"Channel {channel.name} - Response status: {res.status_code}")
        logger.info(f"Channel {channel.name} - Response headers: {dict(res.headers)}")
        
        result = res.json()
        logger.info(f"Channel {channel.name} - Response body: {result}")
    except Exception as e:
        logger.error(f"Channel {channel.name} request failed: {e}")
        return None

    if "id" not in result:
        err = result.get('error') or result
        err_msg = err.get('message', str(result)) if isinstance(err, dict) else str(result)
        logger.error(f"Channel {channel.name} task creation failed. payload={payload} response={result}")
        
        # 翻译为友好提示
        friendly = translate_error(err_msg)
        
        # 如果是接入点不存在错误，且正在使用真人素材模式，尝试降级
        if task_config.get("use_real_people") and ("does not exist" in err_msg.lower() or "not found" in err_msg.lower()) and is_r2v_supported(endpoint.models or []):
            logger.info(f"[DEBUG] Endpoint {endpoint_id} not found or failed, trying fallback to other r2v-supported endpoints")
            
            # 尝试寻找其他支持 r2v 的接入点
            fallback_eps = db.query(Endpoint).filter(
                Endpoint.channel_id == channel.id,
                Endpoint.is_active == True,
                Endpoint.type == EndpointType.VIDEO,
                Endpoint.endpoint_id != endpoint_id
            ).all()
            
            for fallback_ep in fallback_eps:
                fallback_models = fallback_ep.models or []
                if is_r2v_supported(fallback_models):
                    logger.info(f"[DEBUG] Found fallback endpoint: {fallback_ep.endpoint_id} with models: {fallback_models}")
                    # 更新 endpoint 和 endpoint_id，重新构建请求
                    endpoint = fallback_ep
                    endpoint_id = fallback_ep.endpoint_id
                    model = endpoint_id
                    payload["model"] = model
                    
                    # 重新发送请求
                    try:
                        logger.info(f"[DEBUG] Retrying with fallback endpoint: {endpoint_id}")
                        res = requests.post(api_url, headers=headers, json=payload, timeout=30)
                        result = res.json()
                        logger.info(f"[DEBUG] Fallback response: {result}")
                        
                        if "id" in result:
                            # 成功了，继续处理
                            break
                    except Exception as e:
                        logger.error(f"[DEBUG] Fallback request failed: {e}")
                        continue
        
        if "id" not in result:
            raise ValueError(friendly)

    task = TaskRecord(
        user_id=user_id,
        channel_id=channel.id,
        external_task_id=result["id"],
        status=TaskStatus.PROCESSING,
        model=model,
        prompt=task_config.get("prompt"),
        duration_seconds=task_config.get("duration_seconds", 5),
        resolution=task_config.get("resolution", "720p"),
        ratio=task_config.get("ratio", "16:9"),
        tokens_consumed=0,  # 稍后更新
        points_consumed=points,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def create_task(db: Session, user_id: int, task_config: dict, channel_id: int = None) -> TaskRecord:
    # 添加调试日志
    logger.info(f"[DEBUG create_task] task_config received: {task_config}")
    logger.info(f"[DEBUG create_task] use_real_people in task_config: {task_config.get('use_real_people')}")
    
    # 0. 检查参考视频时长限制（BytePlus r2v 限制15秒），超长自动拆分
    reference_videos = task_config.get("reference_videos", [])
    if reference_videos:
        max_ref_duration = 15
        split_videos = []
        for vid_url in reference_videos:
            if vid_url.startswith("/"):
                local_path = vid_url.lstrip("/")
                if os.path.exists(local_path):
                    duration = _get_video_duration(local_path)
                    if duration > max_ref_duration:
                        segments = _split_video_segments(local_path, max_ref_duration)
                        for seg_path in segments:
                            seg_url = "/" + seg_path.replace("\\", "/")
                            split_videos.append(seg_url)
                        logger.info(f"[task] Split reference video {vid_url} ({duration:.1f}s) into {len(segments)} segments")
                        continue
            split_videos.append(vid_url)
        task_config["reference_videos"] = split_videos
    
    # 0. 检查是否有相同提示词的任务正在进行中（防重复）
    prompt = task_config.get('prompt', '')
    if prompt:
        from database import TaskStatus
        recent_tasks = db.query(TaskRecord).filter(
            TaskRecord.user_id == user_id,
            TaskRecord.prompt == prompt,
            TaskRecord.status.in_([TaskStatus.PROCESSING, TaskStatus.PENDING])
        ).all()
        if recent_tasks:
            logger.warning(f"[DEBUG create_task] Found {len(recent_tasks)} pending/processing tasks with same prompt, blocking duplicate creation")
            raise ValueError("已有相同提示词的任务正在生成中，请等待完成后再尝试")
    
    # 1. 检查并发限制
    allowed, msg = check_concurrency_limit(db, user_id)
    if not allowed:
        raise ValueError(msg)
    
    # 2. 获取接入点和渠道信息
    endpoint_id = task_config.get("model")
    
    if endpoint_id:
        endpoint = db.query(Endpoint).filter(
            Endpoint.endpoint_id == endpoint_id,
            Endpoint.is_active == True
        ).first()
        
        if not endpoint:
            raise ValueError(f"Endpoint {endpoint_id} not found")
        
        channel = db.query(Channel).filter(
            Channel.id == endpoint.channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise ValueError(f"Channel for endpoint {endpoint_id} not found")
        
        channels = [channel]
    else:
        if channel_id:
            channel = db.query(Channel).filter(Channel.id == channel_id).first()
            if not channel:
                raise ValueError("Specified channel not found")
            channels = [channel]
        else:
            channels = get_active_channels(db)
        
        if not channels:
            raise ValueError("No active channel available")

    # 3. 计算积分消耗
    tokens = calculate_tokens_cost(db, task_config)
    points = calculate_points_cost(db, tokens)

    # 4. 检查订阅权限（分辨率限制）
    sub = get_active_subscription(db, user_id)
    if sub:
        max_res = sub.get("max_resolution", "720p")
        res_order = {"480p": 1, "720p": 2, "1080p": 3}
        if res_order.get(task_config.get("resolution", "720p"), 1) > res_order.get(max_res, 2):
            task_config["resolution"] = max_res

    # 5. 扣除积分
    if not consume_points(db, user_id, points, f"Task creation: {task_config.get('prompt', '')[:50]}"):
        from services.point_service import get_user_points
        balance = get_user_points(db, user_id)
        raise ValueError(f"INSUFFICIENT_POINTS:{points}:{balance}")
    
    # 6. 获取并发令牌
    if not acquire_concurrency_token(db, user_id):
        # 返还积分
        earn_points(db, user_id, points, PointsType.EARN, f"Refund: concurrency limit exceeded")
        db.commit()
        raise ValueError("系统当前任务繁忙，请稍后再试")

    global channel_round_robin_counter
    
    def try_create_task(channels_list, use_real_people=False):
        """尝试创建任务，支持切换到真人素材模式"""
        global channel_round_robin_counter
        
        # 如果需要使用真人素材，直接在任务配置中添加参数
        # 根据 BytePlus 文档：https://docs.byteplus.com/en/docs/ModelArk/2333589
        # 真人素材不需要专用接入点，所有视频生成模型都可以处理
        current_task_config = task_config.copy()
        if use_real_people:
            current_task_config["use_real_people"] = True
            logger.info(f"Enabling real people mode with config: {current_task_config}")
        
        # 获取轮询起始索引
        start_index = channel_round_robin_counter % len(channels_list)
        
        # 尝试所有渠道
        for i in range(len(channels_list)):
            index = (start_index + i) % len(channels_list)
            channel = channels_list[index]
            
            logger.info(f"Trying channel {channel.name} (index: {index})")
            
            task = create_task_with_channel(db, user_id, current_task_config, channel, points)
            
            if task:
                channel_round_robin_counter = index + 1
                return task
            
            logger.warning(f"Channel {channel.name} failed, trying next channel")
        
        return None
    
    # 第一次尝试
    try:
        task = try_create_task(channels)
        if task:
            return task
    except ValueError as e:
        err_msg = str(e)
        logger.info(f"Caught ValueError in create_task: {err_msg}")
        logger.info(f"Error message lowercased: {err_msg.lower()}")
        # 检测是否是真人检测错误（匹配英文原文和中文翻译）
        if is_real_person_error(err_msg):
            logger.info(f"Detected real person error: {err_msg}. Enabling real people mode and retrying.")
            # 在原请求中添加 use_real_people 参数重试
            task = try_create_task(channels, use_real_people=True)
            if task:
                return task
            # 如果重试失败，抛出原始错误
            raise ValueError(err_msg)
        logger.info(f"Not a real person error, re-raising exception")
        raise
    
    # 所有渠道都失败了
    earn_points(db, user_id, points, PointsType.EARN, f"Refund: all channels failed")
    db.commit()
    raise ValueError("All channels failed to create task")


def poll_task(db: Session, task: TaskRecord) -> None:
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))
    if task.created_at:
        created = task.created_at.replace(tzinfo=CST) if task.created_at.tzinfo is None else task.created_at
        elapsed = (datetime.now(CST) - created).total_seconds()
        if elapsed > 43200:
            task.status = TaskStatus.FAILED
            task.error_msg = "任务超时（超过12小时未完成）"
            db.commit()
            release_concurrency_token(db, task.user_id)
            logger.warning(f"Task {task.id} timed out after {int(elapsed)}s, marked as FAILED")
            return

    channel = db.query(Channel).filter(Channel.id == task.channel_id).first()
    if not channel:
        return

    # 构建请求头 - 优先使用 API Key
    headers = {}
    timestamp = str(int(time.time()))

    if channel.api_key_encrypted:
        headers["Authorization"] = f"Bearer {decrypt_value(channel.api_key_encrypted)}"
    elif channel.ak_encrypted and channel.sk_encrypted:
        ak = decrypt_value(channel.ak_encrypted)
        sk = decrypt_value(channel.sk_encrypted)
        signature = generate_signature(ak, sk, timestamp)
        headers["X-Token-Ak"] = ak
        headers["X-Token-Timestamp"] = timestamp
        headers["X-Token-Signature"] = signature

    try:
        api_url = channel.task_url or (channel.api_base_url.rstrip('/') + '/contents/generations/tasks')
        res = requests.get(f"{api_url}/{task.external_task_id}", headers=headers, timeout=10)
        result = res.json()
        logger.info(f"[poll_task] external_id={task.external_task_id} response={result}")
    except Exception as e:
        logger.error(f"[poll_task] network error for task {task.id}: {e}")
        return

    status_map = {
        "SUCCESS": TaskStatus.SUCCESS,
        "succeeded": TaskStatus.SUCCESS,
        "FAILED": TaskStatus.FAILED,
        "failed": TaskStatus.FAILED,
        "CANCELLED": TaskStatus.CANCELLED,
        "cancelled": TaskStatus.CANCELLED,
    }

    # 兼容顶层或嵌套在 data/content 下的响应结构
    payload = result.get("data") or result.get("content") or result

    new_status = status_map.get(payload.get("status") or result.get("status"))
    if new_status:
        was_processing = task.status == TaskStatus.PROCESSING

        task.status = new_status
        if new_status == TaskStatus.SUCCESS:
            content = payload.get("content") or result.get("content") or {}
            video_urls = payload.get("video_urls") or []
            task.video_url = (
                content.get("video_url")
                or result.get("video_url")
                or (video_urls[0] if video_urls else None)
            )
            task.progress = 100
            usage = result.get("usage") or payload.get("usage") or {}
            if usage.get("completion_tokens"):
                task.tokens_consumed = usage["completion_tokens"]
        elif new_status == TaskStatus.FAILED or new_status == TaskStatus.CANCELLED:
            error_obj = payload.get("error") or {}
            raw_err = (
                error_obj.get("message")
                or payload.get("error_msg")
                or result.get("error_msg")
                or result.get("message")
                or ""
            )
            if new_status == TaskStatus.CANCELLED:
                task.error_msg = "已取消"
            else:
                task.error_msg = translate_error(raw_err) if raw_err else "生成失败"

        db.commit()

        # 如果任务完成，释放并发令牌
        if was_processing and (new_status == TaskStatus.SUCCESS or new_status == TaskStatus.FAILED or new_status == TaskStatus.CANCELLED):
            release_concurrency_token(db, task.user_id)
            logger.info(f"Concurrency token released for task {task.id}, user {task.user_id}, status: {new_status.value}")
    else:
        raw_progress = payload.get("progress") if payload is not result else result.get("progress")
        task.progress = int(raw_progress) if raw_progress is not None else task.progress
        db.commit()


def create_batch_tasks(
    db: Session, user_id: int, task_configs: list[dict],
    callback_url: str = None
) -> BatchTask:
    batch = BatchTask(
        user_id=user_id,
        status=TaskStatus.PENDING,
        total_count=len(task_configs),
        config={"tasks": task_configs, "callback_url": callback_url},
    )
    db.add(batch)
    db.flush()

    for cfg in task_configs:
        try:
            task = create_task(db, user_id, cfg)
            task.batch_task_id = batch.id
            batch.completed_count += 1
        except ValueError as e:
            batch.failed_count += 1

    batch.status = TaskStatus.PROCESSING if batch.completed_count > 0 else TaskStatus.FAILED
    db.commit()
    return batch


# ── Video Composition (Long Video Support) ────────────────────────────

def _get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _get_video_duration(video_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒），失败返回 0"""
    try:
        ffmpeg = _get_ffmpeg_exe()
        cmd = [ffmpeg, "-i", video_path, "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            return duration
    except Exception as e:
        logger.error(f"[video-duration] Failed to get duration for {video_path}: {e}")
    return 0.0


def _split_video_segments(video_path: str, max_duration: int = 15) -> list[str]:
    """将视频拆分为多个片段，每个不超过 max_duration 秒，返回片段文件路径列表"""
    ffmpeg = _get_ffmpeg_exe()
    duration = _get_video_duration(video_path)
    if duration <= max_duration:
        return [video_path]
    
    seg_count = int((duration + max_duration - 1) // max_duration)
    seg_dirs = []  # store temp dirs so we can access the output files
    
    base_dir = os.path.dirname(video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    seg_files = []
    
    logger.info(f"[split] Splitting {video_path} ({duration:.1f}s) into {seg_count} segments of ≤{max_duration}s")
    
    for i in range(seg_count):
        start = i * max_duration
        seg_path = os.path.join(base_dir, f"{base_name}_seg{i:02d}.mp4")
        
        cmd = [
            ffmpeg, "-y",
            "-ss", str(start),
            "-t", str(max_duration),
            "-i", video_path,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            "-movflags", "+faststart",
            seg_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"[split] Failed to split segment {i}: {result.stderr[-300:]}")
            continue
        seg_files.append(seg_path)
        logger.info(f"[split] Created segment {i}: {seg_path}")
    
    return seg_files if seg_files else [video_path]


def _extract_last_frame(video_url: str, output_dir: str = None) -> str | None:
    """从视频URL提取最后一帧并保存为图片，返回相对URL（如 /outputs/frame_xxx.jpg）"""
    ffmpeg = _get_ffmpeg_exe()
    tmpdir = tempfile.mkdtemp(prefix="sedgo_frame_")
    
    try:
        # 下载视频
        local_video = os.path.join(tmpdir, "source.mp4")
        
        # 支持本地相对URL和远程URL
        if video_url.startswith("/"):
            # 本地相对URL
            base_dir = os.path.dirname(os.path.dirname(__file__))
            local_video_source = os.path.join(base_dir, video_url.lstrip("/"))
            if os.path.exists(local_video_source):
                shutil.copy(local_video_source, local_video)
            else:
                logger.error(f"[extract_frame] local video not found: {local_video_source}")
                return None
        else:
            # 远程URL
            resp = requests.get(video_url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(local_video, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
        
        # 获取视频时长
        duration = _get_video_duration(local_video)
        if duration <= 0:
            logger.error(f"[extract_frame] failed to get video duration")
            return None
        
        # 取最后0.5秒的帧（确保是视频末尾的帧）
        frame_time = max(0, duration - 0.5)
        
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成唯一的帧文件名
        frame_filename = f"frame_{int(time.time()*1000)}.jpg"
        frame_path = os.path.join(output_dir, frame_filename)
        
        # 使用ffmpeg提取帧
        cmd = [
            ffmpeg, "-y",
            "-ss", str(frame_time),
            "-i", local_video,
            "-frames:v", "1",
            "-q:v", "2",  # 高质量JPEG
            frame_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"[extract_frame] ffmpeg failed: {result.stderr[-500:]}")
            return None
        
        logger.info(f"[extract_frame] extracted frame from {video_url} → {frame_path}")
        
        # 返回相对URL（用于前端和后端访问）
        return f"/outputs/{frame_filename}"
    
    except Exception as e:
        logger.error(f"[extract_frame] error: {e}")
        return None
    finally:
        # 清理临时目录
        shutil.rmtree(tmpdir, ignore_errors=True)


def _concat_videos(segment_urls: list[str], output_path: str) -> bool:
    """下载所有片段并用 ffmpeg 拼接成单文件，返回是否成功。优先尝试 xfade，失败则回退到简单 concat。"""
    ffmpeg = _get_ffmpeg_exe()
    tmpdir = tempfile.mkdtemp(prefix="sedgo_concat_")
    try:
        local_files = []
        for i, url in enumerate(segment_urls):
            local_path = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
            local_files.append(local_path)
            logger.info(f"[concat] downloaded segment {i}: {os.path.getsize(local_path)} bytes")

        if len(local_files) == 1:
            shutil.copy(local_files[0], output_path)
            logger.info(f"[concat] only 1 segment, copied directly")
            return True

        # 获取所有片段时长，缓存避免重复调用
        durations = [_get_video_duration(p) for p in local_files]
        logger.info(f"[concat] segment durations: {durations}")

        fade_duration = 0.5
        can_xfade = all(d > fade_duration for d in durations)

        # 尝试 xfade 过渡
        if can_xfade:
            success = _concat_with_xfade(ffmpeg, local_files, durations, fade_duration, output_path)
            if success:
                return True
            logger.warning("[concat] xfade failed, falling back to simple concat")

        # 回退：简单 concat（无需特殊滤镜）
        return _concat_simple(ffmpeg, local_files, output_path)

    except Exception as e:
        logger.error(f"[concat] error: {e}")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _concat_with_xfade(ffmpeg: str, local_files: list, durations: list, fade_duration: float, output_path: str) -> bool:
    """使用 xfade/acrossfade 滤镜拼接（带交叉淡入过渡效果）"""
    try:
        inputs = []
        for seg in local_files:
            inputs.extend(["-i", seg])

        filters_str = ""
        last_out_vid = ""
        last_out_aud = ""

        for i in range(len(local_files) - 1):
            cur_v_label = f"v{i}"
            cur_a_label = f"a{i}"
            next_v_label = f"v{i+1}"
            next_a_label = f"a{i+1}"
            out_v_label = f"vout{i+1}"
            out_a_label = f"aout{i+1}"

            if i == 0:
                trim_dur = durations[i] - fade_duration
                filters_str += f"[{i}:v]trim=duration={trim_dur:.4f},setpts=PTS-STARTPTS[{cur_v_label}];"
                filters_str += f"[{i}:a]atrim=duration={trim_dur:.4f},asetpts=PTS-STARTPTS[{cur_a_label}];"
            else:
                filters_str += f"[{last_out_vid}]setpts=PTS-STARTPTS[{cur_v_label}];"
                filters_str += f"[{last_out_aud}]asetpts=PTS-STARTPTS[{cur_a_label}];"

            filters_str += f"[{i+1}:v]trim=duration={durations[i+1]:.4f},setpts=PTS-STARTPTS[{next_v_label}];"
            filters_str += f"[{i+1}:a]atrim=duration={durations[i+1]:.4f},asetpts=PTS-STARTPTS[{next_a_label}];"

            offset = (durations[i] - fade_duration) if i == 0 else "0"
            filters_str += f"[{cur_v_label}][{next_v_label}]xfade=transition=fade:duration={fade_duration}:offset={offset}[{out_v_label}];"
            filters_str += f"[{cur_a_label}][{next_a_label}]acrossfade=d={fade_duration}[{out_a_label}];"

            last_out_vid = out_v_label
            last_out_aud = out_a_label

        cmd = [
            ffmpeg, "-y",
            *inputs,
            "-filter_complex", filters_str,
            "-map", f"[{last_out_vid}]",
            "-map", f"[{last_out_aud}]",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            stderr_tail = result.stderr[-800:] if result.stderr else ''
            logger.error(f"[concat] xfade failed: {stderr_tail}")
            return False
        logger.info(f"[concat] merged {len(local_files)} segments with xfade -> {output_path}")
        return True
    except Exception as e:
        logger.error(f"[concat] xfade error: {e}")
        return False


def _concat_simple(ffmpeg: str, local_files: list, output_path: str) -> bool:
    """使用 concat 滤镜简单拼接（无过渡效果，兼容所有 ffmpeg 版本）"""
    try:
        inputs = []
        for seg in local_files:
            inputs.extend(["-i", seg])

        n = len(local_files)
        concat_parts = []
        for i in range(n):
            concat_parts.append(f"[{i}:v][{i}:a]")
        concat_inputs = "".join(concat_parts)
        filter_str = f"{concat_inputs}concat=n={n}:v=1:a=1[v][a]"

        cmd = [
            ffmpeg, "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            stderr_tail = result.stderr[-800:] if result.stderr else ''
            logger.error(f"[concat] simple concat failed: {stderr_tail}")
            return False
        logger.info(f"[concat] merged {n} segments with simple concat -> {output_path}")
        return True
    except Exception as e:
        logger.error(f"[concat] simple concat error: {e}")
        return False


def create_video_composition(db: Session, user_id: int, task_config: dict) -> VideoComposition:
    total_duration = task_config.get("duration_seconds") or task_config.get("duration", 60)
    prompt = task_config.get("prompt", "")
    resolution = task_config.get("resolution", "720p")
    ratio = task_config.get("ratio", "16:9")
    endpoint_id = task_config.get("model", "")
    
    # 检查真人素材功能的模型兼容性
    if task_config.get("use_real_people"):
        # 查询接入点获取模型列表
        endpoint = db.query(Endpoint).filter(
            Endpoint.endpoint_id == endpoint_id,
            Endpoint.is_active == True
        ).first()
        if not endpoint:
            raise ValueError(f"Endpoint '{endpoint_id}' not found or not active.")
        
        if not is_r2v_supported(endpoint.models):
            raise ValueError(f"Endpoint '{endpoint_id}' does not support real person (r2v) feature. Please use an endpoint with 2.0 version models.")
    
    model = endpoint_id
    
    # 根据模型版本获取最大单段时长
    max_duration = get_model_max_duration(model)
    segment_count = (total_duration + max_duration - 1) // max_duration

    # 预先计算每段时长
    seg_durations = []
    for i in range(segment_count):
        start = i * max_duration
        seg_durations.append(min(max_duration, total_duration - start))

    # 计算并一次性扣除总积分（不经过 create_task，避免重复扣）
    total_points = 0
    for dur in seg_durations:
        seg_cfg = {"model": model, "duration": dur, "resolution": resolution}
        tokens = calculate_tokens_cost(db, seg_cfg)
        total_points += calculate_points_cost(db, tokens)

    if not consume_points(db, user_id, total_points, f"Video composition: {prompt[:50]}"):
        from services.point_service import get_user_points
        balance = get_user_points(db, user_id)
        raise ValueError(f"INSUFFICIENT_POINTS:{total_points}:{balance}")

    composition = VideoComposition(
        user_id=user_id,
        status=TaskStatus.PROCESSING,
        total_duration=total_duration,
        prompt=prompt,
        resolution=resolution,
        ratio=ratio,
        total_points_consumed=total_points,
    )
    db.add(composition)
    db.flush()

    # 串行生成方案：只创建第一个片段任务，其余片段在后台线程中串行创建
    for i, dur in enumerate(seg_durations):
        segment = VideoSegment(
            composition_id=composition.id,
            segment_index=i,
            start_time=i * max_duration,
            duration=dur,
            status=TaskStatus.PENDING,
        )
        db.add(segment)
        db.flush()

        # 只为第一个片段（segment_index=0）创建任务
        if i == 0:
            seg_cfg = {
                "model": model,
                "prompt": prompt,
                "duration_seconds": dur,
                "resolution": resolution,
                "ratio": ratio,
                "generate_audio": False if (task_config.get("reference_audios") or []) else task_config.get("generate_audio", True),
                "watermark": task_config.get("watermark", False),
                "reference_images": task_config.get("reference_images") or [],
                "reference_videos": task_config.get("reference_videos") or [],
                "reference_audios": task_config.get("reference_audios") or [],
            }
            
            # 如果任务配置中有真人素材参数，也添加到片段配置中
            if task_config.get("use_real_people"):
                seg_cfg["use_real_people"] = True
                if task_config.get("avatar_id"):
                    seg_cfg["avatar_id"] = task_config["avatar_id"]
                if task_config.get("real_human_portrait_id"):
                    seg_cfg["real_human_portrait_id"] = task_config["real_human_portrait_id"]
                if task_config.get("action_id"):
                    seg_cfg["action_id"] = task_config["action_id"]
                if task_config.get("background_id"):
                    seg_cfg["background_id"] = task_config["background_id"]
                if task_config.get("voice_id"):
                    seg_cfg["voice_id"] = task_config["voice_id"]
            
            task_rec = None
            
            def try_create_segment(channels_list, use_real_people=False):
                """尝试创建片段任务，支持切换到真人素材模式"""
                global channel_round_robin_counter
                current_seg_cfg = seg_cfg.copy()
                if use_real_people:
                    current_seg_cfg["use_real_people"] = True
                    logger.info(f"[composition {composition.id}] segment {i} enabling real people mode")
                
                start_index = channel_round_robin_counter % len(channels_list)
                
                for j in range(len(channels_list)):
                    index = (start_index + j) % len(channels_list)
                    channel = channels_list[index]
                    
                    logger.info(f"[composition {composition.id}] segment {i} trying channel {channel.name} (index: {index})")
                    
                    try:
                        task = create_task_with_channel(db, user_id, current_seg_cfg, channel, 0)
                        if task:
                            channel_round_robin_counter = index + 1
                            return task
                    except Exception as ch_err:
                        logger.warning(f"[composition {composition.id}] segment {i} channel {channel.name} failed: {ch_err}")
                
                return None
            
            channels = db.query(Channel).filter(Channel.is_active == True).order_by(Channel.priority.desc()).all()
            if not channels:
                logger.error(f"[composition {composition.id}] no active channels available")
                composition.status = TaskStatus.FAILED
                composition.error_msg = "系统当前无可用渠道，请稍后再试"
                db.commit()
                earn_points(db, user_id, total_points, PointsType.EARN, "Refund: no channels available")
                db.commit()
                return composition
            
            try:
                task_rec = try_create_segment(channels)
                if task_rec:
                    segment.task_record_id = task_rec.id
                    segment.status = TaskStatus.PROCESSING
                else:
                    raise ValueError("All channels failed to create segment task")
            except Exception as e:
                err_msg = str(e)
                if is_real_person_error(err_msg):
                    logger.info(f"[composition {composition.id}] segment {i} detected real person error, retrying with real people mode")
                    task_rec = try_create_segment(channels, use_real_people=True)
                    if task_rec:
                        segment.task_record_id = task_rec.id
                        segment.status = TaskStatus.PROCESSING
                        db.commit()
                        continue
                
                logger.error(f"[composition {composition.id}] segment {i} failed: {err_msg}")
                segment.status = TaskStatus.FAILED
                composition.status = TaskStatus.FAILED
                composition.error_msg = f"片段{i+1}创建失败: {err_msg}"
                db.commit()
                earn_points(db, user_id, total_points, PointsType.EARN, "Refund: composition segment failed")
                db.commit()
                return composition

    db.commit()
    # 启动后台线程处理片段轮询和拼接（串行生成+传递参考图）
    t = threading.Thread(target=_composition_worker_serial, args=(composition.id, prompt, model, resolution, ratio, task_config, user_id), daemon=True)
    t.start()
    return composition


def _composition_worker(composition_id: int) -> None:
    """后台线程：轮询所有片段，全部完成后 ffmpeg 拼接"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        while True:
            composition = db.query(VideoComposition).filter(
                VideoComposition.id == composition_id
            ).first()
            if not composition or composition.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                break

            segments = db.query(VideoSegment).filter(
                VideoSegment.composition_id == composition_id
            ).order_by(VideoSegment.segment_index).all()

            total = len(segments)
            completed = 0
            failed = 0

            for segment in segments:
                if segment.status == TaskStatus.SUCCESS:
                    completed += 1
                    continue
                if segment.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                    failed += 1
                    continue
                if not segment.task_record_id:
                    failed += 1
                    segment.status = TaskStatus.FAILED
                    continue

                task = db.query(TaskRecord).filter(TaskRecord.id == segment.task_record_id).first()
                if not task:
                    failed += 1
                    segment.status = TaskStatus.FAILED
                    continue

                poll_task(db, task)
                db.refresh(task)

                if task.status == TaskStatus.SUCCESS:
                    segment.status = TaskStatus.SUCCESS
                    segment.video_url = task.video_url
                    completed += 1
                elif task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                    segment.status = TaskStatus.FAILED
                    failed += 1

            composition.progress = int((completed / total) * 90) if total else 0

            if failed > 0:
                composition.status = TaskStatus.FAILED
                composition.error_msg = f"{failed}/{total} 个片段生成失败"
                db.commit()
                break

            if completed == total:
                # 全部完成，开始拼接
                composition.progress = 95
                db.commit()

                segment_urls = [s.video_url for s in segments]
                outputs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
                os.makedirs(outputs_dir, exist_ok=True)
                output_path = os.path.join(outputs_dir, f"composition_{composition_id}.mp4")

                ok = _concat_videos(segment_urls, output_path)
                if ok:
                    composition.final_video_url = f"/outputs/composition_{composition_id}.mp4"
                    composition.status = TaskStatus.SUCCESS
                    composition.progress = 100
                else:
                    composition.status = TaskStatus.FAILED
                    composition.error_msg = "视频拼接失败（ffmpeg 错误）"
                db.commit()
                break

            db.commit()
            time.sleep(5)
    except Exception as e:
        logger.exception(f"[composition_worker {composition_id}] crashed")
        try:
            comp = db.query(VideoComposition).filter(VideoComposition.id == composition_id).first()
            if comp and comp.status == TaskStatus.PROCESSING:
                comp.status = TaskStatus.FAILED
                comp.error_msg = f"后台处理异常: {e}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _composition_worker_serial(composition_id: int, prompt: str, model: str, resolution: str, ratio: str, task_config: dict, user_id: int) -> None:
    """后台线程：串行生成片段，传递参考图保持连续性"""
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        reference_frame = None  # 前一片段的最后一帧
        
        while True:
            composition = db.query(VideoComposition).filter(
                VideoComposition.id == composition_id
            ).first()
            if not composition or composition.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                break
            
            segments = db.query(VideoSegment).filter(
                VideoSegment.composition_id == composition_id
            ).order_by(VideoSegment.segment_index).all()
            
            if not segments:
                break
            
            total = len(segments)
            completed = sum(1 for s in segments if s.status == TaskStatus.SUCCESS)
            failed = sum(1 for s in segments if s.status == TaskStatus.FAILED)
            
            if failed > 0:
                composition.status = TaskStatus.FAILED
                composition.error_msg = f"{failed}/{total} 个片段生成失败"
                db.commit()
                break
            
            if completed == total:
                # 全部完成，开始拼接
                composition.progress = 95
                db.commit()
                
                segment_urls = [s.video_url for s in segments]
                outputs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
                os.makedirs(outputs_dir, exist_ok=True)
                output_path = os.path.join(outputs_dir, f"composition_{composition_id}.mp4")
                
                ok = _concat_videos(segment_urls, output_path)
                if ok:
                    composition.final_video_url = f"/outputs/composition_{composition_id}.mp4"
                    composition.status = TaskStatus.SUCCESS
                    composition.progress = 100
                else:
                    composition.status = TaskStatus.FAILED
                    composition.error_msg = "视频拼接失败（ffmpeg 错误）"
                db.commit()
                break
            
            # 找到当前需要处理的片段（第一个PROCESSING或PENDING状态的片段）
            current_seg = None
            for seg in segments:
                if seg.status == TaskStatus.PROCESSING:
                    current_seg = seg
                    break
                elif seg.status == TaskStatus.PENDING and not seg.task_record_id:
                    current_seg = seg
                    break
            
            if not current_seg:
                # 没有待处理的片段，等待状态更新
                time.sleep(3)
                continue
            
            # 如果是PROCESSING状态，轮询等待完成
            if current_seg.status == TaskStatus.PROCESSING and current_seg.task_record_id:
                task = db.query(TaskRecord).filter(TaskRecord.id == current_seg.task_record_id).first()
                if not task:
                    current_seg.status = TaskStatus.FAILED
                    composition.status = TaskStatus.FAILED
                    composition.error_msg = f"片段{current_seg.segment_index+1}任务记录丢失"
                    db.commit()
                    break
                
                poll_task(db, task)
                db.refresh(task)
                
                if task.status == TaskStatus.SUCCESS:
                    current_seg.status = TaskStatus.SUCCESS
                    current_seg.video_url = task.video_url
                    db.commit()
                    
                    # 提取最后一帧作为下一个片段的参考图（如果不是最后一个片段）
                    if current_seg.segment_index < len(segments) - 1:
                        reference_frame = _extract_last_frame(task.video_url)
                        logger.info(f"[composition {composition_id}] segment {current_seg.segment_index} completed, extracted reference frame: {reference_frame}")
                
                elif task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                    current_seg.status = TaskStatus.FAILED
                    composition.status = TaskStatus.FAILED
                    composition.error_msg = f"片段{current_seg.segment_index+1}生成失败"
                    db.commit()
                    break
            
            # 如果是PENDING状态且没有task_record_id，创建任务
            elif current_seg.status == TaskStatus.PENDING and not current_seg.task_record_id:
                seg_prompt = prompt
                if reference_frame:
                    seg_prompt = f"{prompt}, continue from the previous scene, same characters and background, seamless transition"
                
                seg_cfg = {
                    "model": model,
                    "prompt": seg_prompt,
                    "duration_seconds": current_seg.duration,
                    "resolution": resolution,
                    "ratio": ratio,
                    "generate_audio": False if (task_config.get("reference_audios") or []) else task_config.get("generate_audio", True),
                    "watermark": task_config.get("watermark", False),
                    "reference_videos": task_config.get("reference_videos") or [],
                    "reference_audios": task_config.get("reference_audios") or [],
                }
                
                # 如果有参考帧（前一片段的最后一帧），添加到reference_images
                if reference_frame:
                    seg_cfg["reference_images"] = [reference_frame]
                    logger.info(f"[composition {composition_id}] segment {current_seg.segment_index} using reference frame: {reference_frame}")
                else:
                    seg_cfg["reference_images"] = task_config.get("reference_images") or []
                
                # 真人素材参数
                if task_config.get("use_real_people"):
                    seg_cfg["use_real_people"] = True
                    if task_config.get("avatar_id"):
                        seg_cfg["avatar_id"] = task_config["avatar_id"]
                    if task_config.get("real_human_portrait_id"):
                        seg_cfg["real_human_portrait_id"] = task_config["real_human_portrait_id"]
                    if task_config.get("action_id"):
                        seg_cfg["action_id"] = task_config["action_id"]
                    if task_config.get("background_id"):
                        seg_cfg["background_id"] = task_config["background_id"]
                    if task_config.get("voice_id"):
                        seg_cfg["voice_id"] = task_config["voice_id"]
                
                # 创建任务（使用多渠道轮询）
                channels = db.query(Channel).filter(Channel.is_active == True).order_by(Channel.priority.desc()).all()
                if not channels:
                    composition.status = TaskStatus.FAILED
                    composition.error_msg = "系统当前无可用渠道"
                    db.commit()
                    break
                
                task_rec = None
                for channel in channels:
                    try:
                        task_rec = create_task_with_channel(db, user_id, seg_cfg, channel, 0)
                        if task_rec:
                            logger.info(f"[composition {composition_id}] segment {current_seg.segment_index} created on channel {channel.name}")
                            break
                    except Exception as ch_err:
                        logger.warning(f"[composition {composition_id}] segment {current_seg.segment_index} channel {channel.name} failed: {ch_err}")
                        # 检查真人错误
                        if is_real_person_error(str(ch_err)):
                            logger.info(f"[composition {composition_id}] segment {current_seg.segment_index} retrying with real people mode")
                            seg_cfg["use_real_people"] = True
                            try:
                                task_rec = create_task_with_channel(db, user_id, seg_cfg, channel, 0)
                                if task_rec:
                                    break
                            except Exception as r_err:
                                logger.warning(f"[composition {composition_id}] segment {current_seg.segment_index} real people mode also failed: {r_err}")
                
                if task_rec:
                    current_seg.task_record_id = task_rec.id
                    current_seg.status = TaskStatus.PROCESSING
                    db.commit()
                else:
                    current_seg.status = TaskStatus.FAILED
                    composition.status = TaskStatus.FAILED
                    composition.error_msg = f"片段{current_seg.segment_index+1}创建失败：所有渠道不可用"
                    db.commit()
                    break
            
            # 更新进度
            completed = sum(1 for s in segments if s.status == TaskStatus.SUCCESS)
            composition.progress = int((completed / total) * 90) if total else 0
            db.commit()
            
            time.sleep(5)
    
    except Exception as e:
        logger.exception(f"[composition_worker_serial {composition_id}] crashed")
        try:
            comp = db.query(VideoComposition).filter(VideoComposition.id == composition_id).first()
            if comp and comp.status == TaskStatus.PROCESSING:
                comp.status = TaskStatus.FAILED
                comp.error_msg = f"后台处理异常: {e}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def recover_stuck_compositions() -> None:
    """服务启动时，为所有仍在 PROCESSING 状态的 composition 重启后台线程"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        stuck = db.query(VideoComposition).filter(
            VideoComposition.status == TaskStatus.PROCESSING
        ).all()
        for comp in stuck:
            logger.info(f"[recover] restarting worker for composition {comp.id}")
            
            # 提取第一个segment的model信息
            segments = db.query(VideoSegment).filter(
                VideoSegment.composition_id == comp.id
            ).order_by(VideoSegment.segment_index).all()
            
            if segments and segments[0].task_record_id:
                task_rec = db.query(TaskRecord).filter(TaskRecord.id == segments[0].task_record_id).first()
                model = task_rec.endpoint_id if task_rec else "seedance2.0-fast"
            else:
                model = "seedance2.0-fast"
            
            # 重新构建task_config
            task_config = {
                "generate_audio": True,
                "watermark": False,
                "use_real_people": False,
            }
            
            t = threading.Thread(
                target=_composition_worker_serial,
                args=(comp.id, comp.prompt or "", model, comp.resolution, comp.ratio, task_config, comp.user_id),
                daemon=True
            )
            t.start()
    except Exception:
        logger.exception("recover_stuck_compositions failed")
    finally:
        db.close()


def cleanup_old_segments(max_age_seconds: int = 86400) -> None:
    """删除超过 max_age_seconds 的片段视频文件及其 VideoSegment 记录"""
    from database import SessionLocal, TaskStatus
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow().timestamp() - max_age_seconds
        # 只清理已完成、已失败或已取消的composition关联的片段
        old_segs = db.query(VideoSegment).join(
            VideoComposition, VideoSegment.composition_id == VideoComposition.id
        ).filter(
            VideoComposition.created_at != None,
            VideoComposition.status.in_([
                TaskStatus.SUCCESS, 
                TaskStatus.FAILED, 
                TaskStatus.CANCELLED,
                TaskStatus.EXPIRED
            ])
        ).all()

        deleted = 0
        for seg in old_segs:
            comp = db.query(VideoComposition).filter(VideoComposition.id == seg.composition_id).first()
            if not comp or not comp.created_at:
                continue
            age = datetime.utcnow().timestamp() - comp.created_at.timestamp()
            if age < max_age_seconds:
                continue
            # 只删除本地文件，跳过外部URL
            if seg.video_url and seg.video_url.startswith("/"):
                local = pathlib.Path(seg.video_url.lstrip("/"))
                if local.exists():
                    local.unlink(missing_ok=True)
                    deleted += 1
            db.delete(seg)
        db.commit()
        if deleted:
            logger.info(f"[cleanup] removed {deleted} expired segment files (>{max_age_seconds}s old)")
    except Exception:
        logger.exception("cleanup_old_segments failed")
    finally:
        db.close()


def cleanup_old_compositions(max_age_seconds: int = 86400) -> None:
    """删除超过 max_age_seconds 的长视频（完整视频）记录及其视频文件"""
    from database import SessionLocal, TaskStatus
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # 只清理已完成、已失败或已取消的任务，跳过正在处理的任务
        old_comps = db.query(VideoComposition).filter(
            VideoComposition.created_at != None,
            VideoComposition.status.in_([
                TaskStatus.SUCCESS, 
                TaskStatus.FAILED, 
                TaskStatus.CANCELLED,
                TaskStatus.EXPIRED
            ])
        ).all()

        deleted_comp = 0
        deleted_seg = 0
        for comp in old_comps:
            age = (now - comp.created_at).total_seconds()
            if age < max_age_seconds:
                continue
            
            # 只删除本地文件，跳过外部URL
            if comp.final_video_url and comp.final_video_url.startswith("/"):
                local = pathlib.Path(comp.final_video_url.lstrip("/"))
                if local.exists():
                    local.unlink(missing_ok=True)
            
            segs = db.query(VideoSegment).filter(
                VideoSegment.composition_id == comp.id
            ).all()
            for seg in segs:
                # 只删除本地文件，跳过外部URL
                if seg.video_url and seg.video_url.startswith("/"):
                    local = pathlib.Path(seg.video_url.lstrip("/"))
                    if local.exists():
                        local.unlink(missing_ok=True)
                db.delete(seg)
                deleted_seg += 1
            
            db.delete(comp)
            deleted_comp += 1
        
        db.commit()
        if deleted_comp or deleted_seg:
            logger.info(f"[cleanup] removed {deleted_comp} expired compositions and {deleted_seg} segment records (>{max_age_seconds}s old)")
    except Exception:
        logger.exception("cleanup_old_compositions failed")
    finally:
        db.close()


def cleanup_old_tasks(max_age_seconds: int = 86400) -> None:
    """删除超过 max_age_seconds 的普通视频任务记录及其视频文件"""
    from database import SessionLocal, TaskRecord, TaskStatus
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # 只清理已完成、已失败或已取消的任务
        old_tasks = db.query(TaskRecord).filter(
            TaskRecord.created_at != None,
            TaskRecord.status.in_([
                TaskStatus.SUCCESS, 
                TaskStatus.FAILED, 
                TaskStatus.CANCELLED,
                TaskStatus.EXPIRED
            ])
        ).all()

        deleted = 0
        for task in old_tasks:
            age = (now - task.created_at).total_seconds()
            if age < max_age_seconds:
                continue
            
            # 只删除本地文件，跳过外部URL
            if task.video_url and task.video_url.startswith("/"):
                local = pathlib.Path(task.video_url.lstrip("/"))
                if local.exists():
                    local.unlink(missing_ok=True)
            
            db.delete(task)
            deleted += 1
        
        db.commit()
        if deleted:
            logger.info(f"[cleanup] removed {deleted} expired task records (>{max_age_seconds}s old)")
    except Exception:
        logger.exception("cleanup_old_tasks failed")
    finally:
        db.close()


def poll_video_composition(db: Session, composition_id: int) -> dict:
    """只读数据库状态，不做任何阻塞操作"""
    composition = db.query(VideoComposition).filter(
        VideoComposition.id == composition_id
    ).first()

    if not composition:
        return {"success": False, "error": "Composition not found"}

    segments = db.query(VideoSegment).filter(
        VideoSegment.composition_id == composition_id
    ).order_by(VideoSegment.segment_index).all()

    total = len(segments)
    completed = sum(1 for s in segments if s.status == TaskStatus.SUCCESS)

    status_str = composition.status.value if hasattr(composition.status, 'value') else str(composition.status)

    return {
        "success": True,
        "status": status_str,
        "composition_id": composition.id,
        "video_url": composition.final_video_url,
        "prompt": composition.prompt,
        "progress": composition.progress or 0,
        "total_duration": composition.total_duration,
        "completed_segments": completed,
        "total_segments": total,
        "error_msg": composition.error_msg,
    }


def delete_remote_task(db: Session, channel_id: int, external_task_id: str) -> bool:
    """删除火山引擎上的任务内容"""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        logger.warning(f"[delete_remote_task] Channel {channel_id} not found")
        return False

    try:
        api_url = channel.task_url or (channel.api_base_url.rstrip('/') + '/contents/generations/tasks')
        delete_url = f"{api_url.rstrip('/')}/api/v3/contents/generations/tasks/{external_task_id}"
        
        headers = {"Content-Type": "application/json"}
        timestamp = str(int(time.time()))
        
        # 构建认证头
        if channel.api_key_encrypted:
            api_key = decrypt_value(channel.api_key_encrypted)
            headers["Authorization"] = f"Bearer {api_key}"
        elif channel.ak_encrypted and channel.sk_encrypted:
            ak = decrypt_value(channel.ak_encrypted)
            sk = decrypt_value(channel.sk_encrypted)
            signature = generate_signature(ak, sk, timestamp, "DELETE", f"/api/v3/contents/generations/tasks/{external_task_id}", "")
            headers["X-Token-Ak"] = ak
            headers["X-Token-Timestamp"] = timestamp
            headers["X-Token-Signature"] = signature
        else:
            logger.warning(f"[delete_remote_task] No credentials for channel {channel.name}")
            return False

        res = requests.delete(delete_url, headers=headers, timeout=30)
        logger.info(f"[delete_remote_task] Deleted remote task {external_task_id}, status: {res.status_code}")
        
        if res.status_code in [200, 204, 404]:
            return True
        else:
            logger.error(f"[delete_remote_task] Failed to delete remote task {external_task_id}: {res.text}")
            return False
            
    except Exception as e:
        logger.error(f"[delete_remote_task] Error deleting remote task {external_task_id}: {str(e)}")
        return False


def get_video_composition(db: Session, composition_id: int, user_id: int) -> VideoComposition | None:
    """获取视频合成任务"""
    return db.query(VideoComposition).filter(
        VideoComposition.id == composition_id,
        VideoComposition.user_id == user_id
    ).first()