from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, Float, JSON, Enum as SAEnum, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.sql import func
import enum
from datetime import datetime, timezone, timedelta
from config import DATABASE_URL, DATABASE_POOL_SIZE, DATABASE_MAX_OVERFLOW, DATABASE_POOL_TIMEOUT, DATABASE_POOL_RECYCLE, DATABASE_ECHO

CST = timezone(timedelta(hours=8))

def beijing_now():
    return datetime.now(CST).replace(tzinfo=None)

_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

# SQLite不支持连接池，使用简单配置
if "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        connect_args=_connect_args,
        echo=False,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=DATABASE_POOL_SIZE,
        max_overflow=DATABASE_MAX_OVERFLOW,
        pool_timeout=DATABASE_POOL_TIMEOUT,
        pool_recycle=DATABASE_POOL_RECYCLE,
        pool_pre_ping=True,
        pool_use_lifo=True,  # 使用LIFO策略，减少连接回收频率
        connect_args=_connect_args,
        echo=DATABASE_ECHO,
        max_identifier_length=128,  # MySQL支持的最大标识符长度
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """获取数据库会话（用于后台任务）"""
    return SessionLocal()


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class EndpointType(str, enum.Enum):
    """接入点类型枚举"""
    VIDEO = "video"           # 视频生成
    IMAGE = "image"           # 图片生成
    INFERENCE = "inference"   # 推理
    REAL_PEOPLE = "real_people"  # 真人素材
    DEFAULT = "default"       # 通用


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    TRIAL = "trial"


class PointsType(str, enum.Enum):
    EARN = "earn"
    CONSUME = "consume"
    EXPIRE = "expire"
    ADMIN_ADJUST = "admin_adjust"
    SUBSCRIPTION = "subscription"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    display_name = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    role = Column(SAEnum(UserRole), default=UserRole.USER, nullable=False)
    status = Column(SAEnum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    email_verified = Column(Boolean, default=False)
    last_login_at = Column(DateTime, nullable=True)
    asset_group_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    subscriptions = relationship("UserSubscription", back_populates="user")
    points = relationship("PointsRecord", back_populates="user")
    api_keys = relationship("ApiKey", back_populates="user")
    tasks = relationship("TaskRecord", back_populates="user")
    batch_tasks = relationship("BatchTask", back_populates="user")


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, default=0)
    duration_days = Column(Integer, default=30)
    points_per_month = Column(Integer, default=0)
    max_batch_size = Column(Integer, default=1)
    max_concurrent_tasks = Column(Integer, default=1)  # 最大并发任务数
    max_resolution = Column(String(20), default="720p")
    features = Column(JSON, nullable=True)
    annual_discount = Column(Integer, default=0)  # 年付折扣（百分比，0-100）
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)


class SystemConfig(Base):
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(JSON, nullable=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False)
    status = Column(SAEnum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE, nullable=False)
    billing_cycle = Column(String(20), default="monthly")  # monthly 或 annual
    started_at = Column(DateTime, default=beijing_now)
    expires_at = Column(DateTime, nullable=False)
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=beijing_now)

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan")


class PointsRecord(Base):
    __tablename__ = "points_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    points = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    type = Column(SAEnum(PointsType), nullable=False)
    description = Column(String(500), nullable=True)
    reference_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=beijing_now)

    user = relationship("User", back_populates="points")


class PointsConfig(Base):
    __tablename__ = "points_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    points_per_token = Column(Integer, default=1, nullable=False)
    token_unit = Column(String(50), default="request", nullable=False)
    effective_from = Column(DateTime, nullable=False)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=beijing_now)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    provider = Column(String(50), default="byteplus")
    
    # API 基础配置
    api_base_url = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=True)
    task_url = Column(String(500), nullable=True)
    
    # AK/SK 配置（加密存储）
    ak_encrypted = Column(Text, nullable=True)
    sk_encrypted = Column(Text, nullable=True)
    
    # API Key 配置（加密存储）
    api_key_encrypted = Column(Text, nullable=True)
    
    # 项目配置
    project_id = Column(String(100), nullable=True)
    project_name = Column(String(200), nullable=True)
    portrait_group_id = Column(String(100), nullable=True)
    public_base_url = Column(String(500), nullable=True)

    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)


class Endpoint(Base):
    __tablename__ = "endpoints"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    
    # 接入点配置
    endpoint_id = Column(String(100), nullable=False)
    endpoint_name = Column(String(200), nullable=True)
    endpoint_url = Column(String(500), nullable=True)
    
    # 用途类型
    type = Column(SAEnum(EndpointType), default=EndpointType.DEFAULT)
    
    # 模型映射（使用此接入点的模型列表）
    models = Column(JSON, nullable=True)  # ["model1", "model2"]
    
    # 默认接入点标记
    is_default = Column(Boolean, default=False)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)


