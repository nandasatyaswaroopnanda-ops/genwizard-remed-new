"""Nexus ITSM — Enterprise Identity Management Service."""
import os
import re
import json
import logging
import datetime
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Header, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import engine, SessionLocal, get_db, migrate_legacy_schema, Base
from backend.models import (
    User, CustomGroup, UserCustomGroup, ADGroupMapping, SSOProviderConfig,
    AssignmentGroup, GroupMember
)
from identity_service.security import (
    hash_password, verify_password, create_access_token, decode_access_token,
    ALL_PERMISSIONS, ROLE_PERMISSIONS, get_role_permissions
)

# Logger setup
logger = logging.getLogger("identity_service")
current_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, current_log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

app = FastAPI(
    title="Nexus ITSM — Enterprise Identity Management Service",
    description="Dedicated microservice for Local Authentication, Roles & Custom Groups, Active Directory Mapping, and B2B/B2C SSO with SAML 2.0 Metadata.",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup & DB Bootstrapping ──

@app.on_event("startup")
def on_startup():
    migrate_legacy_schema()
    Base.metadata.create_all(bind=engine)
    bootstrap_admin_user()
    bootstrap_default_groups()

def bootstrap_default_groups():
    """Ensure the core groups with attached permissions and default AD group / DL mappings exist."""
    db = SessionLocal()
    try:
        # 1. Bootstrap core permission-bearing groups
        core_groups = [
            ("IM_SAML", "Default SSO End-User Group for creating tickets, viewing own tickets, updating comments/worknotes, and viewing applications/projects.", [
                "ticket_create", "ticket_read_own", "ticket_update", "applications_read", "projects_read",
                "tickets:create", "tickets:read_own", "tickets:update", "applications:read", "projects:read"
            ]),
            ("itsm_admin", "ITSM Platform Administrator Group with full management and operational permissions.", [
                "admin_all", "ticket_create", "ticket_read", "ticket_update", "ticket_delete", "ticket_assign", "ticket_resolve", "ticket_close", "admin_routing", "admin_slas", "admin_config", "users_manage", "applications_read", "projects_read",
                "admin:all", "tickets:create", "tickets:read", "tickets:update", "tickets:delete", "tickets:assign", "tickets:resolve", "tickets:close", "routing:manage", "slas:manage", "config:manage", "users:manage"
            ]),
            ("itsm_user", "ITSM Support Fulfiller Group with queue assignment and ticket resolution permissions.", [
                "ticket_create", "ticket_read", "ticket_update", "ticket_assign", "ticket_resolve", "applications_read", "projects_read",
                "tickets:create", "tickets:read", "tickets:update", "tickets:assign", "tickets:resolve"
            ]),
            ("itsm_read", "ITSM Read-Only Group with read access to tickets, applications, and projects.", [
                "ticket_read", "applications_read", "projects_read",
                "tickets:read"
            ]),
        ]
        group_map = {}
        for g_name, g_desc, g_perms in core_groups:
            grp = db.query(CustomGroup).filter(CustomGroup.name == g_name).first()
            if not grp:
                logger.info("Bootstrapping group with permissions: %s", g_name)
                grp = CustomGroup(
                    name=g_name,
                    description=g_desc,
                    permissions=json.dumps(g_perms),
                    active=True
                )
                db.add(grp)
                db.commit()
                db.refresh(grp)
            else:
                # Upgrade existing permissions to clean underscore notation
                grp.permissions = json.dumps(g_perms)
                db.commit()
            group_map[g_name] = grp

        # Ensure 'itsm_admin' group is attached to the admin user
        admin_grp = group_map.get("itsm_admin")
        if admin_grp:
            admin_username = os.getenv("ITSM_BOOTSTRAP_ADMIN_USERNAME", "admin").strip()
            admin_user = db.query(User).filter(User.username == admin_username).first()
            if admin_user:
                user_grp = db.query(UserCustomGroup).filter(
                    UserCustomGroup.user_id == admin_user.id,
                    UserCustomGroup.custom_group_id == admin_grp.id
                ).first()
                if not user_grp:
                    db.add(UserCustomGroup(user_id=admin_user.id, custom_group_id=admin_grp.id))
                    db.commit()
                    logger.info("Attached 'itsm_admin' group to existing admin user '%s'", admin_username)
    except Exception as e:
        logger.error(f"Error during default group bootstrap: {e}")
        db.rollback()
    finally:
        db.close()

def bootstrap_admin_user():
    """Ensure the fixed 'admin' user is bootstrapped with generated or configured credentials."""
    db = SessionLocal()
    try:
        admin_username = os.getenv("ITSM_BOOTSTRAP_ADMIN_USERNAME", "admin").strip()
        admin_user = db.query(User).filter(User.username == admin_username).first()
        bootstrap_pass = os.getenv("ITSM_BOOTSTRAP_ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "")).strip()
        consul_addr = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
        if consul_addr and not bootstrap_pass:
            try:
                import requests
                consul_token = os.getenv("CONSUL_HTTP_TOKEN", "")
                hdrs = {"X-Consul-Token": consul_token} if consul_token else {}
                candidate_keys = [
                    "configuration/aaam-atr-v3/identity-management/admin.password",
                    os.getenv("CONSUL_ADMIN_KEY", "").strip(),
                    "nexus-itsm/bootstrap/itsm-admin",
                    "nexus-itsm/admin",
                    "im/admin",
                    "identity/admin",
                    "bootstrap/itsm-admin"
                ]
                for key in candidate_keys:
                    if not key:
                        continue
                    r = requests.get(f"{consul_addr}/v1/kv/{key}", params={"raw": ""}, headers=hdrs, timeout=3)
                    if r.status_code == 200:
                        cred_data = None
                        try:
                            cred_data = r.json()
                        except Exception:
                            cred_data = r.text.strip()
                        if isinstance(cred_data, dict):
                            bootstrap_pass = cred_data.get("password") or cred_data.get("pass") or cred_data.get("admin_password") or ""
                            admin_username = cred_data.get("username") or cred_data.get("user") or admin_username
                        elif isinstance(cred_data, str) and cred_data:
                            bootstrap_pass = cred_data
                        if bootstrap_pass:
                            logger.info("Resolved admin password from Consul key: %s", key)
                            break
            except Exception as e:
                logger.debug("Could not resolve admin credentials from Consul: %s", e)
        if not bootstrap_pass:
            bootstrap_pass = "Admin@Secure2026!"
        
        if not admin_user:
            logger.info("Bootstrapping fixed administrator account: admin")
            admin_user = User(
                employee_id="EMP-ADMIN-001",
                username="admin",
                full_name="Platform Administrator",
                first_name="Platform",
                last_name="Administrator",
                email="admin@company.local",
                role="itsm_admin",
                password_hash=hash_password(bootstrap_pass),
                is_local=True,
                active=True
            )
            db.add(admin_user)
            db.commit()
            logger.info("Administrator 'admin' created successfully.")
        else:
            # If user exists but role or password need alignment
            if not admin_user.password_hash or not verify_password(bootstrap_pass, admin_user.password_hash):
                admin_user.password_hash = hash_password(bootstrap_pass)
            if admin_user.role not in ["itsm_admin", "administrator"]:
                admin_user.role = "itsm_admin"
            admin_user.is_local = True
            db.commit()
            logger.info("Administrator 'admin' credentials validated.")

        # Ensure itsm_admin group is attached
        admin_grp = db.query(CustomGroup).filter(CustomGroup.name == "itsm_admin").first()
        if admin_grp and admin_user:
            user_grp = db.query(UserCustomGroup).filter(
                UserCustomGroup.user_id == admin_user.id,
                UserCustomGroup.custom_group_id == admin_grp.id
            ).first()
            if not user_grp:
                db.add(UserCustomGroup(user_id=admin_user.id, custom_group_id=admin_grp.id))
                db.commit()
                logger.info("Attached 'itsm_admin' group to administrator '%s'.", admin_user.username)
    except Exception as e:
        logger.error(f"Error during administrator bootstrap: {e}")
        db.rollback()
    finally:
        db.close()


# ── Schemas ──

class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreateRequest(BaseModel):
    username: str
    password: str
    email: str
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = "itsm_user" # itsm_admin, itsm_user, itsm_read
    department: Optional[str] = "IT"
    custom_groups: Optional[List[str]] = []

class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    password: Optional[str] = None # Reset password if provided
    active: Optional[bool] = None
    custom_groups: Optional[List[str]] = None

class CustomGroupRequest(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str]

class ADMappingRequest(BaseModel):
    ad_group_name: str
    target_role: Optional[str] = None
    custom_group_id: Optional[int] = None
    description: Optional[str] = None

class ADResolveRequest(BaseModel):
    ad_groups: List[str]

class SSOConfigRequest(BaseModel):
    name: str
    provider_type: str = "saml" # saml, oidc
    b2b_or_b2c: str = "b2b" # b2b, b2c
    entity_id: Optional[str] = None
    sso_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    discovery_url: Optional[str] = None
    metadata_xml: Optional[str] = None
    certificate: Optional[str] = None
    eso_app_id: Optional[str] = None
    claims_email_path: Optional[str] = "email"
    claims_group_path: Optional[str] = "groups"
    claims_name_path: Optional[str] = "name"
    default_role: Optional[str] = "itsm_user"
    auto_provision: Optional[bool] = True
    role_mapping_rules: Optional[Dict[str, str]] = {}
    custom_group_mapping_rules: Optional[Dict[str, List[str]]] = {}
    assignment_group_mapping_rules: Optional[Dict[str, List[str]]] = {}
    enabled: bool = True

class ESORegisterRequest(BaseModel):
    eso_app_id: str
    name: Optional[str] = None
    provider_type: str = "saml" # saml, oidc
    b2b_or_b2c: str = "b2b" # b2b, b2c
    idp_sso_url: Optional[str] = None
    idp_entity_id: Optional[str] = None
    idp_certificate: Optional[str] = None
    discovery_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    claims_email_path: Optional[str] = "email"
    claims_group_path: Optional[str] = "groups"
    claims_name_path: Optional[str] = "name"
    default_role: Optional[str] = "itsm_user"
    auto_provision: Optional[bool] = True
    role_mapping_rules: Optional[Dict[str, str]] = {}
    custom_group_mapping_rules: Optional[Dict[str, List[str]]] = {}
    assignment_group_mapping_rules: Optional[Dict[str, List[str]]] = {}

class SSOLoginProcessRequest(BaseModel):
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    eso_app_id: Optional[str] = None
    claims: Dict[str, Any]
    redirect_uri: Optional[str] = None

class ClaimMappingTestRequest(BaseModel):
    claims: Dict[str, Any]
    provider_id: Optional[int] = None
    claims_email_path: Optional[str] = None
    claims_group_path: Optional[str] = None
    claims_name_path: Optional[str] = None
    default_role: Optional[str] = "itsm_user"
    role_mapping_rules: Optional[Dict[str, str]] = {}
    custom_group_mapping_rules: Optional[Dict[str, List[str]]] = {}
    assignment_group_mapping_rules: Optional[Dict[str, List[str]]] = {}

class LogLevelRequest(BaseModel):
    level: str # DEBUG, INFO, WARNING, ERROR


# ── Health & Observability ──

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "identity-management",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "log_level": logging.getLevelName(logger.getEffectiveLevel())
    }

@app.get("/ready")
def readiness_check():
    return {"ready": True, "service": "identity-management"}

@app.get("/system/log-level")
def get_log_level():
    level_name = logging.getLevelName(logger.getEffectiveLevel())
    return {"service": "identity-management", "log_level": level_name}

@app.post("/system/log-level")
def set_log_level(payload: LogLevelRequest):
    new_level = payload.level.upper()
    if new_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
        raise HTTPException(status_code=400, detail=f"Invalid log level: {new_level}")
    level_num = getattr(logging, new_level)
    logger.setLevel(level_num)
    logging.getLogger().setLevel(level_num)
    logger.info(f"Identity Service logger level updated to: {new_level}")
    return {"service": "identity-management", "log_level": new_level, "message": f"Log level changed to {new_level}"}


# ── Local User Authentication & Authorization ──

def get_current_identity_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    """Validate bearer token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token is required")
    token = authorization[len("Bearer "):].strip()
    try:
        claims = decode_access_token(token)
        user_id = int(claims.get("sub", 0))
        user = db.query(User).filter(User.id == user_id, User.active == True).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found or deactivated")
        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")

def require_identity_admin(user: User = Depends(get_current_identity_user)):
    if user.role not in ["itsm_admin", "administrator"]:
        raise HTTPException(status_code=403, detail="Administrator privileges required")
    return user


@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a local user (including fixed 'admin') and return a JWT access token."""
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    if user.username == "admin" and not user.password_hash:
        bootstrap_admin_user()
        db.refresh(user)

    if not verify_password(payload.password, user.password_hash):
        logger.warning(f"Failed login attempt for user: {payload.username}")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Gather user's custom group names and additional permissions
    custom_groups = []
    custom_permissions = set()
    for uc in user.custom_groups:
        if uc.custom_group and uc.custom_group.active:
            custom_groups.append(uc.custom_group.name)
            try:
                perms = json.loads(uc.custom_group.permissions or "[]")
                custom_permissions.update(perms)
            except Exception:
                pass

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        custom_groups=custom_groups,
        permissions=list(custom_permissions)
    )

    all_perms = set(get_role_permissions(user.role)) | custom_permissions

    is_end_user = (user.role in ["itsm_read", "employee"]) or ("IM_SAML" in custom_groups and user.role not in ["itsm_admin", "administrator", "itsm_user", "support_member", "group_manager"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "is_end_user": is_end_user,
            "custom_groups": custom_groups,
            "permissions": sorted(list(all_perms))
        }
    }


