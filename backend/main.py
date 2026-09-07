import os
import time
import datetime
import logging
from typing import Optional
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import text

from backend.database import engine, SessionLocal
from backend.seed_data import init_db_and_seed

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from backend.routes import (
    auth, incidents, service_requests, changes,
    admin_projects, admin_applications, admin_groups, admin_routing, admin_slas,
    admin_calendars, admin_configuration, admin_sso, simulator, config_io, knowledge,
    dashboard, ai_chat, attachments, notifications, exports
)

app = FastAPI(
    title="GenWizard Support Portal — Accenture",
    description="Configuration-driven ITSM platform with Project -> Assignment Group -> SLA Policy Engine and AI Support Copilot",
    version="1.0.0"
)

# CORS Configuration - Production hardened with configurable origins
cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
if cors_origins_env:
    allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    allow_creds = True
else:
    allowed_origins = ["*"]
    allow_creds = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Subpath /itsm ASGI Middleware (supports hosting under /itsm seamlessly) + Cache-Control
@app.middleware("http")
async def itsm_subpath_middleware(request: Request, call_next):
    path = request.scope.get("path", "")
    if path == "/itsm":
        request.scope["path"] = "/"
    elif path.startswith("/itsm/"):
        request.scope["path"] = path[len("/itsm"):]
    response = await call_next(request)
    if path.endswith(".js") or path.endswith(".html") or path in ("", "/", "/itsm", "/itsm/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Startup DB Initialization & Seed
@app.on_event("startup")
def on_startup():
    init_db_and_seed()
    try:
        from identity_service.main import bootstrap_admin_user, bootstrap_default_groups
        bootstrap_admin_user()
        bootstrap_default_groups()
    except Exception as exc:
        logging.getLogger("backend").warning(f"Could not bootstrap admin user or default groups: {exc}")
    try:
        from scripts.bootstrap_external_im import main as sync_im_main
        sync_im_main()
    except Exception as _sync_exc:
        logging.getLogger("backend").debug(f"External IM sync skipped or deferred: {_sync_exc}")

# Include REST Routers
app.include_router(auth.router)
app.include_router(incidents.router)
app.include_router(service_requests.router)
app.include_router(changes.router)
app.include_router(admin_projects.router)
app.include_router(admin_applications.router)
app.include_router(admin_groups.router)
app.include_router(admin_routing.router)
app.include_router(admin_slas.router)
app.include_router(admin_calendars.router)
app.include_router(admin_configuration.router)
app.include_router(admin_sso.router)
app.include_router(simulator.router)
app.include_router(config_io.router)
app.include_router(knowledge.router)
app.include_router(dashboard.router)
app.include_router(ai_chat.router)
app.include_router(attachments.router)
app.include_router(notifications.router)
app.include_router(exports.router)

# Mount Identity Management Service sub-app
try:
    from identity_service.main import app as identity_app
    app.mount("/api/id", identity_app)
except Exception as _e:
    pass

# Dynamic log level & Consul routes on /api/admin/
from backend.security import require_admin
from backend.models import User
from backend.database import get_db
from sqlalchemy.orm import Session
from backend.routes.admin_configuration import LogLevelSchema, get_system_log_level, set_system_log_level
from backend.routes.config_io import get_consul_status, sync_configuration_to_consul, load_configuration_from_consul

@app.get("/api/admin/system/log-level")
def get_system_log_level_api():
    return get_system_log_level()

@app.post("/api/admin/system/log-level")
def set_system_log_level_api(payload: LogLevelSchema, admin_user: User = Depends(require_admin)):
    return set_system_log_level(payload, admin_user)

@app.get("/api/admin/configuration/consul-status")
def get_consul_status_alias():
    return get_consul_status()

@app.put("/api/admin/configuration/sync-consul")
def sync_consul_alias(db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    return sync_configuration_to_consul(db, admin_user)

@app.post("/api/admin/configuration/load-consul")
def load_consul_alias(db: Session = Depends(get_db), admin_user: User = Depends(require_admin)):
    return load_configuration_from_consul(db, admin_user)

@app.get("/api/assignment-groups")
def get_assignment_groups_alias(
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
    application_id: Optional[int] = None,
    application_name: Optional[str] = None,
    application_ids: Optional[str] = None,
    application_names: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from backend.routes.admin_groups import list_groups
    return list_groups(
        project_id=project_id,
        project_name=project_name,
        application_id=application_id,
        application_name=application_name,
        application_ids=application_ids,
        application_names=application_names,
        db=db
    )

@app.get("/api/users")
def get_users_alias(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.active == True).order_by(User.full_name.asc()).all()
    return [u.to_dict() for u in users]

# Health & Observability Endpoints
@app.get("/health")
def health_check():
    mongo_ok = False
    try:
        from backend.database import get_mongo_db
        db = get_mongo_db()
        if db is not None:
            db.command("ping")
            mongo_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if mongo_ok else "degraded",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "database": "connected (mongodb)" if mongo_ok else "disconnected",
        "mongodb": "connected" if mongo_ok else "disconnected",
        "engines": {
            "routing_engine": "operational",
            "sla_engine": "operational",
            "ai_copilot": "operational",
            "notification_engine": "operational"
        }
    }

# Legacy compat alias — frontend may call /api/config/export
@app.get("/api/config/export")
def config_export_alias():
    """Alias for /api/admin/config/export so the Create Incident modal can load its dropdowns."""
    from backend.models import Application, Project, AssignmentGroup, RoutingRule, ProjectAssignmentMapping, SLAPolicy, BusinessCalendar
    import datetime as _dt
    db_sess = SessionLocal()
    try:
        return {
            "metadata": {"platform": "GenWizard Support Portal", "version": "1.0.0",
                         "exported_at": _dt.datetime.utcnow().isoformat()},
            "applications": [a.to_dict() for a in db_sess.query(Application).all()],
            "projects": [p.to_dict() for p in db_sess.query(Project).all()],
            "assignment_groups": [g.to_dict() for g in db_sess.query(AssignmentGroup).all()],
            "routing_rules": [r.to_dict() for r in db_sess.query(RoutingRule).all()],
            "project_mappings": [m.to_dict() for m in db_sess.query(ProjectAssignmentMapping).all()],
            "sla_policies": [s.to_dict() for s in db_sess.query(SLAPolicy).all()],
            "business_calendars": [c.to_dict() for c in db_sess.query(BusinessCalendar).all()]
        }
    finally:
        db_sess.close()


@app.get("/ready")
def readiness_check():
    return {"ready": True, "timestamp": datetime.datetime.utcnow().isoformat()}

@app.get("/metrics")
def metrics_endpoint():
    db = SessionLocal()
    try:
        from backend.models import Incident, ServiceRequest, ChangeRequest, SLAInstance
        return {
            "incidents_total": db.query(Incident).count(),
            "service_requests_total": db.query(ServiceRequest).count(),
            "change_requests_total": db.query(ChangeRequest).count(),
            "sla_instances_active": db.query(SLAInstance).filter(SLAInstance.stage == "in_progress").count(),
            "sla_instances_breached": db.query(SLAInstance).filter(SLAInstance.stage == "breached").count()
        }
    finally:
        db.close()

# Static Frontend SPA
frontend_dir = os.path.abspath("frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
app.mount("/itsm/static", StaticFiles(directory=frontend_dir), name="itsm_static")

# Mount subdirectories directly so relative paths work from root or /itsm
vendor_dir = os.path.join(frontend_dir, "vendor")
css_dir = os.path.join(frontend_dir, "css")
js_dir = os.path.join(frontend_dir, "js")

if os.path.exists(vendor_dir):
    app.mount("/vendor", StaticFiles(directory=vendor_dir), name="vendor")
    app.mount("/itsm/vendor", StaticFiles(directory=vendor_dir), name="itsm_vendor")
if os.path.exists(css_dir):
    app.mount("/css", StaticFiles(directory=css_dir), name="css")
    app.mount("/itsm/css", StaticFiles(directory=css_dir), name="itsm_css")
if os.path.exists(js_dir):
    app.mount("/js", StaticFiles(directory=js_dir), name="js")
    app.mount("/itsm/js", StaticFiles(directory=js_dir), name="itsm_js")

@app.get("/favicon.ico")
def get_favicon():
    from fastapi import Response
    return Response(status_code=204)


@app.get("/api/applications")
def get_public_applications(db: Session = Depends(get_db)):
    from backend.models import Application
    return [app.to_dict() for app in db.query(Application).filter(Application.active == True).order_by(Application.name).all()]

@app.get("/api/projects")
def get_public_projects(db: Session = Depends(get_db)):
    from backend.models import Project
    return [p.to_dict() for p in db.query(Project).filter(Project.active == True).order_by(Project.name).all()]

@app.delete("/api/projects/{project_id}")
def delete_project_alias(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    from backend.routes.admin_projects import delete_project
    return delete_project(project_id=project_id, db=db, current_user=current_user)

@app.delete("/api/applications/{application_id}")
def delete_application_alias(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    from backend.routes.admin_applications import delete_application
    return delete_application(application_id=application_id, db=db, current_user=current_user)


@app.get("/")
@app.get("/itsm")
@app.get("/itsm/")
def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "GenWizard Support Portal API is running. Build frontend/index.html to view UI."}

@app.get("/sso-redirect.html")
@app.get("/sso")
@app.get("/itsm/sso-redirect.html")
@app.get("/itsm/sso")
def serve_sso_redirect():
    sso_path = os.path.join(frontend_dir, "sso-redirect.html")
    if os.path.exists(sso_path):
        return FileResponse(sso_path)
    return RedirectResponse(url="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
