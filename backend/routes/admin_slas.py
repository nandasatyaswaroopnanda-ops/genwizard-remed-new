import json
import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from backend.database import get_db
from backend.models import SLAPolicy, User, ConfigurationAudit, Project, AssignmentGroup
from backend.security import get_user_scopes

router = APIRouter(prefix="/api/admin/slas", tags=["admin-slas"])


def get_current_user_for_sla(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()


def can_user_manage_sla(user: User, policy: SLAPolicy, db: Session) -> bool:
    """
    Returns True if the user is authorised to create / update this SLA policy.
    Rules:
    - Global admin → can manage any policy.
    - Project-group admin (<proj>-admin, <proj>-l2-admin, <proj>-l3-admin) →
        can manage policies explicitly scoped to their project or assignment group.
    - Group manager / group admin → can manage policies scoped to their assignment group.
    - Everyone else → denied.
    """
    scopes = get_user_scopes(user, db)
    if scopes["is_global_admin"]:
        return True

    admin_project_names_lower = [p.lower() for p in scopes.get("admin_projects", [])]
    c_groups = [g.lower() for g in scopes.get("custom_groups", [])]

    # 1. Scoped to a project
    if policy.project_id:
        proj = db.query(Project).filter(Project.id == policy.project_id).first()
        if proj and proj.name.lower() in admin_project_names_lower:
            return True

    # 2. Scoped to an assignment group
    if policy.assignment_group_id:
        grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == policy.assignment_group_id).first()
        if grp:
            if grp.manager_id == user.id:
                return True
            if f"{grp.name.lower()}-admin" in c_groups:
                return True
            if grp.name.lower() in admin_project_names_lower:
                return True
            if grp.name.lower().endswith("-l2") and grp.name[:-3].lower() in admin_project_names_lower:
                return True
            if grp.name.lower().endswith("-l3") and grp.name[:-3].lower() in admin_project_names_lower:
                return True
            try:
                ps = json.loads(grp.projects_supported or "[]")
                if any(p.lower() in admin_project_names_lower for p in ps):
                    return True
            except Exception:
                pass

    return False


def sla_with_can_edit(policy: SLAPolicy, user: User, db: Session) -> Dict[str, Any]:
    """Serialise an SLAPolicy including a computed can_edit flag."""
    d = policy.to_dict()
    d["can_edit"] = can_user_manage_sla(user, policy, db)
    return d


class SLAPolicySchema(BaseModel):
    policy_code: str
    name: str
    description: Optional[str] = None
    ticket_type: str = "Incident"
    application_id: Optional[int] = None
    project_id: Optional[int] = None
    assignment_group_id: Optional[int] = None
    priority: str = "P1"
    response_target_mins: int
    resolution_target_mins: int
    business_calendar_id: Optional[int] = None
    pause_conditions: Optional[List[str]] = ["Pending Customer", "Awaiting Approval", "Awaiting Vendor"]
    escalation_rules: Optional[List[dict]] = None
    warning_threshold_pct: int = 75
    active: bool = True
    effective_from: Optional[datetime.datetime] = None
    effective_to: Optional[datetime.datetime] = None
    create_new_version: bool = False
    reason: Optional[str] = "SLA configuration update"


