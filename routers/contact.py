from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from database import get_db, User
from middleware.auth_middleware import get_current_user
import uuid, pathlib, mimetypes

router = APIRouter(prefix="/api/contact", tags=["contact"])

CONTACT_UPLOAD_DIR = pathlib.Path("static/uploads/contact")
CONTACT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIME_PREFIXES = ("image/", "video/", "application/pdf", "text/")
MAX_FILE_SIZE = 20 * 1024 * 1024


@router.post("/upload")
async def contact_upload_file(
    file: UploadFile = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件不能超过 20MB")
    mime = file.content_type or "application/octet-stream"
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail="不支持该文件类型")
    ext = pathlib.Path(file.filename or "file").suffix or mimetypes.guess_extension(mime) or ""
    local_name = f"{uuid.uuid4()}{ext}"
    (CONTACT_UPLOAD_DIR / local_name).write_bytes(content)
    return {"success": True, "url": f"/static/uploads/contact/{local_name}",
            "filename": file.filename, "mime_type": mime}


class TicketCreateRequest(BaseModel):
    email: str
    subject: str
    message: str
    attachments: Optional[List[dict]] = None


@router.post("")
async def submit_ticket(
    req: TicketCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not req.email or not req.subject or not req.message:
        raise HTTPException(status_code=400, detail="所有字段均为必填")
    from database import ContactMessage
    ticket = ContactMessage(
        user_id=current_user.id,
        email=req.email,
        subject=req.subject,
        message=req.message,
        attachments=req.attachments or [],
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return {"success": True, "ticket_id": ticket.id}


class ReplyRequest(BaseModel):
    content: str
    attachments: Optional[List[dict]] = None


@router.post("/{ticket_id}/reply")
async def user_reply_ticket(
    ticket_id: int,
    req: ReplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage, ContactReply, TicketStatus
    ticket = db.query(ContactMessage).filter(
        ContactMessage.id == ticket_id,
        ContactMessage.user_id == current_user.id,
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=400, detail="工单已关闭，无法继续回复")
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="回复内容不能为空")
    reply = ContactReply(
        ticket_id=ticket_id,
        sender="user",
        content=req.content.strip(),
        attachments=req.attachments or [],
    )
    db.add(reply)
    ticket.is_read = False  # 标记管理员需要查看
    db.commit()
    return {"success": True}


@router.get("/my")
async def list_my_tickets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from database import ContactMessage
    tickets = db.query(ContactMessage).filter(
        ContactMessage.user_id == current_user.id
    ).order_by(ContactMessage.created_at.desc()).limit(50).all()
    return {"items": [_ticket_dict(t, include_replies=True) for t in tickets]}


def _ticket_dict(t, include_replies=False):
    d = {
        "id": t.id,
        "subject": t.subject,
        "message": t.message,
        "attachments": t.attachments or [],
        "status": t.status.value if t.status else "open",
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if include_replies:
        d["replies"] = [{
            "id": r.id,
            "sender": r.sender,
            "content": r.content,
            "attachments": r.attachments or [],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in (t.replies or [])]
    return d
