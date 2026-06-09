"""
价格工具类 - 全系统统一计价逻辑

核心设计原则：
1. 单一数据源：所有价格计算依赖全局汇率配置 system.usd_to_points
2. 统一换算公式：积分↔美元转换使用固定公式
3. 禁止硬编码：任何地方不允许硬编码汇率或价格
4. 强制调用工具类：所有计价必须通过此类，禁止自行写换算逻辑

配置项（存储在 SystemConfig 表）：
- system.usd_to_points: 1美元可兑换积分（例：100）
- video_cost_points_480p: 默认480p视频生成消耗积分
- video_cost_points_720p: 默认720p视频生成消耗积分
- video_cost_points_1080p: 默认1080p视频生成消耗积分
- video_cost_points_4k: 默认4K视频生成消耗积分
- image_cost_points_sm: 默认小尺寸图片生成消耗积分
- image_cost_points_md: 默认中尺寸图片生成消耗积分
- image_cost_points_lg: 默认大尺寸图片生成消耗积分
- video_cost_{model_id}_{resolution}: 特定模型的视频成本（如 video_cost_ep-20260506111316-nsx8s_720p）
- image_cost_{model_id}_{size}: 特定模型的图片成本（如 image_cost_doubao-seedream-3-0-t2i-250415_medium）

换算公式：
- 积分 → 美元（展示用）：美元 = 积分 / 汇率
- 美元 → 积分（结算用）：积分 = 美元 × 汇率（四舍五入取整）
"""

from sqlalchemy.orm import Session
from database import SystemConfig
import math

# 配置键常量
CONFIG_USD_TO_POINTS = "system.usd_to_points"

# 视频成本配置键（按分辨率，默认值）
CONFIG_VIDEO_COST_480P = "video_cost_points_480p"
CONFIG_VIDEO_COST_720P = "video_cost_points_720p"
CONFIG_VIDEO_COST_1080P = "video_cost_points_1080p"
CONFIG_VIDEO_COST_4K = "video_cost_points_4k"

# 图片成本配置键（按尺寸，默认值）
CONFIG_IMAGE_COST_SM = "image_cost_points_sm"
CONFIG_IMAGE_COST_MD = "image_cost_points_md"
CONFIG_IMAGE_COST_LG = "image_cost_points_lg"

# 默认值（仅作为 fallback，生产环境应通过后台配置）
DEFAULT_USD_TO_POINTS = 100  # 1美元 = 100积分

# 默认视频成本（按分辨率）
DEFAULT_VIDEO_COST_480P = 8
DEFAULT_VIDEO_COST_720P = 10
DEFAULT_VIDEO_COST_1080P = 15
DEFAULT_VIDEO_COST_4K = 30

# 默认图片成本（按尺寸）
DEFAULT_IMAGE_COST_SM = 3
DEFAULT_IMAGE_COST_MD = 5
DEFAULT_IMAGE_COST_LG = 10

# 分辨率映射
VIDEO_RESOLUTIONS = {
    "480p": CONFIG_VIDEO_COST_480P,
    "720p": CONFIG_VIDEO_COST_720P,
    "1080p": CONFIG_VIDEO_COST_1080P,
    "4k": CONFIG_VIDEO_COST_4K,
    "4K": CONFIG_VIDEO_COST_4K,
}

# 图片尺寸映射
IMAGE_SIZES = {
    "small": CONFIG_IMAGE_COST_SM,
    "medium": CONFIG_IMAGE_COST_MD,
    "large": CONFIG_IMAGE_COST_LG,
    "sm": CONFIG_IMAGE_COST_SM,
    "md": CONFIG_IMAGE_COST_MD,
    "lg": CONFIG_IMAGE_COST_LG,
    # 分辨率 → 尺寸映射（前端分辨率格式）
    "480p": CONFIG_IMAGE_COST_SM,
    "720p": CONFIG_IMAGE_COST_MD,
    "1080p": CONFIG_IMAGE_COST_LG,
}

# 默认视频和图片成本（兼容旧代码）
DEFAULT_VIDEO_COST_POINTS = DEFAULT_VIDEO_COST_720P
DEFAULT_IMAGE_COST_POINTS = DEFAULT_IMAGE_COST_MD


