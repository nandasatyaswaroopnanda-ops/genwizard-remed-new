import os
import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models import Attachment, User, Incident, ServiceRequest, ChangeRequest

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

UPLOAD_DIR = os.path.abspath("uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".txt", ".log", ".json", ".zip"
}
MAX_FILE_SIZE = 15 * 1024 * 1024 # 15 MB

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()

@router.post("")
async def upload_attachment(
    ticket_type: str = Form(...),
    ticket_id: int = Form(...),
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File extension '{ext}' is not permitted.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds maximum allowable size of 15MB.")

    clean_basename = os.path.basename(file.filename or "attachment")
    safe_filename = f"{uuid.uuid4()}_{clean_basename}"
    filepath = os.path.abspath(os.path.join(UPLOAD_DIR, safe_filename))
    if not filepath.startswith(UPLOAD_DIR):
        raise HTTPException(status_code=400, detail="Invalid attachment destination path.")

    with open(filepath, "wb") as f:
        f.write(content)

    att = Attachment(
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        filename=file.filename,
        filepath=filepath,
        content_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        uploaded_by_id=current_user.id
    )
    db.add(att)
    db.commit()

    return att.to_dict()

@router.get("/ticket/{ticket_type}/{ticket_id}")
def list_ticket_attachments(
    ticket_type: str,
    ticket_id: int,
    db: Session = Depends(get_db)
):
    atts = db.query(Attachment).filter(
        Attachment.ticket_type == ticket_type,
        Attachment.ticket_id == ticket_id
    ).all()
    return [a.to_dict() for a in atts]

@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db)
):
    att = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    real_path = os.path.abspath(att.filepath)
    if not real_path.startswith(UPLOAD_DIR) or not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Attachment file not found")

    return FileResponse(
        path=real_path,
        filename=os.path.basename(att.filename),
        media_type=att.content_type
    )
