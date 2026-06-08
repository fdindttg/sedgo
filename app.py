from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, UploadFile, File as FastAPIFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import gradio as gr
import requests
import hmac
import hashlib
import time
import threading
import os
import uvicorn

from database import engine, Base, get_db, SessionLocal
from routers import auth, subscriptions, points, tasks, channels, admin, images, optimize, asset_library, payments, contact, drama
from config import DEFAULT_FILE_URL, DEFAULT_TASK_URL, DEFAULT_LIST_URL

# 直接使用 config.py 中的配置（已从 .env 文件加载）
FILE_URL = DEFAULT_FILE_URL
TASK_BASE_URL = DEFAULT_TASK_URL
LIST_FILES_URL = DEFAULT_LIST_URL


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_defaults()
    # Migrations: add merged_video_url to drama_episodes if not exists
     with engine.connect() as conn:
         try:
             conn.exec_driver_sql(
                 "ALTER TABLE drama_episodes ADD COLUMN merged_video_url VARCHAR(500)"
             )
             conn.commit()
             print("[Migrate] Added merged_video_url column to drama_episodes")
         except Exception:
             pass  # Column already exists
    # 启动高并发任务轮询服务
    from services.poll_service import ensure_poll_service_started, stop_poll_service
    ensure_poll_service_started()
    print(f"[Seed] High-concurrency poll service started")
    yield
    # 停止轮询服务
    stop_poll_service()
    print(f"[Seed] High-concurrency poll service stopped")
    engine.dispose()


