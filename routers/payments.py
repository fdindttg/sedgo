from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta, timedelta
import uuid
import requests
import logging

from database import get_db, User, PaymentOrder, PaymentStatus, PaymentType, SubscriptionPlan, SystemConfig
from middleware.auth_middleware import get_current_user, get_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])

USDT_DECIMALS = 6  # TRC20 USDT decimals
TRONGRID_API = "https://api.trongrid.io"
# 合约地址：TRC20 USDT
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
# 订单有效期（分钟）
ORDER_EXPIRE_MINUTES = 30


def _get_usdt_config(db: Session) -> dict:
    """从 SystemConfig 获取支付配置"""
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "usdt_payment").first()
    if cfg and cfg.config_value:
        return cfg.config_value
    return {
        "addresses": [],
        "usd_to_usdt_rate": 1.0,  # 1 USDT ≈ 1 USD，后台可配置溢价
        "enabled": False,
    }


def _pick_address(config: dict) -> Optional[str]:
    addresses = config.get("addresses", [])
    if not addresses:
        return None
    return addresses[0]  # 简单轮转：始终用第一个；可扩展为轮询


def _usd_to_usdt(usd_cents: int, rate: float) -> float:
    """美分 → USDT，保留2位小数"""
    return round(usd_cents / 100 / rate, 2)


def _check_tron_payment(address: str, amount_usdt: float, since_timestamp_ms: int) -> Optional[dict]:
    """
    查询 TronGrid 确认收款。
    返回 {"tx_hash": ..., "from": ..., "amount": ...} 或 None。
    """
    try:
        url = f"{TRONGRID_API}/v1/accounts/{address}/transactions/trc20"
        params = {
            "contract_address": USDT_CONTRACT,
            "only_confirmed": True,
            "limit": 20,
            "min_timestamp": since_timestamp_ms,
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        target = int(amount_usdt * (10 ** USDT_DECIMALS))
        for tx in data:
            value = int(tx.get("value", 0))
            to_addr = tx.get("to", "")
            # 允许金额误差 ±0.01 USDT
            if to_addr.lower() == address.lower() and abs(value - target) <= 10000:
                return {
                    "tx_hash": tx.get("transaction_id"),
                    "from": tx.get("from"),
                    "amount": value / (10 ** USDT_DECIMALS),
                }
    except Exception as e:
        logger.warning(f"TronGrid query failed: {e}")
    return None


def _fulfill_order(db: Session, order: PaymentOrder, tx_info: dict):
    """订单到账后：激活订阅或充值积分"""
    order.status = PaymentStatus.COMPLETED
    order.tx_hash = tx_info["tx_hash"]
    order.from_address = tx_info["from"]
    order.confirmed_amount = tx_info["amount"]
    order.confirmed_at = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)

    if order.payment_type == PaymentType.SUBSCRIPTION and order.plan_id:
        from services.subscription_service import subscribe_user
        try:
            subscribe_user(db, order.user_id, order.plan_id, order.billing_cycle or "monthly")
        except Exception as e:
            logger.error(f"subscribe_user failed for order {order.order_no}: {e}")

    elif order.payment_type == PaymentType.POINTS and order.points_amount:
        from services.point_service import earn_points
        from database import PointsType
        earn_points(db, order.user_id, order.points_amount, PointsType.EARN,
                    f"USDT充值积分 订单{order.order_no}")

    db.commit()


# ── 后台轮询任务 ─────────────────────────────────────────────────────

