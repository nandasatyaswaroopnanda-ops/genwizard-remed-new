import json
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from backend.database import get_db
from backend.models import Project, Application, AssignmentGroup, ProjectAssignmentMapping, ConfigurationAudit, User
from backend.security import require_admin, require_global_admin, get_user_scopes

router = APIRouter(prefix="/api/admin/projects", tags=["admin-projects"])

class ProjectSchema(BaseModel):
    project_id: str
    name: str
    description: Optional[str] = None
    application_id: Optional[int] = None
    project_manager: Optional[str] = None
    business_owner: Optional[str] = None
    technical_owner: Optional[str] = None
    default_assignment_group_id: Optional[int] = None
    l2_assignment_group_id: Optional[int] = None
    l3_assignment_group_id: Optional[int] = None
    default_sla_policy_id: Optional[int] = None
    support_hours: Optional[str] = "Standard Business Hours"
    environment: Optional[str] = "Production"
    criticality: Optional[str] = "Medium"
    custom_fields: Dict[str, Any] = {}
    active: bool = True
    effective_from: Optional[datetime.datetime] = None
    effective_to: Optional[datetime.datetime] = None
    reason: Optional[str] = "Admin update"

class MappingSchema(BaseModel):
    mapping_id: str
    project_id: int
    application_id: int
    assignment_group_id: int
    category: Optional[str] = None
    priority_override: Optional[str] = None
    sla_policy_override_id: Optional[int] = None
    routing_priority: int = 100
    active: bool = True
    reason: Optional[str] = "Mapping rule update"

import os
import requests
import logging
from backend.models import CustomGroup
from backend.security import get_session_user, get_user_scopes, can_edit_project_oncall

logger = logging.getLogger("admin_projects")

class ProjectOnCallUpdateSchema(BaseModel):
    l2_on_call_contact: Optional[str] = None
    l3_on_call_contact: Optional[str] = None
    first_escalation_contact: Optional[str] = None
    second_escalation_contact: Optional[str] = None
    application_on_calls: Optional[Dict[str, str]] = {}
    application_first_escalations: Optional[Dict[str, str]] = {}
    application_second_escalations: Optional[Dict[str, str]] = {}

def get_project_applications(db: Session, proj: Project) -> List[Application]:
    app_ids = set()
    if proj.application_id:
        app_ids.add(proj.application_id)
    apps_by_pid = db.query(Application).filter(Application.project_id == proj.id).all()
    for a in apps_by_pid:
        app_ids.add(a.id)
    mappings = db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.project_id == proj.id).all()
    for m in mappings:
        app_ids.add(m.application_id)
    return db.query(Application).filter(Application.id.in_(list(app_ids))).all() if app_ids else []

