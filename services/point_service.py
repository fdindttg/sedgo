from datetime import datetime, timezone, timedelta, timedelta
from sqlalchemy.orm import Session
from database import (
    User, UserRole, UserStatus,
    PointsRecord, PointsType, PointsConfig,
    UserSubscription, SubscriptionPlan, SubscriptionStatus,
    Channel, TaskRecord, TaskStatus, BatchTask,
    ApiKey
)
from redis_client import get_points_balance, set_points_balance, del_points_balance
from services.price_utils import (
    get_video_cost_points, get_image_cost_points,
    get_price_display, calculate_task_cost_display
)
from config import DEFAULT_POINTS_PER_TOKEN, DEFAULT_TOKEN_UNIT
import hashlib
import secrets


def get_user_points(db: Session, user_id: int) -> int:
    cached = get_points_balance(user_id)
    if cached is not None:
        return cached

    from sqlalchemy import func
    total = db.query(func.coalesce(func.sum(PointsRecord.points), 0)).filter(
        PointsRecord.user_id == user_id
    ).scalar()

    set_points_balance(user_id, total)
    return int(total)


def consume_points(db: Session, user_id: int, amount: int, description: str = "") -> bool:
    amount = int(amount)
    balance = get_user_points(db, user_id)
    balance = int(balance)
    if balance < amount:
        return False

    record = PointsRecord(
        user_id=user_id,
        points=-amount,
        balance_after=balance - amount,
        type=PointsType.CONSUME,
        description=description,
    )
    db.add(record)
    db.flush()
    del_points_balance(user_id)
    return True


def earn_points(db: Session, user_id: int, amount: int, ptype: PointsType, description: str = ""):
    from sqlalchemy import func
    amount = int(amount)
    total = int(db.query(func.coalesce(func.sum(PointsRecord.points), 0)).filter(
        PointsRecord.user_id == user_id
    ).scalar())

    record = PointsRecord(
        user_id=user_id,
        points=amount,
        balance_after=total + amount,
        type=ptype,
        description=description,
    )
    db.add(record)
    db.flush()
    del_points_balance(user_id)


def get_active_config(db: Session) -> PointsConfig:
    return db.query(PointsConfig).order_by(PointsConfig.effective_from.desc()).first()


# ── 定价体系 ──────────────────────────────────────────────────────────
# 官方成本（每5秒）：
#   Seedance 2.0:      480p=$0.35, 720p=$0.76, 1080p=$1.87
#   Seedance 2.0 Fast: 480p=$0.28, 720p=$0.60
# 平台溢价：月付 200%（3x）、年付 100%（2x），汇率 ¥7.3/$
# 1积分 ≈ ¥1，按每5秒收费再按实际时长比例计算

# 每5秒积分表（月付定价，endpoint_id → resolution → points）
POINTS_PER_5S = {
    "ep-20260506111316-nsx8s": {"480p": 8,  "720p": 17, "1080p": 41},  # Seedance 2.0
    "ep-20260506113134-gct7l": {"480p": 6,  "720p": 13},                # Seedance 2.0 Fast
    # Seedance 1.5 Pro ($0.12/$0.26/$0.58 per 5s × 3 × ¥7.3)
    "seedance-1.5-pro":        {"480p": 3,  "720p": 6,  "1080p": 13},
    # Seedance 1.0 Pro ($0.12/$0.26/$0.61 per 5s × 3 × ¥7.3)
    "seedance-1.0-pro":        {"480p": 3,  "720p": 6,  "1080p": 13},
    # Seedance 1.0 Pro Fast ($0.05/$0.10/$0.24 per 5s × 3 × ¥7.3)
    "seedance-1.0-pro-fast":   {"480p": 1,  "720p": 2,  "1080p": 5},
}
POINTS_PER_5S_DEFAULT = {"480p": 8, "720p": 17, "1080p": 41}

# 图片生成积分（固定，按尺寸）
IMAGE_POINTS_MAP = {
    "2048x2048": 10,
    "1024x1024": 5,
    "512x512": 2,
}

# 分辨率 token 系数保留（兼容旧代码引用）
RESOLUTION_MULTIPLIERS = {
    "480p": 1.0,
    "720p": 1.5,
    "1080p": 3.0,
}

IMAGE_TOKEN_MAP = {
    "2048x2048": 10,
    "1024x1024": 5,
    "512x512": 2,
}


POINTS_PER_SEC_DEFAULT = {"480p": 2, "720p": 4, "1080p": 9}


