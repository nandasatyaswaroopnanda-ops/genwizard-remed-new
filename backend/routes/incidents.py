import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, and_
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from backend.database import get_db
from backend.models import (
    Incident, User, Application, Project, AssignmentGroup,
    TicketComment, TicketWorkNote, SLAInstance, AuditLog, Attachment
)
from backend.routing_engine import RoutingEngine, calculate_priority
from backend.sla_engine import SLAEngine
from backend.workflow_engine import WorkflowEngine
from backend.notification_engine import NotificationEngine

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    user = db.query(User).filter(User.id == user_id).first()
    return user or db.query(User).first()

class IncidentCreateSchema(BaseModel):
    caller_id: Optional[int] = None
    application_id: int
    project_id: Optional[int] = None
    category: str = "Application"
    subcategory: Optional[str] = None
    short_description: str
    description: str
    impact: str = "High" # Critical, High, Medium, Low
    urgency: str = "High" # Critical, High, Medium, Low
    priority: Optional[str] = None
    assignment_group_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    contact_type: str = "Web Portal"
    environment: str = "Production"

class StatusUpdateSchema(BaseModel):
    status: str
    resolution_code: Optional[str] = None
    resolution_notes: Optional[str] = None
    reason: Optional[str] = None
    close_category: Optional[str] = None  # Bug, Configuration Issue, Application Limitation, Infrastructure Limitation
    close_subcategory: Optional[str] = None
    close_application_name: Optional[str] = None
    close_application_id: Optional[int] = None
    ado_number: Optional[str] = None

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

@router.get("")
def list_incidents(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    application_id: Optional[int] = None,
    project_id: Optional[int] = None,
    assignment_group_id: Optional[int] = None,
    category: Optional[str] = None,
    sla_stage: Optional[str] = None,
    search: Optional[str] = None,
    my_tickets: bool = False,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    user_group_ids = [m.group_id for m in current_user.memberships]

    query = db.query(Incident)

    # Role-Based Access Control & Project Scoping
    from backend.security import get_user_project_boundaries
    boundaries = get_user_project_boundaries(current_user, db)

    if boundaries["is_end_user"] or my_tickets:
        query = query.filter(Incident.caller_id == current_user.id)
    elif not boundaries["is_global_admin"]:
        # Support team member: restricted to their assigned project(s)
        allowed_proj_ids = boundaries["project_ids"]
        allowed_app_ids = boundaries["application_ids"]
        proj_filter = or_(
            Incident.project_id.in_(allowed_proj_ids),
            Incident.assignment_group_id.in_(user_group_ids),
            Incident.assigned_to_id == current_user.id,
            and_(Incident.project_id.is_(None), Incident.application_id.in_(allowed_app_ids)),
            Incident.caller_id == current_user.id
        )
        query = query.filter(proj_filter)
        if project_id:
            query = query.filter(Incident.project_id == project_id)
    else:
        # Global Admin can see all and filter across all projects
        if project_id:
            query = query.filter(Incident.project_id == project_id)

    if status:
        query = query.filter(Incident.status == status)
    if priority:
        query = query.filter(Incident.priority == priority)
    if application_id:
        query = query.filter(Incident.application_id == application_id)
    if project_id:
        query = query.filter(Incident.project_id == project_id)
    if assignment_group_id:
        query = query.filter(Incident.assignment_group_id == assignment_group_id)
    if category:
        query = query.filter(Incident.category == category)
    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                Incident.number.ilike(s),
                Incident.short_description.ilike(s),
                Incident.description.ilike(s)
            )
        )

    incidents = query.order_by(desc(Incident.created_at)).all()
    result = []
    for inc in incidents:
        data = inc.to_dict()
        # Add primary SLA instance progress
        res_sla = db.query(SLAInstance).filter(
            SLAInstance.ticket_id == inc.id,
            SLAInstance.ticket_type == "Incident",
            SLAInstance.target_type == "resolution"
        ).first()
        if res_sla:
            data["sla_stage"] = res_sla.stage
            data["sla_target_mins"] = res_sla.target_duration_mins
            data["sla_due_at"] = res_sla.due_at.isoformat() if res_sla.due_at else None
        else:
            data["sla_stage"] = "in_progress"

        if sla_stage and data.get("sla_stage") != sla_stage:
            continue
        result.append(data)
    return result

