import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_
from typing import Optional, List
from pydantic import BaseModel

from backend.database import get_db
from backend.models import (
    ChangeRequest, User, AssignmentGroup, TicketComment,
    TicketWorkNote, Approval, AuditLog, Application, Project, Attachment
)
from backend.routing_engine import RoutingEngine
from backend.workflow_engine import WorkflowEngine
from backend.notification_engine import NotificationEngine

router = APIRouter(prefix="/api/changes", tags=["changes"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    user = db.query(User).filter(User.id == user_id).first()
    return user or db.query(User).first()

class ChangeCreateSchema(BaseModel):
    application_id: int
    project_id: int
    change_type: str = "Normal" # Standard, Normal, Emergency
    category: str = "Software"
    short_description: str
    description: str
    business_justification: str
    risk: str = "Medium" # Low, Medium, High, Critical
    impact: str = "Medium"
    priority: str = "P3"
    planned_start: Optional[datetime.datetime] = None
    planned_end: Optional[datetime.datetime] = None
    implementation_plan: Optional[str] = None
    backout_plan: Optional[str] = None
    test_plan: Optional[str] = None
    validation_plan: Optional[str] = None

class ChangeStatusSchema(BaseModel):
    change_status: str
    reason: Optional[str] = None

class ApprovalActionSchema(BaseModel):
    decision: str # Approved, Rejected
    comments: Optional[str] = None

class CommentCreateSchema(BaseModel):
    comment: str

class WorkNoteCreateSchema(BaseModel):
    note: str

class AssignSchema(BaseModel):
    assignment_group_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    project_id: Optional[int] = None
    application_id: Optional[int] = None
    priority: Optional[str] = None

class PriorityUpdateSchema(BaseModel):
    priority: str
    reason: Optional[str] = "Priority updated"

@router.get("")
def list_changes(
    status: Optional[str] = None,
    change_type: Optional[str] = None,
    priority: Optional[str] = None,
    application_id: Optional[int] = None,
    project_id: Optional[int] = None,
    assignment_group_id: Optional[int] = None,
    search: Optional[str] = None,
    my_tickets: bool = False,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    user_group_ids = [m.group_id for m in current_user.memberships]
    query = db.query(ChangeRequest)

    from backend.security import get_user_project_boundaries
    boundaries = get_user_project_boundaries(current_user, db)

    if boundaries["is_end_user"] or my_tickets:
        query = query.filter(ChangeRequest.requested_by_id == current_user.id)
    elif not boundaries["is_global_admin"]:
        # Project-scoped support team member
        allowed_proj_ids = boundaries["project_ids"]
        allowed_app_ids = boundaries["application_ids"]
        proj_filter = or_(
            ChangeRequest.project_id.in_(allowed_proj_ids),
            ChangeRequest.assignment_group_id.in_(user_group_ids),
            ChangeRequest.assigned_to_id == current_user.id,
            and_(ChangeRequest.project_id.is_(None), ChangeRequest.application_id.in_(allowed_app_ids)),
            ChangeRequest.requested_by_id == current_user.id
        )
        query = query.filter(proj_filter)
        if project_id:
            query = query.filter(ChangeRequest.project_id == project_id)
    else:
        # Global admin sees all and filters across all projects
        if project_id:
            query = query.filter(ChangeRequest.project_id == project_id)

    if status:
        query = query.filter(ChangeRequest.change_status == status)
    if change_type:
        query = query.filter(ChangeRequest.change_type == change_type)
    if priority:
        query = query.filter(ChangeRequest.priority == priority)
    if application_id:
        query = query.filter(ChangeRequest.application_id == application_id)
    if assignment_group_id:
        query = query.filter(ChangeRequest.assignment_group_id == assignment_group_id)
    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                ChangeRequest.number.ilike(s),
                ChangeRequest.short_description.ilike(s),
                ChangeRequest.description.ilike(s)
            )
        )

    changes = query.order_by(desc(ChangeRequest.created_at)).all()
    return [c.to_dict() for c in changes]

@router.post("")
def create_change(
    payload: ChangeCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)

    last_chg = db.query(ChangeRequest).order_by(desc(ChangeRequest.id)).first()
    next_seq = (last_chg.id + 1001) if last_chg else 1001
    chg_number = f"CHG{next_seq:07d}"

    # Routing
    routing_result = RoutingEngine.resolve_assignment_group(
        db=db,
        application_id=payload.application_id,
        project_id=payload.project_id,
        category="Change"
    )
    assignment_group_id = routing_result["assignment_group_id"]

    # Initial state
    initial_status = "Draft"
    approval_status = "Pending"
    if payload.change_type == "Standard":
        approval_status = "Approved"
        initial_status = "Scheduled"

    change = ChangeRequest(
        number=chg_number,
        requested_by_id=current_user.id,
        application_id=payload.application_id,
        project_id=payload.project_id,
        change_type=payload.change_type,
        category=payload.category,
        short_description=payload.short_description,
        description=payload.description,
        business_justification=payload.business_justification,
        risk=payload.risk,
        impact=payload.impact,
        priority=payload.priority,
        assignment_group_id=assignment_group_id,
        assigned_to_id=current_user.id,
        planned_start=payload.planned_start,
        planned_end=payload.planned_end,
        implementation_plan=payload.implementation_plan,
        backout_plan=payload.backout_plan,
        test_plan=payload.test_plan,
        validation_plan=payload.validation_plan,
        approval_status=approval_status,
        change_status=initial_status
    )
    db.add(change)
    db.flush()

    if payload.change_type != "Standard":
        # Create approval record
        approval = Approval(
            ticket_type="Change Request",
            ticket_id=change.id,
            ticket_number=change.number,
            approver_id=1, # Admin / CAB approver
            status="Pending"
        )
        db.add(approval)

    audit = AuditLog(
        entity_type="ChangeRequest",
        entity_id=change.id,
        entity_number=change.number,
        action="CREATE",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        new_values=json.dumps({"type": payload.change_type, "risk": payload.risk}),
        reason="Initiated Change Request"
    )
    db.add(audit)

    db.commit()
    return change.to_dict()

@router.get("/{ticket_id_or_number}")
def get_change(
    ticket_id_or_number: str,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    # Authorization check & Project Boundaries
    from backend.security import get_user_project_boundaries
    boundaries = get_user_project_boundaries(current_user, db)
    user_group_ids = [m.group_id for m in current_user.memberships]
    if boundaries["is_end_user"]:
        if chg.requested_by_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied: You can only view change requests requested by you.")
    elif not boundaries["is_global_admin"]:
        allowed_proj_ids = boundaries["project_ids"]
        allowed_app_ids = boundaries["application_ids"]
        is_own_project = (chg.project_id in allowed_proj_ids) or \
                         (chg.assignment_group_id in user_group_ids) or \
                         (chg.assigned_to_id == current_user.id) or \
                         (not chg.project_id and chg.application_id in allowed_app_ids) or \
                         (chg.requested_by_id == current_user.id)
        if not is_own_project:
            raise HTTPException(status_code=403, detail="Access denied: You only have access to change requests in your assigned project(s) or queue.")

    data = chg.to_dict()
    approvals = db.query(Approval).filter(
        Approval.ticket_type == "Change Request",
        Approval.ticket_id == chg.id
    ).all()
    data["approvals"] = [a.to_dict() for a in approvals]

    comments = db.query(TicketComment).filter(
        TicketComment.ticket_type == "Change Request",
        TicketComment.ticket_id == chg.id
    ).all()
    data["comments"] = [c.to_dict() for c in comments]

    work_notes = db.query(TicketWorkNote).filter(
        TicketWorkNote.ticket_type == "Change Request",
        TicketWorkNote.ticket_id == chg.id
    ).all()
    data["work_notes"] = [w.to_dict() for w in work_notes]

    attachments = db.query(Attachment).filter(
        Attachment.ticket_type == "Change Request",
        Attachment.ticket_id == chg.id
    ).order_by(Attachment.created_at.desc()).all()
    data["attachments"] = [a.to_dict() for a in attachments]

    return data

@router.patch("/{ticket_id_or_number}/status")
def update_change_status(
    ticket_id_or_number: str,
    payload: ChangeStatusSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    valid, msg = WorkflowEngine.validate_transition("Change Request", chg.change_status, payload.change_status)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    # If moving to Scheduled, ensure approval is approved
    if payload.change_status == "Scheduled" and chg.approval_status != "Approved":
        raise HTTPException(status_code=400, detail="Cannot schedule change without CAB approval")

    old_status = chg.change_status
    chg.change_status = payload.change_status
    if payload.change_status == "Implementation" and not chg.actual_start:
        chg.actual_start = datetime.datetime.utcnow()
    elif payload.change_status in ["Completed", "Closed"] and not chg.actual_end:
        chg.actual_end = datetime.datetime.utcnow()

    audit = AuditLog(
        entity_type="ChangeRequest",
        entity_id=chg.id,
        entity_number=chg.number,
        action="UPDATE_STATUS",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"status": old_status}),
        new_values=json.dumps({"status": payload.change_status, "reason": payload.reason}),
        reason=payload.reason or f"Status changed to {payload.change_status}"
    )
    db.add(audit)

    db.commit()
    return chg.to_dict()

@router.post("/{ticket_id_or_number}/approve")
def decide_approval(
    ticket_id_or_number: str,
    payload: ApprovalActionSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    approval = db.query(Approval).filter(
        Approval.ticket_type == "Change Request",
        Approval.ticket_id == chg.id,
        Approval.status == "Pending"
    ).first()

    if not approval:
        approval = Approval(
            ticket_type="Change Request",
            ticket_id=chg.id,
            ticket_number=chg.number,
            approver_id=current_user.id,
            status="Pending"
        )
        db.add(approval)
        db.flush()

    approval.status = payload.decision
    approval.comments = payload.comments
    approval.decided_at = datetime.datetime.utcnow()
    approval.approver_id = current_user.id

    chg.approval_status = payload.decision
    if payload.decision == "Approved":
        chg.change_status = "Scheduled"
    elif payload.decision == "Rejected":
        chg.change_status = "Draft"

    db.commit()
    return {"message": f"Change {payload.decision}", "change": chg.to_dict()}

@router.post("/{ticket_id_or_number}/comments")
def add_change_comment(
    ticket_id_or_number: str,
    payload: CommentCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    comment = TicketComment(
        ticket_type="Change Request",
        ticket_id=chg.id,
        user_id=current_user.id,
        comment=payload.comment
    )
    db.add(comment)
    db.commit()
    return comment.to_dict()

@router.post("/{ticket_id_or_number}/work-notes")
def add_change_work_note(
    ticket_id_or_number: str,
    payload: WorkNoteCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    from backend.security import get_user_scopes
    if (current_user.role in ["employee", "itsm_read", "im_saml", "atr_saml"] or get_user_scopes(current_user, db)["is_end_user"]) and chg.requested_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Requesters can only update notes on their own change requests")

    work_note = TicketWorkNote(
        ticket_type="Change Request",
        ticket_id=chg.id,
        user_id=current_user.id,
        note=payload.note
    )
    db.add(work_note)
    db.commit()
    return work_note.to_dict()

@router.patch("/{ticket_id_or_number}/assign")
@router.put("/{ticket_id_or_number}/assign")
def assign_change(
    ticket_id_or_number: str,
    payload: AssignSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    from backend.security import get_user_scopes
    scopes = get_user_scopes(current_user)

    if scopes["is_end_user"]:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: End users are not permitted to reassign tickets or change assignment groups. Only support team members can reassign."
        )

    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    old_assignee = chg.assigned_to.full_name if getattr(chg, "assigned_to", None) else "Unassigned"
    if payload.project_id:
        chg.project_id = payload.project_id
    if payload.application_id:
        chg.application_id = payload.application_id
    if payload.priority:
        chg.priority = payload.priority
    if payload.assignment_group_id:
        chg.assignment_group_id = payload.assignment_group_id
    if payload.assigned_to_id is not None and payload.assigned_to_id != 0:
        chg.assigned_to_id = payload.assigned_to_id
        if chg.change_status in ["Draft", "Active", "Assess", "Assessment"]:
            chg.change_status = "In Progress"
    elif payload.assignment_group_id:
        chg.assigned_to_id = None
        chg.change_status = "Active"

    new_assignee = chg.assigned_to.full_name if getattr(chg, "assigned_to", None) else "Unassigned"

    audit = AuditLog(
        entity_type="ChangeRequest",
        entity_id=chg.id,
        entity_number=chg.number,
        action="ASSIGN",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"assigned_to": old_assignee}),
        new_values=json.dumps({"assigned_to": new_assignee}),
        reason=f"Assigned by {current_user.full_name}"
    )
    db.add(audit)
    db.commit()
    return chg.to_dict()

@router.patch("/{ticket_id_or_number}/priority")
def update_change_priority(
    ticket_id_or_number: str,
    payload: PriorityUpdateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    from backend.security import get_user_scopes
    scopes = get_user_scopes(current_user)

    if scopes["is_end_user"]:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: End users are not permitted to change ticket priority. Only support members can adjust priority."
        )

    if ticket_id_or_number.isdigit():
        chg = db.query(ChangeRequest).filter(ChangeRequest.id == int(ticket_id_or_number)).first()
    else:
        chg = db.query(ChangeRequest).filter(ChangeRequest.number == ticket_id_or_number).first()

    if not chg:
        raise HTTPException(status_code=404, detail="Change request not found")

    old_pri = chg.priority
    chg.priority = payload.priority
    audit = AuditLog(
        entity_type="ChangeRequest",
        entity_id=chg.id,
        entity_number=chg.number,
        action="PRIORITY_CHANGE",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"priority": old_pri}),
        new_values=json.dumps({"priority": payload.priority}),
        reason=payload.reason or f"Priority changed to {payload.priority} by {current_user.full_name}"
    )
    db.add(audit)
    db.commit()
    return chg.to_dict()

