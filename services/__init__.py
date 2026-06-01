"""
服务模块导出
"""

# 价格工具类（统一计价逻辑）
from .price_utils import (
    get_usd_to_points_rate,
    points_to_usd,
    usd_to_points,
    format_usd,
    format_points,
    get_video_cost_points,
    get_image_cost_points,
    get_video_cost_by_resolution,
    get_image_cost_by_size,
    calculate_subscription_points,
    get_price_display,
    calculate_task_cost_display,
    validate_pricing_config,
    init_default_pricing_config,
    CONFIG_USD_TO_POINTS,
    # 视频成本配置（按分辨率）
    CONFIG_VIDEO_COST_480P,
    CONFIG_VIDEO_COST_720P,
    CONFIG_VIDEO_COST_1080P,
    CONFIG_VIDEO_COST_4K,
    # 图片成本配置（按尺寸）
    CONFIG_IMAGE_COST_SM,
    CONFIG_IMAGE_COST_MD,
    CONFIG_IMAGE_COST_LG,
    # 兼容旧代码的别名
    CONFIG_VIDEO_COST_720P as CONFIG_VIDEO_COST_POINTS,
    CONFIG_IMAGE_COST_MD as CONFIG_IMAGE_COST_POINTS,
)

# 积分服务
from .point_service import (
    get_user_points,
    consume_points,
    earn_points,
    calculate_tokens_cost,
    calculate_points_cost,
    calculate_task_cost_display as legacy_calculate_task_cost_display,  # 已废弃
    get_user_points_history,
    admin_adjust_points,
    get_points_stats,
    get_user_points_by_type,
)

# 订阅服务
from .subscription_service import (
    get_active_subscription,
    subscribe_user,
    cancel_subscription,
    check_expired_subscriptions,
    create_or_update_subscription,
)

# 认证服务
from .auth_service import (
    create_token,
    hash_password,
    verify_password,
)

# 任务服务
from .task_service import (
    create_task,
    create_batch_tasks,
    delete_remote_task,
    poll_task,
)

# 渠道服务（已移除，相关功能在task_service中）

# 并发服务
from .concurrency_service import (
    check_concurrency_limit,
    acquire_concurrency_token,
    release_concurrency_token,
    get_concurrency_stats,
)

__all__ = [
    # 价格工具类
    'get_usd_to_points_rate',
    'points_to_usd',
    'usd_to_points',
    'format_usd',
    'format_points',
    'get_video_cost_points',
    'get_image_cost_points',
    'get_video_cost_by_resolution',
    'get_image_cost_by_size',
    'calculate_subscription_points',
    'get_price_display',
    'calculate_task_cost_display',
    'validate_pricing_config',
    'init_default_pricing_config',
    'CONFIG_USD_TO_POINTS',
    # 视频成本配置（按分辨率）
    'CONFIG_VIDEO_COST_480P',
    'CONFIG_VIDEO_COST_720P',
    'CONFIG_VIDEO_COST_1080P',
    'CONFIG_VIDEO_COST_4K',
    # 图片成本配置（按尺寸）
    'CONFIG_IMAGE_COST_SM',
    'CONFIG_IMAGE_COST_MD',
    'CONFIG_IMAGE_COST_LG',
    # 兼容旧代码的别名
    'CONFIG_VIDEO_COST_POINTS',
    'CONFIG_IMAGE_COST_POINTS',
    # 积分服务
    'get_user_points',
    'consume_points',
    'earn_points',
    'calculate_tokens_cost',
    'calculate_points_cost',
    'get_user_points_history',
    'admin_adjust_points',
    'get_points_stats',
    'get_user_points_by_type',
    # 订阅服务
    'get_active_subscription',
    'subscribe_user',
    'cancel_subscription',
    'check_expired_subscriptions',
    'create_or_update_subscription',
    # 认证服务
    'create_token',
    'hash_password',
    'verify_password',
    # 任务服务
    'create_task',
    'create_batch_tasks',
    'delete_remote_task',
    'poll_task',
    # 渠道服务（已移除）
    # 并发服务
    'check_concurrency_limit',
    'acquire_concurrency_token',
    'release_concurrency_token',
    'get_concurrency_stats',
]
