from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import logging
from database import get_db, User, TaskRecord, TaskStatus, BatchTask, Channel, Endpoint, EndpointType, VideoSegment
from middleware.auth_middleware import get_current_user, verify_api_key
from services.task_service import create_task, poll_task, create_batch_tasks, create_video_composition, poll_video_composition
from schemas import TaskCreate, BatchTaskCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ── Public Endpoints (No auth required) ──────────────────────────────
# NOTE: These must be defined BEFORE parameterized routes like /{task_id}
# to avoid being shadowed by the parameter matching

@router.get("/endpoints")
def api_list_endpoints(db: Session = Depends(get_db), type: Optional[str] = None):
    """获取可用的接入点列表，支持按类型过滤"""
    from services.task_service import get_active_channels
    
    channels = get_active_channels(db)
    endpoints = []
    
    for channel in channels:
        query = db.query(Endpoint).filter(
            Endpoint.channel_id == channel.id,
            Endpoint.is_active == True
        )
        
        if type:
            query = query.filter(Endpoint.type == type)
        
        channel_endpoints = query.all()
        
        for ep in channel_endpoints:
            endpoints.append({
                "id": ep.id,
                "endpoint_id": ep.endpoint_id,
                "endpoint_name": ep.endpoint_name or ep.endpoint_id,
                "type": ep.type,
                "is_default": ep.is_default,
                "channel_id": channel.id,
                "channel_name": channel.name,
            })
    
    return {"endpoints": endpoints}


# ── Authenticated Endpoints ─────────────────────────────────────────

