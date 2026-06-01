from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, User, UserRole, UserStatus, PointsConfig, Channel, Endpoint, EndpointType, TaskRecord, TaskStatus, VideoSegment, VideoComposition
from middleware.auth_middleware import get_admin_user
from services.point_service import get_active_config
from schemas import AdminUserUpdate, PointsConfigSet, DashboardStats, PaginatedResponse, ChannelCreate, ChannelUpdate, EndpointCreate, EndpointUpdate, AdminPointsAdjust, AdminSubscriptionUpdate
from sqlalchemy import func, text

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard")
def api_admin_dashboard(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    total_users = db.query(func.count(User.id)).scalar()
    active_today = db.query(func.count(User.id)).filter(
        User.updated_at >= func.date(func.now())
    ).scalar()

    from database import TaskRecord, PointsRecord
    total_tasks = db.query(func.count(TaskRecord.id)).scalar()
    total_points = db.query(func.coalesce(func.sum(PointsRecord.points), 0)).filter(
        PointsRecord.type == "consume"
    ).scalar()

    from database import TaskStatus
    task_by_status = {}
    for status in TaskStatus:
        count = db.query(func.count(TaskRecord.id)).filter(
            TaskRecord.status == status
        ).scalar()
        task_by_status[status.value] = count

    recent_days = db.query(
        func.date(TaskRecord.created_at).label("day"),
        func.count(TaskRecord.id).label("cnt")
    ).filter(
        TaskRecord.created_at >= text("DATE_SUB(NOW(), INTERVAL 6 DAY)")
    ).group_by("day").order_by("day").all()
    task_trend = [{"date": str(d), "count": c} for d, c in recent_days]

    recent_users = db.query(
        func.date(User.created_at).label("day"),
        func.count(User.id).label("cnt")
    ).filter(
        User.created_at >= text("DATE_SUB(NOW(), INTERVAL 6 DAY)")
    ).group_by("day").order_by("day").all()
    user_trend = [{"date": str(d), "count": c} for d, c in recent_users]

    return {
        "total_users": total_users,
        "total_tasks": total_tasks,
        "total_points_consumed": abs(total_points or 0),
        "active_users_today": active_today,
        "task_by_status": task_by_status,
        "task_trend": task_trend,
        "user_trend": user_trend,
    }


@router.get("/users")
def api_admin_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if search:
        query = query.filter(
            User.email.contains(search) | User.display_name.contains(search)
        )
    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    from services.point_service import get_user_points
    from services.subscription_service import get_active_subscription

    items = []
    for u in users:
        items.append({
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role.value,
            "status": u.status.value,
            "points_balance": get_user_points(db, u.id),
            "subscription": get_active_subscription(db, u.id),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.put("/users/{user_id}")
def api_admin_update_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.status:
        user.status = UserStatus(data.status)
    if data.role:
        user.role = UserRole(data.role)
    db.commit()
    return {"success": True}


@router.post("/users/{user_id}/points")
def api_admin_adjust_user_points(
    user_id: int,
    data: AdminPointsAdjust,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.point_service import admin_adjust_points
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    result = admin_adjust_points(db, user_id, data.amount, data.reason or "管理员调整")
    
    if result:
        db.commit()
        return {"success": True, "balance": result}
    else:
        raise HTTPException(status_code=400, detail="Failed to adjust points")


@router.put("/users/{user_id}/subscription")
def api_admin_update_user_subscription(
    user_id: int,
    data: AdminSubscriptionUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.subscription_service import create_or_update_subscription
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    subscription = create_or_update_subscription(
        db,
        user_id,
        plan_id=data.plan_id,
        duration=data.duration,
        status=data.status,
        expires_at=data.expires_at,
        billing_cycle=data.billing_cycle or "monthly",
    )
    
    return {
        "success": True,
        "subscription": {
            "id": subscription.id,
            "plan_id": subscription.plan_id,
            "status": subscription.status.value,
            "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
            "billing_cycle": subscription.billing_cycle,
        }
    }


@router.get("/plans")
def api_admin_plans(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SubscriptionPlan
    from services.price_utils import usd_to_points
    
    plans = db.query(SubscriptionPlan).order_by(SubscriptionPlan.sort_order).all()
    result = []
    for p in plans:
        # 计算年付折扣后的价格
        annual_price_cents = None
        annual_points = None
        if p.annual_discount > 0:
            annual_price_cents = int(p.price_cents * 12 * (100 - p.annual_discount) / 100)
            annual_points = usd_to_points(db, annual_price_cents / 100)
        
        # 根据汇率自动计算月付积分
        monthly_points = usd_to_points(db, p.price_cents / 100) if p.price_cents > 0 else 0
        
        result.append({
            "id": p.id, "name": p.name, "description": p.description,
            "price_cents": p.price_cents, "duration_days": p.duration_days,
            # 自动计算的积分（不可编辑）
            "points_per_month": monthly_points,
            "max_batch_size": p.max_batch_size,
            "max_concurrent_tasks": p.max_concurrent_tasks,
            "max_resolution": p.max_resolution, "features": p.features,
            "sort_order": p.sort_order, "is_active": p.is_active,
            "annual_discount": p.annual_discount,
            "annual_price_cents": annual_price_cents,
            "annual_points": annual_points,
        })
    return result


@router.post("/plans")
def api_admin_create_plan(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SubscriptionPlan
    from services.price_utils import usd_to_points
    
    price_cents = data.get("price_cents", 0)
    # 根据汇率自动计算积分
    points_per_month = usd_to_points(db, price_cents / 100) if price_cents > 0 else 0
    
    plan = SubscriptionPlan(
        name=data.get("name"),
        description=data.get("description"),
        price_cents=price_cents,
        duration_days=data.get("duration_days", 30),
        points_per_month=points_per_month,
        max_batch_size=data.get("max_batch_size", 1),
        max_concurrent_tasks=data.get("max_concurrent_tasks", 1),
        max_resolution=data.get("max_resolution", "720p"),
        features=data.get("features"),
        annual_discount=data.get("annual_discount", 0),
        sort_order=data.get("sort_order", 0),
        is_active=data.get("is_active", True),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"success": True, "plan": {"id": plan.id, "name": plan.name, "points_per_month": points_per_month}}


@router.put("/plans/{plan_id}")
def api_admin_update_plan(
    plan_id: int,
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SubscriptionPlan
    from services.price_utils import usd_to_points
    
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    for key in ["name", "description", "price_cents", "duration_days",
                "max_batch_size", "max_concurrent_tasks", "max_resolution",
                "features", "sort_order", "is_active", "annual_discount"]:
        if key in data:
            setattr(plan, key, data[key])
    
    # 如果价格变更，自动重新计算积分
    if "price_cents" in data:
        price_cents = data["price_cents"]
        plan.points_per_month = usd_to_points(db, price_cents / 100) if price_cents > 0 else 0
    
    db.commit()
    return {"success": True, "points_per_month": plan.points_per_month}


@router.delete("/plans/{plan_id}")
def api_admin_delete_plan(
    plan_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SubscriptionPlan
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    db.delete(plan)
    db.commit()
    return {"success": True}


@router.get("/subscriptions")
def api_admin_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import UserSubscription
    query = db.query(UserSubscription)
    total = query.count()
    subs = query.order_by(UserSubscription.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for s in subs:
        u = db.query(User).filter(User.id == s.user_id).first()
        from database import SubscriptionPlan
        p = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == s.plan_id).first()
        items.append({
            "id": s.id,
            "user_id": s.user_id,
            "user_email": u.email if u else None,
            "plan_id": s.plan_id,
            "plan_name": p.name if p else None,
            "status": s.status.value,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "auto_renew": s.auto_renew,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/subscriptions")
def api_admin_create_subscription(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.subscription_service import subscribe_user
    try:
        sub = subscribe_user(db, data["user_id"], data["plan_id"], data.get("duration_days"))
        return {"success": True, "subscription_id": sub.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/subscriptions/{sub_id}/cancel")
def api_admin_cancel_subscription(
    sub_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.subscription_service import cancel_subscription
    if cancel_subscription(db, sub_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Subscription not found")


@router.get("/config/points")
def api_admin_get_points_config(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    config = get_active_config(db)
    if config:
        return {
            "points_per_token": config.points_per_token,
            "token_unit": config.token_unit,
            "effective_from": config.effective_from.isoformat() if config.effective_from else None,
        }
    return {"points_per_token": 1, "token_unit": "request", "effective_from": None}


@router.post("/config/points")
def api_admin_set_points_config(
    data: PointsConfigSet,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone, timedelta
    config = PointsConfig(
        points_per_token=data.points_per_token,
        token_unit=data.token_unit,
        effective_from=datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None),
        created_by=admin.id,
    )
    db.add(config)
    db.commit()
    return {"success": True}


@router.get("/points-config")
def api_admin_get_points_config_legacy(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return api_admin_get_points_config(admin, db)


@router.put("/points-config")
def api_admin_set_points_config_legacy(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone, timedelta
    config = PointsConfig(
        points_per_token=data.get("points_per_token", 1),
        token_unit=data.get("token_unit", "request"),
        effective_from=datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None),
        created_by=admin.id,
    )
    db.add(config)
    db.commit()
    return {"success": True}


_DEFAULT_POINTS_PER_SEC = {
    "ep-20260506111316-nsx8s": {"label": "Seedance 2.0",      "480p": 2,   "720p": 4,   "1080p": 9},
    "ep-20260506113134-gct7l": {"label": "Seedance 2.0 Fast", "480p": 1,   "720p": 3},
    "seedance-1.5-pro":        {"label": "Seedance 1.5 Pro",  "480p": 1,   "720p": 2,   "1080p": 3},
    "seedance-1.0-pro":        {"label": "Seedance 1.0 Pro",  "480p": 1,   "720p": 2,   "1080p": 3},
    "seedance-1.0-pro-fast":   {"label": "Seedance 1.0 Fast", "480p": 0.2, "720p": 0.4, "1080p": 1},
}


@router.get("/points-per-5s")
def admin_get_points_per_5s(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_per_sec").first()
    if cfg and cfg.config_value:
        return cfg.config_value
    return _DEFAULT_POINTS_PER_SEC


@router.put("/points-per-5s")
def admin_set_points_per_5s(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    from sqlalchemy.orm.attributes import flag_modified
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_per_sec").first()
    if cfg:
        cfg.config_value = data
        flag_modified(cfg, "config_value")
    else:
        cfg = SystemConfig(config_key="points_per_sec", config_value=data, description="每秒积分消耗配置")
        db.add(cfg)
    db.commit()
    return {"success": True}


# ── 积分配置中心 API ────────────────────────────────────────────────────

@router.get("/pricing-config")
def api_admin_get_pricing_config(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """获取积分配置中心（全局汇率、视频/图片生成成本）"""
    from services.price_utils import validate_pricing_config, get_usd_to_points_rate, get_video_cost_points, get_image_cost_points
    return validate_pricing_config(db)


@router.put("/pricing-config")
def api_admin_update_pricing_config(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """更新积分配置中心（支持按分辨率/尺寸设置成本）"""
    from sqlalchemy.orm.attributes import flag_modified
    from database import SystemConfig
    from services.price_utils import (
        CONFIG_USD_TO_POINTS,
        CONFIG_VIDEO_COST_480P, CONFIG_VIDEO_COST_720P, CONFIG_VIDEO_COST_1080P, CONFIG_VIDEO_COST_4K,
        CONFIG_IMAGE_COST_SM, CONFIG_IMAGE_COST_MD, CONFIG_IMAGE_COST_LG,
    )
    from services import CONFIG_VIDEO_COST_POINTS, CONFIG_IMAGE_COST_POINTS  # 兼容旧配置
    
    def update_config(key: str, value, desc: str):
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if cfg:
            cfg.config_value = value
            flag_modified(cfg, "config_value")
        else:
            cfg = SystemConfig(config_key=key, config_value=value, description=desc)
            db.add(cfg)
    
    # 更新全局汇率
    if "usd_to_points" in data:
        update_config(CONFIG_USD_TO_POINTS, data["usd_to_points"], "全局汇率：1美元可兑换的积分数量")
    
    # 更新视频生成成本（按分辨率）
    video_costs = {
        "video_cost_480p": (CONFIG_VIDEO_COST_480P, "480p视频生成消耗积分"),
        "video_cost_720p": (CONFIG_VIDEO_COST_720P, "720p视频生成消耗积分"),
        "video_cost_1080p": (CONFIG_VIDEO_COST_1080P, "1080p视频生成消耗积分"),
        "video_cost_4k": (CONFIG_VIDEO_COST_4K, "4K视频生成消耗积分"),
    }
    for key, (config_key, desc) in video_costs.items():
        if key in data:
            update_config(config_key, data[key], desc)
    
    # 更新图片生成成本（按尺寸）
    image_costs = {
        "image_cost_small": (CONFIG_IMAGE_COST_SM, "小尺寸图片生成消耗积分"),
        "image_cost_medium": (CONFIG_IMAGE_COST_MD, "中尺寸图片生成消耗积分"),
        "image_cost_large": (CONFIG_IMAGE_COST_LG, "大尺寸图片生成消耗积分"),
    }
    for key, (config_key, desc) in image_costs.items():
        if key in data:
            update_config(config_key, data[key], desc)
    
    # 兼容旧的单个成本字段（优先使用新字段）
    if "video_cost_points" in data and all(k not in data for k in video_costs.keys()):
        update_config(CONFIG_VIDEO_COST_POINTS, data["video_cost_points"], "视频生成消耗积分")
    if "image_cost_points" in data and all(k not in data for k in image_costs.keys()):
        update_config(CONFIG_IMAGE_COST_POINTS, data["image_cost_points"], "图片生成消耗积分")
    
    db.commit()
    return {"success": True}


@router.post("/pricing-config/init")
def api_admin_init_pricing_config(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """初始化默认定价配置"""
    from services.price_utils import init_default_pricing_config
    init_default_pricing_config(db)
    return {"success": True}


# ── 模型定价配置 API ────────────────────────────────────────────────────

@router.get("/model-pricing-config")
def api_admin_get_model_pricing_config(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """获取所有模型特定的定价配置"""
    from services.price_utils import get_all_model_pricing_configs
    return get_all_model_pricing_configs(db)


@router.put("/model-pricing-config/{model_type}/{model_id}")
def api_admin_update_model_pricing_config(
    model_type: str,
    model_id: str,
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """更新特定模型的定价配置"""
    from services.price_utils import save_model_pricing_config
    
    if model_type not in ["video", "image"]:
        raise HTTPException(status_code=400, detail="Invalid model_type. Must be 'video' or 'image'")
    
    save_model_pricing_config(db, model_type, model_id, data)
    return {"success": True}


@router.delete("/model-pricing-config/{model_type}/{model_id}")
def api_admin_delete_model_pricing_config(
    model_type: str,
    model_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """删除特定模型的定价配置"""
    from database import SystemConfig
    
    if model_type not in ["video", "image"]:
        raise HTTPException(status_code=400, detail="Invalid model_type. Must be 'video' or 'image'")
    
    # 删除该模型的所有成本配置
    if model_type == "video":
        config_keys = db.query(SystemConfig).filter(
            SystemConfig.config_key.like(f"video_cost_{model_id}_%")
        ).all()
    else:
        config_keys = db.query(SystemConfig).filter(
            SystemConfig.config_key.like(f"image_cost_{model_id}_%")
        ).all()
    
    for cfg in config_keys:
        db.delete(cfg)
    
    db.commit()
    return {"success": True}


@router.get("/tasks")
def api_admin_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import TaskRecord
    from sqlalchemy.orm import joinedload

    query = db.query(TaskRecord).options(joinedload(TaskRecord.user))
    if status:
        query = query.filter(TaskRecord.status == status)
    total = query.count()
    tasks = query.order_by(TaskRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for t in tasks:
        items.append({
            "id": t.id,
            "user_id": t.user_id,
            "user_email": t.user.email if t.user else None,
            "external_task_id": t.external_task_id,
            "status": t.status.value,
            "model": t.model,
            "prompt": t.prompt,
            "duration_seconds": t.duration_seconds,
            "resolution": t.resolution,
            "ratio": t.ratio,
            "points_consumed": t.points_consumed,
            "tokens_consumed": t.tokens_consumed,
            "progress": t.progress,
            "video_url": t.video_url,
            "error_msg": t.error_msg,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.delete("/tasks/{task_id}")
def api_admin_force_delete_task(
    task_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 如果是 composition 的 segment，同时删除整个 composition
    seg = db.query(VideoSegment).filter(VideoSegment.task_record_id == task_id).first()
    if seg:
        comp_id = seg.composition_id
        sibling_ids = [
            s.task_record_id for s in db.query(VideoSegment).filter(
                VideoSegment.composition_id == comp_id,
                VideoSegment.task_record_id.isnot(None)
            ).all()
        ]
        db.query(VideoSegment).filter(VideoSegment.composition_id == comp_id).delete()
        if sibling_ids:
            db.query(TaskRecord).filter(TaskRecord.id.in_(sibling_ids)).delete(synchronize_session=False)
        comp = db.query(VideoComposition).filter(VideoComposition.id == comp_id).first()
        if comp:
            db.delete(comp)
    else:
        db.delete(task)

    db.commit()
    return {"success": True}

@router.get("/channels")
def api_admin_channels(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import Channel
    channels = db.query(Channel).order_by(Channel.priority.desc()).all()
    return [{
        "id": c.id, "name": c.name, "provider": c.provider,
        "api_base_url": c.api_base_url, "file_url": c.file_url,
        "task_url": c.task_url, "project_id": c.project_id,
        "is_active": c.is_active, "priority": c.priority,
    } for c in channels]


@router.post("/channels")
def api_admin_create_channel(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import Channel
    from services.auth_service import encrypt_value

    ak_encrypted = None
    sk_encrypted = None
    if data.get("ak"):
        ak_encrypted = encrypt_value(data["ak"])
    if data.get("sk"):
        sk_encrypted = encrypt_value(data["sk"])

    channel = Channel(
        name=data.get("name"),
        provider=data.get("provider", "byteplus"),
        api_base_url=data.get("api_base_url"),
        file_url=data.get("file_url"),
        task_url=data.get("task_url"),
        ak_encrypted=ak_encrypted,
        sk_encrypted=sk_encrypted,
        project_id=data.get("project_id"),
        priority=data.get("priority", 0),
        is_active=data.get("is_active", True),
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return {"success": True, "channel": {"id": channel.id, "name": channel.name}}


@router.put("/channels/{channel_id}")
def api_admin_update_channel(
    channel_id: int,
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import Channel
    from services.auth_service import encrypt_value

    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if "name" in data:
        channel.name = data["name"]
    if "api_base_url" in data:
        channel.api_base_url = data["api_base_url"]
    if "file_url" in data:
        channel.file_url = data["file_url"]
    if "task_url" in data:
        channel.task_url = data["task_url"]
    if "project_id" in data:
        channel.project_id = data["project_id"]
    if "priority" in data:
        channel.priority = data["priority"]
    if "is_active" in data:
        channel.is_active = data["is_active"]

    if data.get("ak"):
        channel.ak_encrypted = encrypt_value(data["ak"])
    if data.get("sk"):
        channel.sk_encrypted = encrypt_value(data["sk"])
    
    # 处理 API Key（支持空字符串清除）
    if "api_key" in data:
        api_key_value = data["api_key"].strip() if data["api_key"] else None
        channel.api_key_encrypted = encrypt_value(api_key_value) if api_key_value else None

    db.commit()
    return {"success": True}


@router.delete("/channels/{channel_id}")
def api_admin_delete_channel(
    channel_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import Channel
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(channel)
    db.commit()
    return {"success": True}


@router.get("/channels/{channel_id}/endpoints")
def api_admin_get_channel_endpoints(
    channel_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    endpoints = db.query(Endpoint).filter(
        Endpoint.channel_id == channel_id,
        Endpoint.is_active == True
    ).all()
    return [{
        "id": e.id,
        "channel_id": e.channel_id,
        "endpoint_id": e.endpoint_id,
        "endpoint_name": e.endpoint_name,
        "endpoint_url": e.endpoint_url,
        "type": e.type,
        "models": e.models,
        "is_default": e.is_default,
        "is_active": e.is_active,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    } for e in endpoints]


@router.post("/channels/{channel_id}/endpoints")
def api_admin_create_channel_endpoint(
    channel_id: int,
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    if data.get("is_default"):
        db.query(Endpoint).filter(
            Endpoint.channel_id == channel_id,
            Endpoint.is_default == True
        ).update({"is_default": False})
    
    endpoint = Endpoint(
        channel_id=channel_id,
        endpoint_id=data.get("endpoint_id"),
        endpoint_name=data.get("endpoint_name"),
        endpoint_url=data.get("endpoint_url"),
        type=data.get("type"),
        models=data.get("models"),
        is_default=data.get("is_default", False),
        is_active=data.get("is_active", True),
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return {"success": True, "id": endpoint.id}


@router.put("/channels/{channel_id}/endpoints/{endpoint_id}")
def api_admin_update_channel_endpoint(
    channel_id: int,
    endpoint_id: int,
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    endpoint = db.query(Endpoint).filter(
        Endpoint.id == endpoint_id,
        Endpoint.channel_id == channel_id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    
    if "endpoint_id" in data:
        endpoint.endpoint_id = data["endpoint_id"]
    if "endpoint_name" in data:
        endpoint.endpoint_name = data["endpoint_name"]
    if "endpoint_url" in data:
        endpoint.endpoint_url = data["endpoint_url"]
    if "type" in data:
        # 验证 type 字段不为空且是有效值
        type_value = data["type"]
        if type_value and type_value in [e.value for e in EndpointType]:
            endpoint.type = type_value
        elif type_value == "":
            # 如果是空字符串，使用默认值
            endpoint.type = EndpointType.DEFAULT
    if "models" in data:
        endpoint.models = data["models"]
    if "is_default" in data:
        endpoint.is_default = data["is_default"]
        if data["is_default"]:
            db.query(Endpoint).filter(
                Endpoint.channel_id == channel_id,
                Endpoint.id != endpoint_id,
                Endpoint.is_default == True
            ).update({"is_default": False})
    if "is_active" in data:
        endpoint.is_active = data["is_active"]
    
    db.commit()
    return {"success": True}


@router.delete("/channels/{channel_id}/endpoints/{endpoint_id}")
def api_admin_delete_channel_endpoint(
    channel_id: int,
    endpoint_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    endpoint = db.query(Endpoint).filter(
        Endpoint.id == endpoint_id,
        Endpoint.channel_id == channel_id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    db.delete(endpoint)
    db.commit()
    return {"success": True}


@router.post("/channels/{channel_id}/test")
def api_admin_test_channel(
    channel_id: int,
    data: Optional[dict] = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.task_service import test_endpoint
    
    endpoint_id = data.get("endpoint_id") if data else None
    result = test_endpoint(db, channel_id, endpoint_id)
    
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Test failed"))


@router.get("/points/records")
def api_admin_points_records(
    user_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import PointsRecord, PointsType
    from sqlalchemy.orm import joinedload
    
    query = db.query(PointsRecord).options(joinedload(PointsRecord.user))
    if user_id:
        query = query.filter(PointsRecord.user_id == user_id)
    
    total = query.count()
    records = query.order_by(PointsRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    
    items = []
    for r in records:
        items.append({
            "id": r.id,
            "user_id": r.user_id,
            "user_email": r.user.email if r.user else None,
            "points": r.points,
            "balance_after": r.balance_after,
            "type": r.type.value,
            "description": r.description,
            "reference_id": r.reference_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/points/adjust")
def api_admin_adjust_points(
    data: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user_id = data.get("user_id")
    amount = data.get("amount")
    description = data.get("description", "")
    
    if not user_id or amount is None:
        raise HTTPException(status_code=400, detail="user_id and amount are required")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    from services.point_service import admin_adjust_points
    if admin_adjust_points(db, user_id, amount, description):
        db.commit()
        return {"success": True}
    raise HTTPException(status_code=400, detail="Invalid adjustment amount")


@router.get("/points/stats")
def api_admin_points_stats(
    days: int = Query(30, ge=1, le=365),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.point_service import get_points_stats
    return get_points_stats(db, days)


@router.get("/points/user/{user_id}")
def api_admin_get_user_points(
    user_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from services.point_service import get_user_points, get_user_points_by_type
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    balance = get_user_points(db, user_id)
    stats = get_user_points_by_type(db, user_id)
    
    return {
        "user_id": user_id,
        "user_email": user.email,
        "balance": balance,
        "stats": stats,
    }


@router.get("/billing")
def api_admin_billing(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import UserSubscription, SubscriptionPlan, SubscriptionStatus
    query = db.query(UserSubscription, User, SubscriptionPlan).join(
        User, UserSubscription.user_id == User.id
    ).join(
        SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id
    ).order_by(UserSubscription.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for sub, user, plan in rows:
        billing_cycle = getattr(sub, 'billing_cycle', 'monthly')
        if billing_cycle == 'annual' and plan.annual_discount > 0:
            price_cents = int(plan.price_cents * 12 * (100 - plan.annual_discount) / 100)
        else:
            price_cents = plan.price_cents

        items.append({
            "id": sub.id,
            "user_id": user.id,
            "user_email": user.email,
            "user_name": user.display_name,
            "plan_id": plan.id,
            "plan_name": plan.name,
            "billing_cycle": billing_cycle,
            "status": sub.status.value,
            "price_cents": price_cents,
            "points_per_month": plan.points_per_month,
            "started_at": sub.started_at.isoformat() if sub.started_at else None,
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ── Ticket (工单) Admin APIs ────────────────────────────────────────────

class TicketReplyRequest(BaseModel):
    content: str
    attachments: list = []


@router.get("/contact-messages")
async def admin_list_tickets(
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
    status: str = "",
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage, TicketStatus
    q = db.query(ContactMessage)
    if unread_only:
        q = q.filter(ContactMessage.is_read == False)
    if status:
        q = q.filter(ContactMessage.status == status)
    total = q.count()
    tickets = q.order_by(ContactMessage.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for t in tickets:
        last_reply = t.replies[-1] if t.replies else None
        items.append({
            "id": t.id,
            "user_id": t.user_id,
            "email": t.email,
            "subject": t.subject,
            "message": t.message,
            "attachments": t.attachments or [],
            "is_read": t.is_read,
            "status": t.status.value if t.status else "open",
            "reply_count": len(t.replies),
            "last_reply_at": last_reply.created_at.isoformat() if last_reply else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/contact-messages/{ticket_id}")
async def admin_get_ticket(
    ticket_id: int,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage
    t = db.query(ContactMessage).filter(ContactMessage.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    t.is_read = True
    db.commit()
    return {
        "id": t.id,
        "user_id": t.user_id,
        "email": t.email,
        "subject": t.subject,
        "message": t.message,
        "attachments": t.attachments or [],
        "is_read": t.is_read,
        "status": t.status.value if t.status else "open",
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "replies": [{
            "id": r.id,
            "sender": r.sender,
            "content": r.content,
            "attachments": r.attachments or [],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in t.replies],
    }


@router.post("/contact-messages/{ticket_id}/reply")
async def admin_reply_ticket(
    ticket_id: int,
    req: TicketReplyRequest,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage, ContactReply, TicketStatus
    t = db.query(ContactMessage).filter(ContactMessage.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    if t.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=400, detail="工单已关闭")
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="回复内容不能为空")
    reply = ContactReply(
        ticket_id=ticket_id,
        sender="admin",
        content=req.content.strip(),
        attachments=req.attachments or [],
    )
    db.add(reply)
    t.is_read = True
    db.commit()
    return {"success": True}


@router.put("/contact-messages/{ticket_id}/close")
async def admin_close_ticket(
    ticket_id: int,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage, TicketStatus
    t = db.query(ContactMessage).filter(ContactMessage.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    t.status = TicketStatus.CLOSED
    db.commit()
    return {"success": True}


@router.put("/contact-messages/{ticket_id}/reopen")
async def admin_reopen_ticket(
    ticket_id: int,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage, TicketStatus
    t = db.query(ContactMessage).filter(ContactMessage.id == ticket_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    t.status = TicketStatus.OPEN
    db.commit()
    return {"success": True}


@router.put("/contact-messages/{msg_id}/read")
async def admin_mark_ticket_read(
    msg_id: int,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage
    t = db.query(ContactMessage).filter(ContactMessage.id == msg_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    t.is_read = True
    db.commit()
    return {"success": True}


@router.delete("/contact-messages/{msg_id}")
async def admin_delete_ticket(
    msg_id: int,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage, ContactReply
    t = db.query(ContactMessage).filter(ContactMessage.id == msg_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    db.query(ContactReply).filter(ContactReply.ticket_id == msg_id).delete()
    db.delete(t)
    db.commit()
    return {"success": True}


class SiteConfigRequest(BaseModel):
    telegram_url: Optional[str] = None
    telegram_name: Optional[str] = None


@router.get("/site-config")
async def get_site_config(
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "site_config").first()
    return cfg.config_value if cfg and cfg.config_value else {}


@router.put("/site-config")
async def update_site_config(
    req: SiteConfigRequest,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "site_config").first()
    value = {"telegram_url": req.telegram_url or "", "telegram_name": req.telegram_name or ""}
    if cfg:
        cfg.config_value = value
    else:
        cfg = SystemConfig(config_key="site_config", config_value=value, description="网站公开配置")
        db.add(cfg)
    db.commit()
    return {"success": True}


# ── Models Config ─────────────────────────────────────────────────────────

_DEFAULT_MODELS_CONFIG = {
    "video": [
        {"id": "ep-20260506111316-nsx8s", "name": "Seedance 2.0", "enabled": True, "is_default": True, "resolutions": ["480p", "720p", "1080p"], "durations": [5, 10], "sort": 0},
        {"id": "ep-20260506113134-gct7l", "name": "Seedance 2.0 Fast", "enabled": True, "is_default": False, "resolutions": ["480p", "720p"], "durations": [5, 10], "sort": 1},
        {"id": "seedance-1.5-pro", "name": "Seedance 1.5 Pro", "enabled": True, "is_default": False, "resolutions": ["480p", "720p", "1080p"], "durations": [5, 10], "sort": 2},
        {"id": "seedance-1.0-pro", "name": "Seedance 1.0 Pro", "enabled": True, "is_default": False, "resolutions": ["480p", "720p", "1080p"], "durations": [5, 10], "sort": 3},
        {"id": "seedance-1.0-pro-fast", "name": "Seedance 1.0 Fast", "enabled": True, "is_default": False, "resolutions": ["480p", "720p", "1080p"], "durations": [5, 10], "sort": 4},
    ],
    "image": [
        {"id": "doubao-seedream-3-0-t2i-250415", "name": "Seedream 3.0", "enabled": True, "is_default": True, "sizes": ["512x512", "1024x1024", "2048x2048"], "sort": 0},
    ],
}


@router.get("/models-config")
async def get_models_config(
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "models_config").first()
    return cfg.config_value if cfg and cfg.config_value else _DEFAULT_MODELS_CONFIG


@router.put("/models-config")
async def update_models_config(
    data: dict,
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    from sqlalchemy.orm.attributes import flag_modified
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "models_config").first()
    if cfg:
        cfg.config_value = data
        flag_modified(cfg, "config_value")
    else:
        cfg = SystemConfig(config_key="models_config", config_value=data, description="模型配置")
        db.add(cfg)
    db.commit()
    return {"success": True}


# ── Points Packages Admin ─────────────────────────────────────────────────

@router.get("/points-packages")
async def admin_get_points_packages(
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_packages").first()
    return cfg.config_value if cfg and cfg.config_value else []


@router.put("/points-packages")
async def admin_set_points_packages(
    data: list = Body(...),
    current_admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from database import SystemConfig
    from sqlalchemy.orm.attributes import flag_modified
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_packages").first()
    if cfg:
        cfg.config_value = data
        flag_modified(cfg, "config_value")
    else:
        cfg = SystemConfig(config_key="points_packages", config_value=data, description="积分充值包配置")
        db.add(cfg)
    db.commit()
    return {"success": True}
