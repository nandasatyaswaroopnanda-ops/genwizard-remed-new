import json
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from backend.database import get_db
from backend.models import AssignmentGroup, GroupMember, User, ConfigurationAudit, DistributionList, GroupDistributionList
from backend.security import require_admin, get_user_scopes

router = APIRouter(prefix="/api/admin/groups", tags=["admin-groups"])

class GroupSchema(BaseModel):
    group_id: str
    name: str
    description: Optional[str] = None
    manager_id: Optional[int] = None
    applications_supported: Optional[List[str]] = []
    projects_supported: Optional[List[str]] = []
    default_sla_policy_id: Optional[int] = None
    business_calendar_id: Optional[int] = None
    escalation_group_id: Optional[int] = None
    on_call_contact: Optional[str] = None
    first_escalation_contact: Optional[str] = None
    second_escalation_contact: Optional[str] = None
    custom_fields: Dict[str, Any] = {}
    active: bool = True
    reason: Optional[str] = "Group configuration update"

class MemberSchema(BaseModel):
    user_id: int
    role_in_group: str = "member"

class DistributionListSchema(BaseModel):
    email: str
    display_name: Optional[str] = None
    privilege: str = "support"
    notification_enabled: bool = True

def get_group_eligible_assignees(db: Session, group: AssignmentGroup) -> List[Dict[str, Any]]:
    clean_grp = group.name.strip().lower()
    base_grp = clean_grp.replace("_", "-")
    for sfx in ("-l2", "-l3", "-support", "-engineering"):
        if base_grp.endswith(sfx):
            base_grp = base_grp[:-len(sfx)].strip()
            break

    matching_cgroup_names = {
        clean_grp,
        f"{clean_grp}-admin",
        f"{clean_grp}_admin",
        f"{clean_grp}-user",
        f"{clean_grp}_user",
        f"{base_grp}-admin",
        f"{base_grp}_admin",
    }
    has_tier = clean_grp.endswith("-l2") or clean_grp.endswith("-l3") or clean_grp.endswith("_l2") or clean_grp.endswith("_l3")
    if not has_tier:
        matching_cgroup_names.update({
            base_grp,
            f"{base_grp}-user",
            f"{base_grp}_user",
            f"{base_grp}-l2",
            f"{base_grp}-l3",
            f"{base_grp}-l2-admin",
            f"{base_grp}-l2_admin",
            f"{base_grp}-l3-admin",
            f"{base_grp}-l3_admin",
        })

    from backend.models import CustomGroup, UserCustomGroup
    cg_objs = db.query(CustomGroup).all()
    matching_cg_ids = {cg.id for cg in cg_objs if cg.name.strip().lower() in matching_cgroup_names}

    user_ids = set()
    for m in (group.members or []):
        user_ids.add(m.user_id)
    if group.manager_id:
        user_ids.add(group.manager_id)

    if matching_cg_ids:
        ucgs = db.query(UserCustomGroup).filter(UserCustomGroup.custom_group_id.in_(list(matching_cg_ids))).all()
        for ucg in ucgs:
            user_ids.add(ucg.user_id)

    # For general project queues without tier, also find support team members assigned to the project
    if base_grp and not has_tier:
        all_active_users = db.query(User).filter(User.active == True).all()
        for u in all_active_users:
            if u.role == "employee":
                continue
            u_dict = u.to_dict()
            if u_dict.get("is_end_user"):
                continue
            user_projs = [p.lower().replace("_", "-") for p in (u_dict.get("admin_projects", []) + u_dict.get("support_projects", []))]
            if any(base_grp in p or p in base_grp for p in user_projs):
                user_ids.add(u.id)

    if not user_ids:
        return []

    users = db.query(User).filter(
        User.id.in_(list(user_ids)),
        User.active == True,
        User.role != "employee"
    ).order_by(User.full_name.asc()).all()

    return [
        {
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role
        }
        for u in users
    ]