# ---------------------------------------------------------------------------
# GET /api/admin/slas
# ---------------------------------------------------------------------------
@router.get("")
def list_sla_policies(
    project_id: Optional[int] = None,
    ticket_type: Optional[str] = None,
    priority: Optional[str] = None,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    List SLA policies.
    - Global admin: all policies (optionally filtered by project_id, ticket_type, priority).
    - Project/Group admin: policies scoped to their admin projects or groups, plus global reference policies.
    - Others: 403 Forbidden.
    """
    current_user = get_current_user_for_sla(db, x_user_id)
    scopes = get_user_scopes(current_user, db)

    if not (scopes["is_global_admin"] or scopes["admin_projects"] or scopes["is_support_member"]):
        raise HTTPException(status_code=403, detail="Administrator or support role required to manage SLA policies")

    q = db.query(SLAPolicy)

    if ticket_type:
        q = q.filter(SLAPolicy.ticket_type == ticket_type)
    if priority:
        q = q.filter(SLAPolicy.priority == priority)

    if scopes["is_global_admin"]:
        if project_id:
            q = q.filter(SLAPolicy.project_id == project_id)
    else:
        admin_project_names_lower = [p.lower() for p in scopes.get("admin_projects", [])]
        admin_proj_objs = db.query(Project).all()
        admin_proj_ids = [
            p.id for p in admin_proj_objs
            if p.name.lower() in admin_project_names_lower
        ]

        admin_group_objs = db.query(AssignmentGroup).all()
        admin_group_ids = []
        c_groups = [g.lower() for g in scopes.get("custom_groups", [])]
        for grp in admin_group_objs:
            if (grp.manager_id == current_user.id or
                f"{grp.name.lower()}-admin" in c_groups or
                grp.name.lower() in admin_project_names_lower or
                (grp.name.lower().endswith("-l2") and grp.name[:-3].lower() in admin_project_names_lower) or
                (grp.name.lower().endswith("-l3") and grp.name[:-3].lower() in admin_project_names_lower)):
                admin_group_ids.append(grp.id)

        if project_id:
            if project_id not in admin_proj_ids:
                raise HTTPException(status_code=403, detail="Access denied to requested project SLAs")
            q = q.filter(SLAPolicy.project_id == project_id)
        else:
            from sqlalchemy import or_
            filters = []
            if admin_proj_ids:
                filters.append(SLAPolicy.project_id.in_(admin_proj_ids))
            if admin_group_ids:
                filters.append(SLAPolicy.assignment_group_id.in_(admin_group_ids))
            # Global reference policies
            filters.append((SLAPolicy.project_id.is_(None)) & (SLAPolicy.assignment_group_id.is_(None)))
            q = q.filter(or_(*filters))

    policies = q.order_by(SLAPolicy.policy_code.asc(), desc(SLAPolicy.version)).all()
    return [sla_with_can_edit(p, current_user, db) for p in policies]


# ---------------------------------------------------------------------------
# POST /api/admin/slas  (Create new policy)
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def create_sla_policy(
    payload: SLAPolicySchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Create a new SLA policy.
    - Global admin: may create policies with any scope (project_id optional).
    - Project/Group admin: must supply a project_id or assignment_group_id that belongs to their scope.
    """
    current_user = get_current_user_for_sla(db, x_user_id)
    scopes = get_user_scopes(current_user, db)

    if not (scopes["is_global_admin"] or scopes["admin_projects"] or scopes["is_support_member"]):
        raise HTTPException(status_code=403, detail="Administrator role required to create SLA policies")

    if not scopes["is_global_admin"]:
        admin_project_names_lower = [p.lower() for p in scopes.get("admin_projects", [])]
        c_groups = [g.lower() for g in scopes.get("custom_groups", [])]

        if payload.project_id:
            proj = db.query(Project).filter(Project.id == payload.project_id).first()
            if not proj:
                raise HTTPException(status_code=404, detail="Project not found")
            if proj.name.lower() not in admin_project_names_lower:
                raise HTTPException(
                    status_code=403,
                    detail=f"You are not an admin of project '{proj.name}'"
                )
        elif payload.assignment_group_id:
            grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == payload.assignment_group_id).first()
            if not grp:
                raise HTTPException(status_code=404, detail="Assignment group not found")
            if not (grp.manager_id == current_user.id or
                    f"{grp.name.lower()}-admin" in c_groups or
                    grp.name.lower() in admin_project_names_lower or
                    (grp.name.lower().endswith("-l2") and grp.name[:-3].lower() in admin_project_names_lower) or
                    (grp.name.lower().endswith("-l3") and grp.name[:-3].lower() in admin_project_names_lower)):
                raise HTTPException(
                    status_code=403,
                    detail=f"You are not an admin of assignment group '{grp.name}'"
                )
        else:
            raise HTTPException(
                status_code=403,
                detail="Project and group admins must specify a project_id or assignment_group_id when creating an SLA policy"
            )

    policy = SLAPolicy(
        policy_code=payload.policy_code,
        name=payload.name,
        version=1,
        description=payload.description,
        ticket_type=payload.ticket_type,
        application_id=payload.application_id,
        project_id=payload.project_id,
        assignment_group_id=payload.assignment_group_id,
        priority=payload.priority,
        response_target_mins=payload.response_target_mins,
        resolution_target_mins=payload.resolution_target_mins,
        business_calendar_id=payload.business_calendar_id,
        pause_conditions=json.dumps(payload.pause_conditions or []),
        escalation_rules=json.dumps(payload.escalation_rules or []),
        warning_threshold_pct=payload.warning_threshold_pct,
        active=payload.active,
        effective_from=payload.effective_from or datetime.datetime.utcnow(),
        effective_to=payload.effective_to
    )
    db.add(policy)
    db.flush()

    audit = ConfigurationAudit(
        entity_type="SLAPolicy",
        entity_id=f"{policy.policy_code}-v1",
        user_name=current_user.full_name,
        old_configuration="{}",
        new_configuration=json.dumps(policy.to_dict()),
        reason=payload.reason or "Created initial SLA policy version 1",
        effective_date=policy.effective_from
    )
    db.add(audit)
    db.commit()
    return sla_with_can_edit(policy, current_user, db)