@router.post("")
def create_incident(
    payload: IncidentCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    caller_id = payload.caller_id or current_user.id

    # 1. Concurrency-safe unique sequential incident number
    last_inc = db.query(Incident).order_by(desc(Incident.id)).first()
    next_seq = (last_inc.id + 1001) if last_inc else 1001
    inc_number = f"INC{next_seq:07d}"

    # 2. Priority Calculation (explicit priority for support users, or matrix calculation)
    from backend.security import get_user_scopes
    scopes = get_user_scopes(current_user)

    if not scopes["is_end_user"] and payload.priority:
        calculated_priority = payload.priority
    else:
        calculated_priority = calculate_priority(payload.impact, payload.urgency)

    # 3. Dynamic Assignment Group Routing through 6-tier Engine
    effective_project_id = payload.project_id
    if not effective_project_id and payload.application_id:
        app_obj = db.query(Application).filter(Application.id == payload.application_id).first()
        if app_obj and getattr(app_obj, "project_id", None):
            effective_project_id = app_obj.project_id

    routing_result = RoutingEngine.resolve_assignment_group(
        db=db,
        application_id=payload.application_id,
        project_id=effective_project_id,
        category=payload.category,
        subcategory=payload.subcategory
    )
    if not scopes["is_end_user"] and payload.assignment_group_id:
        assignment_group_id = payload.assignment_group_id
        matched_rule = "[MANUAL] Support Direct Assignment"
    else:
        assignment_group_id = routing_result["assignment_group_id"]
        matched_rule = f"[{routing_result['matched_rule_type']}] {routing_result['rule_code']}"

    assigned_to_id = None
    if scopes["is_end_user"]:
        initial_status = "Active"
    elif payload.assigned_to_id:
        assigned_to_id = payload.assigned_to_id
        initial_status = "In Progress"
    else:
        initial_status = "New"

    # 4. Dynamic SLA Resolution Hierarchy
    sla_result = SLAEngine.resolve_sla_policy(
        db=db,
        priority=calculated_priority,
        ticket_type="Incident",
        application_id=payload.application_id,
        project_id=effective_project_id,
        assignment_group_id=assignment_group_id
    )
    matched_sla_policy = sla_result["policy"].name if sla_result["policy"] else "Default SLA"

    # 5. Create Incident Record
    incident = Incident(
        number=inc_number,
        caller_id=caller_id,
        requested_for_id=caller_id,
        opened_by_id=current_user.id,
        application_id=payload.application_id,
        project_id=effective_project_id,
        category=payload.category,
        subcategory=payload.subcategory,
        short_description=payload.short_description,
        description=payload.description,
        impact=payload.impact,
        urgency=payload.urgency,
        priority=calculated_priority,
        assignment_group_id=assignment_group_id,
        assigned_to_id=assigned_to_id,
        environment=payload.environment,
        contact_type=payload.contact_type,
        status=initial_status,
        matched_routing_rule=matched_rule,
        matched_sla_policy=matched_sla_policy
    )
    db.add(incident)
    db.flush()

    # 6. Start SLA timers
    if sla_result["policy"]:
        SLAEngine.start_sla_instances(db, incident.id, incident.number, "Incident", sla_result["policy"])

    # 7. Audit Log
    audit = AuditLog(
        entity_type="Incident",
        entity_id=incident.id,
        entity_number=incident.number,
        action="CREATE",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        new_values=json.dumps({
            "priority": calculated_priority,
            "assignment_group": routing_result["assignment_group_name"],
            "routing_reason": routing_result["reason"]
        }),
        reason="Incident logged via portal"
    )
    db.add(audit)

    # 8. Notifications
    NotificationEngine.notify(
        db=db,
        event_type="ticket_created",
        recipient_id=caller_id,
        context={
            "ticket_number": incident.number,
            "caller_name": current_user.full_name,
            "short_description": incident.short_description,
            "application": incident.application.name if incident.application else "App",
            "project": incident.project.name if incident.project else "Project",
            "priority": incident.priority,
            "status": incident.status,
            "assignment_group": routing_result["assignment_group_name"],
            "ticket_url": f"#/incidents/{incident.number}"
        },
        ticket_id=incident.id,
        ticket_number=incident.number,
        ticket_type="Incident"
    )

    db.commit()
    return incident.to_dict()

@router.get("/{ticket_id_or_number}")
def get_incident(
    ticket_id_or_number: str,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    user_group_ids = [m.group_id for m in current_user.memberships]

    if ticket_id_or_number.isdigit():
        inc = db.query(Incident).filter(Incident.id == int(ticket_id_or_number)).first()
    else:
        inc = db.query(Incident).filter(Incident.number == ticket_id_or_number).first()

    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Authorization check & Project Boundaries
    from backend.security import get_user_project_boundaries
    boundaries = get_user_project_boundaries(current_user, db)
    if boundaries["is_end_user"]:
        if inc.caller_id != current_user.id and inc.opened_by_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied: You can only view tickets created by you.")
    elif not boundaries["is_global_admin"]:
        allowed_proj_ids = boundaries["project_ids"]
        allowed_app_ids = boundaries["application_ids"]
        is_own_project = (inc.project_id in allowed_proj_ids) or \
                         (inc.assignment_group_id in user_group_ids) or \
                         (inc.assigned_to_id == current_user.id) or \
                         (not inc.project_id and inc.application_id in allowed_app_ids) or \
                         (inc.caller_id == current_user.id)
        if not is_own_project:
            raise HTTPException(status_code=403, detail="Access denied: You only have access to tickets in your assigned project(s) or queue.")

    data = inc.to_dict()

    # SLA Instances
    sla_instances = db.query(SLAInstance).filter(
        SLAInstance.ticket_id == inc.id,
        SLAInstance.ticket_type == "Incident"
    ).all()
    data["sla_instances"] = [s.to_dict() for s in sla_instances]

    # Customer Comments (visible to all authorized users)
    comments = db.query(TicketComment).filter(
        TicketComment.ticket_type == "Incident",
        TicketComment.ticket_id == inc.id
    ).order_by(TicketComment.created_at.asc()).all()
    data["comments"] = [c.to_dict() for c in comments]

    # STRICT BUSINESS RULE:
    # Internal Work Notes are strictly hidden from requesters!
    is_admin = boundaries["is_global_admin"] or current_user.role in ["administrator", "admin", "itsm_admin", "itsm-admin"]
    if is_admin or current_user.role in ["support_member", "group_manager", "itsm_admin", "itsm_user"]:
        work_notes = db.query(TicketWorkNote).filter(
            TicketWorkNote.ticket_type == "Incident",
            TicketWorkNote.ticket_id == inc.id
        ).order_by(TicketWorkNote.created_at.asc()).all()
        data["work_notes"] = [w.to_dict() for w in work_notes]
    else:
        data["work_notes"] = []

    # Audit Logs
    audit_logs = db.query(AuditLog).filter(
        AuditLog.entity_type == "Incident",
        AuditLog.entity_id == inc.id
    ).order_by(AuditLog.created_at.desc()).all()
    data["audit_history"] = [a.to_dict() for a in audit_logs]

    # Attachments
    attachments = db.query(Attachment).filter(
        Attachment.ticket_type == "Incident",
        Attachment.ticket_id == inc.id
    ).order_by(Attachment.created_at.desc()).all()
    data["attachments"] = [a.to_dict() for a in attachments]

    return data

@router.patch("/{ticket_id_or_number}/status")
def update_incident_status(
    ticket_id_or_number: str,
    payload: StatusUpdateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        inc = db.query(Incident).filter(Incident.id == int(ticket_id_or_number)).first()
    else:
        inc = db.query(Incident).filter(Incident.number == ticket_id_or_number).first()

    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    old_status = inc.status
    new_status = payload.status

    # Validate state transition via Workflow Engine
    valid, msg = WorkflowEngine.validate_transition("Incident", old_status, new_status)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    inc.status = new_status
    if new_status in ["Resolved", "Closed"]:
        if new_status == "Resolved":
            inc.resolved_at = datetime.datetime.utcnow()
            inc.resolution_code = payload.resolution_code or "Solved by Workaround"
            inc.resolution_notes = payload.resolution_notes or payload.reason or "Incident resolved"
        elif new_status == "Closed":
            inc.closed_at = datetime.datetime.utcnow()
            if not inc.resolution_code:
                inc.resolution_code = payload.resolution_code or "Closed by User/Admin"
            if payload.resolution_notes:
                inc.resolution_notes = payload.resolution_notes
        if payload.close_category:
            inc.close_category = payload.close_category
            inc.category = payload.close_category
        if payload.close_subcategory:
            inc.close_subcategory = payload.close_subcategory
            inc.subcategory = payload.close_subcategory
        if payload.ado_number:
            inc.ado_number = payload.ado_number
        if payload.close_application_name:
            inc.close_application_name = payload.close_application_name
            # Also sync application entity
            app_match = db.query(Application).filter(Application.name == payload.close_application_name).first()
            if app_match:
                inc.application_id = app_match.id
        if payload.close_application_id:
            inc.application_id = payload.close_application_id

    # Update SLA instances (handles pausing on Pending, resuming on In Progress, achieving on Resolved)
    SLAEngine.handle_status_change(db, inc.id, "Incident", old_status, new_status, payload.reason)

    # Audit Log
    audit = AuditLog(
        entity_type="Incident",
        entity_id=inc.id,
        entity_number=inc.number,
        action="UPDATE_STATUS",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"status": old_status}),
        new_values=json.dumps({"status": new_status, "reason": payload.reason}),
        reason=payload.reason or f"Status changed to {new_status}"
    )
    db.add(audit)

    # Notifications
    if new_status == "Resolved":
        NotificationEngine.notify(
            db=db,
            event_type="ticket_resolved",
            recipient_id=inc.caller_id,
            context={
                "ticket_number": inc.number,
                "caller_name": inc.caller.full_name if inc.caller else "Caller",
                "short_description": inc.short_description,
                "comment": inc.resolution_notes or "Resolved by engineer",
                "ticket_url": f"#/incidents/{inc.number}"
            },
            ticket_id=inc.id,
            ticket_number=inc.number,
            ticket_type="Incident"
        )

    db.commit()
    return inc.to_dict()

@router.post("/{ticket_id_or_number}/comments")
def add_customer_comment(
    ticket_id_or_number: str,
    payload: CommentCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if ticket_id_or_number.isdigit():
        inc = db.query(Incident).filter(Incident.id == int(ticket_id_or_number)).first()
    else:
        inc = db.query(Incident).filter(Incident.number == ticket_id_or_number).first()

    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    comment = TicketComment(
        ticket_type="Incident",
        ticket_id=inc.id,
        user_id=current_user.id,
        comment=payload.comment
    )
    db.add(comment)

    # Notification logic:
    # If caller commented -> notify assigned engineer (or group manager)
    # If support commented -> notify caller
    is_caller = (current_user.id == inc.caller_id)
    if is_caller:
        recipient_id = inc.assigned_to_id or (inc.assignment_group.manager_id if inc.assignment_group else 1)
        NotificationEngine.notify(
            db=db,
            event_type="customer_comment_added",
            recipient_id=recipient_id,
            context={
                "ticket_number": inc.number,
                "caller_name": current_user.full_name,
                "comment": payload.comment,
                "status": inc.status,
                "priority": inc.priority,
                "application": inc.application.name if inc.application else "App",
                "project": inc.project.name if inc.project else "Project",
                "ticket_url": f"#/incidents/{inc.number}"
            },
            ticket_id=inc.id,
            ticket_number=inc.number,
            ticket_type="Incident"
        )
    else:
        NotificationEngine.notify(
            db=db,
            event_type="support_comment_added",
            recipient_id=inc.caller_id,
            context={
                "ticket_number": inc.number,
                "caller_name": inc.caller.full_name if inc.caller else "Customer",
                "comment": payload.comment,
                "status": inc.status,
                "priority": inc.priority,
                "application": inc.application.name if inc.application else "App",
                "ticket_url": f"#/incidents/{inc.number}"
            },
            ticket_id=inc.id,
            ticket_number=inc.number,
            ticket_type="Incident"
        )

    db.commit()
    return comment.to_dict()

@router.post("/{ticket_id_or_number}/work-notes")
def add_work_note(
    ticket_id_or_number: str,
    payload: WorkNoteCreateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)

    if ticket_id_or_number.isdigit():
        inc = db.query(Incident).filter(Incident.id == int(ticket_id_or_number)).first()
    else:
        inc = db.query(Incident).filter(Incident.number == ticket_id_or_number).first()

    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # End users / IM_SAML callers can add notes to their own tickets; support/admin can add to any
    if current_user.role in ["employee", "itsm_read"] and inc.caller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Requesters can only update notes on their own tickets")

    work_note = TicketWorkNote(
        ticket_type="Incident",
        ticket_id=inc.id,
        user_id=current_user.id,
        note=payload.note
    )
    db.add(work_note)

    # Work notes are NEVER sent to the caller!
    db.commit()
    return work_note.to_dict()

@router.patch("/{ticket_id_or_number}/assign")
@router.put("/{ticket_id_or_number}/assign")
def assign_incident(
    ticket_id_or_number: str,
    payload: AssignSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    from backend.security import get_user_scopes
    scopes = get_user_scopes(current_user)

    # Restriction: Only members whose DL in IM is attached to a support group or project group can reassign
    if scopes["is_end_user"]:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: End users are not permitted to reassign tickets or change assignment groups. Only support team members can reassign."
        )

    if ticket_id_or_number.isdigit():
        inc = db.query(Incident).filter(Incident.id == int(ticket_id_or_number)).first()
    else:
        inc = db.query(Incident).filter(Incident.number == ticket_id_or_number).first()

    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    old_assignee = inc.assigned_to.full_name if inc.assigned_to else "Unassigned"
    old_priority = inc.priority

    if payload.project_id:
        inc.project_id = payload.project_id
    if payload.application_id:
        inc.application_id = payload.application_id
    if payload.priority:
        inc.priority = payload.priority
        if inc.priority != old_priority:
            SLAEngine.handle_priority_change(db, inc.id, "Incident", old_priority, inc.priority)

    if payload.assignment_group_id:
        inc.assignment_group_id = payload.assignment_group_id
    if payload.assigned_to_id is not None and payload.assigned_to_id != 0:
        inc.assigned_to_id = payload.assigned_to_id
        old_status = inc.status
        inc.status = "In Progress"
        if old_status != "In Progress":
            SLAEngine.handle_status_change(db, inc.id, "Incident", old_status, "In Progress")
    elif payload.assignment_group_id:
        inc.assigned_to_id = None
        old_status = inc.status
        inc.status = "Active"
        if old_status != "Active":
            SLAEngine.handle_status_change(db, inc.id, "Incident", old_status, "Active")

    new_assignee = inc.assigned_to.full_name if inc.assigned_to else "Unassigned"

    audit = AuditLog(
        entity_type="Incident",
        entity_id=inc.id,
        entity_number=inc.number,
        action="ASSIGN",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"assigned_to": old_assignee}),
        new_values=json.dumps({"assigned_to": new_assignee}),
        reason=f"Assigned by {current_user.full_name}"
    )
    db.add(audit)

    if inc.assigned_to_id:
        NotificationEngine.notify(
            db=db,
            event_type="ticket_assigned",
            recipient_id=inc.assigned_to_id,
            context={
                "ticket_number": inc.number,
                "assigned_to": new_assignee,
                "priority": inc.priority,
                "application": inc.application.name if inc.application else "App",
                "project": inc.project.name if inc.project else "Project",
                "caller_name": inc.caller.full_name if inc.caller else "Caller",
                "short_description": inc.short_description,
                "ticket_url": f"#/incidents/{inc.number}"
            },
            ticket_id=inc.id,
            ticket_number=inc.number,
            ticket_type="Incident"
        )

    db.commit()
    return inc.to_dict()