def get_usd_to_points_rate(db: Session) -> int:
    """获取全局汇率：1美元兑换多少积分"""
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == CONFIG_USD_TO_POINTS).first()
    if cfg and cfg.config_value:
        return int(cfg.config_value)
    return DEFAULT_USD_TO_POINTS


def points_to_usd(db: Session, points: int) -> float:
    """积分 → 美元（展示用）"""
    rate = get_usd_to_points_rate(db)
    return round(points / rate, 2)


def usd_to_points(db: Session, usd: float) -> int:
    """美元 → 积分（结算用），四舍五入取整"""
    rate = get_usd_to_points_rate(db)
    return max(1, round(usd * rate))


def format_usd(usd: float) -> str:
    """格式化美元价格显示：$X.XX"""
    return f"${usd:.2f}"


def format_points(points: int) -> str:
    """格式化积分显示：X 积分"""
    return f"{points} 积分"


def _get_config_value(db: Session, config_key: str, default: int) -> float:
    """获取配置值的通用方法（支持小数）"""
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == config_key).first()
    if cfg and cfg.config_value:
        return float(cfg.config_value)
    return float(default)


def _get_points_per_sec_config(db: Session) -> dict:
    """获取积分/秒配置（与前端保持一致）"""
    from database import SystemConfig
    from routers.admin import _DEFAULT_POINTS_PER_SEC
    
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


def get_video_cost_points(db: Session, resolution: str = "720p", model_id: str = None, duration: int = 5) -> float:
    """
    获取视频生成消耗积分（按分辨率和时长计算，可选按模型）
    
    Args:
        db: 数据库会话
        resolution: 分辨率，支持 480p, 720p, 1080p, 4k
        model_id: 模型ID，可选。如果提供，优先查找该模型特定的成本配置
        duration: 视频时长（秒），默认为5秒
    
    Returns:
        消耗的积分数量，如果没有配置返回0
    """
    # 获取积分/秒配置（只使用数据库配置，不使用默认值）
    points_per_sec_config = _get_points_per_sec_config(db)
    
    # 如果配置为空，返回0
    if not points_per_sec_config:
        return 0
    
    # 如果指定了模型ID，先尝试获取该模型特定的积分/秒配置
    if model_id and model_id in points_per_sec_config:
        model_config = points_per_sec_config[model_id]
        per_sec = model_config.get(resolution.lower()) or model_config.get("720p")
    else:
        # 尝试使用任意模型的配置
        per_sec = None
        for config in points_per_sec_config.values():
            if isinstance(config, dict):
                per_sec = config.get(resolution.lower()) or config.get("720p")
                if per_sec:
                    break
    
    # 如果没有找到配置，返回0
    if per_sec is None:
        return 0
    
    # 计算积分：积分 = 每秒积分 × 时长（支持小数点1位）
    return max(0.1, round(float(per_sec) * duration * 10) / 10)


def get_image_cost_points(db: Session, size: str = "medium", model_id: str = None) -> int:
    """
    获取图片生成消耗积分（按尺寸，可选按模型）
    
    Args:
        db: 数据库会话
        size: 尺寸，支持 small/sm, medium/md, large/lg
        model_id: 模型ID，可选。如果提供，优先查找该模型特定的成本配置
    
    Returns:
        消耗的积分数量
    """
    # 如果指定了模型ID，先尝试获取该模型特定的成本配置
    if model_id:
        normalized_size = IMAGE_SIZES.get(size.lower(), size.lower())
        # 获取标准尺寸标识
        size_key = size.lower()
        if size_key in ["small", "sm"]:
            size_key = "sm"
        elif size_key in ["medium", "md"]:
            size_key = "md"
        elif size_key in ["large", "lg"]:
            size_key = "lg"
        
        model_config_key = f"image_cost_{model_id}_{size_key}"
        model_cost = _get_config_value(db, model_config_key, None)
        if model_cost is not None:
            return model_cost
    
    # 使用默认的按尺寸配置
    config_key = IMAGE_SIZES.get(size.lower(), CONFIG_IMAGE_COST_MD)
    defaults = {
        CONFIG_IMAGE_COST_SM: DEFAULT_IMAGE_COST_SM,
        CONFIG_IMAGE_COST_MD: DEFAULT_IMAGE_COST_MD,
        CONFIG_IMAGE_COST_LG: DEFAULT_IMAGE_COST_LG,
    }
    return _get_config_value(db, config_key, defaults.get(config_key, DEFAULT_IMAGE_COST_MD))


