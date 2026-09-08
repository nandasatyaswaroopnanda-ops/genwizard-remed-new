import datetime
import json
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func
from backend.database import get_db
from backend.models import Application, AssignmentGroup, ConfigurationAudit, User, Project
from backend.security import require_admin, get_user_scopes, get_session_user

router = APIRouter(prefix="/api/admin/applications", tags=["admin-applications"])

class ApplicationSchema(BaseModel):
    app_id: str
    name: str
    description: Optional[str] = None
    business_owner: Optional[str] = None
    technical_owner: Optional[str] = None
    default_assignment_group_id: Optional[int] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    support_hours: str = "24x7"
    environment: str = "Production"
    criticality: str = "High"
    business_service: Optional[str] = None
    categories: Optional[Any] = None
    custom_fields: Dict[str, Any] = {}
    active: bool = True
    reason: str = "Application configuration update"


class ApplicationUpdateSchema(BaseModel):
    app_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    business_owner: Optional[str] = None
    technical_owner: Optional[str] = None
    default_assignment_group_id: Optional[int] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    support_hours: Optional[str] = None
    environment: Optional[str] = None
    criticality: Optional[str] = None
    business_service: Optional[str] = None
    categories: Optional[Any] = None
    custom_fields: Optional[Dict[str, Any]] = None
    active: Optional[bool] = None
    reason: Optional[str] = "Application configuration update"


def validate_group(group_id: Optional[int], db: Session):
    if group_id and not db.query(AssignmentGroup).filter(AssignmentGroup.id == group_id, AssignmentGroup.active == True).first():
        raise HTTPException(status_code=422, detail="Default assignment group does not exist or is inactive")

