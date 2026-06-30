from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any, Literal
from datetime import datetime
from enum import Enum


class EndpointType(str, Enum):
    """接入点类型枚举"""
    VIDEO = "video"           # 视频生成
    IMAGE = "image"           # 图片生成
    INFERENCE = "inference"   # 推理
    DEFAULT = "default"       # 通用


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class SubscriptionStatus(str, Enum):
    """订阅状态枚举"""
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PointsType(str, Enum):
    """积分类型枚举"""
    EARNED = "earned"
    CONSUMED = "consumed"
    ADJUSTED = "adjusted"
    SUBSCRIPTION = "subscription"
    REFERRAL = "referral"


class UserRegister(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=128)
    display_name: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class GoogleLogin(BaseModel):
    id_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: int
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    status: str
    points_balance: int = 0
    subscription: Optional[dict] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AdminUserUpdate(BaseModel):
    status: Optional[str] = None
    role: Optional[str] = None
    user_type: Optional[str] = None
    remark: Optional[str] = None


class SubscriptionPlanCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price_cents: int = 0
    duration_days: int = 30
    points_per_month: int = 0
    max_batch_size: int = 1
    max_resolution: str = "720p"
    features: Optional[dict] = None
    sort_order: int = 0
    is_active: bool = True


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = None
    duration_days: Optional[int] = None
    points_per_month: Optional[int] = None
    max_batch_size: Optional[int] = None
    max_resolution: Optional[str] = None
    features: Optional[dict] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class AdminSubscriptionCreate(BaseModel):
    user_id: int
    plan_id: int
    duration_days: Optional[int] = None


class PointsConfigSet(BaseModel):
    points_per_token: int
    token_unit: str = "request"


class PointsRecordResponse(BaseModel):
    id: int
    points: int
    balance_after: int
    type: str
    description: Optional[str] = None
    reference_id: Optional[str] = None
    created_at: Optional[str] = None


class PointsHistoryResponse(BaseModel):
    items: List[PointsRecordResponse]
    total: int
    page: int
    page_size: int


class AdminPointsAdjust(BaseModel):
    amount: int
    reason: Optional[str] = None


class AdminSubscriptionUpdate(BaseModel):
    plan_id: Optional[int] = None
    duration: Optional[int] = None
    status: Optional[str] = None
    expires_at: Optional[datetime] = None
    billing_cycle: Optional[str] = "monthly"  # monthly 或 annual


class PointsStatsResponse(BaseModel):
    total_earned: int
    total_consumed: int
    total_adjusted: int
    total_subscription: int
    daily_stats: List[dict]


class ChannelCreate(BaseModel):
    name: str
    provider: str = "byteplus"
    
    # API 基础配置
    api_base_url: str
    file_url: Optional[str] = None
    task_url: Optional[str] = None
    
    # AK/SK 配置
    ak: Optional[str] = None
    sk: Optional[str] = None
    
    # API Key 配置（优先使用）
    api_key: Optional[str] = None
    
    # 项目配置
    project_id: Optional[str] = None
    portrait_group_id: Optional[str] = None
    public_base_url: Optional[str] = None

    priority: int = 0
    is_active: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    
    # API 基础配置
    api_base_url: Optional[str] = None
    file_url: Optional[str] = None
    task_url: Optional[str] = None
    
    # AK/SK 配置
    ak: Optional[str] = None
    sk: Optional[str] = None
    
    # API Key 配置（优先使用）
    api_key: Optional[str] = None
    
    # 项目配置
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    portrait_group_id: Optional[str] = None
    public_base_url: Optional[str] = None

    priority: Optional[int] = None
    is_active: Optional[bool] = None


class EndpointCreate(BaseModel):
    channel_id: int
    endpoint_id: str
    endpoint_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    type: Literal["video", "image", "inference", "default", "real_people"] = "default"
    models: Optional[list] = None
    is_default: bool = False
    is_active: bool = True


class EndpointUpdate(BaseModel):
    endpoint_id: Optional[str] = None
    endpoint_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    type: Optional[Literal["video", "image", "inference", "default", "real_people"]] = None
    models: Optional[list] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class TaskCreate(BaseModel):
    model: str = "sedgo-fast"
    prompt: Optional[str] = None
    duration_seconds: int = 5
    resolution: str = "720p"
    ratio: str = "16:9"
    reference_images: Optional[List[str]] = None
    reference_audios: Optional[List[str]] = None
    reference_videos: Optional[List[str]] = None
    mode: str = "txt2vid"
    
    # 音频和水印控制
    generate_audio: bool = True
    watermark: bool = False
    
    # 真人素材参数（参考 BytePlus 文档：https://docs.byteplus.com/en/docs/ModelArk/2333601）
    use_real_people: Optional[bool] = None
    avatar_id: Optional[str] = None
    asset_library_id: Optional[str] = None
    real_human_portrait_id: Optional[str] = None
    action_id: Optional[str] = None
    background_id: Optional[str] = None
    voice_id: Optional[str] = None
    
    # 精细化字幕擦除功能（参考文档：https://bytedance.larkoffice.com/docx/FG9AdmjyDoTRugxYsMWci956nwd）
    subtitle_removal: Optional[bool] = None
    subtitle_removal_mode: str = "accurate"