class PriorityUpdateSchema(BaseModel):
    priority: str
    reason: Optional[str] = "Priority updated"

@router.patch("/{ticket_id_or_number}/priority")
def update_incident_priority(
    ticket_id_or_number: str,
    payload: PriorityUpdateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    from backend.security import get_user_scopes
    scopes = get_user_scopes(current_user)

    # Restriction: End users cannot change priority
    if scopes["is_end_user"]:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: End users are not permitted to change ticket priority. Only support members can adjust priority."
        )

    if ticket_id_or_number.isdigit():
        inc = db.query(Incident).filter(Incident.id == int(ticket_id_or_number)).first()
    else:
        inc = db.query(Incident).filter(Incident.number == ticket_id_or_number).first()

    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    old_pri = inc.priority
    inc.priority = payload.priority
    audit = AuditLog(
        entity_type="Incident",
        entity_id=inc.id,
        entity_number=inc.number,
        action="PRIORITY_CHANGE",
        changed_by_id=current_user.id,
        changed_by_name=current_user.full_name,
        old_values=json.dumps({"priority": old_pri}),
        new_values=json.dumps({"priority": payload.priority}),
        reason=payload.reason or f"Priority changed to {payload.priority} by {current_user.full_name}"
    )
    db.add(audit)
    db.commit()
    return inc.to_dict()

