from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional

from backend.database import get_db
from backend.models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()

@router.get("")
def list_notifications(
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    notifs = db.query(Notification).filter(
        Notification.recipient_id == current_user.id
    ).order_by(desc(Notification.created_at)).limit(30).all()
    unread_count = db.query(Notification).filter(
        Notification.recipient_id == current_user.id,
        Notification.is_read == False
    ).count()

    return {
        "unread_count": unread_count,
        "notifications": [n.to_dict() for n in notifs]
    }

@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db)
):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"status": "ok"}

@router.post("/read-all")
def mark_all_read(
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    db.query(Notification).filter(
        Notification.recipient_id == current_user.id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"status": "ok"}
