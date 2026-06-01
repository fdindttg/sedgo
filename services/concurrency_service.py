"""
并发限制服务
用于管理任务并发数，根据用户套餐等级和全局限制进行限流

上游火山引擎限制：
- 最大并发数：100
- 最大请求速率：6000 RPM（每分钟）

用户套餐限制：
- 根据订阅套餐的 max_concurrent_tasks 字段限制单用户并发
"""

import time
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import TaskRecord, TaskStatus, SubscriptionPlan, SystemConfig
from services.subscription_service import get_active_subscription
from redis_client import get_redis
from config import REDIS_PREFIX

logger = logging.getLogger(__name__)

# Redis 键前缀
REDIS_KEY_PREFIX = f"{REDIS_PREFIX}:rate_limit"

# 全局配置常量
GLOBAL_CONFIG_KEY = "system_concurrency_limit"
DEFAULT_GLOBAL_MAX_CONCURRENT = 100  # 火山引擎限制
DEFAULT_GLOBAL_MAX_RPM = 6000        # 每分钟最大请求数

# 时间窗口（秒）
RATE_LIMIT_WINDOW = 60  # 1分钟窗口


class ConcurrencyLimitError(Exception):
    """并发限制异常"""
    pass


class RateLimitError(Exception):
    """速率限制异常"""
    pass


def get_system_config(db: Session, key: str):
    """获取系统配置"""
    config = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if config:
        return config.config_value
    return None


def set_system_config(db: Session, key: str, value: dict, description: str = None):
    """设置系统配置"""
    config = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if config:
        config.config_value = value
        if description:
            config.description = description
    else:
        config = SystemConfig(
            config_key=key,
            config_value=value,
            description=description
        )
        db.add(config)
    db.commit()


def initialize_system_config(db: Session):
    """初始化系统并发配置"""
    config = get_system_config(db, GLOBAL_CONFIG_KEY)
    if not config:
        set_system_config(db, GLOBAL_CONFIG_KEY, {
            "max_concurrent_tasks": DEFAULT_GLOBAL_MAX_CONCURRENT,
            "max_requests_per_minute": DEFAULT_GLOBAL_MAX_RPM
        }, "系统并发限制配置（火山引擎限制：100并发，6000RPM）")
        logger.info("系统并发配置已初始化")


def get_current_global_concurrent(db: Session) -> int:
    """获取当前全局并发任务数"""
    redis = get_redis()
    if not redis:
        # 降级：从数据库查询
        return db.query(TaskRecord).filter(
            TaskRecord.status == TaskStatus.PROCESSING
        ).count()
    
    # 使用 Redis 获取活跃任务计数
    active_tasks_key = f"{REDIS_KEY_PREFIX}:active_tasks"
    try:
        count = redis.get(active_tasks_key)
        return int(count) if count else 0
    except Exception as e:
        logger.error(f"Failed to get global concurrent from Redis: {e}")
        # 降级到数据库查询
        return db.query(TaskRecord).filter(
            TaskRecord.status == TaskStatus.PROCESSING
        ).count()


def increment_global_concurrent(db: Session) -> bool:
    """增加全局并发计数"""
    redis = get_redis()
    if not redis:
        return True  # 无Redis时跳过限制
    
    active_tasks_key = f"{REDIS_KEY_PREFIX}:active_tasks"
    try:
        count = redis.incr(active_tasks_key)
        return count > 0
    except Exception as e:
        logger.error(f"Failed to increment global concurrent: {e}")
        return True


def decrement_global_concurrent(db: Session):
    """减少全局并发计数"""
    redis = get_redis()
    if not redis:
        return
    
    active_tasks_key = f"{REDIS_KEY_PREFIX}:active_tasks"
    try:
        redis.decr(active_tasks_key)
    except Exception as e:
        logger.error(f"Failed to decrement global concurrent: {e}")