def _poll_order(order_id: int):
    """后台任务：轮询链上确认，最多 ORDER_EXPIRE_MINUTES 分钟"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        order = db.query(PaymentOrder).filter(PaymentOrder.id == order_id).first()
        if not order:
            return
        since_ms = int(order.created_at.timestamp() * 1000)
        import time
        for _ in range(ORDER_EXPIRE_MINUTES * 2):  # 每30秒轮询一次
            time.sleep(30)
            order = db.query(PaymentOrder).filter(PaymentOrder.id == order_id).first()
            if not order or order.status != PaymentStatus.PENDING:
                return
            if datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) > order.expires_at:
                order.status = PaymentStatus.EXPIRED
                db.commit()
                return
            result = _check_tron_payment(order.receive_address, order.amount_usdt, since_ms)
            if result:
                _fulfill_order(db, order, result)
                return
    finally:
        db.close()


# ── API 接口 ─────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    payment_type: str           # "subscription" | "points"
    plan_id: Optional[int] = None
    billing_cycle: Optional[str] = "monthly"
    points_package: Optional[str] = None  # "small"|"medium"|"large"|"xlarge"


def _get_points_packages(db: Session) -> list:
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "points_packages").first()
    if cfg and cfg.config_value:
        return cfg.config_value if isinstance(cfg.config_value, list) else []
    return []


@router.get("/packages")
async def list_packages(db: Session = Depends(get_db)):
    return {"packages": _get_points_packages(db)}


@router.post("/create")
async def create_payment_order(
    req: CreateOrderRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = _get_usdt_config(db)
    if not config.get("enabled"):
        raise HTTPException(status_code=400, detail="USDT支付暂未开启，请联系管理员")

    address = _pick_address(config)
    if not address:
        raise HTTPException(status_code=400, detail="未配置收款地址")

    rate = float(config.get("usd_to_usdt_rate", config.get("cny_to_usdt_rate", 1.0)))
    plan = None
    points_amount = None
    amount_usd = None
    billing_cycle = req.billing_cycle or "monthly"

    if req.payment_type == "subscription":
        if not req.plan_id:
            raise HTTPException(status_code=400, detail="缺少套餐ID")
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == req.plan_id, SubscriptionPlan.is_active == True
        ).first()
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在")
        if plan.price_cents == 0:
            raise HTTPException(status_code=400, detail="免费套餐无需支付")

        if billing_cycle == "annual" and plan.annual_discount > 0:
            amount_usd = int(plan.price_cents * 12 * (100 - plan.annual_discount) / 100)
        else:
            amount_usd = plan.price_cents

    elif req.payment_type == "points":
        pkgs = {p["key"]: p for p in _get_points_packages(db)}
        pkg = pkgs.get(req.points_package)
        if not pkg:
            raise HTTPException(status_code=400, detail="无效的积分包")
        points_amount = pkg["points"]
        amount_usd = pkg["price_cents"]
    else:
        raise HTTPException(status_code=400, detail="无效的支付类型")

    amount_usdt = _usd_to_usdt(amount_usd, rate)
    # 加随机尾数避免金额碰撞（0.001 ~ 0.009 USDT）
    import random
    amount_usdt = round(amount_usdt + random.randint(1, 9) * 0.001, 3)

    order_no = "PAY" + uuid.uuid4().hex[:16].upper()
    expires_at = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) + timedelta(minutes=ORDER_EXPIRE_MINUTES)

    order = PaymentOrder(
        order_no=order_no,
        user_id=current_user.id,
        payment_type=req.payment_type,
        plan_id=req.plan_id,
        billing_cycle=billing_cycle,
        points_amount=points_amount,
        amount_usdt=amount_usdt,
        amount_cny=amount_usd,
        receive_address=address,
        network="TRC20",
        status=PaymentStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    background_tasks.add_task(_poll_order, order.id)

    return {
        "order_no": order_no,
        "amount_usdt": amount_usdt,
        "receive_address": address,
        "network": "TRC20",
        "expires_at": expires_at.isoformat(),
        "qr_data": f"tron:{address}?amount={amount_usdt}",
        "memo": f"请转账精确金额 {amount_usdt} USDT(TRC20) 到上述地址，{ORDER_EXPIRE_MINUTES}分钟内有效",
    }


@router.get("/status/{order_no}")
async def get_payment_status(
    order_no: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(PaymentOrder).filter(
        PaymentOrder.order_no == order_no,
        PaymentOrder.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 过期检查
    if order.status == PaymentStatus.PENDING and datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) > order.expires_at:
        order.status = PaymentStatus.EXPIRED
        db.commit()

    return {
        "order_no": order.order_no,
        "status": order.status.value,
        "amount_usdt": order.amount_usdt,
        "receive_address": order.receive_address,
        "tx_hash": order.tx_hash,
        "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
        "expires_at": order.expires_at.isoformat(),
    }


@router.get("/my")
async def list_my_orders(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PaymentOrder).filter(PaymentOrder.user_id == current_user.id)
    total = query.count()
    items = query.order_by(PaymentOrder.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    result = []
    for o in items:
        result.append({
            "order_no": o.order_no,
            "payment_type": o.payment_type.value,
            "amount_usdt": o.amount_usdt,
            "status": o.status.value,
            "tx_hash": o.tx_hash,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
        })
    return {"items": result, "total": total}


# ── 管理员接口 ────────────────────────────────────────────────────────

class UsdtConfigUpdate(BaseModel):
    addresses: list
    usd_to_usdt_rate: float = 1.0
    enabled: bool = True


@router.get("/admin/config")
async def admin_get_config(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return _get_usdt_config(db)


@router.put("/admin/config")
async def admin_update_config(
    body: UsdtConfigUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "usdt_payment").first()
    value = {
        "addresses": body.addresses,
        "usd_to_usdt_rate": body.usd_to_usdt_rate,
        "enabled": body.enabled,
    }
    if cfg:
        cfg.config_value = value
    else:
        cfg = SystemConfig(
            config_key="usdt_payment",
            config_value=value,
            description="USDT TRC20 收款配置",
        )
        db.add(cfg)
    db.commit()
    return {"success": True}


@router.get("/admin/orders")
async def admin_list_orders(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    query = db.query(PaymentOrder)
    if status:
        query = query.filter(PaymentOrder.status == status)
    total = query.count()
    items = query.order_by(PaymentOrder.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    result = []
    for o in items:
        result.append({
            "id": o.id,
            "order_no": o.order_no,
            "user_id": o.user_id,
            "payment_type": o.payment_type.value,
            "amount_usdt": o.amount_usdt,
            "amount_cny": o.amount_cny,
            "receive_address": o.receive_address,
            "tx_hash": o.tx_hash,
            "from_address": o.from_address,
            "confirmed_amount": o.confirmed_amount,
            "status": o.status.value,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
            "expires_at": o.expires_at.isoformat(),
        })
    return {"items": result, "total": total}


@router.post("/admin/orders/{order_no}/confirm")
async def admin_manual_confirm(
    order_no: str,
    tx_hash: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """管理员手动确认订单（用于链上查询失败时人工处理）"""
    order = db.query(PaymentOrder).filter(PaymentOrder.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == PaymentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="订单已完成")
    _fulfill_order(db, order, {
        "tx_hash": tx_hash,
        "from": "manual",
        "amount": order.amount_usdt,
    })
    return {"success": True}