def _seed_defaults():
    from sqlalchemy.orm import Session
    from database import SubscriptionPlan, Channel, PointsConfig, User, UserRole, UserStatus, SystemConfig, Endpoint, EndpointType
    from datetime import datetime, timezone, timedelta
    from services.auth_service import hash_password
    from services.concurrency_service import initialize_system_config

    db: Session = SessionLocal()
    try:
        if not db.query(User).filter(User.role == UserRole.ADMIN).count():
            admin = User(
                email="admin@seedance.com",
                password_hash=hash_password("admin123"),
                display_name="Admin",
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            db.add(admin)
            db.commit()
            print(f"[Seed] Admin user created: admin@seedance.com / admin123")

        if not db.query(SubscriptionPlan).count():
            # 定价基准：BytePlus官方价 × 平台溢价
            # 月付溢价200%（3x成本），年付30-35%折扣对应溢价约100%（2x成本）
            # 积分单价：points_per_token=10，1 token=1秒480p基准
            # 示例：720p 5秒视频 = 5×1.5×10 = 75积分
            plans = [
                SubscriptionPlan(id=1, name="免费试用", description="新用户专享体验套餐，含100积分",
                                 price_cents=0, duration_days=7, points_per_month=100,
                                 max_batch_size=1, max_concurrent_tasks=1, max_resolution="720p",
                                 annual_discount=0, sort_order=1),
                SubscriptionPlan(id=2, name="标准版", description="适合个人创作者，每月1500积分",
                                 price_cents=2999, duration_days=30, points_per_month=1500,
                                 max_batch_size=5, max_concurrent_tasks=3, max_resolution="720p",
                                 annual_discount=30, sort_order=2),
                SubscriptionPlan(id=3, name="团队版", description="适合中小型团队，每月5000积分",
                                 price_cents=7999, duration_days=30, points_per_month=5000,
                                 max_batch_size=10, max_concurrent_tasks=5, max_resolution="1080p",
                                 annual_discount=30, sort_order=3),
                SubscriptionPlan(id=4, name="团队专业版", description="适合专业团队和企业，每月12000积分",
                                 price_cents=14999, duration_days=30, points_per_month=12000,
                                 max_batch_size=20, max_concurrent_tasks=10, max_resolution="1080p",
                                 annual_discount=35, sort_order=4),
            ]
            db.add_all(plans)
            db.commit()
            print(f"[Seed] Subscription plans created")

        # 初始化系统并发配置
        initialize_system_config(db)
        print(f"[Seed] System concurrency config initialized")

        # 重启因服务重启而孤立的 composition 后台线程
        from services.task_service import recover_stuck_compositions, cleanup_old_segments, cleanup_old_compositions, cleanup_old_tasks
        recover_stuck_compositions()
        cleanup_old_segments(86400)  # 清理超过24小时的片段文件
        cleanup_old_compositions(86400)  # 清理超过24小时的完整视频记录
        cleanup_old_tasks(86400)  # 清理超过24小时的普通任务记录
        print(f"[Seed] Stuck composition recovery done")

        # 每小时定期清理过期片段、完整视频和普通任务
        def _periodic_cleanup():
            while True:
                time.sleep(3600)
                cleanup_old_segments(86400)
                cleanup_old_compositions(86400)
                cleanup_old_tasks(86400)
        threading.Thread(target=_periodic_cleanup, daemon=True).start()

        if not db.query(Channel).count():
            from services.auth_service import encrypt_value
            
            channel = Channel(
                id=1,
                name="BytePlus Default",
                provider="byteplus",
                api_base_url="https://ark.ap-southeast.bytepluses.com",
                file_url=FILE_URL,
                task_url=TASK_BASE_URL,
                api_key_encrypted=None,
                is_active=True,
                priority=10,
            )
            db.add(channel)
            db.commit()

        if not db.query(Endpoint).count():
            endpoints = [
                Endpoint(
                    channel_id=1,
                    endpoint_id="ep-20260506111316-nsx8s",
                    endpoint_name="Seedance 1.0",
                    type=EndpointType.VIDEO,
                    models=["seedance-1.0", "dreamina-seedance-2-0-20128"],
                    is_default=False,
                    is_active=True,
                ),
                Endpoint(
                    channel_id=1,
                    endpoint_id="ep-20260506113134-gct7l",
                    endpoint_name="Seedance 1.0 Fast",
                    type=EndpointType.VIDEO,
                    models=["seedance-1.0-fast", "dreamina-seedance-2-0-fast"],
                    is_default=True,
                    is_active=True,
                ),
                Endpoint(
                    channel_id=1,
                    endpoint_id="doubao-seedream-3-0-t2i-250415",
                    endpoint_name="Seedream 3.0",
                    type=EndpointType.IMAGE,
                    models=["doubao-seedream-3-0-t2i-250415"],
                    is_default=True,
                    is_active=True,
                ),
            ]
            db.add_all(endpoints)
            db.commit()
            print(f"[Seed] Default endpoints created")
        else:
            # Ensure IMAGE endpoint exists even if seeded before this change
            img_ep = db.query(Endpoint).filter(Endpoint.type == EndpointType.IMAGE).first()
            if not img_ep:
                db.add(Endpoint(
                    channel_id=1,
                    endpoint_id="doubao-seedream-3-0-t2i-250415",
                    endpoint_name="Seedream 3.0",
                    type=EndpointType.IMAGE,
                    models=["doubao-seedream-3-0-t2i-250415"],
                    is_default=True,
                    is_active=True,
                ))
                db.commit()
                print(f"[Seed] IMAGE endpoint added")

        # Clean up old deprecated endpoints
        old_endpoint = db.query(Endpoint).filter(
            Endpoint.endpoint_id == "ep-real-people-20260526"
        ).first()
        if old_endpoint:
            db.delete(old_endpoint)
            db.commit()
            print(f"[Cleanup] Removed deprecated endpoint: ep-real-people-20260526")

        if not db.query(PointsConfig).count():
            config = PointsConfig(
                points_per_token=10,
                token_unit="request",
                effective_from=datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None),
            )
            db.add(config)
            db.commit()

        # 初始化积分/秒配置（后台设置的是每秒消耗的积分）
        points_per_sec_config = db.query(SystemConfig).filter(SystemConfig.config_key == "points_per_sec").first()
        default_points_config = {
            "ep-20260506111316-nsx8s": {"label": "Seedance 2.0",      "480p": 2,   "720p": 4,   "1080p": 9},
            "ep-20260506113134-gct7l": {"label": "Seedance 2.0 Fast", "480p": 1,   "720p": 3},
            "seedance-1.5-pro":        {"label": "Seedance 1.5 Pro",  "480p": 1,   "720p": 2,   "1080p": 3},
            "seedance-1.0-pro":        {"label": "Seedance 1.0 Pro",  "480p": 1,   "720p": 2,   "1080p": 3},
            "seedance-1.0-pro-fast":   {"label": "Seedance 1.0 Fast", "480p": 0.2, "720p": 0.4, "1080p": 1},
        }
        
        if not points_per_sec_config:
            # 如果没有记录，创建新记录
            db.add(SystemConfig(
                config_key="points_per_sec",
                config_value=default_points_config,
                description="各模型在不同分辨率下每秒消耗的积分配置"
            ))
            db.commit()
            print(f"[Seed] Default points per sec config created")
        elif not points_per_sec_config.config_value or len(points_per_sec_config.config_value) == 0:
            # 如果记录存在但配置为空，更新配置
            from sqlalchemy.orm.attributes import flag_modified
            points_per_sec_config.config_value = default_points_config
            flag_modified(points_per_sec_config, "config_value")
            db.commit()
            print(f"[Seed] Updated empty points per sec config")
    finally:
        db.close()