def get_user_concurrent(db: Session, user_id: int) -> int:
    """获取用户当前并发任务数"""
    redis = get_redis()
    if not redis:
        # 降级：从数据库查询
        return db.query(TaskRecord).filter(
            TaskRecord.user_id == user_id,
            TaskRecord.status == TaskStatus.PROCESSING
        ).count()
    
    user_key = f"{REDIS_KEY_PREFIX}:user:{user_id}:active_tasks"
    try:
        count = redis.get(user_key)
        return int(count) if count else 0
    except Exception as e:
        logger.error(f"Failed to get user concurrent from Redis: {e}")
        return db.query(TaskRecord).filter(
            TaskRecord.user_id == user_id,
            TaskRecord.status == TaskStatus.PROCESSING
        ).count()


def increment_user_concurrent(db: Session, user_id: int) -> bool:
    """增加用户并发计数"""
    redis = get_redis()
    if not redis:
        return True
    
    user_key = f"{REDIS_KEY_PREFIX}:user:{user_id}:active_tasks"
    try:
        count = redis.incr(user_key)
        return count > 0
    except Exception as e:
        logger.error(f"Failed to increment user concurrent: {e}")
        return True


def decrement_user_concurrent(db: Session, user_id: int):
    """减少用户并发计数"""
    redis = get_redis()
    if not redis:
        return
    
    user_key = f"{REDIS_KEY_PREFIX}:user:{user_id}:active_tasks"
    try:
        redis.decr(user_key)
    except Exception as e:
        logger.error(f"Failed to decrement user concurrent: {e}")


def check_rate_limit(db: Session) -> bool:
    """检查全局速率限制（6000 RPM）"""
    redis = get_redis()
    if not redis:
        return True  # 无Redis时跳过限制
    
    # 获取系统配置
    config = get_system_config(db, GLOBAL_CONFIG_KEY)
    max_rpm = config.get("max_requests_per_minute", DEFAULT_GLOBAL_MAX_RPM) if config else DEFAULT_GLOBAL_MAX_RPM
    
    # 使用滑动窗口计数
    window_key = f"{REDIS_KEY_PREFIX}:requests:{int(time.time() // RATE_LIMIT_WINDOW)}"
    try:
        count = redis.incr(window_key)
        redis.expire(window_key, RATE_LIMIT_WINDOW + 10)  # 过期时间稍长于窗口
        
        if count > max_rpm:
            logger.warning(f"Rate limit exceeded: {count}/{max_rpm} RPM")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to check rate limit: {e}")
        return True


def get_user_max_concurrent(db: Session, user_id: int) -> int:
    """获取用户最大并发数（根据套餐等级）"""
    sub = get_active_subscription(db, user_id)
    if sub:
        plan_id = sub.get("plan_id")
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if plan:
            return plan.max_concurrent_tasks
    
    # 默认免费用户限制
    return 1


def check_concurrency_limit(db: Session, user_id: int) -> tuple[bool, str]:
    """
    检查并发限制
    返回：(是否允许, 错误信息)
    """
    # 1. 检查全局速率限制
    if not check_rate_limit(db):
        return False, "系统当前请求过于频繁，请稍后再试"
    
    # 2. 获取系统并发配置
    config = get_system_config(db, GLOBAL_CONFIG_KEY)
    global_max = config.get("max_concurrent_tasks", DEFAULT_GLOBAL_MAX_CONCURRENT) if config else DEFAULT_GLOBAL_MAX_CONCURRENT
    
    # 3. 获取当前全局并发数
    global_current = get_current_global_concurrent(db)
    if global_current >= global_max:
        return False, f"系统当前任务繁忙，请稍后再试（当前并发：{global_current}/{global_max}）"
    
    # 4. 获取用户最大并发数
    user_max = get_user_max_concurrent(db, user_id)
    
    # 5. 获取用户当前并发数
    user_current = get_user_concurrent(db, user_id)
    if user_current >= user_max:
        return False, f"您的任务队列已满，请等待当前任务完成（当前并发：{user_current}/{user_max}）"
    
    return True, ""


