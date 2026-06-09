from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db, User, Endpoint, Channel, EndpointType
from middleware.auth_middleware import get_current_user
import uuid
import os
import time
import requests
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["images"])


def _compute_image_size(ratio: str, resolution: str) -> str:
    """根据比例和分辨率计算图片像素尺寸，返回 "WxH" 格式"""
    # 短边像素
    short_side = {"480p": 480, "720p": 720, "1080p": 1080}.get(resolution, 720)
    
    ratio_map = {
        "16:9": (16/9, True),   # width > height
        "4:3":  (4/3, True),
        "1:1":  (1.0, True),
        "3:4":  (3/4, False),   # width < height, short side is width
        "9:16": (9/16, False),
    }
    r, wide = ratio_map.get(ratio, (16/9, True))
    
    if wide:
        w = round(short_side * r)
        h = short_side
    else:
        w = short_side
        h = round(short_side / r)
    
    return f"{w}x{h}"


@router.get("")
async def api_list_images(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import TaskRecord
    image_endpoint_ids = {
        ep.endpoint_id for ep in db.query(Endpoint).filter(
            Endpoint.type == EndpointType.IMAGE, Endpoint.is_active == True
        ).all()
    }

    all_tasks = db.query(TaskRecord).filter(
        TaskRecord.user_id == current_user.id
    ).order_by(TaskRecord.created_at.desc()).all()

    image_tasks = [t for t in all_tasks if (t.model or "") in image_endpoint_ids]

    items = []
    for t in image_tasks:
        items.append({
            "task_id": t.external_task_id,
            "id": t.id,
            "prompt": t.prompt,
            "status": t.status.value,
            "progress": t.progress,
            "image_url": t.video_url,
            "error_msg": t.error_msg,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"items": items, "total": len(items)}


class ImageGenerateRequest(BaseModel):
    prompt: str
    endpoint_id: str = ""
    size: str = ""
    ratio: str = "16:9"
    resolution: str = "720p"
    reference_images: list[str] = []


@router.post("/generate")
async def api_generate_image(
    request: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    # 查找合适的图片生成接入点
    endpoint = None
    channel = None

    if request.endpoint_id:
        endpoint = db.query(Endpoint).filter(
            Endpoint.endpoint_id == request.endpoint_id,
            Endpoint.is_active == True
        ).first()

        if endpoint and endpoint.type == EndpointType.IMAGE:
            channel = db.query(Channel).filter(
                Channel.id == endpoint.channel_id,
                Channel.is_active == True
            ).first()

    # 如果没有指定或无效，查找默认的图片接入点
    if not endpoint or not channel:
        endpoint = db.query(Endpoint).filter(
            Endpoint.type == EndpointType.IMAGE,
            Endpoint.is_active == True
        ).first()

        if endpoint:
            channel = db.query(Channel).filter(
                Channel.id == endpoint.channel_id,
                Channel.is_active == True
            ).first()

    if not endpoint or not channel:
        raise HTTPException(status_code=400, detail="未找到可用的图片生成接入点")

    # 积分检查和扣除
    from services.point_service import calculate_points_cost, calculate_tokens_cost, consume_points
    tokens = calculate_tokens_cost(db, {"mode": "image", "size": request.size})
    points_cost = calculate_points_cost(db, tokens)
    if not consume_points(db, current_user.id, points_cost, f"图片生成: {request.prompt[:50]}"):
        from services.point_service import get_user_points
        balance = get_user_points(db, current_user.id)
        raise HTTPException(status_code=402, detail=f"INSUFFICIENT_POINTS:{points_cost}:{balance}")

    # 解密API Key
    from services.auth_service import decrypt_value
    api_key = decrypt_value(channel.api_key_encrypted) if channel.api_key_encrypted else None
    if not api_key:
        raise HTTPException(status_code=400, detail=f"渠道 {channel.name} 未配置API Key")

    # 构建API URL
    base_url = channel.api_base_url.rstrip('/') if channel.api_base_url else "https://ark.ap-southeast.bytepluses.com"
    if "/api/v3" not in base_url:
        base_url = f"{base_url}/api/v3"
    url = f"{base_url}/images/generations"

    logger.info(f"图片生成API URL: {url}")
    logger.info(f"使用接入点: {endpoint.endpoint_id}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # 根据比例和分辨率计算像素尺寸
    size_map = _compute_image_size(request.ratio, request.resolution)
    
    # 构建请求体
    payload = {
        "model": endpoint.endpoint_id,
        "prompt": request.prompt,
        "size": request.size or size_map,
        "n": 1,
        "response_format": "url"
    }
    
    # 如果有参考图片，构建 content 数组
    if request.reference_images:
        content = [{"type": "text", "text": request.prompt}]
        for img_url in request.reference_images:
            resolved = img_url
            if img_url.startswith("/"):
                from config import PUBLIC_BASE_URL
                resolved = f"{PUBLIC_BASE_URL.rstrip('/')}/{img_url.lstrip('/')}"
            content.append({"type": "image_url", "image_url": {"url": resolved}})
        payload["content"] = content
        del payload["prompt"]  # content 模式下不需要顶层 prompt
        logger.info(f"[image] Reference images: {len(request.reference_images)} images")

    logger.info(f"发送图片生成请求: {payload}")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        logger.info(f"图片生成响应状态: {response.status_code}")
        logger.info(f"图片生成响应内容: {response.text[:500]}")
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=500, detail="图片生成API调用超时")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"图片生成API调用失败: {str(e)}")

    if response.status_code != 200:
        # 退还积分
        from services.point_service import earn_points
        from database import PointsType
        earn_points(db, current_user.id, points_cost, PointsType.EARN, f"图片生成失败退款")
        try:
            error_json = response.json()
            error_msg = error_json.get("error", {}).get("message", error_json.get("error", {}).get("code", response.text))
        except Exception:
            error_msg = response.text[:200]
        raise HTTPException(status_code=400, detail=f"图片生成失败: {error_msg}")

    try:
        result = response.json()
    except Exception:
        from services.point_service import earn_points
        from database import PointsType
        earn_points(db, current_user.id, points_cost, PointsType.EARN, "图片生成失败退款")
        raise HTTPException(status_code=400, detail=f"图片生成API返回非JSON响应: {response.text[:200]}")
    logger.info(f"图片生成结果: {result}")

    # 处理响应 - 图片生成API返回的格式
    image_url = None
    if isinstance(result, dict):
        # 字典格式
        data = result.get("data", [])
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            image_url = data[0].get("url")  # API返回的字段是"url"而不是"image_url"
    elif isinstance(result, list) and len(result) > 0:
        # 列表格式
        data = result[0].get("data", []) if isinstance(result[0], dict) else []
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            image_url = data[0].get("url")

    # 生成任务ID
    task_id = str(uuid.uuid4())

    # 保存任务到数据库
    from database import TaskRecord, TaskStatus
    status = TaskStatus.SUCCESS if image_url else TaskStatus.PROCESSING
    task = TaskRecord(
        user_id=current_user.id,
        external_task_id=task_id,
        status=status,
        prompt=request.prompt,
        model=endpoint.endpoint_id,
        video_url=image_url,
        progress=100 if image_url else 0,
        points_consumed=points_cost,
    )
    db.add(task)
    db.commit()

    return {
        "success": True,
        "task_id": task_id,
        "image_url": image_url,
        "status": task.status
    }


@router.get("/{task_id}")
async def api_get_image_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import TaskRecord
    # Support both numeric id and external_task_id
    if task_id.isdigit():
        task = db.query(TaskRecord).filter(TaskRecord.id == int(task_id), TaskRecord.user_id == current_user.id).first()
    else:
        task = db.query(TaskRecord).filter(TaskRecord.external_task_id == task_id, TaskRecord.user_id == current_user.id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "id": task.id,
        "task_id": task.external_task_id,
        "status": task.status.value,
        "image_url": task.video_url,
        "progress": task.progress,
        "error_msg": task.error_msg,
    }


@router.delete("/{task_id}")
async def api_delete_image_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import TaskRecord
    if task_id.isdigit():
        task = db.query(TaskRecord).filter(TaskRecord.id == int(task_id), TaskRecord.user_id == current_user.id).first()
    else:
        task = db.query(TaskRecord).filter(TaskRecord.external_task_id == task_id, TaskRecord.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"success": True}
