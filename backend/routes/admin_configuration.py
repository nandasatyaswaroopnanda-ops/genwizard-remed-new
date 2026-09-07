import os
import logging
import requests
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ClosureTaxonomy, TicketColumnPreference, Application, User, AIConfiguration, Project
from backend.security import require_admin, get_user_scopes

router = APIRouter(prefix="/api/admin/configuration", tags=["admin-configuration"])


class TaxonomySchema(BaseModel):
    ticket_type: str = "Incident"
    category: str
    subcategory: str
    application_id: Optional[int] = None
    active: bool = True


class ColumnSchema(BaseModel):
    ticket_type: str
    column_key: str
    label: str
    enabled: bool = True
    display_order: int = 100


@router.get("/taxonomy")
def list_taxonomy(ticket_type: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(ClosureTaxonomy)
    if ticket_type:
        query = query.filter(ClosureTaxonomy.ticket_type == ticket_type)
    return [item.to_dict() for item in query.order_by(ClosureTaxonomy.ticket_type, ClosureTaxonomy.category, ClosureTaxonomy.subcategory).all()]


def _can_admin_app_taxonomy(db: Session, scopes: dict, app_id: Optional[int]) -> bool:
    if scopes.get("is_global_admin"):
        return True
    if not app_id:
        return False
    app_obj = db.query(Application).filter(Application.id == app_id).first()
    if not app_obj:
        return False
    from backend.routes.admin_projects import get_project_applications
    for p_name in scopes.get("admin_projects", []):
        p = db.query(Project).filter(Project.name.ilike(p_name.strip())).first()
        if not p:
            p = db.query(Project).filter(Project.name == p_name.strip()).first()
        if p:
            p_apps = get_project_applications(db, p)
            if any(a.id == app_obj.id for a in p_apps) or p.id == app_obj.project_id or p.application_id == app_obj.id or p.name == app_obj.name:
                return True
    return False


@router.post("/taxonomy")
def create_taxonomy(payload: TaxonomySchema, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    scopes = get_user_scopes(current_user)
    if not scopes["is_global_admin"]:
        if not payload.application_id:
            raise HTTPException(status_code=403, detail="Project administrators must specify an application belonging to their project")
        if not _can_admin_app_taxonomy(db, scopes, payload.application_id):
            allowed = ", ".join(scopes["admin_projects"]) if scopes["admin_projects"] else "none"
            raise HTTPException(status_code=403, detail=f"Access denied: You only have admin rights for project(s): [{allowed}]")
    else:
        if payload.application_id and not db.query(Application).filter(Application.id == payload.application_id).first():
            raise HTTPException(status_code=422, detail="Application not found")

    item = ClosureTaxonomy(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item.to_dict()


@router.put("/taxonomy/{item_id}")
def update_taxonomy(item_id: int, payload: TaxonomySchema, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    item = db.get(ClosureTaxonomy, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Closure option not found")

    scopes = get_user_scopes(current_user)
    if not scopes["is_global_admin"]:
        app_id = payload.application_id or item.application_id
        if not app_id:
            raise HTTPException(status_code=403, detail="Access denied: Global taxonomy can only be modified by platform administrators")
        if not _can_admin_app_taxonomy(db, scopes, app_id):
            raise HTTPException(status_code=403, detail="Access denied: You do not administer the project associated with this category")

    for name, value in payload.model_dump().items():
        setattr(item, name, value)
    db.commit(); db.refresh(item)
    return item.to_dict()


@router.delete("/taxonomy/{item_id}")
def delete_taxonomy(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    item = db.get(ClosureTaxonomy, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Closure option not found")
    scopes = get_user_scopes(current_user)
    if not scopes["is_global_admin"]:
        if not item.application_id:
            raise HTTPException(status_code=403, detail="Only global platform administrators can delete global categories")
        if not _can_admin_app_taxonomy(db, scopes, item.application_id):
            raise HTTPException(status_code=403, detail="Access denied: You can only delete categories belonging to your project")
    db.delete(item); db.commit()
    return {"message": "Closure option removed"}


@router.get("/columns")
def list_columns(ticket_type: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(TicketColumnPreference)
    if ticket_type:
        query = query.filter(TicketColumnPreference.ticket_type == ticket_type)
    return [item.to_dict() for item in query.order_by(TicketColumnPreference.ticket_type, TicketColumnPreference.display_order).all()]


@router.post("/columns")
def create_column(payload: ColumnSchema, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    existing = db.query(TicketColumnPreference).filter(
        TicketColumnPreference.ticket_type == payload.ticket_type,
        TicketColumnPreference.column_key == payload.column_key
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This column is already configured for the selected ticket type")
    item = TicketColumnPreference(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item.to_dict()


@router.put("/columns/{item_id}")
def update_column(item_id: int, payload: ColumnSchema, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = db.get(TicketColumnPreference, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Column configuration not found")
    for name, value in payload.model_dump().items():
        setattr(item, name, value)
    db.commit(); db.refresh(item)
    return item.to_dict()


@router.delete("/columns/{item_id}")
def delete_column(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = db.get(TicketColumnPreference, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Column configuration not found")
    db.delete(item); db.commit()
    return {"message": "Column configuration removed"}


# ── KM Integration & Consul Configuration ──

class KMConfigSchema(BaseModel):
    km_base_url: str
    api_endpoint: Optional[str] = "/api/chat/completions"
    username: Optional[str] = None
    password: Optional[str] = None
    km_index: Optional[str] = "itsm-kb"
    auth_token: Optional[str] = None
    sync_to_consul: bool = True


@router.get("/km")
def get_km_configuration(db: Session = Depends(get_db)):
    """Retrieve external Knowledge Management integration settings."""
    cfg = db.query(AIConfiguration).first()
    if not cfg:
        cfg = AIConfiguration()
        db.add(cfg); db.commit(); db.refresh(cfg)
    data = cfg.to_dict()
    # Mask username and password for display / UI security
    data["username"] = "••••••••" if cfg.username else ""
    data["password"] = "••••••••" if cfg.password else ""
    return data


@router.put("/km")
def update_km_configuration(
    payload: KMConfigSchema,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    """Update Knowledge Management settings and sync to Consul if configured."""
    cfg = db.query(AIConfiguration).first()
    if not cfg:
        cfg = AIConfiguration()
        db.add(cfg)
    
    cfg.km_base_url = payload.km_base_url
    cfg.api_endpoint = payload.api_endpoint or "/api/chat/completions"
    if payload.username is not None and payload.username != "••••••••":
        cfg.username = payload.username
    if payload.password is not None and payload.password != "••••••••":
        cfg.password = payload.password
    if payload.km_index is not None:
        cfg.km_index = payload.km_index
    if payload.auth_token is not None and payload.auth_token != "••••••••":
        cfg.auth_token = payload.auth_token
    
    db.commit()
    db.refresh(cfg)

    # Sync to Consul KV if requested and configured
    consul_synced = False
    if payload.sync_to_consul:
        address = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
        token = os.getenv("CONSUL_HTTP_TOKEN", "")
        if address:
            headers = {"X-Consul-Token": token} if token else {}
            try:
                import json
                km_consul_data = {
                    "base_url": cfg.km_base_url,
                    "endpoint": cfg.api_endpoint,
                    "username": cfg.username or "",
                    "password": cfg.password or "",
                    "index": cfg.km_index or "itsm-kb",
                    "auth_token": cfg.auth_token or ""
                }
                requests.put(
                    f"{address}/v1/kv/nexus-itsm/km/config",
                    headers=headers,
                    data=json.dumps(km_consul_data),
                    timeout=3
                )
                consul_synced = True
            except Exception as e:
                logging.getLogger("admin_configuration").warning(f"Failed to sync KM to Consul: {e}")

    result = cfg.to_dict()
    result["consul_synced"] = consul_synced
    result["username"] = "••••••••" if cfg.username else ""
    result["password"] = "••••••••" if cfg.password else ""
    return result


# ── Dynamic System Log Level Management ──

class LogLevelSchema(BaseModel):
    level: str  # DEBUG, INFO, WARNING, ERROR


@router.get("/system/log-level")
def get_system_log_level():
    """Returns current active log level across platform engines."""
    root_logger = logging.getLogger()
    level_name = logging.getLevelName(root_logger.getEffectiveLevel())
    return {
        "log_level": level_name,
        "platform": "nexus-itsm-backend",
        "supported_levels": ["DEBUG", "INFO", "WARNING", "ERROR"]
    }


@router.post("/system/log-level")
def set_system_log_level(payload: LogLevelSchema, _: User = Depends(require_admin)):
    """Dynamically switch logger level in runtime without container restart."""
    new_level = payload.level.upper()
    if new_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
        raise HTTPException(status_code=400, detail=f"Invalid log level: {new_level}")
    
    level_num = getattr(logging, new_level)
    logging.getLogger().setLevel(level_num)
    for name in ["ai_copilot", "routing_engine", "sla_engine", "workflow_engine", "uvicorn", "fastapi"]:
        logging.getLogger(name).setLevel(level_num)
    
    logging.getLogger("system").info(f"Platform log level changed to {new_level}")
    return {
        "message": f"Log level successfully changed to {new_level}",
        "log_level": new_level
    }