@router.get("")
def list_groups(
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
    application_id: Optional[int] = None,
    application_name: Optional[str] = None,
    application_ids: Optional[str] = None,
    application_names: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from backend.models import Project, Application
    target_pname = None
    target_proj_obj = None
    if project_id:
        p = db.query(Project).filter(Project.id == project_id).first()
        if p:
            target_pname = p.name
            target_proj_obj = p
    elif project_name:
        target_pname = project_name
        target_proj_obj = db.query(Project).filter(Project.name == project_name).first()

    target_anames = []
    target_app_objs = []

    # Collect application IDs
    app_id_list = []
    if application_id:
        app_id_list.append(application_id)
    if application_ids:
        for aid_part in application_ids.split(","):
            aid_part = aid_part.strip()
            if aid_part.isdigit():
                app_id_list.append(int(aid_part))

    for aid in app_id_list:
        a = db.query(Application).filter(Application.id == aid).first()
        if a:
            target_anames.append(a.name)
            target_app_objs.append(a)
            if not target_pname and a.project_id:
                p = db.query(Project).filter(Project.id == a.project_id).first()
                if p:
                    target_pname = p.name
                    target_proj_obj = p

    # Collect application names
    app_name_list = []
    if application_name:
        app_name_list.append(application_name)
    if application_names:
        for aname_part in application_names.split(","):
            aname_part = aname_part.strip()
            if aname_part:
                app_name_list.append(aname_part)

    for aname in app_name_list:
        if aname not in target_anames:
            target_anames.append(aname)
        a = db.query(Application).filter(Application.name == aname).first()
        if a and a not in target_app_objs:
            target_app_objs.append(a)
            if not target_pname and a.project_id:
                p = db.query(Project).filter(Project.id == a.project_id).first()
                if p:
                    target_pname = p.name
                    target_proj_obj = p

    groups = db.query(AssignmentGroup).filter(AssignmentGroup.active == True).order_by(AssignmentGroup.name.asc()).all()

    if target_pname or target_anames:
        p_clean = target_pname.strip().lower() if target_pname else None
        a_cleans = [an.strip().lower() for an in target_anames if an.strip()]
        filtered = []
        for g in groups:
            g_name = g.name.strip().lower()
            projs_supp = []
            try:
                projs_supp = [x.lower() for x in json.loads(g.projects_supported or "[]")]
            except Exception:
                pass
            apps_supp = []
            try:
                apps_supp = [x.lower() for x in json.loads(g.applications_supported or "[]")]
            except Exception:
                pass

            matches_proj = False
            if p_clean:
                matches_proj = (g_name.startswith(f"{p_clean}-") or g_name == p_clean or p_clean in projs_supp)
                if target_proj_obj:
                    if g.id in (target_proj_obj.l2_assignment_group_id, target_proj_obj.l3_assignment_group_id, target_proj_obj.default_assignment_group_id):
                        matches_proj = True

            matches_app = False
            if a_cleans:
                for a_clean in a_cleans:
                    if (
                        a_clean in apps_supp
                        or g_name.startswith(f"{a_clean}-")
                        or g_name == a_clean
                        or any(app_obj.default_assignment_group_id == g.id for app_obj in target_app_objs if app_obj.name.strip().lower() == a_clean)
                    ):
                        matches_app = True
                        break

            if p_clean and a_cleans:
                if matches_app or matches_proj:
                    filtered.append(g)
            elif p_clean:
                if matches_proj:
                    filtered.append(g)
            elif a_cleans:
                if matches_app or (target_pname and matches_proj):
                    filtered.append(g)
        groups = filtered

    res = []
    for g in groups:
        d = g.to_dict()
        d["members"] = [m.to_dict() for m in g.members]
        d["distribution_lists"] = [dl.to_dict() for dl in g.distribution_lists]
        d["eligible_assignees"] = get_group_eligible_assignees(db, g)
        res.append(d)
    return res

@router.get("/{group_id_or_name}/assignees")
def get_group_assignees(group_id_or_name: str, db: Session = Depends(get_db)):
    if group_id_or_name.isdigit():
        grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == int(group_id_or_name)).first()
    else:
        grp = db.query(AssignmentGroup).filter(AssignmentGroup.name == group_id_or_name).first()

    if not grp:
        raise HTTPException(status_code=404, detail="Assignment group not found")

    return get_group_eligible_assignees(db, grp)