@router.get("")
def list_applications(
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    apps = db.query(Application).order_by(Application.name).all()
    if x_user_id:
        current_user = get_session_user(db, x_user_id)
        scopes = get_user_scopes(current_user)
        # Project admin scoping: only see applications belonging to their projects
        if not scopes["is_global_admin"] and scopes["admin_projects"]:
            admin_projs = db.query(Project).filter(Project.name.in_(scopes["admin_projects"])).all()
            allowed_app_ids = {p.application_id for p in admin_projs if p.application_id}
            for p in admin_projs:
                for a in apps:
                    if getattr(a, "project_id", None) == p.id:
                        allowed_app_ids.add(a.id)
            apps = [a for a in apps if a.id in allowed_app_ids or a.name in scopes["admin_projects"]]
    return [app.to_dict() for app in apps]

@router.post("")
def create_application(payload: ApplicationSchema, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    scopes = get_user_scopes(current_user, db)

    # 1. Cross-project uniqueness check: check if same app_id or name exists in other projects
    clean_app_id = payload.app_id.strip()
    clean_name = payload.name.strip()
    all_apps = db.query(Application).all()
    existing_app = None
    for a in all_apps:
        if a.app_id.strip().lower() == clean_app_id.lower() or a.name.strip().lower() == clean_name.lower():
            existing_app = a
            break
    if existing_app:
        existing_proj = None
        if existing_app.project_id:
            existing_proj = db.query(Project).filter(Project.id == existing_app.project_id).first()
        if not existing_proj and existing_app.projects:
            existing_proj = existing_app.projects[0]
        proj_info = f" in project '{existing_proj.name}'" if existing_proj else ""
        if existing_app.app_id.lower() == clean_app_id.lower():
            raise HTTPException(
                status_code=409,
                detail=f"Application ID '{clean_app_id}' already exists{proj_info}. An application is specific to a project and cannot share duplicate IDs."
            )
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Application name '{clean_name}' already exists{proj_info}. An application is specific to a project and cannot share duplicate names."
            )

    # 2. Scoped project admin authorization check
    target_proj = None
    if not scopes["is_global_admin"]:
        admin_projs = scopes["admin_projects"]
        admin_projs_lower = [p.lower() for p in admin_projs]

        if payload.project_id:
            target_proj = db.query(Project).filter(Project.id == payload.project_id).first()
        elif payload.project_name:
            all_p = db.query(Project).all()
            for p in all_p:
                if p.name.strip().lower() == payload.project_name.strip().lower():
                    target_proj = p
                    break

        # Match from admin_projects if omitted
        if not target_proj and admin_projs:
            all_p = db.query(Project).all()
            for p_name in admin_projs:
                for p in all_p:
                    if p.name.strip().lower() == p_name.strip().lower():
                        target_proj = p
                        break
                if target_proj:
                    break

        # If project does not exist yet in DB, auto-bootstrap it with its L2 & L3 queues for this project admin
        if not target_proj and admin_projs:
            from backend.routes.admin_projects import setup_project_queues_and_groups
            default_pname = payload.project_name or admin_projs[0]
            clean_pid = f"PRJ-{default_pname.upper().replace(' ', '-')[:12]}"
            grp_l2, grp_l3 = setup_project_queues_and_groups(db, default_pname)
            target_proj = Project(
                project_id=clean_pid,
                name=default_pname,
                description=f"Project workspace for {default_pname}",
                default_assignment_group_id=grp_l2.id,
                l2_assignment_group_id=grp_l2.id,
                l3_assignment_group_id=grp_l3.id,
                active=True
            )
            db.add(target_proj)
            db.flush()

        if not target_proj or target_proj.name.lower() not in admin_projs_lower:
            allowed = ", ".join(admin_projs) if admin_projs else "none"
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: You only have project administrator rights for [{allowed}]. You cannot add applications to other projects."
            )
    else:
        if payload.project_id:
            target_proj = db.query(Project).filter(Project.id == payload.project_id).first()
        elif payload.project_name:
            all_p = db.query(Project).all()
            for p in all_p:
                if p.name.strip().lower() == payload.project_name.strip().lower():
                    target_proj = p
                    break

    validate_group(payload.default_assignment_group_id, db)
    values = payload.model_dump(exclude={"reason", "project_id", "project_name"})
    values["custom_fields"] = json.dumps(values.get("custom_fields") or {})
    if "categories" in values and values["categories"] is not None:
        values["categories"] = json.dumps(values["categories"]) if not isinstance(values["categories"], str) else values["categories"]
    if target_proj:
        values["project_id"] = target_proj.id
        if not values.get("default_assignment_group_id"):
            values["default_assignment_group_id"] = target_proj.l2_assignment_group_id or target_proj.default_assignment_group_id
    app = Application(**values)
    db.add(app); db.flush()

    # Link application to project and vice-versa
    if target_proj:
        app.project_id = target_proj.id
        if not target_proj.application_id:
            target_proj.application_id = app.id
            db.add(target_proj)
        db.flush()

    db.add(ConfigurationAudit(entity_type="Application", entity_id=app.app_id, user_name=current_user.full_name,
        old_configuration="{}", new_configuration=json.dumps(app.to_dict()), reason=payload.reason, effective_date=datetime.datetime.utcnow()))
    db.commit(); return app.to_dict()

@router.put("/{application_id}")
def update_application(application_id: int, payload: ApplicationUpdateSchema, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    scopes = get_user_scopes(current_user)
    if not scopes["is_global_admin"]:
        allowed_names_lower = [p.lower() for p in scopes["admin_projects"]]
        matching_proj = None
        if app.project_id:
            matching_proj = db.query(Project).filter(Project.id == app.project_id).first()
        if not matching_proj:
            matching_proj = db.query(Project).filter((Project.application_id == app.id) | (Project.name == app.name)).first()

        if not matching_proj or matching_proj.name.lower() not in allowed_names_lower:
            allowed = ", ".join(scopes["admin_projects"]) if scopes["admin_projects"] else "none"
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: You can only edit applications belonging to your project [{allowed}]."
            )

    # Uniqueness check on update: exclude current application
    clean_app_id = payload.app_id.strip() if payload.app_id else app.app_id
    clean_name = payload.name.strip() if payload.name else app.name
    if payload.app_id or payload.name:
        all_apps = db.query(Application).filter(Application.id != application_id).all()
        existing_app = None
        for a in all_apps:
            if (payload.app_id and a.app_id.strip().lower() == clean_app_id.lower()) or (payload.name and a.name.strip().lower() == clean_name.lower()):
                existing_app = a
                break
        if existing_app:
            existing_proj = None
            if existing_app.project_id:
                existing_proj = db.query(Project).filter(Project.id == existing_app.project_id).first()
            if not existing_proj and existing_app.projects:
                existing_proj = existing_app.projects[0]
            proj_info = f" in project '{existing_proj.name}'" if existing_proj else ""
            if existing_app.app_id.lower() == clean_app_id.lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"Application ID '{clean_app_id}' already exists{proj_info}. Applications are project-specific and cannot share duplicate IDs."
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"Application name '{clean_name}' already exists{proj_info}. Applications are project-specific and cannot share duplicate names."
                )

    if payload.default_assignment_group_id is not None:
        validate_group(payload.default_assignment_group_id, db)

    # Update project association if specified
    target_proj = None
    if payload.project_id is not None:
        target_proj = db.query(Project).filter(Project.id == payload.project_id).first()
    elif payload.project_name:
        all_p = db.query(Project).all()
        for p in all_p:
            if p.name.strip().lower() == payload.project_name.strip().lower():
                target_proj = p
                break

    if target_proj:
        app.project_id = target_proj.id
        if not target_proj.application_id:
            target_proj.application_id = app.id
        db.add(target_proj)

    old = app.to_dict()
    update_data = payload.model_dump(exclude_unset=True, exclude={"reason", "project_id", "project_name"})
    for field, value in update_data.items():
        if field in ("custom_fields", "categories") and value is not None and not isinstance(value, str):
            value = json.dumps(value)
        setattr(app, field, value)
    db.add(app)
    db.add(ConfigurationAudit(entity_type="Application", entity_id=app.app_id, user_name=current_user.full_name,
        old_configuration=json.dumps(old), new_configuration=json.dumps(app.to_dict()), reason=payload.reason, effective_date=datetime.datetime.utcnow()))
    db.commit()
    return app.to_dict()