fapp = FastAPI(title="Sedgo API", version="2.0", lifespan=lifespan)

# 请求日志中间件
from fastapi import Request
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

@fapp.middleware("http")
async def log_requests(request: Request, call_next):
    if request.method == "POST" and "/api/tasks/" in str(request.url):
        try:
            body = await request.json()
            logger.info(f"[REQUEST LOG] URL: {request.url}, Body: {body}")
            logger.info(f"[REQUEST LOG] use_real_people in request: {body.get('use_real_people')}")
        except Exception as e:
            logger.info(f"[REQUEST LOG] Failed to parse body: {e}")
    
    response = await call_next(request)
    return response

fapp.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 在 Gradio 挂载之前注册所有 API 路由
api_routers = [
    auth.router,
    subscriptions.router,
    points.router,
    tasks.router,
    channels.router,
    admin.router,
    images.router,
    optimize.router,
    asset_library.router,
    payments.router,
    contact.router,
    drama.router,
]

for router in api_routers:
    fapp.include_router(router)


@fapp.get("/api/public/site-config")
async def public_site_config():
    from database import SessionLocal, SystemConfig
    db = SessionLocal()
    try:
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "site_config").first()
        return cfg.config_value if cfg and cfg.config_value else {}
    finally:
        db.close()


@fapp.get("/api/public/points-per-sec")
async def public_points_per_sec():
    from database import SessionLocal, SystemConfig
    from routers.admin import _DEFAULT_POINTS_PER_SEC
    
    db = SessionLocal()
    try:
        # 首先获取默认配置作为基础
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_per_sec").first()
        result = cfg.config_value if (cfg and cfg.config_value) else _DEFAULT_POINTS_PER_SEC
        
        # 然后读取管理员设置的模型定价配置，覆盖默认值
        video_cfgs = db.query(SystemConfig).filter(SystemConfig.config_key.like("video_cost_%")).all()
        for video_cfg in video_cfgs:
            # 跳过默认配置
            if video_cfg.config_key.startswith("video_cost_points_"):
                continue
            # 解析 model_id 和 resolution
            parts = video_cfg.config_key.split("_")
            if len(parts) >= 4:
                model_id = "_".join(parts[2:-1])
                resolution = parts[-1]
                # 如果模型已在结果中，更新分辨率配置
                if model_id in result:
                    result[model_id][resolution] = video_cfg.config_value
        
        return result
    finally:
        db.close()
