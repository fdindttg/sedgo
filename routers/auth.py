from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db, User
from middleware.auth_middleware import get_current_user
from services.auth_service import register_user, login_email, login_google, create_token, create_api_key
from services.point_service import get_user_points
from services.subscription_service import get_active_subscription
from schemas import UserRegister, UserLogin, GoogleLogin
from config import ALLOW_REGISTRATION, ALLOW_EMAIL_LOGIN, ALLOW_GOOGLE_LOGIN
import os
import uuid

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def get_auth_config():
    return {
        "allow_registration": ALLOW_REGISTRATION,
        "allow_email_login": ALLOW_EMAIL_LOGIN,
        "allow_google_login": ALLOW_GOOGLE_LOGIN,
    }


@router.post("/register")
def api_register(data: UserRegister, db: Session = Depends(get_db)):
    try:
        user = register_user(db, data.email, data.password, data.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    token = create_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_response(db, user),
    }


@router.post("/login")
def api_login(data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = login_email(db, data.email, data.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    token = create_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_response(db, user),
    }


@router.post("/google")
def api_google_login(data: GoogleLogin, db: Session = Depends(get_db)):
    try:
        user = login_google(db, data.id_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    token = create_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_response(db, user),
    }


@router.get("/me")
def api_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_response(db, current_user)


@router.post("/api-keys")
def api_create_key(
    name: str = "default",
    permissions: list = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_api_key(db, current_user.id, name, permissions)


def _user_response(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "role": user.role.value,
        "status": user.status.value,
        "points_balance": get_user_points(db, user.id),
        "subscription": get_active_subscription(db, user.id),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/profile")
def api_update_profile(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    display_name = data.get("display_name", "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="Display name cannot be empty")

    current_user.display_name = display_name
    db.commit()
    return _user_response(db, current_user)


@router.put("/password")
def api_change_password(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.auth_service import verify_password, hash_password
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")
    if not new_pw or len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")
    if current_user.password_hash and not verify_password(old_pw, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    current_user.password_hash = hash_password(new_pw)
    db.commit()
    return {"success": True}


@router.put("/profile/avatar")
async def api_update_avatar(
    avatar: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed_extensions = ["jpg", "jpeg", "png", "webp", "gif"]
    ext = avatar.filename.split(".")[-1].lower() if avatar.filename else ""

    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Invalid file type")

    os.makedirs("static/avatars", exist_ok=True)

    filename = f"{uuid.uuid4()}.{ext}"
    filepath = f"static/avatars/{filename}"

    with open(filepath, "wb") as f:
        f.write(await avatar.read())

    current_user.avatar_url = f"/static/avatars/{filename}"
    db.commit()

    return {"avatar_url": current_user.avatar_url}