def get_video_cost_by_resolution(db: Session) -> dict:
    """获取所有分辨率的默认视频成本"""
    return {
        "480p": get_video_cost_points(db, "480p"),
        "720p": get_video_cost_points(db, "720p"),
        "1080p": get_video_cost_points(db, "1080p"),
        "4k": get_video_cost_points(db, "4k"),
    }


def get_image_cost_by_size(db: Session) -> dict:
    """获取所有尺寸的默认图片成本"""
    return {
        "small": get_image_cost_points(db, "small"),
        "medium": get_image_cost_points(db, "medium"),
        "large": get_image_cost_points(db, "large"),
        "480p": get_image_cost_points(db, "480p"),
        "720p": get_image_cost_points(db, "720p"),
        "1080p": get_image_cost_points(db, "1080p"),

    }


def get_video_cost_by_model_and_resolution(db: Session, model_id: str) -> dict:
    """获取指定模型在各分辨率下的成本"""
    return {
        "480p": get_video_cost_points(db, "480p", model_id),
        "720p": get_video_cost_points(db, "720p", model_id),
        "1080p": get_video_cost_points(db, "1080p", model_id),
        "4k": get_video_cost_points(db, "4k", model_id),
    }


def get_image_cost_by_model_and_size(db: Session, model_id: str) -> dict:
    """获取指定模型在各尺寸下的成本"""
    return {
        "small": get_image_cost_points(db, "small", model_id),
        "medium": get_image_cost_points(db, "medium", model_id),
        "large": get_image_cost_points(db, "large", model_id),
    }


def calculate_subscription_points(db: Session, usd_price: float) -> int:
    """计算订阅套餐到账积分：美元价格 × 汇率"""
    return usd_to_points(db, usd_price)


def get_price_display(db: Session, cost_points: int) -> dict:
    """获取价格展示信息（美元 + 积分）"""
    usd_price = points_to_usd(db, cost_points)
    return {
        "points": cost_points,
        "usd": usd_price,
        "usd_formatted": format_usd(usd_price),
        "points_formatted": format_points(cost_points),
    }


def calculate_task_cost_display(db: Session, task_config: dict) -> dict:
    """
    计算任务费用展示信息
    
    Args:
        db: 数据库会话
        task_config: 任务配置字典，包含 mode, resolution, size, model, duration 等
    
    Returns:
        {points, usd, usd_formatted, points_formatted}
    """
    mode = task_config.get("mode", "txt2vid")
    model_id = task_config.get("model", task_config.get("endpoint_id"))
    
    if mode in ("txt2img", "image"):
        size = task_config.get("size", "medium")
        cost_points = get_image_cost_points(db, size, model_id)
    else:
        resolution = task_config.get("resolution", "720p")
        duration = task_config.get("duration", 5)
        cost_points = get_video_cost_points(db, resolution, model_id, duration)
    
    return get_price_display(db, cost_points)


def validate_pricing_config(db: Session) -> dict:
    """验证定价配置完整性"""
    rate = get_usd_to_points_rate(db)
    
    video_costs = get_video_cost_by_resolution(db)
    image_costs = get_image_cost_by_size(db)
    
    return {
        "usd_to_points": rate,
        "video_costs": video_costs,
        "image_costs": image_costs,
        "video_cost_usd": {k: points_to_usd(db, v) for k, v in video_costs.items()},
        "image_cost_usd": {k: points_to_usd(db, v) for k, v in image_costs.items()},
        "is_valid": rate > 0 and all(v > 0 for v in video_costs.values()) and all(v > 0 for v in image_costs.values()),
    }