@app.get("/auth/me")
def get_current_user_profile(user: User = Depends(get_current_identity_user)):
    custom_groups = [uc.custom_group.name for uc in user.custom_groups if uc.custom_group and uc.custom_group.active]
    custom_perms = set()
    for uc in user.custom_groups:
        if uc.custom_group and uc.custom_group.active:
            try:
                custom_perms.update(json.loads(uc.custom_group.permissions or "[]"))
            except Exception:
                pass
    effective_permissions = sorted(list(set(get_role_permissions(user.role)) | custom_perms))
    is_end_user = (user.role in ["itsm_read", "employee"]) or ("IM_SAML" in custom_groups and user.role not in ["itsm_admin", "administrator", "itsm_user", "support_member", "group_manager"])
    
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "is_local": user.is_local,
        "is_end_user": is_end_user,
        "custom_groups": custom_groups,
        "permissions": effective_permissions
    }


# ── Local User Management ──

@app.get("/users")
def list_local_users(db: Session = Depends(get_db)):
    """List all users."""
    users = db.query(User).order_by(User.id).all()
    return [u.to_dict() for u in users]


@app.post("/users")
def create_local_user(payload: UserCreateRequest, db: Session = Depends(get_db)):
    """Create a new local user."""
    existing = db.query(User).filter(
        or_(User.username == payload.username.strip(), User.email == payload.email.strip().lower())
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username or email already exists")

    next_id = (db.query(User).count() + 1)
    emp_id = f"EMP-{next_id:04d}"

    user = User(
        employee_id=emp_id,
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        department=payload.department,
        is_local=True,
        active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Attach custom groups
    if payload.custom_groups:
        for grp_name in payload.custom_groups:
            grp = db.query(CustomGroup).filter(CustomGroup.name == grp_name.strip()).first()
            if grp:
                db.add(UserCustomGroup(user_id=user.id, custom_group_id=grp.id))
        db.commit()
        db.refresh(user)

    return user.to_dict()


@app.get("/users/{user_id}")
def get_local_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()


@app.put("/users/{user_id}")
def update_local_user(user_id: int, payload: UserUpdateRequest, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email.strip().lower()
    if payload.role is not None:
        user.role = payload.role
    if payload.department is not None:
        user.department = payload.department
    if payload.active is not None:
        user.active = payload.active
    if payload.password:
        user.password_hash = hash_password(payload.password)

    if payload.custom_groups is not None:
        # Update group memberships
        db.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id).delete()
        for grp_name in payload.custom_groups:
            grp = db.query(CustomGroup).filter(CustomGroup.name == grp_name.strip()).first()
            if grp:
                db.add(UserCustomGroup(user_id=user.id, custom_group_id=grp.id))

    db.commit()
    db.refresh(user)
    return user.to_dict()


@app.delete("/users/{user_id}")
def delete_local_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete default admin account")
    user.active = False
    db.commit()
    return {"message": f"User {user.username} deactivated successfully"}


# ── Roles & Permissions Catalog ──

@app.get("/roles")
def list_system_roles():
    """Return standard system roles and their permission assignments."""
    return [
        {
            "role": "itsm_admin",
            "name": "ITSM Administrator",
            "description": "Full administrative permissions across all platform modules, configuration, and security.",
            "permissions": ROLE_PERMISSIONS["itsm_admin"]
        },
        {
            "role": "itsm_user",
            "name": "ITSM Service Agent / User",
            "description": "Standard support rights: manage and fulfill incidents, service requests, and work notes.",
            "permissions": ROLE_PERMISSIONS["itsm_user"]
        },
        {
            "role": "itsm_read",
            "name": "ITSM Read-Only",
            "description": "Read-only access to view tickets, schedules, and knowledge base.",
            "permissions": ROLE_PERMISSIONS["itsm_read"]
        }
    ]


@app.get("/permissions")
def list_permissions():
    """Return catalog of all granular permissions available in the system."""
    return ALL_PERMISSIONS


# ── Custom Groups Management ──

@app.get("/groups")
def list_custom_groups(db: Session = Depends(get_db)):
    groups = db.query(CustomGroup).filter(CustomGroup.active == True).all()
    return [g.to_dict() for g in groups]


@app.post("/groups")
def create_custom_group(payload: CustomGroupRequest, db: Session = Depends(get_db)):
    existing = db.query(CustomGroup).filter(CustomGroup.name == payload.name.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Group with this name already exists")
    
    group = CustomGroup(
        name=payload.name.strip(),
        description=payload.description,
        permissions=json.dumps(payload.permissions),
        active=True
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group.to_dict()


@app.get("/groups/{group_id}")
def get_custom_group(group_id: int, db: Session = Depends(get_db)):
    group = db.get(CustomGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group.to_dict()


@app.put("/groups/{group_id}")
def update_custom_group(group_id: int, payload: CustomGroupRequest, db: Session = Depends(get_db)):
    group = db.get(CustomGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    group.name = payload.name.strip()
    group.description = payload.description
    group.permissions = json.dumps(payload.permissions)
    db.commit()
    db.refresh(group)
    return group.to_dict()


@app.delete("/groups/{group_id}")
def delete_custom_group(group_id: int, db: Session = Depends(get_db)):
    group = db.get(CustomGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    group.active = False
    db.commit()
    return {"message": f"Custom group {group.name} deactivated"}


# ── Active Directory (AD) / LDAP Group Mapping ──

@app.get("/ad-mappings")
def list_ad_mappings(db: Session = Depends(get_db)):
    mappings = db.query(ADGroupMapping).filter(ADGroupMapping.active == True).all()
    return [m.to_dict() for m in mappings]


@app.post("/ad-mappings")
def create_ad_mapping(payload: ADMappingRequest, db: Session = Depends(get_db)):
    existing = db.query(ADGroupMapping).filter(ADGroupMapping.ad_group_name == payload.ad_group_name.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Mapping for this AD group already exists")
    
    mapping = ADGroupMapping(
        ad_group_name=payload.ad_group_name.strip(),
        target_role=payload.target_role,
        custom_group_id=payload.custom_group_id,
        description=payload.description,
        active=True
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping.to_dict()


@app.put("/ad-mappings/{mapping_id}")
def update_ad_mapping(mapping_id: int, payload: ADMappingRequest, db: Session = Depends(get_db)):
    mapping = db.get(ADGroupMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    mapping.ad_group_name = payload.ad_group_name.strip()
    mapping.target_role = payload.target_role
    mapping.custom_group_id = payload.custom_group_id
    mapping.description = payload.description
    db.commit()
    db.refresh(mapping)
    return mapping.to_dict()


@app.delete("/ad-mappings/{mapping_id}")
def delete_ad_mapping(mapping_id: int, db: Session = Depends(get_db)):
    mapping = db.get(ADGroupMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    mapping.active = False
    db.commit()
    return {"message": "AD group mapping deleted"}


@app.post("/ad-resolve")
def resolve_ad_groups(payload: ADResolveRequest, db: Session = Depends(get_db)):
    """
    Given a list of AD group claims from an external SSO token or LDAP directory,
    resolves the highest effective ITSM role, custom groups, and combined permissions.
    """
    active_mappings = db.query(ADGroupMapping).filter(ADGroupMapping.active == True).all()
    matched_roles = set()
    matched_custom_groups = []
    matched_permissions = set()
    matched_ad_groups = set()

    for mapping in active_mappings:
        for ad_group in payload.ad_groups:
            ad_clean = ad_group.lower().strip()
            map_name = mapping.ad_group_name.lower().strip()
            if map_name == ad_clean or f"cn={map_name}," in ad_clean or ad_clean.endswith(f"cn={map_name}") or f"cn={map_name}" == ad_clean or map_name in ad_clean:
                matched_ad_groups.add(ad_group)
                if mapping.target_role:
                    matched_roles.add(mapping.target_role)
                if mapping.custom_group:
                    matched_custom_groups.append(mapping.custom_group.name)
                    try:
                        perms = json.loads(mapping.custom_group.permissions or "[]")
                        matched_permissions.update(perms)
                    except Exception:
                        pass

    # Role precedence: itsm_admin > itsm_user > itsm_read
    effective_role = "itsm_read"
    if "itsm_admin" in matched_roles or "administrator" in matched_roles:
        effective_role = "itsm_admin"
    elif "itsm_user" in matched_roles or "support_member" in matched_roles or "group_manager" in matched_roles:
        effective_role = "itsm_user"

    final_permissions = sorted(list(set(get_role_permissions(effective_role)) | matched_permissions))

    return {
        "matched_ad_groups": list(matched_ad_groups),
        "effective_role": effective_role,
        "custom_groups": list(set(matched_custom_groups)),
        "permissions": final_permissions
    }


# ── B2B & B2C Enterprise SSO & SAML Metadata ──

@app.get("/sso/config")
def list_sso_configs(db: Session = Depends(get_db)):
    configs = db.query(SSOProviderConfig).filter(SSOProviderConfig.enabled == True).all()
    return [c.to_dict() for c in configs]


@app.get("/sso/providers")
def list_public_sso_providers(db: Session = Depends(get_db)):
    """Public endpoint listing active SSO providers for login selection."""
    configs = db.query(SSOProviderConfig).filter(SSOProviderConfig.enabled == True).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "provider_type": c.provider_type,
            "b2b_or_b2c": c.b2b_or_b2c,
            "eso_app_id": c.eso_app_id,
            "sso_url": c.sso_url,
            "discovery_url": c.discovery_url,
            "has_metadata": bool(c.metadata_xml),
            "default_role": c.default_role
        }
        for c in configs
    ]


@app.post("/sso/config")
def save_sso_config(payload: SSOConfigRequest, db: Session = Depends(get_db)):
    data = payload.model_dump()
    if isinstance(data.get("role_mapping_rules"), dict):
        data["role_mapping_rules"] = json.dumps(data["role_mapping_rules"])
    if isinstance(data.get("custom_group_mapping_rules"), dict):
        data["custom_group_mapping_rules"] = json.dumps(data["custom_group_mapping_rules"])
    if isinstance(data.get("assignment_group_mapping_rules"), dict):
        data["assignment_group_mapping_rules"] = json.dumps(data["assignment_group_mapping_rules"])

    existing = db.query(SSOProviderConfig).filter(SSOProviderConfig.name == payload.name.strip()).first()
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing.to_dict()
    
    cfg = SSOProviderConfig(**data)
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg.to_dict()


def _get_nested_val(data: Any, path: str) -> Any:
    if not path or not isinstance(data, dict):
        return None
    parts = path.split(".")
    cur = data
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def extract_and_map_claims(claims: Dict[str, Any], provider: Optional[SSOProviderConfig], db: Session, dry_run: bool = False) -> Dict[str, Any]:
    """
    Extracts identity claims (email, full name, groups) from Keycloak, Azure AD, B2B/B2C, or SAML/ESO assertions.
    Maps enterprise groups to:
    1. Platform Roles: itsm_admin, itsm_user, itsm_read
    2. Custom Groups: CustomGroup records and permissions
    3. Assignment Groups: AssignmentGroup records present in the app for immediate ticket routing.
    Automatically provisions/updates user and issues JWT.
    """
    # 1. Email Extraction
    email = None
    email_path = provider.claims_email_path if provider else "email"
    if email_path:
        val = _get_nested_val(claims, email_path)
        if isinstance(val, str) and "@" in val:
            email = val.strip()
        elif isinstance(val, list) and len(val) > 0 and isinstance(val[0], str) and "@" in val[0]:
            email = val[0].strip()

    if not email:
        candidate_email_keys = [
            "email", "mail", "upn", "preferred_username",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
            "userPrincipalName", "sub"
        ]
        for k in candidate_email_keys:
            v = _get_nested_val(claims, k) or claims.get(k)
            if isinstance(v, str) and "@" in v:
                email = v.strip()
                break
            elif isinstance(v, list) and v and isinstance(v[0], str) and "@" in v[0]:
                email = v[0].strip()
                break

    if not email:
        email = "sso-user@enterprise.local"

    # 2. Name Extraction
    full_name = None
    name_path = provider.claims_name_path if provider else "name"
    if name_path:
        val = _get_nested_val(claims, name_path)
        if isinstance(val, str) and val.strip():
            full_name = val.strip()

    if not full_name:
        candidate_name_keys = [
            "name", "displayName",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
            "cn", "fullName"
        ]
        for k in candidate_name_keys:
            v = _get_nested_val(claims, k) or claims.get(k)
            if isinstance(v, str) and v.strip():
                full_name = v.strip()
                break

    if not full_name:
        fn = claims.get("given_name") or claims.get("firstName") or ""
        ln = claims.get("family_name") or claims.get("lastName") or ""
        if fn or ln:
            full_name = f"{fn} {ln}".strip()

    if not full_name:
        prefix = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        full_name = prefix or "Enterprise SSO User"

    # 3. Group Claims Extraction
    raw_groups = []
    grp_path = provider.claims_group_path if provider else "groups"
    if grp_path:
        gval = _get_nested_val(claims, grp_path)
        if isinstance(gval, list):
            raw_groups.extend(gval)
        elif isinstance(gval, str):
            raw_groups.extend([x.strip() for x in gval.split(",") if x.strip()])

    # Keycloak realm_access.roles
    realm_roles = _get_nested_val(claims, "realm_access.roles")
    if isinstance(realm_roles, list):
        raw_groups.extend(realm_roles)

    # Keycloak resource_access.<client>.roles
    res_access = _get_nested_val(claims, "resource_access")
    if isinstance(res_access, dict):
        for client_data in res_access.values():
            if isinstance(client_data, dict) and "roles" in client_data and isinstance(client_data["roles"], list):
                raw_groups.extend(client_data["roles"])

    # Azure AD / SAML / Standard group attributes
    for k in [
        "groups", "roles", "memberOf",
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
        "http://schemas.xmlsoap.org/claims/Group"
    ]:
        val = claims.get(k)
        if isinstance(val, list):
            raw_groups.extend(val)
        elif isinstance(val, str) and val not in raw_groups:
            raw_groups.extend([x.strip() for x in val.split(",") if x.strip()])

    # Normalize groups
    extracted_groups = set()
    for g in raw_groups:
        if not isinstance(g, str):
            continue
        g_str = g.strip()
        if not g_str:
            continue
        extracted_groups.add(g_str)
        if "cn=" in g_str.lower():
            cn_match = re.search(r'cn=([^,]+)', g_str, re.IGNORECASE)
            if cn_match:
                extracted_groups.add(cn_match.group(1).strip())

    # 4. Resolve Platform Role & Support vs End-User Status
    # AD Groups and DLs configured in Identity Management (IM)
    db_ad_mappings = db.query(ADGroupMapping).filter(ADGroupMapping.active == True).all()
    matched_ad_roles = set()
    matched_ad_group_names = set()
    matched_ad_custom_group_names = set()

    for adm in db_ad_mappings:
        adm_name = adm.ad_group_name.lower().strip()
        for eg in extracted_groups:
            eg_lower = eg.lower().strip()
            # Match exact, substring, or CN=...
            if (adm_name == eg_lower or
                adm_name in eg_lower or
                f"cn={adm_name}" in eg_lower or
                f"cn={adm_name}," in eg_lower or
                eg_lower.endswith(f"cn={adm_name}")):
                matched_ad_group_names.add(adm.ad_group_name)
                if adm.target_role:
                    matched_ad_roles.add(adm.target_role)
                if adm.custom_group and adm.custom_group.active:
                    matched_ad_custom_group_names.add(adm.custom_group.name)

    # Check provider explicit role rules if any
    role_rules = {}
    if provider and provider.role_mapping_rules:
        try:
            role_rules = json.loads(provider.role_mapping_rules) if isinstance(provider.role_mapping_rules, str) else provider.role_mapping_rules
        except Exception:
            role_rules = {}

    matched_provider_roles = set()
    for rule_grp, target_r in role_rules.items():
        for eg in extracted_groups:
            if rule_grp.lower() == eg.lower() or rule_grp.lower() in eg.lower():
                matched_provider_roles.add(target_r)

    all_matched_roles = matched_ad_roles | matched_provider_roles
    has_im_support_match = bool(all_matched_roles)

    if has_im_support_match:
        # Role is assigned based on the role attached to the matched AD group / DL in IM
        if "itsm_admin" in all_matched_roles or "administrator" in all_matched_roles:
            effective_role = "itsm_admin"
        elif "itsm_user" in all_matched_roles or "support_member" in all_matched_roles or "group_manager" in all_matched_roles:
            effective_role = "itsm_user"
        else:
            effective_role = "itsm_read"
        is_end_user = (effective_role not in ["itsm_admin", "administrator", "itsm_user", "support_member", "group_manager"])
    else:
        # User's groups are not in IM -> default to end-user with IM_SAML
        effective_role = "itsm_read"
        is_end_user = True

    # 5. Resolve Custom Groups (Always attach default 'IM_SAML' for SSO users)
    matched_cg_names = set(matched_ad_custom_group_names)
    # Always include IM_SAML
    matched_cg_names.add("IM_SAML")

    custom_rules = {}
    if provider and provider.custom_group_mapping_rules:
        try:
            custom_rules = json.loads(provider.custom_group_mapping_rules) if isinstance(provider.custom_group_mapping_rules, str) else provider.custom_group_mapping_rules
        except Exception:
            custom_rules = {}

    for rule_grp, target_cgs in custom_rules.items():
        for eg in extracted_groups:
            if rule_grp.lower() == eg.lower() or rule_grp.lower() in eg.lower():
                if isinstance(target_cgs, list):
                    matched_cg_names.update(target_cgs)
                elif isinstance(target_cgs, str):
                    matched_cg_names.add(target_cgs)

    # Retrieve matching custom groups from DB
    db_custom_groups = db.query(CustomGroup).filter(CustomGroup.active == True).all()
    resolved_custom_groups = []
    custom_permissions = set()

    for cg in db_custom_groups:
        cg_matched = False
        if cg.name in matched_cg_names:
            cg_matched = True
        elif not is_end_user:
            # Only match arbitrary custom group names for support/admin users, not end-users
            for eg in extracted_groups:
                if cg.name.lower() == eg.lower() or cg.name.lower().replace(" ", "") == eg.lower().replace(" ", "").replace("-", ""):
                    cg_matched = True
                    break
        if cg_matched:
            resolved_custom_groups.append(cg)
            try:
                perms = json.loads(cg.permissions or "[]")
                custom_permissions.update(perms)
            except Exception:
                pass

    # Ensure IM_SAML is in resolved_custom_groups if it exists in DB
    im_saml_obj = next((cg for cg in resolved_custom_groups if cg.name == "IM_SAML"), None)
    if not im_saml_obj:
        im_saml_db = db.query(CustomGroup).filter(CustomGroup.name == "IM_SAML").first()
        if not im_saml_db:
            im_saml_db = CustomGroup(
                name="IM_SAML",
                description="Default SSO End-User Group for creating tickets, viewing own tickets, updating comments/worknotes, and viewing applications/projects.",
                permissions=json.dumps([
                    "ticket_create",
                    "ticket_read_own",
                    "ticket_update",
                    "applications_read",
                    "projects_read",
                    "tickets:create",
                    "tickets:read_own",
                    "tickets:update",
                    "applications:read",
                    "projects:read"
                ]),
                active=True
            )
            db.add(im_saml_db)
            db.commit()
            db.refresh(im_saml_db)
        resolved_custom_groups.append(im_saml_db)
        try:
            custom_permissions.update(json.loads(im_saml_db.permissions or "[]"))
        except Exception:
            pass

    # 6. Resolve Assignment Groups
    # If the user is an end user, they do NOT get assigned to ticket queues (only support teams get queues)
    resolved_assignment_groups = []
    if not is_end_user:
        asgn_rules = {}
        if provider and provider.assignment_group_mapping_rules:
            try:
                asgn_rules = json.loads(provider.assignment_group_mapping_rules) if isinstance(provider.assignment_group_mapping_rules, str) else provider.assignment_group_mapping_rules
            except Exception:
                asgn_rules = {}

        matched_ag_names = set()
        for rule_grp, target_ags in asgn_rules.items():
            for eg in extracted_groups:
                if rule_grp.lower() == eg.lower() or rule_grp.lower() in eg.lower():
                    if isinstance(target_ags, list):
                        matched_ag_names.update(target_ags)
                    elif isinstance(target_ags, str):
                        matched_ag_names.add(target_ags)

        db_assignment_groups = db.query(AssignmentGroup).filter(AssignmentGroup.active == True).all()
        for ag in db_assignment_groups:
            ag_matched = False
            if ag.name in matched_ag_names or ag.group_id in matched_ag_names:
                ag_matched = True
            else:
                for eg in extracted_groups:
                    clean_eg = eg.lower().replace(" ", "").replace("-", "").replace("_", "")
                    clean_ag = ag.name.lower().replace(" ", "").replace("-", "").replace("_", "")
                    clean_ag_id = ag.group_id.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if clean_ag == clean_eg or clean_ag_id == clean_eg or clean_ag in clean_eg:
                        ag_matched = True
                        break
            if ag_matched:
                resolved_assignment_groups.append(ag)

    effective_permissions = sorted(list(set(get_role_permissions(effective_role)) | custom_permissions))

    if dry_run:
        return {
            "extracted_email": email,
            "extracted_name": full_name,
            "extracted_groups": sorted(list(extracted_groups)),
            "effective_role": effective_role,
            "is_end_user": is_end_user,
            "custom_groups": [cg.name for cg in resolved_custom_groups],
            "assignment_groups": [ag.to_dict() for ag in resolved_assignment_groups],
            "permissions": effective_permissions
        }

    # 7. JIT Provisioning / Update User
    user = db.query(User).filter(or_(User.email == email, User.username == email.split("@")[0])).first()
    if not user:
        import uuid
        uname = email.split("@")[0]
        if db.query(User).filter(User.username == uname).first():
            uname = f"{uname}_{uuid.uuid4().hex[:4]}"
        
        user = User(
            employee_id=f"EMP-SSO-{uuid.uuid4().hex[:6].upper()}",
            username=uname,
            full_name=full_name,
            email=email,
            role=effective_role,
            is_local=False,
            active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"JIT provisioned new SSO user: {user.username} ({user.email}) with role {effective_role} (is_end_user={is_end_user})")
    else:
        if effective_role == "itsm_admin" or user.role != "itsm_admin":
            user.role = effective_role
        if full_name and (not user.full_name or user.full_name == "SSO Enterprise User"):
            user.full_name = full_name
        user.active = True
        db.commit()
        db.refresh(user)

    # Associate Custom Groups
    for cg in resolved_custom_groups:
        uc = db.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id, UserCustomGroup.custom_group_id == cg.id).first()
        if not uc:
            uc = UserCustomGroup(user_id=user.id, custom_group_id=cg.id)
            db.add(uc)
    db.commit()

    # Associate Assignment Groups (for immediate ITSM ticket queue participation - only for support users)
    for ag in resolved_assignment_groups:
        gm = db.query(GroupMember).filter(GroupMember.group_id == ag.id, GroupMember.user_id == user.id).first()
        if not gm:
            gm = GroupMember(
                group_id=ag.id,
                user_id=user.id,
                role_in_group="lead" if user.role == "itsm_admin" else "member"
            )
            db.add(gm)
    db.commit()

    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        custom_groups=[cg.name for cg in resolved_custom_groups],
        permissions=effective_permissions
    )

    return {
        "success": True,
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400,
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "is_end_user": is_end_user,
            "custom_groups": [cg.name for cg in resolved_custom_groups],
            "assignment_groups": [{"id": ag.id, "group_id": ag.group_id, "name": ag.name} for ag in resolved_assignment_groups],
            "permissions": effective_permissions
        },
        "mapped_details": {
            "extracted_email": email,
            "extracted_name": full_name,
            "extracted_groups": sorted(list(extracted_groups)),
            "effective_role": effective_role,
            "is_end_user": is_end_user,
            "custom_groups": [cg.name for cg in resolved_custom_groups],
            "assignment_groups": [ag.name for ag in resolved_assignment_groups]
        },
        "redirect_url": "/#dashboard" if not is_end_user else "/#my-tickets"
    }


@app.post("/sso/register-eso")
def register_eso_provider(payload: ESORegisterRequest, db: Session = Depends(get_db)):
    """
    Seamless Enterprise Sign-On (ESO) registration via existing App ID.
    Pre-populates Service Provider endpoints and configures default claim mapping paths.
    """
    eso_app_id = payload.eso_app_id.strip()
    if not eso_app_id:
        raise HTTPException(status_code=400, detail="eso_app_id is required")

    app_url = os.getenv("APP_URL", "http://localhost:8080").rstrip("/")
    sp_entity_id = f"{app_url}/api/id/saml/metadata/{eso_app_id}"
    acs_url = f"{app_url}/api/id/saml/acs?eso_app_id={eso_app_id}"
    sls_url = f"{app_url}/api/id/saml/sls"

    provider_name = payload.name.strip() if payload.name else f"ESO Provider ({eso_app_id})"

    existing = db.query(SSOProviderConfig).filter(
        or_(SSOProviderConfig.eso_app_id == eso_app_id, SSOProviderConfig.name == provider_name)
    ).first()

    rmr_str = json.dumps(payload.role_mapping_rules or {})
    cgmr_str = json.dumps(payload.custom_group_mapping_rules or {})
    agmr_str = json.dumps(payload.assignment_group_mapping_rules or {})

    if existing:
        existing.name = provider_name
        existing.eso_app_id = eso_app_id
        existing.provider_type = payload.provider_type
        existing.b2b_or_b2c = payload.b2b_or_b2c
        if payload.idp_sso_url:
            existing.sso_url = payload.idp_sso_url
        if payload.idp_entity_id:
            existing.entity_id = payload.idp_entity_id
        if payload.idp_certificate:
            existing.certificate = payload.idp_certificate
        if payload.discovery_url:
            existing.discovery_url = payload.discovery_url
        if payload.client_id:
            existing.client_id = payload.client_id
        if payload.client_secret:
            existing.client_secret = payload.client_secret
        existing.claims_email_path = payload.claims_email_path or "email"
        existing.claims_group_path = payload.claims_group_path or "groups"
        existing.claims_name_path = payload.claims_name_path or "name"
        existing.default_role = payload.default_role or "itsm_user"
        existing.role_mapping_rules = rmr_str
        existing.custom_group_mapping_rules = cgmr_str
        existing.assignment_group_mapping_rules = agmr_str
        existing.enabled = True
        cfg = existing
    else:
        cfg = SSOProviderConfig(
            name=provider_name,
            eso_app_id=eso_app_id,
            provider_type=payload.provider_type,
            b2b_or_b2c=payload.b2b_or_b2c,
            sso_url=payload.idp_sso_url,
            entity_id=payload.idp_entity_id or f"urn:eso:{eso_app_id}",
            certificate=payload.idp_certificate,
            discovery_url=payload.discovery_url,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            claims_email_path=payload.claims_email_path or "email",
            claims_group_path=payload.claims_group_path or "groups",
            claims_name_path=payload.claims_name_path or "name",
            default_role=payload.default_role or "itsm_user",
            role_mapping_rules=rmr_str,
            custom_group_mapping_rules=cgmr_str,
            assignment_group_mapping_rules=agmr_str,
            enabled=True
        )
        db.add(cfg)

    db.commit()
    db.refresh(cfg)

    return {
        "success": True,
        "message": f"Enterprise SSO Provider for App ID '{eso_app_id}' registered successfully.",
        "provider": cfg.to_dict(),
        "service_provider_endpoints": {
            "entity_id": sp_entity_id,
            "acs_url": acs_url,
            "sls_url": sls_url,
            "metadata_url": f"{app_url}/api/id/saml/metadata.xml",
            "sso_redirect_url": f"{app_url}/sso-redirect.html?provider_id={cfg.id}&eso_app_id={eso_app_id}"
        }
    }


@app.post("/sso/process-login")
def process_sso_login(payload: SSOLoginProcessRequest, db: Session = Depends(get_db)):
    """
    Processes SSO login assertions/tokens from Keycloak, Azure AD, B2B/B2C, or ESO.
    Maps groups and claims, provisions the user, and issues the JWT token.
    """
    provider = None
    if payload.provider_id:
        provider = db.get(SSOProviderConfig, payload.provider_id)
    elif payload.eso_app_id:
        provider = db.query(SSOProviderConfig).filter(SSOProviderConfig.eso_app_id == payload.eso_app_id).first()
    elif payload.provider_name:
        provider = db.query(SSOProviderConfig).filter(SSOProviderConfig.name == payload.provider_name).first()

    result = extract_and_map_claims(payload.claims, provider, db, dry_run=False)
    if payload.redirect_uri and not result.get("user", {}).get("is_end_user"):
        result["redirect_url"] = payload.redirect_uri
    return result


@app.post("/sso/test-claim-mapping")
def test_claim_mapping(payload: ClaimMappingTestRequest, db: Session = Depends(get_db)):
    """
    Simulates and validates claim extraction and group mapping without writing to the database.
    """
    provider = None
    if payload.provider_id:
        provider = db.get(SSOProviderConfig, payload.provider_id)

    mock_cfg = SSOProviderConfig(
        name="Test Provider",
        claims_email_path=payload.claims_email_path or (provider.claims_email_path if provider else "email"),
        claims_group_path=payload.claims_group_path or (provider.claims_group_path if provider else "groups"),
        claims_name_path=payload.claims_name_path or (provider.claims_name_path if provider else "name"),
        default_role=payload.default_role or (provider.default_role if provider else "itsm_user"),
        role_mapping_rules=json.dumps(payload.role_mapping_rules) if payload.role_mapping_rules else (provider.role_mapping_rules if provider else "{}"),
        custom_group_mapping_rules=json.dumps(payload.custom_group_mapping_rules) if payload.custom_group_mapping_rules else (provider.custom_group_mapping_rules if provider else "{}"),
        assignment_group_mapping_rules=json.dumps(payload.assignment_group_mapping_rules) if payload.assignment_group_mapping_rules else (provider.assignment_group_mapping_rules if provider else "{}"),
    )

    res = extract_and_map_claims(payload.claims, mock_cfg, db, dry_run=True)
    return {
        "success": True,
        "preview": res
    }


@app.post("/saml/acs")
@app.get("/saml/acs")
def saml_acs_endpoint(eso_app_id: Optional[str] = None, db: Session = Depends(get_db)):
    """
    SAML 2.0 Assertion Consumer Service (ACS) endpoint.
    Handles IdP POST assertion, validates claims, and redirects to ITSM portal.
    """
    provider = None
    if eso_app_id:
        provider = db.query(SSOProviderConfig).filter(SSOProviderConfig.eso_app_id == eso_app_id).first()
    return {
        "status": "ready",
        "service": "saml-acs",
        "eso_app_id": eso_app_id,
        "provider": provider.name if provider else "Default SAML Provider"
    }


@app.get("/sso/metadata.xml")
@app.get("/saml/metadata.xml")
def get_saml_sp_metadata():
    """
    Returns standard SAML 2.0 Service Provider (SP) Metadata XML.
    This file can be downloaded and registered with Enterprise Single Sign-On (ESO),
    Azure Active Directory, Okta, PingFederate, or other B2B/B2C IdPs.
    """
    app_url = os.getenv("APP_URL", "http://localhost:8080").rstrip("/")
    entity_id = f"{app_url}/api/id/saml/metadata"
    acs_url = f"{app_url}/api/id/saml/acs"
    sls_url = f"{app_url}/api/id/saml/sls"
    org_name = os.getenv("ORGANIZATION_NAME", "Enterprise ITSM Platform")

    xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                     xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
                     entityID="{entity_id}">
    <md:SPSSODescriptor AuthnRequestsSigned="false"
                        WantAssertionsSigned="true"
                        protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        <md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                                Location="{sls_url}"/>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:persistent</md:NameIDFormat>
        <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                                     Location="{acs_url}"
                                     index="1"
                                     isDefault="true"/>
    </md:SPSSODescriptor>
    <md:Organization>
        <md:OrganizationName xml:lang="en">{org_name}</md:OrganizationName>
        <md:OrganizationDisplayName xml:lang="en">{org_name}</md:OrganizationDisplayName>
        <md:OrganizationURL xml:lang="en">{app_url}</md:OrganizationURL>
    </md:Organization>
    <md:ContactPerson contactType="technical">
        <md:GivenName>ITSM Identity Support</md:GivenName>
        <md:EmailAddress>itsm-identity-support@company.local</md:EmailAddress>
    </md:ContactPerson>
</md:EntityDescriptor>'''

    return Response(
        content=xml_content.strip(),
        media_type="application/xml",
        headers={
            "Content-Disposition": 'attachment; filename="nexus-itsm-sp-metadata.xml"'
        }
    )


@app.post("/sso/import-idp-metadata")
def import_idp_metadata(payload: Dict[str, str], db: Session = Depends(get_db)):
    """
    Parses an uploaded Enterprise IdP SAML Metadata XML document
    and saves the configuration for seamless ESO registration.
    """
    metadata_xml = payload.get("metadata_xml", "").strip()
    provider_name = payload.get("name", "Enterprise SAML SSO").strip()
    b2b_or_b2c = payload.get("b2b_or_b2c", "b2b").strip()

    if not metadata_xml:
        raise HTTPException(status_code=400, detail="metadata_xml content is required")

    try:
        # Remove namespaces for lenient XML parsing
        clean_xml = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', metadata_xml)
        root = ET.fromstring(clean_xml)

        entity_id = root.attrib.get("entityID", "")
        sso_url = ""
        certificate = ""

        # Find SingleSignOnService
        for elem in root.iter("SingleSignOnService"):
            loc = elem.attrib.get("Location")
            if loc:
                sso_url = loc
                break

        # Find X509Certificate
        for elem in root.iter("X509Certificate"):
            if elem.text:
                certificate = elem.text.strip()
                break

        if not entity_id:
            entity_id = f"urn:idp:{provider_name.lower().replace(' ', '-')}"

        existing = db.query(SSOProviderConfig).filter(SSOProviderConfig.name == provider_name).first()
        if not existing:
            cfg = SSOProviderConfig(
                name=provider_name,
                provider_type="saml",
                b2b_or_b2c=b2b_or_b2c,
                entity_id=entity_id,
                sso_url=sso_url,
                certificate=certificate,
                metadata_xml=metadata_xml,
                enabled=True
            )
            db.add(cfg)
        else:
            existing.entity_id = entity_id
            existing.sso_url = sso_url
            existing.certificate = certificate
            existing.metadata_xml = metadata_xml
            existing.b2b_or_b2c = b2b_or_b2c
            existing.enabled = True
            cfg = existing

        db.commit()
        db.refresh(cfg)
        return {
            "success": True,
            "message": "IdP SAML metadata successfully parsed and stored",
            "provider": cfg.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to parse IdP metadata: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to parse IdP metadata XML: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("IDENTITY_PORT", "8001"))
    uvicorn.run("identity_service.main:app", host="0.0.0.0", port=port, reload=True)
