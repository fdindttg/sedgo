from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db, User
from middleware.auth_middleware import get_current_user
from services.point_service import get_user_points, get_user_points_history

router = APIRouter(prefix="/api/points", tags=["points"])


@router.get("/balance")
def get_balance(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"balance": get_user_points(db, current_user.id)}


@router.get("/history")
def get_points_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_user_points_history(db, current_user.id, page, page_size)