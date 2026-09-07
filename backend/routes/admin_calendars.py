import json
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel

from backend.database import get_db
from backend.models import BusinessCalendar, User, ConfigurationAudit

router = APIRouter(prefix="/api/admin/calendars", tags=["admin-calendars"])

def get_admin_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()

class CalendarSchema(BaseModel):
    name: str
    description: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    working_days: List[int] = [1, 2, 3, 4, 5]
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    holidays: List[str] = []
    exceptions: List[dict] = []
    reason: Optional[str] = "Calendar update"

@router.get("")
def list_calendars(db: Session = Depends(get_db)):
    calendars = db.query(BusinessCalendar).order_by(BusinessCalendar.name.asc()).all()
    return [c.to_dict() for c in calendars]

@router.post("")
def create_calendar(
    payload: CalendarSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    cal = BusinessCalendar(
        name=payload.name,
        description=payload.description,
        timezone=payload.timezone,
        working_days=json.dumps(payload.working_days),
        working_hours_start=payload.working_hours_start,
        working_hours_end=payload.working_hours_end,
        holidays=json.dumps(payload.holidays),
        exceptions=json.dumps(payload.exceptions)
    )
    db.add(cal)
    db.flush()

    audit = ConfigurationAudit(
        entity_type="BusinessCalendar",
        entity_id=cal.name,
        user_name=current_user.full_name,
        old_configuration="{}",
        new_configuration=json.dumps(cal.to_dict()),
        reason=payload.reason or "Created new business calendar",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return cal.to_dict()

@router.put("/{calendar_id}")
def update_calendar(
    calendar_id: int,
    payload: CalendarSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    cal = db.query(BusinessCalendar).filter(BusinessCalendar.id == calendar_id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="Calendar not found")

    old_cfg = cal.to_dict()
    cal.name = payload.name
    cal.description = payload.description
    cal.timezone = payload.timezone
    cal.working_days = json.dumps(payload.working_days)
    cal.working_hours_start = payload.working_hours_start
    cal.working_hours_end = payload.working_hours_end
    cal.holidays = json.dumps(payload.holidays)
    cal.exceptions = json.dumps(payload.exceptions)

    audit = ConfigurationAudit(
        entity_type="BusinessCalendar",
        entity_id=cal.name,
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration=json.dumps(cal.to_dict()),
        reason=payload.reason or "Updated business calendar",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return cal.to_dict()