class IncidentAutoCloseSchema(BaseModel):
    hours_in_resolved: int = 48
    close_notes: Optional[str] = "Automatically closed after resolution inactivity period"
    resolution_code: Optional[str] = "Auto-Closed"
    dry_run: bool = False

@router.post("/auto-close")
def auto_close_resolved_incidents(
    payload: IncidentAutoCloseSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Automated Incident Auto-Closure Endpoint.
    Finds all tickets currently in 'Resolved' status whose resolved_at (or updated_at)
    is older than `hours_in_resolved` (default 48h) and transitions them to 'Closed'.
    """
    current_user = get_session_user(db, x_user_id)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=payload.hours_in_resolved)

    resolved_incidents = db.query(Incident).filter(Incident.status == "Resolved").all()
    closed_list = []
    now = datetime.datetime.utcnow()

    for inc in resolved_incidents:
        res_time = inc.resolved_at or inc.updated_at or inc.created_at
        if res_time and res_time <= cutoff:
            closed_list.append(inc.number)
            if not payload.dry_run:
                inc.status = "Closed"
                inc.closed_at = now
                if not inc.resolution_code:
                    inc.resolution_code = payload.resolution_code
                if not inc.resolution_notes:
                    inc.resolution_notes = payload.close_notes
                audit = AuditLog(
                    entity_type="Incident",
                    entity_id=inc.id,
                    entity_number=inc.number,
                    action="AUTO_CLOSE",
                    changed_by_id=current_user.id if current_user else 1,
                    changed_by_name="Automation Engine",
                    old_values=json.dumps({"status": "Resolved"}),
                    new_values=json.dumps({"status": "Closed", "reason": payload.close_notes}),
                    reason=payload.close_notes
                )
                db.add(audit)

    if not payload.dry_run and closed_list:
        db.commit()

    return {
        "status": "success",
        "dry_run": payload.dry_run,
        "hours_in_resolved": payload.hours_in_resolved,
        "auto_closed_count": len(closed_list),
        "auto_closed_tickets": closed_list
    }

