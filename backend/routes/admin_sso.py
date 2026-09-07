import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from backend.database import get_db
from backend.models import DistributionList, AssignmentGroup, GroupDistributionList, User

router = APIRouter(prefix="/api/admin/sso", tags=["admin-sso"])

def get_admin_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()

def require_admin(user: User):
    if user.role != "administrator":
        raise HTTPException(status_code=403, detail="Administrator access required")

class DLSchema(BaseModel):
    email: str
    display_name: Optional[str] = None
    privilege: str = "support"   # support | administrator

class GroupDLSchema(BaseModel):
    distribution_list_id: int
    notification_enabled: bool = True

# ---- Distribution Lists (global) ----

@router.get("/distribution-lists")
def list_distribution_lists(db: Session = Depends(get_db)):
    dls = db.query(DistributionList).filter(DistributionList.active == True).order_by(DistributionList.email).all()
    return [dl.to_dict() for dl in dls]

@router.post("/distribution-lists")
def create_distribution_list(
    payload: DLSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    require_admin(current_user)
    valid = ["support", "administrator"]
    if payload.privilege not in valid:
        raise HTTPException(status_code=400, detail=f"privilege must be one of {valid}")
    existing = db.query(DistributionList).filter(DistributionList.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="DL with this email already exists")
    dl = DistributionList(email=payload.email.lower(), display_name=payload.display_name, privilege=payload.privilege)
    db.add(dl)
    db.commit()
    db.refresh(dl)
    return dl.to_dict()

@router.put("/distribution-lists/{dl_id}")
def update_distribution_list(
    dl_id: int,
    payload: DLSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    require_admin(current_user)
    dl = db.query(DistributionList).filter(DistributionList.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Distribution list not found")
    dl.email = payload.email.lower()
    dl.display_name = payload.display_name
    dl.privilege = payload.privilege
    db.commit()
    return dl.to_dict()

@router.delete("/distribution-lists/{dl_id}")
def delete_distribution_list(
    dl_id: int,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    require_admin(current_user)
    dl = db.query(DistributionList).filter(DistributionList.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Distribution list not found")
    dl.active = False
    db.commit()
    return {"message": "Distribution list deactivated"}

# ---- Group ↔ DL mappings ----

@router.get("/groups/{group_id}/distribution-lists")
def list_group_dls(group_id: int, db: Session = Depends(get_db)):
    grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")
    return [m.to_dict() for m in grp.distribution_lists]

@router.post("/groups/{group_id}/distribution-lists")
def add_group_dl(
    group_id: int,
    payload: GroupDLSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    require_admin(current_user)
    grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")
    dl = db.query(DistributionList).filter(DistributionList.id == payload.distribution_list_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Distribution list not found")
    existing = db.query(GroupDistributionList).filter(
        GroupDistributionList.group_id == group_id,
        GroupDistributionList.distribution_list_id == payload.distribution_list_id
    ).first()
    if existing:
        return existing.to_dict()
    mapping = GroupDistributionList(
        group_id=group_id,
        distribution_list_id=payload.distribution_list_id,
        notification_enabled=payload.notification_enabled
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping.to_dict()

@router.delete("/groups/{group_id}/distribution-lists/{mapping_id}")
def remove_group_dl(
    group_id: int,
    mapping_id: int,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_admin_user(db, x_user_id)
    require_admin(current_user)
    mapping = db.query(GroupDistributionList).filter(
        GroupDistributionList.id == mapping_id,
        GroupDistributionList.group_id == group_id
    ).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="DL mapping not found")
    db.delete(mapping)
    db.commit()
    return {"message": "DL removed from group"}