class BatchTaskCreate(BaseModel):
    tasks: List[TaskCreate]
    callback_url: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int


class DashboardStats(BaseModel):
    total_users: int
    total_tasks: int
    total_points_consumed: int
    active_users_today: int


# ── Image Generation Schemas ─────────────────────────────────────────

class ImageTaskCreate(BaseModel):
    prompt: str
    endpoint_id: Optional[str] = None
    model: Optional[str] = None
    style: Optional[str] = None
    resolution: Optional[str] = None
    num_images: int = 1


class ImageTaskResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[int] = None
    image_url: Optional[str] = None
    error_msg: Optional[str] = None


# ── Video Composition Schemas ────────────────────────────────────────

class VideoCompositionCreate(BaseModel):
    duration_seconds: int = 15
    prompt: str
    model: str = "seedance2.0-fast"
    resolution: str = "720p"
    ratio: str = "16:9"
    reference_images: Optional[List[str]] = None
    mode: str = "txt2vid"


class VideoSegmentResponse(BaseModel):
    id: int
    task_id: int
    segment_order: int
    status: str
    video_url: Optional[str] = None
    created_at: Optional[datetime] = None


class VideoCompositionResponse(BaseModel):
    id: int
    user_id: int
    status: str
    total_segments: int
    completed_segments: int
    final_video_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    segments: Optional[List[VideoSegmentResponse]] = None


# ── Endpoint Schemas ─────────────────────────────────────────────────

class EndpointResponse(BaseModel):
    id: int
    channel_id: int
    endpoint_id: str
    endpoint_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    type: str
    models: Optional[list] = None
    is_default: bool
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EndpointListResponse(BaseModel):
    endpoints: List[EndpointResponse]
    total: int


# ── Asset Library Schemas ────────────────────────────────────────────

class AssetCreate(BaseModel):
    name: str
    asset_type: str = "avatar"


class AssetResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    message: Optional[str] = None


class AssetListResponse(BaseModel):
    success: bool
    data: Optional[list] = None
    total: Optional[int] = None


# ── Task Schemas ─────────────────────────────────────────────────────

class TaskResponse(BaseModel):
    id: int
    user_id: int
    channel_id: Optional[int] = None
    endpoint_id: Optional[str] = None
    model: str
    prompt: Optional[str] = None
    status: str
    result_url: Optional[str] = None
    error_msg: Optional[str] = None
    duration_seconds: Optional[int] = None
    resolution: Optional[str] = None
    ratio: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    total: int


# ── Channel Schemas ──────────────────────────────────────────────────

class ChannelResponse(BaseModel):
    id: int
    name: str
    provider: str
    api_base_url: Optional[str] = None
    priority: int
    is_active: bool
    endpoint_count: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChannelListResponse(BaseModel):
    channels: List[ChannelResponse]
    total: int


# ── Subscription Schemas ─────────────────────────────────────────────

class SubscriptionPlanResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price_cents: int
    duration_days: int
    points_per_month: int
    max_batch_size: int
    max_resolution: str
    features: Optional[dict] = None
    sort_order: int
    is_active: bool

    class Config:
        from_attributes = True


class UserSubscriptionResponse(BaseModel):
    id: int
    user_id: int
    plan_id: int
    status: str
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    auto_renew: bool
    plan: Optional[SubscriptionPlanResponse] = None

    class Config:
        from_attributes = True


# ── Points Schemas ───────────────────────────────────────────────────

class PointsBalanceResponse(BaseModel):
    user_id: int
    balance: int
    total_earned: int
    total_consumed: int


class PointsRecordCreate(BaseModel):
    points: int
    type: str
    description: Optional[str] = None
    reference_id: Optional[str] = None


# ── User Schemas ─────────────────────────────────────────────────────

class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserPasswordUpdate(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class UserResponseFull(BaseModel):
    id: int
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    status: str
    points_balance: int
    subscription: Optional[UserSubscriptionResponse] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True