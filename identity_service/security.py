"""Security, password hashing, and JWT token management for Identity Service."""
import os
import hmac
import hashlib
import datetime
from typing import Dict, Any, List, Optional, Set
import jwt

JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("ITSM_JWT_SECRET", "nexus-itsm-super-secure-jwt-token-key-2026"))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# Comprehensive Permission Catalog - Simplified without colons
ALL_PERMISSIONS = [
    # Tickets / Incidents / Service Requests
    {"code": "ticket_create", "category": "Tickets", "description": "Create new incidents and service requests"},
    {"code": "ticket_read", "category": "Tickets", "description": "View incidents and service requests"},
    {"code": "ticket_read_own", "category": "Tickets", "description": "View own created tickets"},
    {"code": "ticket_update", "category": "Tickets", "description": "Update ticket status, details, and work notes"},
    {"code": "ticket_assign", "category": "Tickets", "description": "Assign tickets to groups or engineers"},
    {"code": "ticket_resolve", "category": "Tickets", "description": "Resolve incidents and requests"},
    {"code": "ticket_close", "category": "Tickets", "description": "Close or resolve incidents and requests"},
    {"code": "ticket_delete", "category": "Tickets", "description": "Delete or archive ticket records"},
    
    # Changes / Releases
    {"code": "change_create", "category": "Changes", "description": "Create change requests"},
    {"code": "change_read", "category": "Changes", "description": "View change requests and schedules"},
    {"code": "change_approve", "category": "Changes", "description": "Approve or reject CAB change requests"},
    {"code": "change_manage", "category": "Changes", "description": "Execute and complete change requests"},
    
    # Knowledge Base
    {"code": "kb_read", "category": "Knowledge", "description": "Read published knowledge articles"},
    {"code": "kb_create", "category": "Knowledge", "description": "Create draft knowledge articles"},
    {"code": "kb_publish", "category": "Knowledge", "description": "Publish knowledge articles to portal"},
    
    # Administration & Configuration
    {"code": "admin_applications", "category": "Administration", "description": "Manage applications and metadata"},
    {"code": "applications_read", "category": "Administration", "description": "View applications list for ticket creation"},
    {"code": "admin_projects", "category": "Administration", "description": "Manage projects and mappings"},
    {"code": "projects_read", "category": "Administration", "description": "View projects list for ticket creation"},
    {"code": "admin_groups", "category": "Administration", "description": "Manage assignment groups and support DLs"},
    {"code": "admin_routing", "category": "Administration", "description": "Manage 6-tier routing rules"},
    {"code": "admin_slas", "category": "Administration", "description": "Configure SLA policies and calendars"},
    {"code": "admin_config", "category": "Administration", "description": "Configure ticket fields, taxonomy, and Consul sync"},
    {"code": "admin_all", "category": "Administration", "description": "Full administrative control"},
    
    # Identity & Access
    {"code": "users_manage", "category": "Identity", "description": "Create and manage local users"},
    {"code": "groups_manage", "category": "Identity", "description": "Create and manage custom groups and permissions"},
    {"code": "sso_manage", "category": "Identity", "description": "Manage enterprise SSO and SAML metadata"},
    
    # Observability
    {"code": "system_logs", "category": "System", "description": "View system telemetry and adjust log levels"},
]

def normalize_permission(p: str) -> str:
    """Normalize a permission code by avoiding colons and using clean underscores."""
    if not p:
        return ""
    code = p.strip().replace(":", "_")
    if code.startswith("tickets_"):
        code = "ticket_" + code[len("tickets_"):]
    elif code.startswith("changes_"):
        code = "change_" + code[len("changes_"):]
    elif code == "routing_manage":
        code = "admin_routing"
    elif code == "slas_manage":
        code = "admin_slas"
    elif code == "config_manage":
        code = "admin_config"
    return code

