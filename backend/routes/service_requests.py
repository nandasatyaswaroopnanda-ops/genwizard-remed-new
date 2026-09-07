import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_
from typing import Optional, List
from pydantic import BaseModel

from backend.database import get_db
from backend.models import (
    ServiceRequest, User, AssignmentGroup, TicketComment,
    TicketWorkNote, Approval, AuditLog, Application, Project, Attachment
)
from backend.routing_engine import RoutingEngine
from backend.notification_engine import NotificationEngine

router = APIRouter(prefix="/api/service-requests", tags=["service-requests"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    user = db.query(User).filter(User.id == user_id).first()
    return user or db.query(User).first()

class ServiceRequestCreateSchema(BaseModel):
    catalog_item: str
    short_description: str
    description: str
    application_id: Optional[int] = None
    project_id: Optional[int] = None
    priority: str = "P3"

class StatusUpdateSchema(BaseModel):
    status: str
    reason: Optional[str] = None

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

class ApprovalActionSchema(BaseModel):
    decision: str  # Approved, Rejected
    comments: Optional[str] = None

@router.get("")
def list_service_requests(
    status: Optional[str] = None,
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

    query = db.query(ServiceRequest)

    from backend.security import get_user_project_boundaries
    boundaries = get_user_project_boundaries(current_user, db)

    if boundaries["is_end_user"] or my_tickets:
        query = query.filter(ServiceRequest.requested_by_id == current_user.id)
    elif not boundaries["is_global_admin"]:
        # Project-scoped support team member
        allowed_proj_ids = boundaries["project_ids"]
        allowed_app_ids = boundaries["application_ids"]
        proj_filter = or_(
            ServiceRequest.project_id.in_(allowed_proj_ids),
            ServiceRequest.assignment_group_id.in_(user_group_ids),
            ServiceRequest.assigned_to_id == current_user.id,
            and_(ServiceRequest.project_id.is_(None), ServiceRequest.application_id.in_(allowed_app_ids)),
            ServiceRequest.requested_by_id == current_user.id
        )
        query = query.filter(proj_filter)
        if project_id:
            query = query.filter(ServiceRequest.project_id == project_id)
    else:
        # Global admin sees all and filters across all projects
        if project_id:
            query = query.filter(ServiceRequest.project_id == project_id)

    if status:
        query = query.filter(ServiceRequest.status == status)
    if priority:
        query = query.filter(ServiceRequest.priority == priority)
    if application_id:
        query = query.filter(ServiceRequest.application_id == application_id)
    if assignment_group_id:
        query = query.filter(ServiceRequest.assignment_group_id == assignment_group_id)
    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                ServiceRequest.number.ilike(s),
                ServiceRequest.short_description.ilike(s),
                ServiceRequest.description.ilike(s),
                ServiceRequest.catalog_item.ilike(s)
            )
        )

    requests = query.order_by(desc(ServiceRequest.created_at)).all()
    return [r.to_dict() for r in requests]

@router.post("")
def create_service_request(
    payload: ServiceRequestCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)

    last_req = db.query(ServiceRequest).order_by(desc(ServiceRequest.id)).first()
    next_seq = (last_req.id + 1001) if last_req else 1001
    req_number = f"REQ{next_seq:07d}"

    # Routing
    routing_result = RoutingEngine.resolve_assignment_group(
        db=db,
        application_id=payload.application_id,
        project_id=payload.project_id,
        category="Service Request"
    )
    assignment_group_id = routing_result["assignment_group_id"]

    # Approvals for sensitive requests
    needs_approval = "Access" in payload.catalog_item or "Database" in payload.catalog_item
    approval_status = "Pending" if needs_approval else "Approved"

    req = ServiceRequest(
        number=req_number,
        requested_by_id=current_user.id,
        requested_for_id=current_user.id,
        application_id=payload.application_id,
        project_id=payload.project_id,
        catalog_item=payload.catalog_item,
        category="Service Request",
        short_description=payload.short_description,
        description=payload.description,
        priority=payload.priority,
        assignment_group_id=assignment_group_id,
        status="Active",
        approval_status=approval_status
    )
    db.add(req)
    db.flush()

    if needs_approval:
        # Create approval record assigned to manager or admin
        approval = Approval(
            ticket_type="Service Request",
            ticket_id=req.id,
            ticket_number=req.number,
            approver_id=current_user.manager_id or 1,
            status="Pending"
        )
        db.add(approval)

    audit = AuditLog(
        entity_type="ServiceRequest",
        entity_id=req.id,
        entity_number=req.number,
        action="CREATE",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        new_values=json.dumps({"catalog_item": payload.catalog_item, "priority": payload.priority}),
        reason="Created via Service Catalog"
    )
    db.add(audit)

    db.commit()
    return req.to_dict()

@router.get("/{ticket_id_or_number}")
def get_service_request(
    ticket_id_or_number: str,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    # Authorization check & Project Boundaries
    from backend.security import get_user_project_boundaries
    boundaries = get_user_project_boundaries(current_user, db)
    user_group_ids = [m.group_id for m in current_user.memberships]
    if boundaries["is_end_user"]:
        if req.requested_by_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied: You can only view service requests requested by you.")
    elif not boundaries["is_global_admin"]:
        allowed_proj_ids = boundaries["project_ids"]
        allowed_app_ids = boundaries["application_ids"]
        is_own_project = (req.project_id in allowed_proj_ids) or \
                         (req.assignment_group_id in user_group_ids) or \
                         (req.assigned_to_id == current_user.id) or \
                         (not req.project_id and req.application_id in allowed_app_ids) or \
                         (req.requested_by_id == current_user.id)
        if not is_own_project:
            raise HTTPException(status_code=403, detail="Access denied: You only have access to service requests in your assigned project(s) or queue.")

    data = req.to_dict()
    comments = db.query(TicketComment).filter(
        TicketComment.ticket_type == "Service Request",
        TicketComment.ticket_id == req.id
    ).all()
    data["comments"] = [c.to_dict() for c in comments]

    if current_user.role in ["support_member", "group_manager", "administrator", "itsm_admin", "admin", "itsm_user"]:
        work_notes = db.query(TicketWorkNote).filter(
            TicketWorkNote.ticket_type == "Service Request",
            TicketWorkNote.ticket_id == req.id
        ).all()
        data["work_notes"] = [w.to_dict() for w in work_notes]
    else:
        data["work_notes"] = []

    approvals = db.query(Approval).filter(
        Approval.ticket_type == "Service Request",
        Approval.ticket_id == req.id
    ).all()
    data["approvals"] = [a.to_dict() for a in approvals]

    attachments = db.query(Attachment).filter(
        Attachment.ticket_type == "Service Request",
        Attachment.ticket_id == req.id
    ).order_by(Attachment.created_at.desc()).all()
    data["attachments"] = [a.to_dict() for a in attachments]

    return data

@router.patch("/{ticket_id_or_number}/status")
def update_request_status(
    ticket_id_or_number: str,
    payload: StatusUpdateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    old_status = req.status
    req.status = payload.status

    audit = AuditLog(
        entity_type="ServiceRequest",
        entity_id=req.id,
        entity_number=req.number,
        action="UPDATE_STATUS",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"status": old_status}),
        new_values=json.dumps({"status": payload.status, "reason": payload.reason}),
        reason=payload.reason or f"Status changed to {payload.status}"
    )
    db.add(audit)
    db.commit()
    return req.to_dict()

@router.post("/{ticket_id_or_number}/approve")
def decide_request_approval(
    ticket_id_or_number: str,
    payload: ApprovalActionSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    approval = db.query(Approval).filter(
        Approval.ticket_type == "Service Request",
        Approval.ticket_id == req.id,
        Approval.status == "Pending"
    ).first()

    if not approval:
        approval = Approval(
            ticket_type="Service Request",
            ticket_id=req.id,
            ticket_number=req.number,
            approver_id=current_user.id,
            status="Pending"
        )
        db.add(approval)
        db.flush()

    approval.status = payload.decision
    approval.comments = payload.comments
    approval.decided_at = datetime.datetime.utcnow()
    approval.approver_id = current_user.id

    req.approval_status = payload.decision
    if payload.decision == "Approved":
        req.status = "In Progress"
    elif payload.decision == "Rejected":
        req.status = "Rejected"

    audit = AuditLog(
        entity_type="ServiceRequest",
        entity_id=req.id,
        entity_number=req.number,
        action="APPROVAL_DECISION",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        new_values=json.dumps({"approval_status": payload.decision, "comments": payload.comments}),
        reason=f"Approval decision: {payload.decision}"
    )
    db.add(audit)
    db.commit()
    return {"message": f"Service request {payload.decision}", "request": req.to_dict()}

@router.post("/{ticket_id_or_number}/comments")
def add_service_request_comment(
    ticket_id_or_number: str,
    payload: CommentCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    comment = TicketComment(
        ticket_type="Service Request",
        ticket_id=req.id,
        user_id=current_user.id,
        comment=payload.comment
    )
    db.add(comment)
    db.commit()
    return comment.to_dict()

@router.post("/{ticket_id_or_number}/work-notes")
def add_service_request_work_note(
    ticket_id_or_number: str,
    payload: WorkNoteCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    from backend.security import get_user_scopes
    if (current_user.role in ["employee", "itsm_read", "im_saml", "atr_saml"] or get_user_scopes(current_user, db)["is_end_user"]) and req.requested_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Requesters can only update notes on their own requests")

    work_note = TicketWorkNote(
        ticket_type="Service Request",
        ticket_id=req.id,
        user_id=current_user.id,
        note=payload.note
    )
    db.add(work_note)
    db.commit()
    return work_note.to_dict()

@router.patch("/{ticket_id_or_number}/assign")
@router.put("/{ticket_id_or_number}/assign")
def assign_service_request(
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
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    old_assignee = req.assigned_to.full_name if getattr(req, "assigned_to", None) else "Unassigned"
    if payload.project_id:
        req.project_id = payload.project_id
    if payload.application_id:
        req.application_id = payload.application_id
    if payload.priority:
        req.priority = payload.priority
    from backend.sla_engine import SLAEngine
    if payload.assignment_group_id:
        req.assignment_group_id = payload.assignment_group_id
    if payload.assigned_to_id is not None and payload.assigned_to_id != 0:
        req.assigned_to_id = payload.assigned_to_id
        old_status = req.status
        req.status = "In Progress"
        if old_status != "In Progress":
            SLAEngine.handle_status_change(db, req.id, "Service Request", old_status, "In Progress")
    elif payload.assignment_group_id:
        req.assigned_to_id = None
        old_status = req.status
        req.status = "Active"
        if old_status != "Active":
            SLAEngine.handle_status_change(db, req.id, "Service Request", old_status, "Active")

    new_assignee = req.assigned_to.full_name if getattr(req, "assigned_to", None) else "Unassigned"

    audit = AuditLog(
        entity_type="ServiceRequest",
        entity_id=req.id,
        entity_number=req.number,
        action="ASSIGN",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"assigned_to": old_assignee}),
        new_values=json.dumps({"assigned_to": new_assignee}),
        reason=f"Assigned by {current_user.full_name}"
    )
    db.add(audit)
    db.commit()
    return req.to_dict()

@router.patch("/{ticket_id_or_number}/priority")
def update_service_request_priority(
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
        req = db.query(ServiceRequest).filter(ServiceRequest.id == int(ticket_id_or_number)).first()
    else:
        req = db.query(ServiceRequest).filter(ServiceRequest.number == ticket_id_or_number).first()

    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")

    old_pri = req.priority
    req.priority = payload.priority
    audit = AuditLog(
        entity_type="ServiceRequest",
        entity_id=req.id,
        entity_number=req.number,
        action="PRIORITY_CHANGE",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"priority": old_pri}),
        new_values=json.dumps({"priority": payload.priority}),
        reason=payload.reason or f"Priority changed to {payload.priority} by {current_user.full_name}"
    )
    db.add(audit)
    db.commit()
    return req.to_dict()

class ServiceRequestAutoCloseSchema(BaseModel):
    hours_in_fulfilled: int = 48
    close_notes: Optional[str] = "Automatically closed after fulfillment inactivity period"
    dry_run: bool = False

@router.post("/auto-close")
def auto_close_fulfilled_requests(
    payload: ServiceRequestAutoCloseSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Automated Service Request Auto-Closure Endpoint.
    Finds all requests currently in 'Fulfilled' status whose updated_at
    is older than `hours_in_fulfilled` (default 48h) and transitions them to 'Closed'.
    """
    current_user = get_session_user(db, x_user_id)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=payload.hours_in_fulfilled)

    fulfilled_requests = db.query(ServiceRequest).filter(ServiceRequest.status == "Fulfilled").all()
    closed_list = []
    now = datetime.datetime.utcnow()

    for req in fulfilled_requests:
        res_time = req.updated_at or req.created_at
        if res_time and res_time <= cutoff:
            closed_list.append(req.number)
            if not payload.dry_run:
                req.status = "Closed"
                audit = AuditLog(
                    entity_type="ServiceRequest",
                    entity_id=req.id,
                    entity_number=req.number,
                    action="AUTO_CLOSE",
                    changed_by_id=current_user.id if current_user else 1,
                    changed_by_name="Automation Engine",
                    old_values=json.dumps({"status": "Fulfilled"}),
                    new_values=json.dumps({"status": "Closed", "reason": payload.close_notes}),
                    reason=payload.close_notes
                )
                db.add(audit)

    if not payload.dry_run and closed_list:
        db.commit()

    return {
        "status": "success",
        "dry_run": payload.dry_run,
        "hours_in_fulfilled": payload.hours_in_fulfilled,
        "auto_closed_count": len(closed_list),
        "auto_closed_tickets": closed_list
    }


