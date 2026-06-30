import os
from datetime import timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ============== 数据库配置（必须配置） ==============
DATABASE_URL = os.getenv("SD_DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("环境变量 SD_DATABASE_URL 必须设置！")

DATABASE_POOL_SIZE = int(os.getenv("SD_DB_POOL_SIZE", "200"))
DATABASE_MAX_OVERFLOW = int(os.getenv("SD_DB_MAX_OVERFLOW", "500"))
DATABASE_POOL_TIMEOUT = int(os.getenv("SD_DB_POOL_TIMEOUT", "60"))
DATABASE_POOL_RECYCLE = int(os.getenv("SD_DB_POOL_RECYCLE", "180"))
DATABASE_ECHO = os.getenv("SD_DB_ECHO", "false").lower() == "true"

# ============== 基础配置 ==============
SECRET_KEY = os.getenv("SD_SECRET_KEY", "seedance-super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = timedelta(hours=2)
REFRESH_TOKEN_EXPIRE = timedelta(days=30)

# ============== Redis配置 ==============
REDIS_URL = os.getenv("SD_REDIS_URL", "")
REDIS_PREFIX = "sd:"

# ============== Google OAuth配置 ==============
GOOGLE_CLIENT_ID = os.getenv("SD_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("SD_GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("SD_GOOGLE_REDIRECT_URI", "")

# ============== 用户注册配置 ==============
ALLOW_REGISTRATION = os.getenv("SD_ALLOW_REGISTRATION", "true").lower() == "true"
ALLOW_EMAIL_LOGIN = os.getenv("SD_ALLOW_EMAIL_LOGIN", "true").lower() == "true"
ALLOW_GOOGLE_LOGIN = os.getenv("SD_ALLOW_GOOGLE_LOGIN", "false").lower() == "true"

# ============== 积分配置 ==============
DEFAULT_POINTS_PER_TOKEN = int(os.getenv("SD_POINTS_PER_TOKEN", "10"))
DEFAULT_TOKEN_UNIT = os.getenv("SD_TOKEN_UNIT", "s-480p")

# ============== BytePlus API配置（仅URL，认证信息从数据库读取） ==============
DEFAULT_FILE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/files"
DEFAULT_TASK_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
DEFAULT_LIST_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/files/list"

# ============== 服务器公网URL（素材库上传需要可公网访问的文件URL） ==============
PUBLIC_BASE_URL = os.getenv("SD_PUBLIC_BASE_URL", "")

# ============== 批处理配置 ==============
BATCH_MAX_SIZE = int(os.getenv("SD_BATCH_MAX_SIZE", "20"))
BATCH_POLL_INTERVAL = int(os.getenv("SD_BATCH_POLL_INTERVAL", "3"))

# ============== 限流配置 ==============
RATE_LIMIT_DEFAULT = os.getenv("SD_RATE_LIMIT_DEFAULT", "30/minute")
RATE_LIMIT_PREMIUM = os.getenv("SD_RATE_LIMIT_PREMIUM", "120/minute")