@fapp.get("/api/public/models")
async def public_models():
    from database import SessionLocal, SystemConfig
    from routers.admin import _DEFAULT_MODELS_CONFIG
    db = SessionLocal()
    try:
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "models_config").first()
        return cfg.config_value if cfg and cfg.config_value else _DEFAULT_MODELS_CONFIG
    finally:
        db.close()

def _get_byteplus_file_headers() -> dict:
    from database import SessionLocal, Channel
    from services.auth_service import decrypt_value
    db = SessionLocal()
    try:
        channel = db.query(Channel).filter(Channel.is_active == True).order_by(Channel.priority.desc()).first()
        if channel and channel.api_key_encrypted:
            api_key = decrypt_value(channel.api_key_encrypted)
            return {"Authorization": f"Bearer {api_key}"}
    except Exception:
        pass
    finally:
        db.close()
    return {}


# ── 文件辅助函数 ──────────────────────────────────────────────

def _decode_user_id(authorization: str):
    from jose import jwt as jose_jwt, JWTError
    from config import SECRET_KEY, JWT_ALGORITHM
    token = authorization.replace("Bearer ", "").strip()
    try:
        payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ── 文件列表：从本地 DB 查询 ──────────────────────────────────────
@fapp.get("/api/files/list")
async def api_list_files(authorization: str = Header(None)):
    if not authorization:
        return JSONResponse({"success": False, "message": "Missing Authorization header"}, status_code=401)
    user_id = _decode_user_id(authorization)
    if not user_id:
        return JSONResponse({"success": False, "message": "Invalid token"}, status_code=401)
    try:
        from database import UploadedFile
        db = SessionLocal()
        try:
            local_files = db.query(UploadedFile).filter(
                UploadedFile.user_id == user_id
            ).order_by(UploadedFile.created_at.desc()).limit(200).all()
        finally:
            db.close()
        data = [
            {
                "id": f.file_id,
                "file_id": f.file_id,
                "filename": f.filename or f.file_id,
                "mime_type": f.mime_type or "",
                "bytes": 0,
                "url": f.url if (f.url and f.url.startswith("/static/")) else f"/api/files/proxy/{f.file_id}",
                "purpose": f.purpose or "user_data",
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in local_files
        ]
        return {"success": True, "data": data}
    except Exception as e:
        import traceback
        return JSONResponse({"success": False, "message": str(e), "detail": traceback.format_exc()}, status_code=500)


# ── 代理：文件内容 ──────────────────────────────────────────────
@fapp.get("/api/files/proxy/{file_id}")
async def api_proxy_file(file_id: str):
    from fastapi.responses import StreamingResponse, FileResponse
    import pathlib
    try:
        from database import UploadedFile
        db = SessionLocal()
        try:
            record = db.query(UploadedFile).filter(UploadedFile.file_id == file_id).first()
            if record and record.url and record.url.startswith("/static/uploads/"):
                local_path = pathlib.Path(record.url.lstrip("/"))
                if local_path.exists():
                    return FileResponse(str(local_path))
        finally:
            db.close()
    except Exception:
        pass
    bp_headers = _get_byteplus_file_headers()
    if not bp_headers:
        return JSONResponse({"error": "No API key configured"}, status_code=500)
    try:
        resp = requests.get(f"{FILE_URL}/{file_id}/content", headers=bp_headers, timeout=30, stream=True)
        if resp.status_code == 200:
            return StreamingResponse(resp.iter_content(chunk_size=8192), media_type=resp.headers.get("Content-Type", "application/octet-stream"))
        resp2 = requests.get(f"{FILE_URL}/{file_id}", headers=bp_headers, timeout=15)
        if resp2.status_code == 200:
            dl_url = resp2.json().get("url") or resp2.json().get("download_url", "")
            if dl_url:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(dl_url)
        return JSONResponse({"error": "File not available"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 上传文件：保存本地副本 + BytePlus Files API ───────────────────
@fapp.post("/api/files/upload")
async def api_upload_file(authorization: str = Header(None), file: UploadFile = FastAPIFile(...)):
    if not authorization:
        return JSONResponse({"success": False, "message": "Missing Authorization header"}, status_code=401)
    user_id = _decode_user_id(authorization)
    if not user_id:
        return JSONResponse({"success": False, "message": "Invalid token"}, status_code=401)
    try:
        import uuid, pathlib
        content = await file.read()

        # 保存本地副本供缩略图展示
        uploads_dir = pathlib.Path("static/uploads")
        uploads_dir.mkdir(exist_ok=True)
        suffix = pathlib.Path(file.filename or "file").suffix or ""
        local_name = f"{uuid.uuid4().hex}{suffix}"
        local_path = uploads_dir / local_name
        local_path.write_bytes(content)
        local_url = f"/static/uploads/{local_name}"

        # 上传到 BytePlus Files API
        headers = _get_byteplus_file_headers()
        file_id = ""
        if headers:
            res = requests.post(
                FILE_URL,
                headers=headers,
                data={"purpose": "user_data"},
                files={"file": (file.filename, content, file.content_type)},
                timeout=120,
            )
            if res.status_code == 200:
                file_id = res.json().get("id", "")

        if not file_id:
            import uuid as _uuid
            file_id = f"local-{_uuid.uuid4().hex}"

        from database import UploadedFile
        db = SessionLocal()
        try:
            record = UploadedFile(
                user_id=int(user_id),
                file_id=file_id,
                filename=file.filename,
                mime_type=file.content_type or "",
                url=local_url,
                purpose="user_data",
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        return {
            "success": True,
            "data": {
                "id": file_id,
                "file_id": file_id,
                "filename": file.filename,
                "mime_type": file.content_type or "",
                "url": local_url,
                "local_url": local_url,
            },
        }
    except Exception as e:
        import traceback
        return JSONResponse({"success": False, "message": str(e), "detail": traceback.format_exc()}, status_code=500)


# ── 删除文件 ──────────────────────────────────────────────────────
@fapp.delete("/api/files/{file_id}")
async def api_delete_file(file_id: str, authorization: str = Header(None)):
    if not authorization:
        return JSONResponse({"success": False, "message": "Missing Authorization header"}, status_code=401)
    user_id = _decode_user_id(authorization)
    if not user_id:
        return JSONResponse({"success": False, "message": "Invalid token"}, status_code=401)
    try:
        import pathlib
        from database import UploadedFile
        db = SessionLocal()
        try:
            record = db.query(UploadedFile).filter(
                UploadedFile.file_id == file_id,
                UploadedFile.user_id == user_id,
            ).first()
            if record:
                if record.url and record.url.startswith("/static/uploads/"):
                    local_path = pathlib.Path(record.url.lstrip("/"))
                    local_path.unlink(missing_ok=True)
                db.delete(record)
                db.commit()
        finally:
            db.close()
        try:
            requests.delete(f"{FILE_URL}/{file_id}", headers=_get_byteplus_file_headers(), timeout=10)
        except Exception:
            pass
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)




# ── 代理：创建任务 ──────────────────────────────────────────────
# 注意：这个路由被注释掉，因为 /api/tasks 开头的路由已经在 tasks.py 中定义
# 如果需要代理功能，请使用不同的路径前缀
# @fapp.post("/api/proxy/tasks")
# async def api_proxy_create_task(request_data: dict, authorization: str = Header(None)):
#     ...

# ── 代理：查询任务 ──────────────────────────────────────────────
# 注意：这个路由被注释掉，因为 /api/tasks/{task_id} 会匹配 /api/tasks/endpoints
# 导致 endpoints 接口返回 401 错误
# @fapp.get("/api/proxy/tasks/{task_id}")
# async def api_proxy_get_task(task_id: str, authorization: str = Header(None)):
#     ...

# ── Gradio UI ──────────────────────────────────────────────────
def upload_file_to_server(api_key, file_path):
    if not file_path or not api_key:
        return {"success": False, "message": "参数错误"}
    try:
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        res = requests.post(
            FILE_URL, headers=headers, data={"purpose": "user_data"},
            files={"file": (os.path.basename(file_path), open(file_path, "rb"))},
            timeout=120,
        )
        if res.status_code == 200:
            return {"success": True, "data": res.json()}
        return {"success": False, "message": f"上传失败: {res.text}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def submit_video_task(api_key, prompt, ratio, duration, resolution, model, img_url=""):
    try:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key.strip()}"}
        content = [{"type": "text", "text": prompt}]
        if img_url:
            content.append({"type": "image_url", "image_url": {"url": img_url}})

        model_map = {
            "seedance2.0-fast": "dreamina-seedance-2-0-fast",
            "seedance2.0": "dreamina-seedance-2-0-20128",
        }
        actual_ratio = ratio if ratio != "智能比例" else "16:9"
        actual_duration = int(duration) if duration != "智能时长" else 5

        payload = {
            "model": model_map.get(model, "dreamina-seedance-2-0-20128"),
            "content": content,
            "generate_audio": True,
            "ratio": actual_ratio,
            "duration": actual_duration,
            "resolution": resolution,
            "watermark": False,
        }
        res = requests.post(TASK_BASE_URL, headers=headers, json=payload, timeout=30)
        result = res.json()
        if "id" in result:
            return {"success": True, "task_id": result["id"]}
        return {"success": False, "message": result.get("message", "创建任务失败")}
    except Exception as e:
        return {"success": False, "message": str(e)}

def check_task_status(api_key, task_id):
    try:
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        res = requests.get(f"{TASK_BASE_URL}/{task_id}", headers=headers, timeout=10)
        result = res.json()
        if result.get("status") == "SUCCESS":
            return {"success": True, "status": "SUCCESS", "video_url": result.get("video_url")}
        elif result.get("status") == "FAILED":
            return {"success": True, "status": "FAILED", "message": result.get("error_msg", "生成失败")}
        return {"success": True, "status": "PROCESSING", "progress": result.get("progress", 0)}
    except Exception as e:
        return {"success": False, "message": str(e)}

def list_files(api_key):
    try:
        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        res = requests.get(LIST_FILES_URL, headers=headers, timeout=10)
        if res.status_code == 200:
            return {"success": True, "data": res.json().get("data", [])}
        return {"success": False, "message": "获取文件列表失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}

with gr.Blocks(title="Sedgo - AI视频生成") as demo:
    with gr.Tab("视频生成"):
        api_key_input = gr.Textbox(label="API Key", type="password", placeholder="请输入您的API Key")
        prompt_input = gr.Textbox(label="视频描述", placeholder="描述你想要生成的视频...", lines=3)
        with gr.Row():
            ratio_dropdown = gr.Dropdown(
                choices=["智能比例", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
                value="智能比例", label="视频比例"
            )
            resolution_dropdown = gr.Dropdown(choices=["480p", "720p", "1080p"], value="720p", label="分辨率")
            model_dropdown = gr.Dropdown(choices=["seedance2.0-fast", "seedance2.0"], value="seedance2.0-fast", label="模型")
        with gr.Row():
            duration_input = gr.Textbox(label="视频时长（秒）", value="5", placeholder="5 或 智能时长")
            num_outputs = gr.Slider(minimum=1, maximum=8, value=1, step=1, label="生成数量")
        img_upload = gr.File(label="参考图片", file_types=["image"])
        status_output = gr.Textbox(label="状态", interactive=False)
        video_output = gr.Video(label="生成的视频")
        submit_btn = gr.Button("生成视频")

        def generate_video(api_key, prompt, ratio, resolution, model, duration, num, img):
            yield "正在验证参数...", None
            if not api_key.strip():
                yield "❌ 请输入API Key", None; return
            if not prompt.strip():
                yield "❌ 请输入视频描述", None; return
            if duration != "智能时长":
                try:
                    d = int(duration)
                    if not 1 <= d <= 60:
                        yield "❌ 时长必须在1-60秒之间", None; return
                except:
                    yield "❌ 时长必须是数字或'智能时长'", None; return

            img_url = ""
            if img:
                r = upload_file_to_server(api_key, img.name)
                if r["success"]:
                    img_url = r["data"].get("url", "")
                    yield "✅ 图片上传成功\n正在创建任务...", None
                else:
                    yield f"❌ 图片上传失败: {r['message']}", None; return

            results = []
            for i in range(int(num)):
                if num > 1:
                    yield f"🎬 正在创建第 {i+1}/{int(num)} 个视频任务...", None
                task_result = submit_video_task(api_key, prompt, ratio, duration, resolution, model, img_url)
                if not task_result["success"]:
                    yield f"❌ 任务 {i+1} 创建失败: {task_result['message']}", None; return
                task_id = task_result["task_id"]
                yield f"✅ 任务 {i+1} 创建成功 ID: {task_id}\n正在生成视频...", None
                for _ in range(120):
                    status = check_task_status(api_key, task_id)
                    if not status["success"]:
                        yield f"❌ 查询失败: {status['message']}", None; return
                    if status["status"] == "SUCCESS":
                        results.append(status["video_url"])
                        yield ("🎉 视频生成完成！" if int(num) == 1 else f"🎉 第 {i+1}/{int(num)} 个视频生成完成！"), status["video_url"]
                        break
                    if status["status"] == "FAILED":
                        yield f"❌ 第 {i+1} 个视频生成失败: {status.get('message','')}", None; return
                    yield f"⏳ 生成中 {status.get('progress',0)}%...", None
                    time.sleep(2)
                else:
                    yield f"⏰ 任务 {i+1} 超时", None; return
            if int(num) > 1:
                yield f"🎉 全部 {int(num)} 个视频生成完成！\n{', '.join(results)}", None

        submit_btn.click(
            generate_video,
            inputs=[api_key_input, prompt_input, ratio_dropdown, resolution_dropdown,
                    model_dropdown, duration_input, num_outputs, img_upload],
            outputs=[status_output, video_output],
        )

    with gr.Tab("素材库"):
        api_key_mat = gr.Textbox(label="API Key", type="password")
        refresh_btn = gr.Button("刷新素材库")
        file_upload_mat = gr.File(label="选择文件", file_types=["image"])
        upload_mat_btn = gr.Button("上传素材")
        material_list = gr.JSON(label="素材列表")

        refresh_btn.click(
            lambda k: list_files(k) if k.strip() else {"error": "请输入API Key"},
            inputs=api_key_mat, outputs=material_list
        )
        upload_mat_btn.click(
            lambda k, f: upload_file_to_server(k, f.name) if k.strip() and f else {"error": "请输入API Key和文件"},
            inputs=[api_key_mat, file_upload_mat], outputs=material_list
        )

# 挂载 Gradio 到 /gradio 路径
fapp = gr.mount_gradio_app(fapp, demo, path="/gradio")

# 挂载静态文件服务（放在 API 路由之后，catch-all 之前）
fapp.mount("/static", StaticFiles(directory="static", html=False, check_dir=False), name="static")
fapp.mount("/pages", StaticFiles(directory="pages", html=True, check_dir=False), name="pages")
os.makedirs("outputs", exist_ok=True)
fapp.mount("/outputs", StaticFiles(directory="outputs", html=False, check_dir=False), name="outputs")

# 页面路由重定向
@fapp.get("/admin")
async def redirect_admin():
    return RedirectResponse(url="/pages/admin.html")

@fapp.get("/profile")
async def redirect_profile():
    return RedirectResponse(url="/pages/profile.html")

@fapp.get("/")
async def redirect_root():
    return RedirectResponse(url="/pages/index.html")

if __name__ == "__main__":
    uvicorn.run(fapp, host="0.0.0.0", port=8908)
