from datetime import datetime, timezone, timedelta, timedelta
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt
import requests
import secrets
from cryptography.fernet import Fernet
import base64

from database import User, UserRole, UserStatus, ApiKey
from config import (
    SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE,
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
    ALLOW_REGISTRATION, ALLOW_EMAIL_LOGIN, ALLOW_GOOGLE_LOGIN,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 加密密钥 - 使用 SECRET_KEY 生成一个有效的 Fernet 密钥
def _get_fernet_key():
    key = hashlib.sha256(SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key[:32])

import hashlib
fernet = Fernet(_get_fernet_key())


def encrypt_value(value: str) -> str:
    """加密敏感值"""
    if not value:
        return None
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """解密敏感值"""
    if not encrypted:
        return None
    return fernet.decrypt(encrypted.encode()).decode()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: int, expire_delta=None) -> str:
    data = {"sub": str(user_id), "iat": datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)}
    expire = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) + (expire_delta or ACCESS_TOKEN_EXPIRE)
    data["exp"] = expire
    return jwt.encode(data, SECRET_KEY, algorithm=JWT_ALGORITHM)


def register_user(db: Session, email: str, password: str, display_name: str = None) -> User:
    if not ALLOW_REGISTRATION:
        raise ValueError("Registration is currently disabled")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name or email.split("@")[0],
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 发放新用户体验积分
    try:
        from services.point_service import earn_points
        from database import PointsType
        earn_points(db, user.id, 100, PointsType.EARN, "新用户注册赠送体验积分")
    except Exception:
        pass

    return user


def login_email(db: Session, email: str, password: str) -> User:
    if not ALLOW_EMAIL_LOGIN:
        raise ValueError("Email login is currently disabled")

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash:
        raise ValueError("Invalid credentials")
    if not verify_password(password, user.password_hash):
        raise ValueError("Invalid credentials")
    if user.status == UserStatus.BANNED:
        raise ValueError("Account has been banned")
    if user.status == UserStatus.INACTIVE:
        raise ValueError("Account is inactive")
    return user


def login_google(db: Session, id_token: str) -> User:
    if not ALLOW_GOOGLE_LOGIN:
        raise ValueError("Google login is currently disabled")

    try:
        res = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}", timeout=10)
        res.raise_for_status()
        data = res.json()

        if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
            raise ValueError("Invalid token audience")
    except Exception as e:
        raise ValueError(f"Google token verification failed: {e}")

    google_id = data.get("sub")
    email = data.get("email")
    name = data.get("name")
    picture = data.get("picture")

    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_id = google_id
            user.avatar_url = user.avatar_url or picture
        else:
            user = User(
                email=email,
                google_id=google_id,
                display_name=name,
                avatar_url=picture,
                role=UserRole.USER,
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            db.add(user)
    else:
        user.display_name = user.display_name or name
        user.avatar_url = user.avatar_url or picture

    db.commit()
    db.refresh(user)
    return user


def create_api_key(db: Session, user_id: int, name: str, permissions: list = None) -> dict:
    prefix = "sd_"
    raw_key = prefix + secrets.token_hex(16)
    import hashlib
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    record = ApiKey(
        user_id=user_id,
        key_hash=key_hash,
        key_prefix=prefix,
        name=name,
        permissions=permissions or ["read", "task:create"],
    )
    db.add(record)
    db.commit()
    return {"id": record.id, "api_key": raw_key, "name": name}


def make_admin(db: Session, user_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.role = UserRole.ADMIN
        db.commit()