@router.delete("/{application_id}")
def delete_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Delete an application.
    Allowed for:
    1. Global Administrator.
    2. Respective project support members who are part of projectname-admin for the project owning the application.
    """
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    scopes = get_user_scopes(current_user, db)
    if not scopes["is_global_admin"]:
        # Respective project support members who are part of projectname-admin can delete applications
        allowed_names_lower = [p.lower() for p in scopes["admin_projects"]]

        matching_proj = None
        if app.project_id:
            matching_proj = db.query(Project).filter(Project.id == app.project_id).first()
        if not matching_proj:
            matching_proj = db.query(Project).filter(
                (Project.application_id == app.id) | (Project.name == app.name)
            ).first()
        if not matching_proj and getattr(app, "project_name", None):
            matching_proj = db.query(Project).filter(
                func.lower(Project.name) == app.project_name.strip().lower()
            ).first()

        if not matching_proj or matching_proj.name.lower() not in allowed_names_lower:
            allowed = ", ".join(scopes["admin_projects"]) if scopes["admin_projects"] else "none"
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: You can only delete applications belonging to your project(s) [{allowed}]."
            )

    old_cfg = app.to_dict()
    app_name = app.name
    app_code = app.app_id

    # 1. Unlink any Project.application_id pointing to this app
    for p in db.query(Project).filter(Project.application_id == app.id).all():
        p.application_id = None
        db.add(p)

    # 2. Delete ProjectAssignmentMapping entries
    from backend.models import (
        ProjectAssignmentMapping, SLAPolicy, RoutingRule,
        Incident, ServiceRequest, ChangeRequest, KnowledgeArticle, ClosureTaxonomy
    )
    for m in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.application_id == app.id).all():
        db.delete(m)

    # 3. Clean up SLA policies scoped to this application
    for s in db.query(SLAPolicy).filter(SLAPolicy.application_id == app.id).all():
        db.delete(s)

    # 4. Clean up Routing rules scoped to this application
    for r in db.query(RoutingRule).filter(RoutingRule.application_id == app.id).all():
        db.delete(r)

    # 5. Clean up Taxonomy options scoped to this application
    try:
        for t in db.query(ClosureTaxonomy).filter(ClosureTaxonomy.application_id == app.id).all():
            db.delete(t)
    except Exception:
        pass

    # 6. Unlink application from tickets & KB articles
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

    # 7. Audit log
    audit = ConfigurationAudit(
        entity_type="Application",
        entity_id=app_code,
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration="{}",
        reason=f"Deleted application '{app_name}' ({app_code})",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)

    # 8. Delete application
    db.delete(app)
    db.commit()

    return {"message": f"Application '{app_name}' deleted successfully", "application_id": application_id}

