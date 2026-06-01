from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db, User, SubscriptionPlan, UserSubscription
from middleware.auth_middleware import get_current_user
from services.subscription_service import get_active_subscription, subscribe_user
from services.price_utils import usd_to_points, points_to_usd, format_usd, format_points

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubscribeRequest(BaseModel):
    plan_id: int
    billing_cycle: str = "monthly"  # monthly 或 annual


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    from services.price_utils import usd_to_points, points_to_usd, format_usd
    
    plans = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True).order_by(SubscriptionPlan.sort_order).all()
    result = []
    for p in plans:
        # 计算年付折扣后的价格
        annual_price_cents = None
        annual_points = None
        annual_usd = None
        if p.annual_discount > 0:
            annual_price_cents = int(p.price_cents * 12 * (100 - p.annual_discount) / 100)
            annual_points = usd_to_points(db, annual_price_cents / 100)
            annual_usd = points_to_usd(db, annual_points)
        
        # 根据汇率自动计算月付积分（价格×汇率）
        monthly_points = usd_to_points(db, p.price_cents / 100) if p.price_cents > 0 else 0
        monthly_usd = points_to_usd(db, monthly_points)
        
        result.append({
            "id": p.id, 
            "name": p.name, 
            "description": p.description,
            "price_cents": p.price_cents, 
            "duration_days": p.duration_days,
            "max_batch_size": p.max_batch_size,
            "max_concurrent_tasks": p.max_concurrent_tasks,
            "max_resolution": p.max_resolution, 
            "features": p.features,
            "annual_discount": p.annual_discount,
            "annual_price_cents": annual_price_cents,
            # 前端使用的积分/月（自动计算）
            "points_per_month": monthly_points,
            # 价格展示（使用统一价格工具类）
            "monthly_points": monthly_points,
            "monthly_usd": monthly_usd,
            "monthly_usd_formatted": format_usd(monthly_usd),
            "annual_points": annual_points,
            "annual_usd": annual_usd,
            "annual_usd_formatted": format_usd(annual_usd) if annual_usd else None,
        })
    return result


@router.get("/my")
def my_subscription(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = get_active_subscription(db, current_user.id)
    return {"subscription": sub}


@router.post("/subscribe")
def subscribe_plan(request: SubscribeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sub = subscribe_user(db, current_user.id, request.plan_id, request.billing_cycle)
        return {"success": True, "subscription_id": sub.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))