class TaskRecord(Base):
    __tablename__ = "task_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    external_task_id = Column(String(255), nullable=True, index=True)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    model = Column(String(100), nullable=True)
    prompt = Column(Text, nullable=True)
    duration_seconds = Column(Integer, default=5)
    resolution = Column(String(20), default="720p")
    ratio = Column(String(10), default="16:9")
    tokens_consumed = Column(Integer, default=0)
    points_consumed = Column(Integer, default=0)
    video_url = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)
    progress = Column(Integer, default=0)
    batch_task_id = Column(Integer, ForeignKey("batch_tasks.id"), nullable=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    user = relationship("User", back_populates="tasks")
    batch_task = relationship("BatchTask", back_populates="tasks")


class BatchTask(Base):
    __tablename__ = "batch_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    total_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    user = relationship("User", back_populates="batch_tasks")
    tasks = relationship("TaskRecord", back_populates="batch_task")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key_hash = Column(String(64), unique=True, nullable=False)
    key_prefix = Column(String(10), nullable=False)
    name = Column(String(100), nullable=False)
    permissions = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=beijing_now)

    user = relationship("User", back_populates="api_keys")


class VideoComposition(Base):
    __tablename__ = "video_compositions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    total_duration = Column(Integer, nullable=False)  # 总时长（秒）
    prompt = Column(Text, nullable=True)
    resolution = Column(String(20), default="720p")
    ratio = Column(String(10), default="16:9")
    total_points_consumed = Column(Integer, default=0)
    final_video_url = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)
    progress = Column(Integer, default=0)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    
    segments = relationship("VideoSegment", back_populates="composition")


class VideoSegment(Base):
    __tablename__ = "video_segments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    composition_id = Column(Integer, ForeignKey("video_compositions.id"), nullable=False, index=True)
    task_record_id = Column(Integer, ForeignKey("task_records.id"), nullable=True)
    segment_index = Column(Integer, nullable=False)  # 片段顺序（从0开始）
    start_time = Column(Integer, nullable=False)  # 在原视频中的开始时间（秒）
    duration = Column(Integer, nullable=False)  # 片段时长（秒）
    video_url = Column(Text, nullable=True)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    
    composition = relationship("VideoComposition", back_populates="segments")
    task_record = relationship("TaskRecord")


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"       # 等待付款
    CONFIRMING = "confirming" # 链上确认中
    COMPLETED = "completed"   # 已完成
    EXPIRED = "expired"       # 已过期
    CANCELLED = "cancelled"   # 已取消


class PaymentType(str, enum.Enum):
    SUBSCRIPTION = "subscription"  # 购买订阅
    POINTS = "points"              # 充值积分


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    payment_type = Column(SAEnum(PaymentType), nullable=False)
    # 套餐购买
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=True)
    billing_cycle = Column(String(20), nullable=True)
    # 积分充值
    points_amount = Column(Integer, nullable=True)
    # 金额
    amount_usdt = Column(Float, nullable=False)        # USDT 金额
    amount_cny = Column(Integer, nullable=True)        # 人民币分（参考）
    # 收款地址（每单独立，便于对账）
    receive_address = Column(String(100), nullable=False)
    network = Column(String(20), default="TRC20")
    # 链上信息
    tx_hash = Column(String(100), nullable=True, index=True)
    from_address = Column(String(100), nullable=True)
    confirmed_amount = Column(Float, nullable=True)
    # 状态
    status = Column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    user = relationship("User")
    plan = relationship("SubscriptionPlan", foreign_keys=[plan_id])


class AssetType(str, enum.Enum):
    """资产类型枚举"""
    AVATAR = "avatar"           # 虚拟人
    PORTRAIT = "portrait"       # 真人肖像
    ACTION = "action"           # 动作
    BACKGROUND = "background"   # 背景
    VOICE = "voice"             # 声音


class AssetLibrary(Base):
    __tablename__ = "asset_library"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    asset_type = Column(SAEnum(AssetType), nullable=False)
    external_id = Column(String(255), nullable=True)  # BytePlus 资产ID
    asset_url = Column(Text, nullable=True)  # 资产预览URL
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    
    user = relationship("User")

class TicketStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class ContactMessage(Base):
    __tablename__ = "contact_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    message = Column(Text, nullable=False)
    attachments = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False)
    status = Column(SAEnum(TicketStatus, values_callable=lambda x: [e.value for e in x]), default=TicketStatus.OPEN, nullable=False)
    # legacy single-reply fields kept for migration compat, no longer used
    admin_reply = Column(Text, nullable=True)
    replied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=beijing_now)

    user = relationship("User")
    replies = relationship("ContactReply", back_populates="ticket", order_by="ContactReply.created_at")


class ContactReply(Base):
    __tablename__ = "contact_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("contact_messages.id"), nullable=False, index=True)
    sender = Column(String(10), nullable=False)   # "user" or "admin"
    content = Column(Text, nullable=False)
    attachments = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=beijing_now)

    ticket = relationship("ContactMessage", back_populates="replies")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    file_id = Column(String(255), nullable=False)
    filename = Column(String(500), nullable=True)
    mime_type = Column(String(100), nullable=True)
    url = Column(Text, nullable=True)
    purpose = Column(String(50), default="user_data")
    created_at = Column(DateTime, default=beijing_now)

    user = relationship("User")


# ── 短剧工作室 Models ─────────────────────────────────────────────────


class DramaStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class DramaProject(Base):
    """短剧项目"""
    __tablename__ = "drama_projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    genre = Column(String(50), nullable=True)  # 类型：逆袭/重生/霸总/甜宠/穿越/古装
    logline = Column(Text, nullable=True)  # 一句话梗概
    total_episodes = Column(Integer, default=10)
    cover_url = Column(Text, nullable=True)
    status = Column(SAEnum(DramaStatus), default=DramaStatus.DRAFT, nullable=False)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    user = relationship("User")
    episodes = relationship("DramaEpisode", back_populates="project", cascade="all, delete-orphan", order_by="DramaEpisode.episode_number")


class DramaEpisode(Base):
    """短剧剧集"""
    __tablename__ = "drama_episodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("drama_projects.id"), nullable=False, index=True)
    episode_number = Column(Integer, nullable=False)
    title = Column(String(200), nullable=True)
    # 剧本内容 — 结构化 JSON，包含四幕结构
    script_content = Column(JSON, nullable=True)
    # 情绪走势标注
    emotion_arc = Column(JSON, nullable=True)  # [{"order":1,"emotion":"屈辱","description":"遭受白眼"}, ...]
    # 勾人卡点（每集结尾悬念）
    cliffhanger = Column(Text, nullable=True)
    # 黄金3秒钩子
    hook = Column(Text, nullable=True)
    status = Column(SAEnum(DramaStatus), default=DramaStatus.DRAFT, nullable=False)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    project = relationship("DramaProject", back_populates="episodes")
    scenes = relationship("DramaScene", back_populates="episode", cascade="all, delete-orphan", order_by="DramaScene.scene_number")


class DramaScene(Base):
    """分镜场景"""
    __tablename__ = "drama_scenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    episode_id = Column(Integer, ForeignKey("drama_episodes.id"), nullable=False, index=True)
    scene_number = Column(Integer, nullable=False)
    # 分镜结构化字段
    location = Column(String(200), nullable=True)       # 场景地点
    time_period = Column(String(50), nullable=True)     # 时段：白天/夜晚/黄昏
    characters = Column(JSON, nullable=True)            # [{"name":"林凡","age":25,"outfit":"黑色风衣","expression":"眼神坚毅"}, ...]
    camera_instruction = Column(Text, nullable=True)    # 运镜指示：面部特写/跟拍拉远
    prompt_text = Column(Text, nullable=True)           # 生成用的完整提示词
    # 保一致性：角色特征 ID / Seed
    character_seeds = Column(JSON, nullable=True)       # {"character_name": 12345}
    duration = Column(Integer, default=5)               # 片段时长（秒）
    # 生成结果
    status = Column(SAEnum(DramaStatus), default=DramaStatus.DRAFT, nullable=False)
    video_urls = Column(JSON, nullable=True)            # 候选视频列表（抽卡多选）
    selected_url = Column(Text, nullable=True)          # 选中的最佳视频
    task_record_ids = Column(JSON, nullable=True)       # 关联的任务记录ID列表
    # 质量标注
    quality_score = Column(Integer, nullable=True)      # 1-10 质量评分
    has_defect = Column(Boolean, default=False)          # 是否有缺陷（需重跑）
    retry_count = Column(Integer, default=0)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    episode = relationship("DramaEpisode", back_populates="scenes")


# 分镜 ↔ 任务记录关联表
class DramaSceneTask(Base):
    __tablename__ = "drama_scene_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    drama_scene_id = Column(Integer, ForeignKey("drama_scenes.id"), nullable=False, index=True)
    task_record_id = Column(Integer, ForeignKey("task_records.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=beijing_now)