@router.post("")
def create_group(
    payload: GroupSchema,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    grp = AssignmentGroup(
        group_id=payload.group_id,
        name=payload.name,
        description=payload.description,
        manager_id=payload.manager_id,
        applications_supported=json.dumps(payload.applications_supported or []),
        projects_supported=json.dumps(payload.projects_supported or []),
        default_sla_policy_id=payload.default_sla_policy_id,
        business_calendar_id=payload.business_calendar_id,
        escalation_group_id=payload.escalation_group_id,
        on_call_contact=payload.on_call_contact,
        first_escalation_contact=payload.first_escalation_contact,
        second_escalation_contact=payload.second_escalation_contact,
        custom_fields=json.dumps(payload.custom_fields or {}),
        active=payload.active
    )
    db.add(grp)
    db.flush()

    audit = ConfigurationAudit(
        entity_type="AssignmentGroup",
        entity_id=grp.group_id,
        user_name=current_user.full_name,
        old_configuration="{}",
        new_configuration=json.dumps(grp.to_dict()),
        reason=payload.reason or "Created new assignment group",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return grp.to_dict()

@router.put("/{group_id}")
def update_group(
    group_id: int,
    payload: GroupSchema,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Assignment group not found")

    scopes = get_user_scopes(current_user, db)
    if not scopes["is_global_admin"]:
        admin_projs_lower = [p.lower() for p in scopes["admin_projects"]]
        grp_name_lower = grp.name.lower()
        supported = []
        try:
            supported = [p.lower() for p in json.loads(grp.projects_supported or "[]")]
        except Exception:
            pass
        is_allowed = any(p in grp_name_lower or p in supported for p in admin_projs_lower)
        if not is_allowed:
            from backend.models import Project
            linked_projs = db.query(Project).filter(
                (Project.default_assignment_group_id == grp.id) |
                (Project.l2_assignment_group_id == grp.id) |
                (Project.l3_assignment_group_id == grp.id)
            ).all()
            if any(p.name.lower() in admin_projs_lower for p in linked_projs):
                is_allowed = True
        if not is_allowed:
            allowed = ", ".join(scopes["admin_projects"]) if scopes["admin_projects"] else "none"
            raise HTTPException(status_code=403, detail=f"Access denied: You only have rights to edit assignment groups in [{allowed}].")

    old_cfg = grp.to_dict()
    grp.name = payload.name
    grp.description = payload.description
    grp.manager_id = payload.manager_id
    grp.applications_supported = json.dumps(payload.applications_supported or [])
    grp.projects_supported = json.dumps(payload.projects_supported or [])
    grp.default_sla_policy_id = payload.default_sla_policy_id
    grp.business_calendar_id = payload.business_calendar_id
    grp.escalation_group_id = payload.escalation_group_id
    grp.on_call_contact = payload.on_call_contact
    grp.first_escalation_contact = payload.first_escalation_contact
    grp.second_escalation_contact = payload.second_escalation_contact
    grp.custom_fields = json.dumps(payload.custom_fields or {})
    grp.active = payload.active

    new_cfg = grp.to_dict()

    audit = ConfigurationAudit(
        entity_type="AssignmentGroup",
        entity_id=grp.group_id,
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration=json.dumps(new_cfg),
        reason=payload.reason or "Updated assignment group",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return grp.to_dict()

@router.post("/{group_id}/members")
def add_member(
    group_id: int,
    payload: MemberSchema,
    db: Session = Depends(get_db), current_user: User = Depends(require_admin)
):
    grp = db.query(AssignmentGroup).filter(AssignmentGroup.id == group_id).first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    existing = db.query(GroupMember).filter(GroupMember.group_id == group_id, GroupMember.user_id == payload.user_id).first()
    if existing:
        return existing.to_dict()

    mem = GroupMember(group_id=group_id, user_id=payload.user_id, role_in_group=payload.role_in_group)
    db.add(mem)
    db.commit()
    return mem.to_dict()

@router.delete("/{group_id}/members/{user_id}")
def remove_member(group_id: int, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    mem = db.query(GroupMember).filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Member not in group")
    db.delete(mem)
    db.commit()
    return {"message": "Member removed from group"}

@router.post("/{group_id}/distribution-lists")
def add_distribution_list(group_id: int, payload: DistributionListSchema, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if payload.privilege not in {"support", "administrator"}:
        raise HTTPException(status_code=422, detail="privilege must be support or administrator")
    group = db.query(AssignmentGroup).filter(AssignmentGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="A valid distribution-list email is required")
    dl = db.query(DistributionList).filter(DistributionList.email == email).first()
    if not dl:
        dl = DistributionList(email=email, display_name=payload.display_name, privilege=payload.privilege)
        db.add(dl); db.flush()
    else:
        dl.display_name, dl.privilege, dl.active = payload.display_name or dl.display_name, payload.privilege, True
    mapping = db.query(GroupDistributionList).filter(GroupDistributionList.group_id == group_id, GroupDistributionList.distribution_list_id == dl.id).first()
    if not mapping:
        mapping = GroupDistributionList(group_id=group_id, distribution_list_id=dl.id, notification_enabled=payload.notification_enabled)
        db.add(mapping)
    else:
        mapping.notification_enabled = payload.notification_enabled
    db.commit(); db.refresh(mapping)
    return mapping.to_dict()

@router.delete("/{group_id}/distribution-lists/{distribution_list_id}")
def remove_distribution_list(group_id: int, distribution_list_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    mapping = db.query(GroupDistributionList).filter(GroupDistributionList.group_id == group_id, GroupDistributionList.distribution_list_id == distribution_list_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Distribution list is not configured for this group")
    db.delete(mapping); db.commit()
    return {"message": "Distribution list removed from assignment group"}