def setup_project_queues_and_groups(db: Session, project_name: str, app_id: Optional[int] = None):
    """
    Ensures that for any project created:
    1. Beneath that project, 2 child assignment groups exist: <project>-l2, <project>-l3.
    2. Dynamically creates 6 scoped IM groups:
       - <project>-l2-admin, <project>-l2-user, <project>-l2-read
       - <project>-l3-admin, <project>-l3-user, <project>-l3-read
       (plus project-wide <project>-admin, <project>-user, <project>-read).
    3. Returns (<project>-l2, <project>-l3).
    """
    clean_name = project_name.strip()
    l2_name = f"{clean_name}-l2"
    l3_name = f"{clean_name}-l3"

    # 1. Assignment Groups: L3
    grp_l3 = db.query(AssignmentGroup).filter(AssignmentGroup.name == l3_name).first()
    if not grp_l3:
        grp_l3 = AssignmentGroup(
            group_id=f"GRP-{clean_name.upper().replace(' ', '-')}-L3",
            name=l3_name,
            description=f"Tier-3 Advanced Engineering Support & Escalation for {clean_name}",
            applications_supported=json.dumps([]),
            projects_supported=json.dumps([clean_name]),
            active=True
        )
        db.add(grp_l3)
        db.flush()

    # 2. Assignment Groups: L2
    grp_l2 = db.query(AssignmentGroup).filter(AssignmentGroup.name == l2_name).first()
    if not grp_l2:
        grp_l2 = AssignmentGroup(
            group_id=f"GRP-{clean_name.upper().replace(' ', '-')}-L2",
            name=l2_name,
            description=f"Tier-2 Frontline Support for {clean_name}",
            applications_supported=json.dumps([]),
            projects_supported=json.dumps([clean_name]),
            escalation_group_id=grp_l3.id,
            active=True
        )
        db.add(grp_l2)
        db.flush()
    elif not grp_l2.escalation_group_id:
        grp_l2.escalation_group_id = grp_l3.id

    # 3. Dynamic IM Groups: 6 scoped groups + project groups
    im_groups = [
        (
            f"{clean_name}-l2-admin",
            f"Tier-2 Frontline Administrator for {clean_name} (Manages on-call, queues, and frontline dispatch)",
            [
                f"project_{clean_name}_admin", f"project:{clean_name}:admin",
                f"project_{clean_name}_l2_admin", f"project:{clean_name}:l2:admin",
                f"project_{clean_name}_oncall", f"project:{clean_name}:oncall",
                "ticket_create", "tickets:create", "ticket_read", "tickets:read",
                "ticket_update", "tickets:update", "ticket_assign", "tickets:assign", "ticket_resolve", "tickets:resolve",
                "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-l2-user",
            f"Tier-2 Frontline Support Engineer for {clean_name}",
            [
                f"project_{clean_name}_l2_user", f"project:{clean_name}:l2:user",
                "ticket_create", "tickets:create", "ticket_read", "tickets:read",
                "ticket_update", "tickets:update", "ticket_assign", "tickets:assign", "ticket_resolve", "tickets:resolve",
                "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-l2-read",
            f"Tier-2 Frontline Auditor/Read-Only for {clean_name}",
            [
                f"project_{clean_name}_l2_read", f"project:{clean_name}:l2:read",
                "ticket_read", "tickets:read", "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-l3-admin",
            f"Tier-3 Advanced Engineering Administrator for {clean_name} (Manages on-call, escalations, and technical architecture)",
            [
                f"project_{clean_name}_admin", f"project:{clean_name}:admin",
                f"project_{clean_name}_l3_admin", f"project:{clean_name}:l3:admin",
                f"project_{clean_name}_oncall", f"project:{clean_name}:oncall",
                "ticket_create", "tickets:create", "ticket_read", "tickets:read",
                "ticket_update", "tickets:update", "ticket_assign", "tickets:assign", "ticket_resolve", "tickets:resolve",
                "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-l3-user",
            f"Tier-3 Advanced Support Engineer for {clean_name}",
            [
                f"project_{clean_name}_l3_user", f"project:{clean_name}:l3:user",
                "ticket_create", "tickets:create", "ticket_read", "tickets:read",
                "ticket_update", "tickets:update", "ticket_assign", "tickets:assign", "ticket_resolve", "tickets:resolve",
                "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-l3-read",
            f"Tier-3 Advanced Auditor/Read-Only for {clean_name}",
            [
                f"project_{clean_name}_l3_read", f"project:{clean_name}:l3:read",
                "ticket_read", "tickets:read", "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-admin",
            f"Overall Project Administrator Group for {clean_name}",
            [
                f"project_{clean_name}_admin", f"project:{clean_name}:admin",
                f"project_{clean_name}_apps", f"project:{clean_name}:apps",
                f"project_{clean_name}_taxonomy", f"project:{clean_name}:taxonomy",
                f"project_{clean_name}_oncall", f"project:{clean_name}:oncall",
                "ticket_create", "tickets:create", "ticket_read", "tickets:read",
                "ticket_update", "tickets:update", "ticket_assign", "tickets:assign", "ticket_resolve", "tickets:resolve", "ticket_close", "tickets:close",
                "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-user",
            f"Project Fulfiller Group for {clean_name}",
            [
                f"project_{clean_name}_fulfiller", f"project:{clean_name}:fulfiller",
                "ticket_create", "tickets:create", "ticket_read", "tickets:read",
                "ticket_update", "tickets:update", "ticket_assign", "tickets:assign", "ticket_resolve", "tickets:resolve",
                "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
        (
            f"{clean_name}-read",
            f"Project Read-Only Group for {clean_name}",
            [
                f"project_{clean_name}_read", f"project:{clean_name}:read",
                "ticket_read", "tickets:read", "applications_read", "applications:read", "projects_read", "projects:read"
            ]
        ),
    ]

    for g_name, g_desc, g_perms in im_groups:
        existing_cg = db.query(CustomGroup).filter(CustomGroup.name == g_name).first()
        if not existing_cg:
            cg = CustomGroup(
                name=g_name,
                description=g_desc,
                permissions=json.dumps(g_perms),
                active=True
            )
            db.add(cg)
            db.flush()
        else:
            existing_cg.permissions = json.dumps(g_perms)
            db.flush()

    # 4. Sync to External Identity Management service via REST if configured
    im_url = os.getenv("IDENTITY_SERVICE_URL", "").rstrip("/")
    if im_url:
        try:
            for g_name, g_desc, g_perms in im_groups:
                requests.post(
                    f"{im_url}/groups",
                    json={"name": g_name, "description": g_desc, "permissions": g_perms},
                    timeout=2
                )
        except Exception as _e:
            logger.debug("External IM group sync skipped: %s", _e)

    return grp_l2, grp_l3

@router.get("")
def list_projects(
    db: Session = Depends(get_db)
):
    projects = db.query(Project).order_by(Project.name.asc()).all()
    return [p.to_dict() for p in projects]

@router.post("")
def create_project(
    payload: ProjectSchema,
    current_user: User = Depends(require_global_admin),
    db: Session = Depends(get_db)
):
    # Automatically provision <project>-l2 and <project>-l3 child assignment groups
    # and project-scoped IM groups (<project>-admin, <project>-user, <project>-read)
    grp_l2, grp_l3 = setup_project_queues_and_groups(db, payload.name, payload.application_id)
    l2_grp_id = payload.l2_assignment_group_id or payload.default_assignment_group_id or grp_l2.id
    l3_grp_id = payload.l3_assignment_group_id or grp_l3.id
    default_grp_id = l2_grp_id

    proj = Project(
        project_id=payload.project_id,
        name=payload.name,
        description=payload.description,
        application_id=payload.application_id,
        project_manager=payload.project_manager,
        business_owner=payload.business_owner,
        technical_owner=payload.technical_owner,
        default_assignment_group_id=default_grp_id,
        l2_assignment_group_id=l2_grp_id,
        l3_assignment_group_id=l3_grp_id,
        default_sla_policy_id=payload.default_sla_policy_id,
        support_hours=payload.support_hours,
        environment=payload.environment,
        criticality=payload.criticality,
        custom_fields=json.dumps(payload.custom_fields or {}),
        active=payload.active,
        effective_from=payload.effective_from or datetime.datetime.utcnow(),
        effective_to=payload.effective_to
    )
    db.add(proj)
    db.flush()

    if payload.application_id:
        linked_app = db.query(Application).filter(Application.id == payload.application_id).first()
        if linked_app:
            linked_app.project_id = proj.id
            db.add(linked_app)

    audit = ConfigurationAudit(
        entity_type="Project",
        entity_id=proj.project_id,
        user_name=current_user.full_name,
        old_configuration="{}",
        new_configuration=json.dumps(proj.to_dict()),
        reason=payload.reason or "Created new project",
        effective_date=proj.effective_from
    )
    db.add(audit)
    db.commit()
    return proj.to_dict()

@router.get("/on-call-roster")
def get_on_call_roster(
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    projects = db.query(Project).filter(Project.active == True).order_by(Project.name.asc()).all()
    roster = []
    for p in projects:
        apps = get_project_applications(db, p)
        l2_grp = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{p.name}-l2").first()
        l3_grp = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{p.name}-l3").first()
        can_edit = can_edit_project_oncall(current_user, p.name, db) if current_user else False

        roster.append({
            "project_id": p.id,
            "project_code": p.project_id,
            "project_name": p.name,
            "l2_group_id": l2_grp.id if l2_grp else None,
            "l2_group_name": l2_grp.name if l2_grp else f"{p.name}-l2",
            "l2_on_call_contact": p.l2_on_call_contact or (l2_grp.on_call_contact if l2_grp else None),
            "l3_group_id": l3_grp.id if l3_grp else None,
            "l3_group_name": l3_grp.name if l3_grp else f"{p.name}-l3",
            "l3_on_call_contact": p.l3_on_call_contact or (l3_grp.on_call_contact if l3_grp else None),
            "first_escalation_contact": p.first_escalation_contact or (l2_grp.first_escalation_contact if l2_grp else None),
            "second_escalation_contact": p.second_escalation_contact or (l2_grp.second_escalation_contact if l2_grp else None),
            "can_edit": can_edit,
            "applications": [
                {
                    "id": a.id,
                    "app_id": a.app_id,
                    "name": a.name,
                    "on_call_contact": getattr(a, "on_call_contact", None),
                    "first_escalation_contact": getattr(a, "first_escalation_contact", None),
                    "second_escalation_contact": getattr(a, "second_escalation_contact", None),
                    "technical_owner": a.technical_owner,
                    "business_owner": a.business_owner,
                    "support_hours": a.support_hours
                }
                for a in apps
            ]
        })
    return roster

@router.get("/{project_id_or_name}/on-call")
def get_project_on_call(
    project_id_or_name: str,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if project_id_or_name.isdigit():
        proj = db.query(Project).filter(Project.id == int(project_id_or_name)).first()
    else:
        proj = db.query(Project).filter(Project.name == project_id_or_name).first()

    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    apps = get_project_applications(db, proj)
    l2_grp = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj.name}-l2").first()
    l3_grp = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj.name}-l3").first()
    can_edit = can_edit_project_oncall(current_user, proj.name, db) if current_user else False

    return {
        "project_id": proj.id,
        "project_code": proj.project_id,
        "project_name": proj.name,
        "l2_group_id": l2_grp.id if l2_grp else None,
        "l2_group_name": l2_grp.name if l2_grp else f"{proj.name}-l2",
        "l2_on_call_contact": proj.l2_on_call_contact or (l2_grp.on_call_contact if l2_grp else None),
        "l3_group_id": l3_grp.id if l3_grp else None,
        "l3_group_name": l3_grp.name if l3_grp else f"{proj.name}-l3",
        "l3_on_call_contact": proj.l3_on_call_contact or (l3_grp.on_call_contact if l3_grp else None),
        "first_escalation_contact": proj.first_escalation_contact or (l2_grp.first_escalation_contact if l2_grp else None),
        "second_escalation_contact": proj.second_escalation_contact or (l2_grp.second_escalation_contact if l2_grp else None),
        "can_edit": can_edit,
        "applications": [
            {
                "id": a.id,
                "app_id": a.app_id,
                "name": a.name,
                "on_call_contact": getattr(a, "on_call_contact", None),
                "first_escalation_contact": getattr(a, "first_escalation_contact", None),
                "second_escalation_contact": getattr(a, "second_escalation_contact", None),
                "technical_owner": a.technical_owner,
                "business_owner": a.business_owner,
                "support_hours": a.support_hours
            }
            for a in apps
        ]
    }

@router.put("/{project_id_or_name}/on-call")
def update_project_on_call(
    project_id_or_name: str,
    payload: ProjectOnCallUpdateSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    if project_id_or_name.isdigit():
        proj = db.query(Project).filter(Project.id == int(project_id_or_name)).first()
    else:
        proj = db.query(Project).filter(Project.name == project_id_or_name).first()

    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    if not can_edit_project_oncall(current_user, proj.name, db):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: You must be a global administrator or project administrator ({proj.name}-l2-admin, {proj.name}-l3-admin, {proj.name}-admin) to update on-call and escalation contacts."
        )

    if payload.l2_on_call_contact is not None:
        proj.l2_on_call_contact = payload.l2_on_call_contact
        grp_l2 = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj.name}-l2").first()
        if grp_l2:
            grp_l2.on_call_contact = payload.l2_on_call_contact

    if payload.l3_on_call_contact is not None:
        proj.l3_on_call_contact = payload.l3_on_call_contact
        grp_l3 = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj.name}-l3").first()
        if grp_l3:
            grp_l3.on_call_contact = payload.l3_on_call_contact

    if payload.first_escalation_contact is not None:
        proj.first_escalation_contact = payload.first_escalation_contact

    if payload.second_escalation_contact is not None:
        proj.second_escalation_contact = payload.second_escalation_contact

    # Collect all app keys needing updates across all 3 dicts, then apply all updates in one pass per app
    app_updates: Dict[str, Dict[str, str]] = {}
    for app_key, val in (payload.application_on_calls or {}).items():
        app_updates.setdefault(str(app_key), {})["on_call_contact"] = val
    for app_key, val in (payload.application_first_escalations or {}).items():
        app_updates.setdefault(str(app_key), {})["first_escalation_contact"] = val
    for app_key, val in (payload.application_second_escalations or {}).items():
        app_updates.setdefault(str(app_key), {})["second_escalation_contact"] = val

    for app_key, updates in app_updates.items():
        if app_key.isdigit():
            app = db.query(Application).filter(Application.id == int(app_key)).first()
        else:
            app = db.query(Application).filter((Application.name == app_key) | (Application.app_id == app_key)).first()
        if app:
            for field, value in updates.items():
                setattr(app, field, value)

    db.commit()
    return get_project_on_call(str(proj.id), x_user_id, db)

@router.put("/{project_id}")
def update_project(
    project_id: int,
    payload: ProjectSchema,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    scopes = get_user_scopes(current_user, db)
    if not scopes["is_global_admin"] and proj.name not in scopes["admin_projects"]:
        allowed = ", ".join(scopes["admin_projects"]) if scopes["admin_projects"] else "none"
        raise HTTPException(status_code=403, detail=f"Access denied: You only have admin rights for project(s): [{allowed}]")

    old_cfg = proj.to_dict()

    proj.name = payload.name
    proj.description = payload.description
    proj.application_id = payload.application_id
    if payload.application_id:
        linked_app = db.query(Application).filter(Application.id == payload.application_id).first()
        if linked_app:
            linked_app.project_id = proj.id
            db.add(linked_app)
    proj.project_manager = payload.project_manager
    proj.business_owner = payload.business_owner
    proj.technical_owner = payload.technical_owner
    if payload.l2_assignment_group_id:
        proj.l2_assignment_group_id = payload.l2_assignment_group_id
        proj.default_assignment_group_id = payload.l2_assignment_group_id
    elif payload.default_assignment_group_id:
        proj.default_assignment_group_id = payload.default_assignment_group_id
        proj.l2_assignment_group_id = payload.default_assignment_group_id

    if payload.l3_assignment_group_id:
        proj.l3_assignment_group_id = payload.l3_assignment_group_id

    proj.default_sla_policy_id = payload.default_sla_policy_id
    proj.support_hours = payload.support_hours
    proj.environment = payload.environment
    proj.criticality = payload.criticality
    proj.custom_fields = json.dumps(payload.custom_fields or {})
    proj.active = payload.active
    proj.effective_from = payload.effective_from or proj.effective_from
    proj.effective_to = payload.effective_to

    new_cfg = proj.to_dict()

    audit = ConfigurationAudit(
        entity_type="Project",
        entity_id=proj.project_id,
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration=json.dumps(new_cfg),
        reason=payload.reason or "Project configuration modified",
        effective_date=proj.effective_from
    )
    db.add(audit)
    db.commit()
    return proj.to_dict()

@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a project. Only global administrators have privilege to delete projects.
    When a project is deleted, all respective applications and assignment groups
    under it will also be deleted, and all cascading references cleaned up.
    """
    from backend.models import (
        SLAPolicy, RoutingRule, ClosureTaxonomy, Incident, ServiceRequest,
        ChangeRequest, KnowledgeArticle, GroupMember, GroupDistributionList,
        CustomGroup, UserCustomGroup
    )

    scopes = get_user_scopes(current_user, db)
    if not scopes["is_global_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Access denied: Only system administrator can delete projects."
        )

    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    old_cfg = proj.to_dict()
    proj_name = proj.name
    proj_name_lower = proj_name.strip().lower()
    proj_code = proj.project_id

    # Fallback Assignment Group (Service Desk fallback so tickets don't become orphaned)
    fallback_group = None
    for g in db.query(AssignmentGroup).all():
        if g.name.strip().lower() == "service desk":
            fallback_group = g
            break
    fallback_group_id = fallback_group.id if fallback_group else None

    # ---------------------------------------------------------
    # 1. DELETE ALL RESPECTIVE APPLICATIONS UNDER THIS PROJECT
    # ---------------------------------------------------------
    app_ids = set()
    if proj.application_id:
        app_ids.add(proj.application_id)
    for a in db.query(Application).filter(Application.project_id == proj.id).all():
        app_ids.add(a.id)
    for m in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.project_id == proj.id).all():
        if m.application_id:
            app_ids.add(m.application_id)

    apps_to_delete = db.query(Application).filter(Application.id.in_(list(app_ids))).all() if app_ids else []
    deleted_app_names = []

    for app in apps_to_delete:
        app_old_cfg = app.to_dict()
        app_name = app.name
        app_code = app.app_id
        deleted_app_names.append(app_name)

        # Unlink any other project referencing this app
        for other_p in db.query(Project).filter(Project.application_id == app.id, Project.id != proj.id).all():
            other_p.application_id = None
            db.add(other_p)

        # Delete mappings for this app
        for m in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.application_id == app.id).all():
            db.delete(m)

        # Clean up SLA policies scoped to this app
        for s in db.query(SLAPolicy).filter(SLAPolicy.application_id == app.id).all():
            db.delete(s)

        # Clean up Routing rules scoped to this app
        for r in db.query(RoutingRule).filter(RoutingRule.application_id == app.id).all():
            db.delete(r)

        # Clean up Taxonomy options scoped to this app
        try:
            for t in db.query(ClosureTaxonomy).filter(ClosureTaxonomy.application_id == app.id).all():
                db.delete(t)
        except Exception:
            pass

        # Unlink tickets and KB articles
        for inc in db.query(Incident).filter(Incident.application_id == app.id).all():
            inc.application_id = None
            db.add(inc)
        for req in db.query(ServiceRequest).filter(ServiceRequest.application_id == app.id).all():
            req.application_id = None
            db.add(req)
        for chg in db.query(ChangeRequest).filter(ChangeRequest.application_id == app.id).all():
            chg.application_id = None
            db.add(chg)
        for kb in db.query(KnowledgeArticle).filter(KnowledgeArticle.application_id == app.id).all():
            kb.application_id = None
            db.add(kb)

        # Audit log for application deletion
        db.add(ConfigurationAudit(
            entity_type="Application",
            entity_id=app_code,
            user_name=current_user.full_name,
            old_configuration=json.dumps(app_old_cfg),
            new_configuration="{}",
            reason=f"Cascade deleted application '{app_name}' ({app_code}) upon deletion of project '{proj_name}'",
            effective_date=datetime.datetime.utcnow()
        ))
        db.delete(app)

    # ---------------------------------------------------------
    # 2. DELETE ALL RESPECTIVE ASSIGNMENT GROUPS UNDER THIS PROJECT
    # ---------------------------------------------------------
    groups_to_delete_dict = {}

    # Direct queue references on the project
    for gid in [proj.l2_assignment_group_id, proj.l3_assignment_group_id, proj.default_assignment_group_id]:
        if gid:
            grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == gid).first()
            if grp and grp.name.strip().lower() != "service desk":
                groups_to_delete_dict[grp.id] = grp

    # Search all groups for project naming patterns or projects_supported
    all_groups = db.query(AssignmentGroup).all()
    for g in all_groups:
        if g.name.strip().lower() == "service desk":
            continue
        g_name_lower = g.name.strip().lower()
        if (
            g_name_lower == f"{proj_name_lower}-l2" or
            g_name_lower == f"{proj_name_lower}-l3" or
            g_name_lower.startswith(f"{proj_name_lower}-") or
            g_name_lower.startswith(f"{proj_name_lower}_")
        ):
            groups_to_delete_dict[g.id] = g
        else:
            try:
                supported = json.loads(g.projects_supported or "[]")
                if isinstance(supported, list) and any(str(p).strip().lower() == proj_name_lower for p in supported):
                    if len(supported) <= 1:
                        groups_to_delete_dict[g.id] = g
            except Exception:
                pass

    deleted_group_names = []
    for grp in list(groups_to_delete_dict.values()):
        grp_old_cfg = grp.to_dict()
        grp_name = grp.name
        grp_code = grp.group_id
        deleted_group_names.append(grp_name)

        # Unlink escalation_group_id on other assignment groups
        for other_g in db.query(AssignmentGroup).filter(AssignmentGroup.escalation_group_id == grp.id).all():
            other_g.escalation_group_id = None
            db.add(other_g)

        # Reassign tickets assigned to this group to fallback group
        for inc in db.query(Incident).filter(Incident.assignment_group_id == grp.id).all():
            inc.assignment_group_id = fallback_group_id
            db.add(inc)
        for sr in db.query(ServiceRequest).filter(ServiceRequest.assignment_group_id == grp.id).all():
            sr.assignment_group_id = fallback_group_id
            db.add(sr)
        for cr in db.query(ChangeRequest).filter(ChangeRequest.assignment_group_id == grp.id).all():
            cr.assignment_group_id = fallback_group_id
            db.add(cr)

        # Delete GroupMember records
        for gm in db.query(GroupMember).filter(GroupMember.group_id == grp.id).all():
            db.delete(gm)

        # Delete GroupDistributionList records
        for gdl in db.query(GroupDistributionList).filter(GroupDistributionList.group_id == grp.id).all():
            db.delete(gdl)

        # Delete RoutingRule targeting this group
        for r in db.query(RoutingRule).filter(RoutingRule.assignment_group_id == grp.id).all():
            db.delete(r)

        # Delete ProjectAssignmentMapping referencing this group
        for m in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.assignment_group_id == grp.id).all():
            db.delete(m)

        # Unlink from other applications/projects if any
        for a in db.query(Application).filter(Application.default_assignment_group_id == grp.id).all():
            a.default_assignment_group_id = fallback_group_id
            db.add(a)
        for p in db.query(Project).filter(Project.default_assignment_group_id == grp.id).all():
            p.default_assignment_group_id = fallback_group_id
            db.add(p)
        for p in db.query(Project).filter(Project.l2_assignment_group_id == grp.id).all():
            p.l2_assignment_group_id = None
            db.add(p)
        for p in db.query(Project).filter(Project.l3_assignment_group_id == grp.id).all():
            p.l3_assignment_group_id = None
            db.add(p)

        # Audit log for assignment group deletion
        db.add(ConfigurationAudit(
            entity_type="AssignmentGroup",
            entity_id=grp_code,
            user_name=current_user.full_name,
            old_configuration=json.dumps(grp_old_cfg),
            new_configuration="{}",
            reason=f"Cascade deleted assignment group '{grp_name}' ({grp_code}) upon deletion of project '{proj_name}'",
            effective_date=datetime.datetime.utcnow()
        ))
        db.delete(grp)

    # ---------------------------------------------------------
    # 3. DELETE ALL RESPECTIVE CUSTOM / IM GROUPS UNDER PROJECT
    # ---------------------------------------------------------
    custom_groups = db.query(CustomGroup).all()
    cgs_to_delete = []
    for cg in custom_groups:
        cg_name_lower = cg.name.strip().lower()
        if (
            cg_name_lower == f"{proj_name_lower}-admin" or
            cg_name_lower == f"{proj_name_lower}-user" or
            cg_name_lower == f"{proj_name_lower}-read" or
            cg_name_lower.startswith(f"{proj_name_lower}-") or
            cg_name_lower.startswith(f"{proj_name_lower}_")
        ):
            cgs_to_delete.append(cg)

    for cg in cgs_to_delete:
        for ucg in db.query(UserCustomGroup).filter(UserCustomGroup.custom_group_id == cg.id).all():
            db.delete(ucg)
        db.delete(cg)

    # ---------------------------------------------------------
    # 4. CLEAN UP REMAINING PROJECT-LEVEL REFERENCES
    # ---------------------------------------------------------
    for m in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.project_id == proj.id).all():
        db.delete(m)

    for p in db.query(SLAPolicy).filter(SLAPolicy.project_id == proj.id).all():
        db.delete(p)

    for r in db.query(RoutingRule).filter(RoutingRule.project_id == proj.id).all():
        db.delete(r)

    # Unlink tickets referencing this project
    for inc in db.query(Incident).filter(Incident.project_id == proj.id).all():
        inc.project_id = None
        db.add(inc)
    for sr in db.query(ServiceRequest).filter(ServiceRequest.project_id == proj.id).all():
        sr.project_id = None
        db.add(sr)
    for cr in db.query(ChangeRequest).filter(ChangeRequest.project_id == proj.id).all():
        cr.project_id = None
        db.add(cr)

    # ---------------------------------------------------------
    # 5. AUDIT LOG & DELETE PROJECT
    # ---------------------------------------------------------
    audit = ConfigurationAudit(
        entity_type="Project",
        entity_id=proj_code,
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration="{}",
        reason=f"Deleted project '{proj_name}' ({proj_code}) with cascade deletion of {len(deleted_app_names)} applications and {len(deleted_group_names)} assignment groups",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)

    db.delete(proj)
    db.commit()

    return {
        "message": f"Project '{proj_name}' and all respective applications and assignment groups deleted successfully",
        "project_id": project_id,
        "deleted_applications": deleted_app_names,
        "deleted_assignment_groups": deleted_group_names,
        "deleted_custom_groups": [cg.name for cg in cgs_to_delete]
    }


@router.get("/mappings")
def list_mappings(db: Session = Depends(get_db)):
    mappings = db.query(ProjectAssignmentMapping).order_by(ProjectAssignmentMapping.routing_priority.asc()).all()
    return [m.to_dict() for m in mappings]

@router.post("/mappings")
def create_mapping(
    payload: MappingSchema,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    scopes = get_user_scopes(current_user, db)
    if not scopes["is_global_admin"]:
        proj = db.query(Project).filter(Project.id == payload.project_id).first()
        if not proj or proj.name not in scopes["admin_projects"]:
            allowed = ", ".join(scopes["admin_projects"]) if scopes["admin_projects"] else "none"
            raise HTTPException(status_code=403, detail=f"Access denied: You only have admin rights for project(s): [{allowed}]")

    mapping = ProjectAssignmentMapping(
        mapping_id=payload.mapping_id,
        project_id=payload.project_id,
        application_id=payload.application_id,
        assignment_group_id=payload.assignment_group_id,
        category=payload.category,
        priority_override=payload.priority_override,
        sla_policy_override_id=payload.sla_policy_override_id,
        routing_priority=payload.routing_priority,
        active=payload.active
    )
    db.add(mapping)
    db.flush()

    audit = ConfigurationAudit(
        entity_type="ProjectAssignmentMapping",
        entity_id=mapping.mapping_id,
        user_name=current_user.full_name,
        old_configuration="{}",
        new_configuration=json.dumps(mapping.to_dict()),
        reason=payload.reason or "Created new project assignment mapping",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return mapping.to_dict()

@router.delete("/mappings/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    mapping = db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(mapping)
    db.commit()
    return {"message": "Mapping deleted"}