# ---------------------------------------------------------------------------
# PUT /api/admin/slas/{policy_id}  (Update / new version)
# ---------------------------------------------------------------------------
@router.put("/{policy_id}")
def update_sla_policy(
    policy_id: int,
    payload: SLAPolicySchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Update an SLA policy.
    - If create_new_version=True: archives the existing version and creates a
      new versioned copy — preserving historical SLA for already-opened tickets.
    - If create_new_version=False: in-place edit of the current version.
    - Project admins: may only modify policies scoped to their projects.
    """
    current_user = get_current_user_for_sla(db, x_user_id)
    scopes = get_user_scopes(current_user, db)

    if not (scopes["is_global_admin"] or scopes["admin_projects"] or scopes["is_support_member"]):
        raise HTTPException(status_code=403, detail="Administrator or group manager role required to update SLA policies")

    existing = db.query(SLAPolicy).filter(SLAPolicy.id == policy_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="SLA policy not found")

    # Authorisation check
    if not can_user_manage_sla(current_user, existing, db):
        raise HTTPException(
            status_code=403,
            detail="You are not authorised to modify this SLA policy. "
                   "Group and project admins can only edit policies scoped to their own group or project."
        )

    now = datetime.datetime.utcnow()
    old_cfg = existing.to_dict()

    if payload.create_new_version:
        # ── Versioned update ─────────────────────────────────────────────
        existing.effective_to = payload.effective_from or now
        existing.active = False  # archive old version

        new_version_num = existing.version + 1
        new_policy = SLAPolicy(
            policy_code=existing.policy_code,
            name=payload.name,
            version=new_version_num,
            description=payload.description or f"Version {new_version_num} of {existing.name}",
            ticket_type=payload.ticket_type,
            application_id=payload.application_id,
            project_id=payload.project_id,
            assignment_group_id=payload.assignment_group_id,
            priority=payload.priority,
            response_target_mins=payload.response_target_mins,
            resolution_target_mins=payload.resolution_target_mins,
            business_calendar_id=payload.business_calendar_id,
            pause_conditions=json.dumps(payload.pause_conditions or []),
            escalation_rules=json.dumps(payload.escalation_rules or []),
            warning_threshold_pct=payload.warning_threshold_pct,
            active=payload.active,
            effective_from=payload.effective_from or now,
            effective_to=payload.effective_to
        )
        db.add(new_policy)
        db.flush()

        audit = ConfigurationAudit(
            entity_type="SLAPolicy",
            entity_id=f"{new_policy.policy_code}-v{new_version_num}",
            user_name=current_user.full_name,
            old_configuration=json.dumps(old_cfg),
            new_configuration=json.dumps(new_policy.to_dict()),
            reason=payload.reason or f"Created new SLA version {new_version_num} (historical v{existing.version} retained)",
            effective_date=new_policy.effective_from
        )
        db.add(audit)
        db.commit()
        return sla_with_can_edit(new_policy, current_user, db)

    else:
        # ── In-place edit ────────────────────────────────────────────────
        existing.name = payload.name
        existing.description = payload.description
        if payload.ticket_type:
            existing.ticket_type = payload.ticket_type
        if payload.priority:
            existing.priority = payload.priority
        if payload.application_id is not None:
            existing.application_id = payload.application_id
        if payload.project_id is not None:
            existing.project_id = payload.project_id
        if payload.assignment_group_id is not None:
            existing.assignment_group_id = payload.assignment_group_id
        existing.response_target_mins = payload.response_target_mins
        existing.resolution_target_mins = payload.resolution_target_mins
        existing.business_calendar_id = payload.business_calendar_id
        existing.pause_conditions = json.dumps(payload.pause_conditions or [])
        existing.escalation_rules = json.dumps(payload.escalation_rules or [])
        existing.warning_threshold_pct = payload.warning_threshold_pct
        existing.active = payload.active

        audit = ConfigurationAudit(
            entity_type="SLAPolicy",
            entity_id=f"{existing.policy_code}-v{existing.version}",
            user_name=current_user.full_name,
            old_configuration=json.dumps(old_cfg),
            new_configuration=json.dumps(existing.to_dict()),
            reason=payload.reason or "Updated SLA policy in-place",
            effective_date=existing.effective_from
        )
        db.add(audit)
        db.commit()
        return sla_with_can_edit(existing, current_user, db)


# ---------------------------------------------------------------------------
# DELETE /api/admin/slas/{policy_id}  (Archive / deactivate — global admin only)
# ---------------------------------------------------------------------------
@router.delete("/{policy_id}")
def deactivate_sla_policy(
    policy_id: int,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Deactivate (soft-delete) an SLA policy. Global admin only."""
    current_user = get_current_user_for_sla(db, x_user_id)
    scopes = get_user_scopes(current_user, db)

    if not scopes["is_global_admin"]:
        raise HTTPException(status_code=403, detail="Global administrator access required to deactivate SLA policies")

    policy = db.query(SLAPolicy).filter(SLAPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="SLA policy not found")

    old_cfg = policy.to_dict()
    policy.active = False
    policy.effective_to = datetime.datetime.utcnow()

    audit = ConfigurationAudit(
        entity_type="SLAPolicy",
        entity_id=f"{policy.policy_code}-v{policy.version}",
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration=json.dumps(policy.to_dict()),
        reason="SLA policy deactivated",
        effective_date=policy.effective_to
    )
    db.add(audit)
    db.commit()
    return {"ok": True, "policy_id": policy_id, "message": "SLA policy deactivated"}