LEGACY_ALIASES: Dict[str, List[str]] = {
    "ticket_create": ["tickets:create", "ticket:create"],
    "ticket_read": ["tickets:read", "ticket:read"],
    "ticket_read_own": ["tickets:read_own", "ticket:read_own"],
    "ticket_update": ["tickets:update", "ticket:update"],
    "ticket_assign": ["tickets:assign", "ticket:assign"],
    "ticket_resolve": ["tickets:resolve", "ticket:resolve"],
    "ticket_close": ["tickets:close", "ticket:close"],
    "ticket_delete": ["tickets:delete", "ticket:delete"],
    "admin_all": ["admin:all"],
    "admin_routing": ["admin:routing", "routing:manage"],
    "admin_slas": ["admin:slas", "slas:manage"],
    "admin_config": ["admin:config", "config:manage"],
    "admin_groups": ["admin:groups"],
    "admin_applications": ["admin:applications"],
    "admin_projects": ["admin:projects"],
    "users_manage": ["users:manage"],
    "groups_manage": ["groups:manage"],
    "sso_manage": ["sso:manage"],
    "system_logs": ["system:logs"],
    "applications_read": ["applications:read"],
    "projects_read": ["projects:read"],
}

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "itsm_admin": [p["code"] for p in ALL_PERMISSIONS] + [
        "admin:all", "tickets:create", "tickets:read", "tickets:update", "tickets:delete", "tickets:assign", "tickets:resolve", "tickets:close",
        "routing:manage", "slas:manage", "config:manage", "users:manage", "applications:read", "projects:read"
    ],
    "administrator": [p["code"] for p in ALL_PERMISSIONS] + [
        "admin:all", "tickets:create", "tickets:read", "tickets:update", "tickets:delete", "tickets:assign", "tickets:resolve", "tickets:close",
        "routing:manage", "slas:manage", "config:manage", "users:manage", "applications:read", "projects:read"
    ],
    "itsm_user": [
        "ticket_create", "ticket_read", "ticket_read_own", "ticket_update", "ticket_assign", "ticket_resolve", "ticket_close",
        "change_create", "change_read",
        "kb_read", "kb_create",
        "applications_read", "projects_read",
        "tickets:create", "tickets:read", "tickets:read_own", "tickets:update", "tickets:assign", "tickets:close",
        "changes:create", "changes:read", "kb:read", "kb:create", "applications:read", "projects:read"
    ],
    "support_member": [
        "ticket_create", "ticket_read", "ticket_read_own", "ticket_update", "ticket_assign", "ticket_resolve", "ticket_close",
        "change_create", "change_read",
        "kb_read", "kb_create",
        "applications_read", "projects_read",
        "tickets:create", "tickets:read", "tickets:read_own", "tickets:update", "tickets:assign", "tickets:close",
        "changes:create", "changes:read", "kb:read", "kb:create", "applications:read", "projects:read"
    ],
    "group_manager": [
        "ticket_create", "ticket_read", "ticket_read_own", "ticket_update", "ticket_assign", "ticket_resolve", "ticket_close",
        "change_create", "change_read", "change_approve",
        "kb_read", "kb_create", "admin_groups",
        "applications_read", "projects_read",
        "tickets:create", "tickets:read", "tickets:read_own", "tickets:update", "tickets:assign", "tickets:close",
        "changes:create", "changes:read", "changes:approve", "kb:read", "kb:create", "admin:groups", "applications:read", "projects:read"
    ],
    "itsm_read": [
        "ticket_create", "ticket_read_own", "ticket_update", "applications_read", "projects_read",
        "tickets:create", "tickets:read_own", "tickets:update", "applications:read", "projects:read"
    ],
    "employee": [
        "ticket_create", "ticket_read_own", "ticket_update", "applications_read", "projects_read",
        "tickets:create", "tickets:read_own", "tickets:update", "applications:read", "projects_read"
    ]
}

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a unique random salt."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"pbkdf2_sha256${salt.hex()}${key.hex()}"

def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Verify password against stored PBKDF2 hash."""
    if not stored_hash:
        return False
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3 or parts[0] != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(parts[1])
        expected_key = bytes.fromhex(parts[2])
        computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(computed_key, expected_key)
    except Exception:
        return False

def create_access_token(
    user_id: int,
    username: str,
    email: str,
    role: str,
    custom_groups: Optional[List[str]] = None,
    permissions: Optional[List[str]] = None,
    expires_delta: Optional[datetime.timedelta] = None
) -> str:
    """Generate JWT bearer token with claims."""
    delta = expires_delta or datetime.timedelta(hours=JWT_EXPIRATION_HOURS)
    now = datetime.datetime.utcnow()
    exp = now + delta

    # Compute effective permissions
    raw_perms = set(ROLE_PERMISSIONS.get(role, []))
    if permissions:
        raw_perms.update(permissions)

    effective_permissions = set()
    for p in raw_perms:
        norm = normalize_permission(p)
        if norm:
            effective_permissions.add(norm)
            for alias in LEGACY_ALIASES.get(norm, []):
                effective_permissions.add(alias)
        if p:
            effective_permissions.add(p)

    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "username": username,
        "preferred_username": username,
        "email": email,
        "role": role,
        "custom_groups": custom_groups or [],
        "permissions": sorted(list(effective_permissions)),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": "nexus-itsm-identity"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate JWT bearer token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer="nexus-itsm-identity")

def get_role_permissions(role: str) -> List[str]:
    """Return default permissions for a role."""
    return ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["itsm_read"])