@router.post("/")
def api_create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # 添加调试日志
        logger.info(f"[DEBUG api_create_task] Received request with data: {data.model_dump()}")
        logger.info(f"[DEBUG api_create_task] use_real_people: {data.use_real_people}")
        
        task = create_task(db, current_user.id, data.model_dump())
        return {
            "success": True,
            "task_id": task.id,
            "external_task_id": task.external_task_id,
            "points_consumed": task.points_consumed,
            "tokens_consumed": task.tokens_consumed,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Task creation failed for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error during task creation")


@router.get("/")
def api_list_tasks(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    image_endpoint_ids = {
        ep.endpoint_id for ep in db.query(Endpoint).filter(
            Endpoint.type == EndpointType.IMAGE
        ).all()
    }
    # exclude tasks that are sub-segments of a composition
    segment_task_ids = {
        row.task_record_id for row in db.query(VideoSegment.task_record_id).filter(
            VideoSegment.task_record_id.isnot(None)
        ).all()
    }
    query = db.query(TaskRecord).filter(
        TaskRecord.user_id == current_user.id,
        ~TaskRecord.model.in_(image_endpoint_ids) if image_endpoint_ids else True,
        ~TaskRecord.id.in_(segment_task_ids) if segment_task_ids else True,
    )
    total = query.count()
    tasks = query.order_by(TaskRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for t in tasks:
        items.append({
            "id": t.id,
            "external_task_id": t.external_task_id,
            "status": t.status.value,
            "model": t.model,
            "prompt": t.prompt,
            "duration_seconds": t.duration_seconds,
            "resolution": t.resolution,
            "ratio": t.ratio,
            "progress": t.progress,
            "video_url": t.video_url,
            "error_msg": t.error_msg,
            "points_consumed": t.points_consumed,
            "tokens_consumed": t.tokens_consumed,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/compositions")
def api_list_compositions(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户的视频合成任务列表"""
    from database import VideoComposition

    query = db.query(VideoComposition).filter(VideoComposition.user_id == current_user.id)
    total = query.count()
    compositions = query.order_by(VideoComposition.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for c in compositions:
        segs = db.query(VideoSegment).filter(VideoSegment.composition_id == c.id).all()
        total_segs = len(segs)
        completed_segs = sum(1 for s in segs if s.status.value == 'success')
        items.append({
            "id": c.id,
            "status": c.status.value,
            "prompt": c.prompt,
            "total_duration": c.total_duration,
            "total_points_consumed": c.total_points_consumed,
            "final_video_url": c.final_video_url,
            "video_url": c.final_video_url,
            "progress": c.progress,
            "error_msg": c.error_msg,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "completed_segments": completed_segs,
            "total_segments": total_segs,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{task_id}")
def api_get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskRecord).filter(
        TaskRecord.id == task_id,
        TaskRecord.user_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in (TaskStatus.PROCESSING, TaskStatus.PENDING):
        poll_task(db, task)

    return {
        "id": task.id,
        "external_task_id": task.external_task_id,
        "status": task.status.value,
        "model": task.model,
        "prompt": task.prompt,
        "duration_seconds": task.duration_seconds,
        "resolution": task.resolution,
        "ratio": task.ratio,
        "progress": task.progress,
        "video_url": task.video_url,
        "error_msg": task.error_msg,
    }


@router.delete("/{task_id}")
def api_delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskRecord).filter(
        TaskRecord.id == task_id,
        TaskRecord.user_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 如果有火山引擎的任务ID，尝试删除火山上的内容
    if task.external_task_id:
        from services.task_service import delete_remote_task
        delete_remote_task(db, task.channel_id, task.external_task_id)
    
    db.delete(task)
    db.commit()
    return {"success": True}


@router.post("/batch")
def api_batch_create(
    data: BatchTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        configs = [t.model_dump() for t in data.tasks]
        batch = create_batch_tasks(db, current_user.id, configs, data.callback_url)
        return {
            "success": True,
            "batch_id": batch.id,
            "total": batch.total_count,
            "completed": batch.completed_count,
            "failed": batch.failed_count,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Video Composition APIs (Long Video Support) ───────────────────────

@router.post("/compose")
def api_create_composition(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 添加调试日志
    logger.info(f"[DEBUG api_create_composition] Received request with data: {data.model_dump()}")
    logger.info(f"[DEBUG api_create_composition] use_real_people: {data.use_real_people}")
    
    """创建视频合成任务（支持超过单段最大时长的视频，自动拆分为多个片段拼接）
    
    根据模型版本设置单段最大时长限制：
    - 2.0 版本：15 秒
    - 1.5 和 1.0 版本：12 秒
    
    超过对应版本最大时长的视频会自动拆分为多个片段生成后再拼接。
    所有视频模型都支持此功能。
    """
    try:
        task_config = data.model_dump()
        duration = task_config.get("duration", task_config.get("duration_seconds", 60))
        model = task_config.get("model", "")
        
        # 根据模型版本获取最大单段时长
        from services.task_service import get_model_max_duration
        max_duration = get_model_max_duration(model)
        
        if duration > max_duration:
            composition = create_video_composition(db, current_user.id, task_config)
            return {
                "success": True,
                "composition_id": composition.id,
                "task_id": composition.id,
                "points_consumed": composition.total_points_consumed,
                "message": f"Long video composition created (will be split into multiple segments, max {max_duration}s per segment)",
            }
        else:
            # 短视频直接创建单个任务
            task = create_task(db, current_user.id, task_config)
            return {
                "success": True,
                "task_id": task.id,
                "external_task_id": task.external_task_id,
                "points_consumed": task.points_consumed,
            }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/compositions/{composition_id}")
def api_delete_composition(
    composition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import VideoComposition, VideoSegment
    comp = db.query(VideoComposition).filter(
        VideoComposition.id == composition_id,
        VideoComposition.user_id == current_user.id,
    ).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Composition not found")
    segments = db.query(VideoSegment).filter(VideoSegment.composition_id == composition_id).all()
    task_record_ids = [s.task_record_id for s in segments if s.task_record_id]
    db.query(VideoSegment).filter(VideoSegment.composition_id == composition_id).delete()
    if task_record_ids:
        db.query(TaskRecord).filter(TaskRecord.id.in_(task_record_ids)).delete(synchronize_session=False)
    db.delete(comp)
    db.commit()
    return {"success": True}


@router.get("/compose/{composition_id}")
def api_get_composition(
    composition_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import VideoComposition
    comp = db.query(VideoComposition).filter(
        VideoComposition.id == composition_id,
        VideoComposition.user_id == current_user.id,
    ).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Composition not found")
    result = poll_video_composition(db, composition_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