def init_default_pricing_config(db: Session):
    """初始化默认定价配置（首次部署时调用）"""
    # 设置默认汇率
    if not db.query(SystemConfig).filter(SystemConfig.config_key == CONFIG_USD_TO_POINTS).first():
        db.add(SystemConfig(
            config_key=CONFIG_USD_TO_POINTS,
            config_value=DEFAULT_USD_TO_POINTS,
            description="全局汇率：1美元可兑换的积分数量"
        ))
    
    # 设置视频生成成本（按分辨率，默认值）
    video_configs = [
        (CONFIG_VIDEO_COST_480P, DEFAULT_VIDEO_COST_480P, "默认480p视频生成消耗积分"),
        (CONFIG_VIDEO_COST_720P, DEFAULT_VIDEO_COST_720P, "默认720p视频生成消耗积分"),
        (CONFIG_VIDEO_COST_1080P, DEFAULT_VIDEO_COST_1080P, "默认1080p视频生成消耗积分"),
        (CONFIG_VIDEO_COST_4K, DEFAULT_VIDEO_COST_4K, "默认4K视频生成消耗积分"),
    ]
    for key, value, desc in video_configs:
        if not db.query(SystemConfig).filter(SystemConfig.config_key == key).first():
            db.add(SystemConfig(config_key=key, config_value=value, description=desc))
    
    # 设置图片生成成本（按尺寸，默认值）
    image_configs = [
        (CONFIG_IMAGE_COST_SM, DEFAULT_IMAGE_COST_SM, "默认小尺寸图片生成消耗积分"),
        (CONFIG_IMAGE_COST_MD, DEFAULT_IMAGE_COST_MD, "默认中尺寸图片生成消耗积分"),
        (CONFIG_IMAGE_COST_LG, DEFAULT_IMAGE_COST_LG, "默认大尺寸图片生成消耗积分"),
    ]
    for key, value, desc in image_configs:
        if not db.query(SystemConfig).filter(SystemConfig.config_key == key).first():
            db.add(SystemConfig(config_key=key, config_value=value, description=desc))
    
    db.commit()


def save_model_pricing_config(db: Session, model_type: str, model_id: str, costs: dict):
    """
    保存特定模型的定价配置
    
    Args:
        db: 数据库会话
        model_type: 模型类型，'video' 或 'image'
        model_id: 模型ID
        costs: 成本配置字典，如 {'480p': 8, '720p': 10, ...} 或 {'small': 3, 'medium': 5, ...}
    """
    for key, value in costs.items():
        if model_type == "video":
            config_key = f"video_cost_{model_id}_{key.lower()}"
        else:
            # 标准化图片尺寸键
            size_key = key.lower()
            if size_key in ["small", "sm"]:
                size_key = "sm"
            elif size_key in ["medium", "md"]:
                size_key = "md"
            elif size_key in ["large", "lg"]:
                size_key = "lg"
            config_key = f"image_cost_{model_id}_{size_key}"
        
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == config_key).first()
        if cfg:
            cfg.config_value = value
        else:
            desc = f"{model_id}模型{key}成本"
            db.add(SystemConfig(config_key=config_key, config_value=value, description=desc))
    
    db.commit()


def get_all_model_pricing_configs(db: Session) -> dict:
    """获取所有模型特定的定价配置"""
    result = {"video": {}, "image": {}}
    
    # 查询所有视频模型成本配置
    video_cfgs = db.query(SystemConfig).filter(SystemConfig.config_key.like("video_cost_%")).all()
    for cfg in video_cfgs:
        # 跳过默认配置（video_cost_points_xxx）
        if cfg.config_key.startswith("video_cost_points_"):
            continue
        # 解析 model_id 和 resolution
        parts = cfg.config_key.split("_")
        if len(parts) >= 4:
            model_id = "_".join(parts[2:-1])
            resolution = parts[-1]
            if model_id not in result["video"]:
                result["video"][model_id] = {}
            result["video"][model_id][resolution] = int(cfg.config_value)
    
    # 查询所有图片模型成本配置
    image_cfgs = db.query(SystemConfig).filter(SystemConfig.config_key.like("image_cost_%")).all()
    for cfg in image_cfgs:
        # 跳过默认配置（image_cost_points_xxx）
        if cfg.config_key.startswith("image_cost_points_"):
            continue
        # 解析 model_id 和 size
        parts = cfg.config_key.split("_")
        if len(parts) >= 4:
            model_id = "_".join(parts[2:-1])
            size = parts[-1]
            if model_id not in result["image"]:
                result["image"][model_id] = {}
            result["image"][model_id][size] = int(cfg.config_value)
    
    return result