def acquire_concurrency_token(db: Session, user_id: int) -> bool:
    """
    获取并发令牌（原子操作）
    成功返回True，失败返回False
    """
    # 先检查限制
    allowed, msg = check_concurrency_limit(db, user_id)
    if not allowed:
        logger.warning(f"Concurrency limit rejected for user {user_id}: {msg}")
        return False
    
    # 原子性增加计数
    redis = get_redis()
    if redis:
        # 使用Redis事务保证原子性
        try:
            with redis.pipeline() as pipe:
                active_tasks_key = f"{REDIS_KEY_PREFIX}:active_tasks"
                user_key = f"{REDIS_KEY_PREFIX}:user:{user_id}:active_tasks"
                
                # 获取当前值
                pipe.get(active_tasks_key)
                pipe.get(user_key)
                results = pipe.execute()
                
                global_current = int(results[0]) if results[0] else 0
                user_current = int(results[1]) if results[1] else 0
                
                # 再次检查
                config = get_system_config(db, GLOBAL_CONFIG_KEY)
                global_max = config.get("max_concurrent_tasks", DEFAULT_GLOBAL_MAX_CONCURRENT) if config else DEFAULT_GLOBAL_MAX_CONCURRENT
                user_max = get_user_max_concurrent(db, user_id)
                
                if global_current >= global_max or user_current >= user_max:
                    return False
                
                # 增加计数
                pipe.incr(active_tasks_key)
                pipe.incr(user_key)
                pipe.execute()
                
                logger.info(f"Concurrency token acquired for user {user_id}: global={global_current+1}/{global_max}, user={user_current+1}/{user_max}")
                return True
        except Exception as e:
            logger.error(f"Failed to acquire concurrency token with Redis: {e}")
            increment_global_concurrent(db)
            increment_user_concurrent(db, user_id)
            return True
    else:
        # 无 Redis：数据库二次检查后再增加
        allowed, msg = check_concurrency_limit(db, user_id)
        if not allowed:
            logger.warning(f"Concurrency limit rejected (no-Redis path) for user {user_id}: {msg}")
            return False
        increment_global_concurrent(db)
        increment_user_concurrent(db, user_id)
        return True


def release_concurrency_token(db: Session, user_id: int):
    """释放并发令牌"""
    decrement_global_concurrent(db)
    decrement_user_concurrent(db, user_id)
    logger.debug(f"Concurrency token released for user {user_id}")


def get_concurrency_stats(db: Session, user_id: int = None) -> dict:
    """
    获取并发统计信息
    如果指定user_id，返回用户级别的统计；否则返回全局统计
    """
    config = get_system_config(db, GLOBAL_CONFIG_KEY)
    global_max = config.get("max_concurrent_tasks", DEFAULT_GLOBAL_MAX_CONCURRENT) if config else DEFAULT_GLOBAL_MAX_CONCURRENT
    global_rpm = config.get("max_requests_per_minute", DEFAULT_GLOBAL_MAX_RPM) if config else DEFAULT_GLOBAL_MAX_RPM
    
    if user_id:
        user_max = get_user_max_concurrent(db, user_id)
        user_current = get_user_concurrent(db, user_id)
        
        return {
            "level": "user",
            "user_id": user_id,
            "current_concurrent": user_current,
            "max_concurrent": user_max,
            "remaining": max(0, user_max - user_current),
            "percentage": int((user_current / user_max) * 100) if user_max > 0 else 0
        }
    else:
        global_current = get_current_global_concurrent(db)
        
        return {
            "level": "global",
            "current_concurrent": global_current,
            "max_concurrent": global_max,
            "max_requests_per_minute": global_rpm,
            "remaining": max(0, global_max - global_current),
            "percentage": int((global_current / global_max) * 100) if global_max > 0 else 0
        }