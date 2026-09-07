import csv
import io
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, Response, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Tuple, Any
from sqlalchemy import or_, and_, desc

from backend.database import get_db
from backend.models import (
    Incident, ServiceRequest, ChangeRequest, AssignmentGroup, User, GroupMember, Application
)

router = APIRouter(prefix="/api/export", tags=["export"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    from backend.security import _ensure_local_persona
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    persona = _ensure_local_persona(user_id, db)
    if persona:
        return persona
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()

def get_date_cutoff(time_period: str, start_date: Optional[str], end_date: Optional[str]):
    now = datetime.datetime.utcnow()
    start_dt = None
    end_dt = None

    if time_period == "today":
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_period == "7d":
        start_dt = now - datetime.timedelta(days=7)
    elif time_period == "30d":
        start_dt = now - datetime.timedelta(days=30)
    elif time_period == "90d":
        start_dt = now - datetime.timedelta(days=90)
    elif time_period == "1y":
        start_dt = now - datetime.timedelta(days=365)
    elif time_period == "custom" and start_date:
        try:
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        except Exception:
            pass
        if end_date:
            try:
                end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            except Exception:
                pass
    # "all" leaves start_dt and end_dt as None
    return start_dt, end_dt

def filter_row_by_columns(headers: List[str], rows: List[List[Any]], requested_cols: Optional[List[str]]) -> Tuple[List[str], List[List[Any]]]:
    if not requested_cols:
        return headers, rows
    norm_req = [c.strip().lower() for c in requested_cols]
    selected_indices = [
        idx for idx, h in enumerate(headers)
        if any(r in h.lower() or h.lower() in r for r in norm_req)
    ]
    if not selected_indices:
        return headers, rows
    filt_headers = [headers[i] for i in selected_indices]
    filt_rows = [[r[i] for i in selected_indices] for r in rows]
    return filt_headers, filt_rows

@router.get("/{ticket_type}")
def export_tickets(
    ticket_type: str,
    time_period: str = Query("30d", pattern="^(today|7d|30d|90d|1y|all|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    columns: Optional[str] = None,
    assignment_group_id: Optional[int] = None,
    format: str = Query("csv", pattern="^(csv|json)$"),
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Export all incidents, service requests, or change requests for various time periods.
    Authorized for admin users and respective assignment group members.
    """
    current_user = get_session_user(db, x_user_id)
    user_group_ids = [m.group_id for m in current_user.memberships]
    is_admin = current_user.role in ["administrator", "admin", "itsm_admin", "itsm-admin"]
    is_support_or_manager = current_user.role in ["support_member", "group_manager", "itsm_user"]

    # Strict access check: only assignment group members and admins can export operational tickets
    if not is_admin and not is_support_or_manager:
        raise HTTPException(
            status_code=403,
            detail="Access Denied: Only assignment group members and administrators can export tickets."
        )

    start_dt, end_dt = get_date_cutoff(time_period, start_date, end_date)
    norm_type = ticket_type.lower().replace("-", "_")

    requested_cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None

    if norm_type in ["incidents", "incident"]:
        q = db.query(Incident)
        if not is_admin:
            # Respective group members only see tickets in their assignment groups
            q = q.filter(Incident.assignment_group_id.in_(user_group_ids))
        elif assignment_group_id:
            q = q.filter(Incident.assignment_group_id == assignment_group_id)

        if project_id:
            q = q.filter(Incident.project_id == project_id)
        if status:
            q = q.filter(Incident.status == status)
        if start_dt:
            q = q.filter(Incident.created_at >= start_dt)
        if end_dt:
            q = q.filter(Incident.created_at <= end_dt)

        items = q.order_by(desc(Incident.created_at)).all()

        # Generate export rows
        headers = [
            "Incident Number", "Status", "Priority", "Impact", "Urgency",
            "Short Description", "Application", "Project", "Assignment Group",
            "Assigned To", "Caller Name", "Caller Email", "Category", "Subcategory",
            "Resolution Code", "Close Category", "Close Subcategory", "ADO Work Item #",
            "Close Application", "Created At", "Resolved At", "Closed At", "Close Notes", "Resolution Notes"
        ]
        raw_rows = []
        for inc in items:
            raw_rows.append([
                inc.number,
                inc.status,
                inc.priority,
                inc.impact,
                inc.urgency,
                inc.short_description,
                inc.application.name if inc.application else "",
                inc.project.name if inc.project else "",
                inc.assignment_group.name if inc.assignment_group else "",
                inc.assigned_to.full_name if inc.assigned_to else "Unassigned",
                inc.caller.full_name if inc.caller else "",
                inc.caller.email if inc.caller else "",
                inc.category,
                inc.subcategory or "",
                inc.resolution_code or "",
                inc.close_category or "",
                inc.close_subcategory or "",
                inc.ado_number or "",
                inc.close_application_name or (inc.application.name if inc.application else ""),
                inc.created_at.strftime("%Y-%m-%d %H:%M:%S") if inc.created_at else "",
                inc.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if inc.resolved_at else "",
                inc.closed_at.strftime("%Y-%m-%d %H:%M:%S") if inc.closed_at else "",
                inc.resolution_notes or "",
                inc.resolution_notes or ""
            ])

        out_headers, out_rows = filter_row_by_columns(headers, raw_rows, requested_cols)

        if format == "json":
            if requested_cols:
                return [dict(zip(out_headers, r)) for r in out_rows]
            return [i.to_dict() for i in items]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(out_headers)
        for r in out_rows:
            writer.writerow(r)

        filename = f"incidents_export_{time_period}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    elif norm_type in ["service_requests", "service_request", "requests"]:
        q = db.query(ServiceRequest)
        if not is_admin:
            q = q.filter(ServiceRequest.assignment_group_id.in_(user_group_ids))
        elif assignment_group_id:
            q = q.filter(ServiceRequest.assignment_group_id == assignment_group_id)

        if project_id:
            q = q.filter(ServiceRequest.project_id == project_id)
        if status:
            q = q.filter(ServiceRequest.status == status)
        if start_dt:
            q = q.filter(ServiceRequest.created_at >= start_dt)
        if end_dt:
            q = q.filter(ServiceRequest.created_at <= end_dt)

        items = q.order_by(desc(ServiceRequest.created_at)).all()

        headers = [
            "Request Number", "Status", "Priority", "Catalog Item", "Short Description",
            "Application", "Project", "Assignment Group", "Assigned To", "Requested By",
            "Approval Status", "Created At", "Closed At"
        ]
        raw_rows = []
        for req in items:
            raw_rows.append([
                req.number,
                req.status,
                req.priority,
                req.catalog_item,
                req.short_description,
                req.application.name if req.application else "",
                req.project.name if req.project else "",
                req.assignment_group.name if req.assignment_group else "",
                req.assigned_to.full_name if req.assigned_to else "Unassigned",
                req.requested_by.full_name if req.requested_by else "",
                getattr(req, "approval_status", "Approved"),
                req.created_at.strftime("%Y-%m-%d %H:%M:%S") if req.created_at else "",
                req.closed_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(req, "closed_at", None) else ""
            ])

        out_headers, out_rows = filter_row_by_columns(headers, raw_rows, requested_cols)

        if format == "json":
            if requested_cols:
                return [dict(zip(out_headers, r)) for r in out_rows]
            return [i.to_dict() for i in items]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(out_headers)
        for r in out_rows:
            writer.writerow(r)

        filename = f"service_requests_export_{time_period}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    elif norm_type in ["changes", "change", "change_requests"]:
        q = db.query(ChangeRequest)
        if not is_admin:
            q = q.filter(ChangeRequest.assignment_group_id.in_(user_group_ids))
        elif assignment_group_id:
            q = q.filter(ChangeRequest.assignment_group_id == assignment_group_id)

        if project_id:
            q = q.filter(ChangeRequest.project_id == project_id)
        if status:
            q = q.filter(or_(ChangeRequest.change_status == status, ChangeRequest.approval_status == status))
        if start_dt:
            q = q.filter(ChangeRequest.created_at >= start_dt)
        if end_dt:
            q = q.filter(ChangeRequest.created_at <= end_dt)

        items = q.order_by(desc(ChangeRequest.created_at)).all()

        headers = [
            "Change Number", "Status", "Change Type", "Risk", "Priority",
            "Short Description", "Application", "Project", "Assignment Group",
            "Assigned To", "Requested By", "Approval Status",
            "Planned Start", "Planned End", "Actual Start", "Actual End", "Created At"
        ]
        raw_rows = []
        for chg in items:
            raw_rows.append([
                chg.number,
                chg.change_status,
                chg.change_type,
                chg.risk,
                chg.priority,
                chg.short_description,
                chg.application.name if chg.application else "",
                chg.project.name if chg.project else "",
                chg.assignment_group.name if chg.assignment_group else "",
                chg.assigned_to.full_name if chg.assigned_to else "Unassigned",
                chg.requested_by.full_name if chg.requested_by else "",
                chg.approval_status,
                chg.planned_start.strftime("%Y-%m-%d %H:%M:%S") if chg.planned_start else "",
                chg.planned_end.strftime("%Y-%m-%d %H:%M:%S") if chg.planned_end else "",
                chg.actual_start.strftime("%Y-%m-%d %H:%M:%S") if getattr(chg, "actual_start", None) else "",
                chg.actual_end.strftime("%Y-%m-%d %H:%M:%S") if getattr(chg, "actual_end", None) else "",
                chg.created_at.strftime("%Y-%m-%d %H:%M:%S") if chg.created_at else ""
            ])

        out_headers, out_rows = filter_row_by_columns(headers, raw_rows, requested_cols)

        if format == "json":
            if requested_cols:
                return [dict(zip(out_headers, r)) for r in out_rows]
            return [i.to_dict() for i in items]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(out_headers)
        for r in out_rows:
            writer.writerow(r)

        filename = f"change_requests_export_{time_period}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ticket_type '{ticket_type}'. Choose 'incidents', 'service-requests', or 'changes'."
        )
