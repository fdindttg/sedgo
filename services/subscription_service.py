from datetime import datetime, timezone, timedelta, timedelta
from sqlalchemy.orm import Session
from database import (
    User, UserSubscription, SubscriptionPlan, SubscriptionStatus,
    PointsRecord, PointsType
)
from services.point_service import earn_points
from services.price_utils import calculate_subscription_points
from config import REDIS_PREFIX
from redis_client import get_redis

def parse_datetime(value):
    """解析日期时间值，支持字符串和datetime对象"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # 尝试解析各种常见格式
            formats = [
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d',
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        except Exception:
            pass
    return None


def get_active_subscription(db: Session, user_id: int) -> dict | None:
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    sub = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id,
        UserSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
        UserSubscription.expires_at > now,
    ).order_by(UserSubscription.expires_at.desc()).first()

    if not sub:
        return None

    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
    
    # 计算年付折扣后的价格
    annual_price_cents = None
    if plan and plan.annual_discount > 0:
        annual_price_cents = int(plan.price_cents * 12 * (100 - plan.annual_discount) / 100)
    
    return {
        "id": sub.id,
        "plan_name": plan.name if plan else "Unknown",
        "plan_id": sub.plan_id,
        "status": sub.status.value,
        "started_at": sub.started_at.isoformat(),
        "expires_at": sub.expires_at.isoformat(),
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "auto_renew": sub.auto_renew,
        "points_per_month": plan.points_per_month if plan else 0,
        "max_batch_size": plan.max_batch_size if plan else 1,
        "max_concurrent_tasks": plan.max_concurrent_tasks if plan else 1,
        "max_resolution": plan.max_resolution if plan else "720p",
        "billing_cycle": sub.billing_cycle,
        "annual_discount": plan.annual_discount if plan else 0,
        "annual_price_cents": annual_price_cents,
        "price_cents": annual_price_cents if sub.billing_cycle == "annual" and annual_price_cents else (plan.price_cents if plan else 0),
    }


def subscribe_user(db: Session, user_id: int, plan_id: int, billing_cycle: str = "monthly") -> UserSubscription:
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise ValueError("Plan not found")

    # 根据计费周期计算时长和所需积分
    if billing_cycle == "annual":
        days = plan.duration_days * 12
        discount_factor = (100 - plan.annual_discount) / 100 if plan.annual_discount else 1.0
        usd_price = (plan.price_cents / 100) * 12 * discount_factor
    else:
        days = plan.duration_days
        usd_price = plan.price_cents / 100
    
    # 计算套餐所需积分
    required_points = calculate_subscription_points(db, usd_price)

    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    expires = now + timedelta(days=days)

    # 获取用户当前积分
    user = db.query(User).filter(User.id == user_id).first()
    current_points = user.points if user else 0

    # 检查用户是否有活跃订阅
    active_subs = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id,
        UserSubscription.status == SubscriptionStatus.ACTIVE,
    ).all()

    if active_subs:
        # 如果有活跃订阅，检查是否可以切换
        current_plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == active_subs[0].plan_id).first()
        
        # 检查是否是同一套餐的不同周期切换（月付转年付）
        is_same_plan = current_plan and current_plan.id == plan.id
        
        if not is_same_plan:
            # 不同套餐之间切换，需要检查积分是否足够
            if current_points < required_points:
                raise ValueError(f"积分不足，需要 {required_points} 积分，当前只有 {current_points} 积分")
            
            # 扣除积分
            user.points -= required_points
            db.flush()

            # 将旧订阅标记为已取消
            for s in active_subs:
                s.status = SubscriptionStatus.CANCELLED
        else:
            # 同一套餐升级（月付转年付），需要补差价
            if billing_cycle == "annual":
                # 计算差价积分
                current_plan_monthly_points = calculate_subscription_points(db, current_plan.price_cents / 100)
                upgrade_cost_points = required_points - current_plan_monthly_points
                
                if upgrade_cost_points > 0 and current_points < upgrade_cost_points:
                    raise ValueError(f"升级需要补 {upgrade_cost_points} 积分，当前只有 {current_points} 积分")
                
                if upgrade_cost_points > 0:
                    user.points -= upgrade_cost_points
                    db.flush()
            
            # 将旧订阅标记为已取消
            for s in active_subs:
                s.status = SubscriptionStatus.CANCELLED
    else:
        # 首次订阅，需要检查积分是否足够
        if current_points < required_points:
            raise ValueError(f"积分不足，需要 {required_points} 积分，当前只有 {current_points} 积分")
        
        # 扣除积分
        user.points -= required_points
        db.flush()

    sub = UserSubscription(
        user_id=user_id,
        plan_id=plan_id,
        status=SubscriptionStatus.ACTIVE,
        started_at=now,
        expires_at=expires,
        auto_renew=False,
        billing_cycle=billing_cycle,
    )
    db.add(sub)
    db.flush()

    # 发放套餐积分（原有积分保留，新套餐积分叠加）
    if plan.price_cents > 0:
        total_points = calculate_subscription_points(db, usd_price)
        earn_points(db, user_id, total_points, PointsType.SUBSCRIPTION,
                    f"Points from {plan.name} subscription ({billing_cycle})")

    db.commit()
    return sub


def cancel_subscription(db: Session, subscription_id: int) -> bool:
    sub = db.query(UserSubscription).filter(UserSubscription.id == subscription_id).first()
    if not sub:
        return False
    sub.status = SubscriptionStatus.CANCELLED
    db.commit()
    return True


def check_expired_subscriptions(db: Session):
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    expired = db.query(UserSubscription).filter(
        UserSubscription.status == SubscriptionStatus.ACTIVE,
        UserSubscription.expires_at <= now,
    ).all()
    for sub in expired:
        sub.status = SubscriptionStatus.EXPIRED
    if expired:
        db.commit()
    return len(expired)


def create_or_update_subscription(
    db: Session,
    user_id: int,
    plan_id: int = None,
    duration: int = None,
    status: str = None,
    expires_at: datetime = None,
    billing_cycle: str = "monthly",
) -> UserSubscription:
    """创建或更新用户订阅（管理员用）"""
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    
    # 解析 expires_at 参数
    parsed_expires_at = parse_datetime(expires_at)
    
    # 查找现有活跃订阅
    existing_sub = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id,
        UserSubscription.status != SubscriptionStatus.EXPIRED,
    ).order_by(UserSubscription.created_at.desc()).first()
    
    # 获取套餐信息
    plan = None
    if plan_id:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if not plan:
            raise ValueError("Plan not found")
    
    if existing_sub:
        # 更新现有订阅
        sub = existing_sub
    else:
        # 创建新订阅
        # 如果没有提供 plan_id，使用默认套餐
        if not plan_id:
            default_plan = db.query(SubscriptionPlan).filter(
                SubscriptionPlan.is_active == True
            ).order_by(SubscriptionPlan.id).first()
            if not default_plan:
                raise ValueError("No active subscription plan available")
            plan_id = default_plan.id
            plan = default_plan
        
        sub = UserSubscription(
            user_id=user_id,
            plan_id=plan_id,
            started_at=now,
            auto_renew=False,
            billing_cycle=billing_cycle,
        )
        db.add(sub)
    
    # 如果是更新现有订阅且提供了 plan_id
    if plan_id and existing_sub:
        sub.plan_id = plan_id
        sub.billing_cycle = billing_cycle
    
    # 计算过期时间
    if parsed_expires_at:
        sub.expires_at = parsed_expires_at
    elif duration:
        sub.expires_at = now + timedelta(days=duration)
    elif plan and not existing_sub:
        # 根据计费周期计算时长
        if billing_cycle == "annual":
            sub.expires_at = now + timedelta(days=plan.duration_days * 12)
        else:
            sub.expires_at = now + timedelta(days=plan.duration_days)
    elif plan and existing_sub:
        # 更新订阅时，如果没有指定时长，使用套餐默认时长
        if billing_cycle == "annual":
            sub.expires_at = now + timedelta(days=plan.duration_days * 12)
        else:
            sub.expires_at = now + timedelta(days=plan.duration_days)
    
    if status:
        sub.status = SubscriptionStatus(status.lower())
    
    # 如果没有设置过期时间，默认30天
    if not sub.expires_at:
        sub.expires_at = now + timedelta(days=30)
    
    # 如果没有设置状态，默认为ACTIVE
    if not sub.status:
        sub.status = SubscriptionStatus.ACTIVE
    
    db.flush()
    
    # 如果是激活状态且有价格，发放积分（使用统一价格工具类）
    if sub.status == SubscriptionStatus.ACTIVE and plan_id:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if plan and plan.price_cents > 0:
            usd_price = plan.price_cents / 100
            total_points = calculate_subscription_points(db, usd_price)
            earn_points(db, user_id, total_points, PointsType.SUBSCRIPTION,
                        f"Admin granted points from {plan.name}")
    
    db.commit()
    return sub