def _get_points_per_sec_table(db: Session) -> dict:
    from database import SystemConfig
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_per_sec").first()
    if cfg and cfg.config_value:
        return cfg.config_value
    return POINTS_PER_5S


def calculate_tokens_cost(db: Session, task_config: dict) -> int:
    """计算任务消耗积分（使用统一价格工具类）"""
    mode = task_config.get("mode", "txt2vid")
    model_id = task_config.get("model", task_config.get("endpoint_id"))

    if mode in ("txt2img", "image"):
        size = task_config.get("size", "medium")
        return get_image_cost_points(db, size, model_id)

    resolution = task_config.get("resolution", "720p")
    duration = task_config.get("duration", 5)
    return int(get_video_cost_points(db, resolution, model_id, duration))


def calculate_points_cost(db: Session, tokens: int) -> int:
    return max(1, tokens)


# 已废弃：请使用 services.price_utils.calculate_task_cost_display
def calculate_task_cost_display(db: Session, task_config: dict) -> dict:
    """返回前端展示用的费用信息（已废弃，请使用 price_utils）"""
    from services.price_utils import calculate_task_cost_display as utils_calculate
    return utils_calculate(db, task_config)


def get_user_points_history(db: Session, user_id: int, page: int = 1, page_size: int = 20):
    query = db.query(PointsRecord).filter(
        PointsRecord.user_id == user_id
    ).order_by(PointsRecord.created_at.desc())

    total = query.count()
    records = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [{
            "id": r.id,
            "points": r.points,
            "balance_after": r.balance_after,
            "type": r.type.value,
            "description": r.description,
            "reference_id": r.reference_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def admin_adjust_points(db: Session, user_id: int, amount: int, description: str = "") -> int | bool:
    if amount == 0:
        return False

    balance = get_user_points(db, user_id)
    new_balance = balance + amount

    if new_balance < 0:
        return False

    record = PointsRecord(
        user_id=user_id,
        points=amount,
        balance_after=new_balance,
        type=PointsType.ADMIN_ADJUST,
        description=description,
    )
    db.add(record)
    db.flush()
    del_points_balance(user_id)
    return new_balance


def get_points_stats(db: Session, days: int = 30):
    from sqlalchemy import func, case

    cutoff = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) - timedelta(days=days)

    total_earned = db.query(func.coalesce(func.sum(PointsRecord.points), 0)).filter(
        PointsRecord.type.in_([PointsType.EARN, PointsType.SUBSCRIPTION, PointsType.ADMIN_ADJUST]),
        PointsRecord.points > 0,
        PointsRecord.created_at >= cutoff,
    ).scalar()

    total_consumed = db.query(func.coalesce(func.sum(func.abs(PointsRecord.points)), 0)).filter(
        PointsRecord.type == PointsType.CONSUME,
        PointsRecord.created_at >= cutoff,
    ).scalar()

    total_adjusted = db.query(func.coalesce(func.sum(PointsRecord.points), 0)).filter(
        PointsRecord.type == PointsType.ADMIN_ADJUST,
        PointsRecord.created_at >= cutoff,
    ).scalar()

    total_subscription = db.query(func.coalesce(func.sum(PointsRecord.points), 0)).filter(
        PointsRecord.type == PointsType.SUBSCRIPTION,
        PointsRecord.created_at >= cutoff,
    ).scalar()

    daily_stats = db.query(
        func.date(PointsRecord.created_at).label("day"),
        func.sum(case(
            (PointsRecord.points > 0, PointsRecord.points), else_=0
        )).label("earned"),
        func.sum(case(
            (PointsRecord.type == PointsType.CONSUME, func.abs(PointsRecord.points)), else_=0
        )).label("consumed"),
    ).filter(
        PointsRecord.created_at >= cutoff,
    ).group_by("day").order_by("day").all()

    return {
        "total_earned": total_earned or 0,
        "total_consumed": total_consumed or 0,
        "total_adjusted": total_adjusted or 0,
        "total_subscription": total_subscription or 0,
        "daily_stats": [{
            "date": str(d.day),
            "earned": d.earned or 0,
            "consumed": d.consumed or 0,
        } for d in daily_stats],
    }


def get_user_points_by_type(db: Session, user_id: int):
    from sqlalchemy import func

    stats = db.query(
        PointsRecord.type,
        func.sum(PointsRecord.points).label("total"),
        func.count(PointsRecord.id).label("count"),
    ).filter(
        PointsRecord.user_id == user_id,
    ).group_by(PointsRecord.type).all()

    result = {}
    for s in stats:
        result[s.type.value] = {
            "total": s.total,
            "count": s.count,
        }

    return result
