from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db, Endpoint, Channel, User, EndpointType
from middleware.auth_middleware import get_current_user
import requests
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["optimize"])


class OptimizePromptRequest(BaseModel):
    prompt: str
    model: str = ""  # 可选的接入点ID，不传则自动选择推理接入点


class OptimizePromptResponse(BaseModel):
    success: bool
    optimized_prompt: str = ""
    message: str = ""


def get_inference_endpoint(db: Session, specified_model: str = "") -> tuple[Endpoint, Channel] | None:
    """
    获取推理接入点
    优先使用用户指定的接入点（如果它是推理类型），否则查找默认推理接入点
    """
    endpoint = None
    channel = None

    # 如果用户指定了模型，尝试使用它
    if specified_model:
        endpoint = db.query(Endpoint).filter(
            Endpoint.endpoint_id == specified_model,
            Endpoint.is_active == True
        ).first()

        if endpoint:
            # 检查是否是推理类型
            if endpoint.type == EndpointType.INFERENCE:
                channel = db.query(Channel).filter(
                    Channel.id == endpoint.channel_id,
                    Channel.is_active == True
                ).first()
                if channel:
                    return endpoint, channel
            else:
                logger.warning(f"指定的接入点 {specified_model} 不是推理类型 (type={endpoint.type})，将尝试查找推理接入点")

    # 查找推理类型的接入点：优先 is_default=True，其次取最新添加的（id 最大）
    inference_endpoint = db.query(Endpoint).filter(
        Endpoint.type == EndpointType.INFERENCE,
        Endpoint.is_active == True
    ).order_by(Endpoint.is_default.desc(), Endpoint.id.desc()).first()

    if inference_endpoint:
        channel = db.query(Channel).filter(
            Channel.id == inference_endpoint.channel_id,
            Channel.is_active == True
        ).first()
        if channel:
            logger.info(f"使用推理接入点: {inference_endpoint.endpoint_id} ({inference_endpoint.endpoint_name})")
            return inference_endpoint, channel

    # 如果没有找到推理接入点，尝试使用任何活跃的接入点
    any_endpoint = db.query(Endpoint).filter(
        Endpoint.is_active == True
    ).first()

    if any_endpoint:
        channel = db.query(Channel).filter(
            Channel.id == any_endpoint.channel_id,
            Channel.is_active == True
        ).first()
        if channel:
            logger.info(f"没有找到推理接入点，使用通用接入点: {any_endpoint.endpoint_id}")
            return any_endpoint, channel

    return None, None


@router.post("/optimize-prompt", response_model=OptimizePromptResponse)
async def optimize_prompt(
    request: OptimizePromptRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    使用推理模型优化提示词
    """

    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")

    try:
        # 调用推理模型优化提示词
        optimized_prompt = await call_inference_model(request, db)

        return {
            "success": True,
            "optimized_prompt": optimized_prompt,
            "message": "提示词优化成功"
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"提示词优化失败: {error_msg}")
        # 如果是服务内部错误，返回更友好的提示
        if "InternalServiceError" in error_msg or "InternalServerError" in error_msg:
            raise HTTPException(status_code=500, detail="提示词优化失败：服务暂时不可用，请稍后重试")
        raise HTTPException(status_code=500, detail=f"提示词优化失败: {error_msg}")


async def call_inference_model(request: OptimizePromptRequest, db: Session) -> str:
    """
    调用推理模型优化提示词
    使用渠道配置的 API URL
    """
    # 获取合适的推理接入点
    endpoint, channel = get_inference_endpoint(db, request.model)

    if not endpoint or not channel:
        raise Exception("未找到可用的推理接入点，请联系管理员配置")

    # 获取对应的渠道
    logger.info(f"使用接入点: {endpoint.endpoint_id} (类型: {endpoint.type})")
    logger.info(f"使用渠道: {channel.name}")
    logger.info(f"渠道 API Base URL: {channel.api_base_url}")

    # 解密API Key
    from services.auth_service import decrypt_value
    api_key = decrypt_value(channel.api_key_encrypted) if channel.api_key_encrypted else None
    if not api_key:
        raise Exception(f"渠道 {channel.name} 未配置API Key")

    # 使用渠道配置的 API 基础 URL（确保包含 /api/v3 路径）
    base_url = channel.api_base_url.rstrip('/') if channel.api_base_url else "https://ark.cn-beijing.volces.com/api/v3"
    if "/api/v3" not in base_url:
        base_url = f"{base_url}/api/v3"
    url = f"{base_url}/chat/completions"

    logger.info(f"调用推理模型 API URL: {url}")
    logger.info(f"使用模型: {endpoint.endpoint_id}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # 构建优化提示词的系统提示词
    system_prompt = """你是一个专业的AI提示词优化助手。你的任务是将用户输入的原始提示词优化为更详细、更有效的AI生成提示词。

优化规则：
1. 保持原始提示词的核心含义
2. 添加更多细节描述，使提示词更具体
3. 可以包括风格、氛围、画面质量等要求
4. 返回优化后的提示词，不要包含任何额外的解释或说明"""

    data = {
        "model": endpoint.endpoint_id,  # 使用接入点ID
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"请优化以下提示词：{request.prompt}"
            }
        ]
    }

    logger.info(f"发送请求到 {url}")
    logger.info(f"请求数据: model={data['model']}, messages count={len(data['messages'])}")

    # 调用推理模型API - 添加重试机制
    import time
    max_retries = 3
    retry_delay = 2  # 秒

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=60)
            break
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                logger.warning(f"第 {attempt+1} 次请求超时，正在重试...")
                time.sleep(retry_delay)
                continue
            raise Exception("API调用超时，请稍后重试")
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                logger.warning(f"第 {attempt+1} 次请求失败 ({str(e)})，正在重试...")
                time.sleep(retry_delay)
                continue
            raise Exception(f"API调用失败: {str(e)}")

    logger.info(f"响应状态码: {response.status_code}")
    logger.info(f"响应内容: {response.text[:1000]}")

    if response.status_code != 200:
        error_detail = response.text
        try:
            error_json = response.json()
            if "error" in error_json:
                error_detail = error_json["error"].get("message", error_json["error"].get("code", error_detail))
                error_code = error_json["error"].get("code", "")
                # 如果是内部服务错误，尝试重试
                if "InternalServiceError" in error_code or "InternalServerError" in error_code:
                    logger.warning(f"遇到内部服务错误，尝试重试...")
                    time.sleep(retry_delay)
                    response = requests.post(url, headers=headers, json=data, timeout=60)
                    logger.info(f"重试后状态码: {response.status_code}")
                    if response.status_code == 200:
                        # 重试成功，继续处理
                        pass
                    else:
                        raise Exception(f"API调用失败 (HTTP {response.status_code}): {error_detail}")
        except:
            pass
        raise Exception(f"API调用失败 (HTTP {response.status_code}): {error_detail}")

    result = response.json()

    # 提取优化后的提示词（标准 chat completions 格式，兼容推理模型）
    if "choices" in result and len(result["choices"]) > 0:
        msg = result["choices"][0]["message"]
        optimized_prompt = (msg.get("content") or msg.get("reasoning_content") or "").strip()
        logger.info(f"优化成功: {optimized_prompt[:100]}...")
        return optimized_prompt
    else:
        raise Exception(f"响应格式错误: {result}")
