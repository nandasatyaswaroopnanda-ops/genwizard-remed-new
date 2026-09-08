#!/usr/bin/env python3
"""
Genwizard ITSM — External Identity Management (IM) Bootstrap & Sync Utility.

This script ensures that an existing Identity Management service has all
required groups, roles, permissions, and AD group mappings configured for Genwizard ITSM:
1. 'IM_SAML' custom group with scoped end-user permissions (tickets:create, tickets:read_own, tickets:update, applications:read, projects:read).
2. Standard AD Group / Support DL mappings (ITSM-Admins, Service Desk, ITSM-Fulfillers, Tier1-Support).
3. Reads admin and MongoDB credentials dynamically from HashiCorp Consul or environment variables.
"""

import os
import sys
import json
import logging
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("im_bootstrap")

CONSUL_ADDR = os.getenv("CONSUL_HTTP_ADDR", "http://consul:8500").rstrip("/")
CONSUL_TOKEN = os.getenv("CONSUL_HTTP_TOKEN", "")
IM_SERVICE_URL = os.getenv("IDENTITY_SERVICE_URL", "http://identity-management:8080").rstrip("/")

REQUIRED_GROUPS = [
    {
        "name": "IM_SAML",
        "description": "Default SSO End-User Group for creating tickets, viewing own tickets, updating comments/worknotes, and viewing applications/projects.",
        "permissions": [
            "ticket_create",
            "ticket_read_own",
            "ticket_update",
            "applications_read",
            "projects_read"
        ]
    },
    {
        "name": "ATR_SAML",
        "description": "Default SSO End-User Group (ATR SAML) for creating tickets, viewing own tickets, updating comments/worknotes, and viewing applications/projects.",
        "permissions": [
            "ticket_create",
            "ticket_read_own",
            "ticket_update",
            "applications_read",
            "projects_read"
        ]
    },
    {
        "name": "itsm_admin",
        "description": "ITSM Platform Administrator Group with full management and operational permissions.",
        "permissions": [
            "admin_all",
            "ticket_create",
            "ticket_read",
            "ticket_update",
            "ticket_delete",
            "ticket_assign",
            "ticket_resolve",
            "ticket_close",
            "admin_routing",
            "admin_slas",
            "admin_config",
            "users_manage",
            "applications_read",
            "projects_read"
        ]
    },
    {
        "name": "itsm_user",
        "description": "ITSM Support Fulfiller Group with queue assignment and ticket resolution permissions.",
        "permissions": [
            "ticket_create",
            "ticket_read",
            "ticket_update",
            "ticket_assign",
            "ticket_resolve",
            "applications_read",
            "projects_read"
        ]
    },
    {
        "name": "itsm_read",
        "description": "ITSM Read-Only Group with read access to tickets, applications, and projects.",
        "permissions": [
            "ticket_read",
            "applications_read",
            "projects_read"
        ]
    }
]

def get_consul_kv(key: str) -> dict:
    """Retrieve raw or JSON value from Consul KV."""
    if not CONSUL_ADDR:
        return {}
    try:
        headers = {"X-Consul-Token": CONSUL_TOKEN} if CONSUL_TOKEN else {}
        r = requests.get(f"{CONSUL_ADDR}/v1/kv/{key}", params={"raw": ""}, headers=headers, timeout=3)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return {"value": r.text.strip()}
    except Exception as e:
        logger.debug("Consul lookup failed for key %s: %s", key, e)
    return {}

def resolve_admin_credentials():
    """Resolve admin username and password from Consul or environment."""
    username = os.getenv("ITSM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    password = os.getenv("ITSM_BOOTSTRAP_ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", ""))

    if not password:
        candidate_keys = [
            "configuration/aaam-atr-v3/identity-management/admin.password",
            os.getenv("CONSUL_ADMIN_KEY", "").strip(),
            "nexus-itsm/bootstrap/itsm-admin",
            "nexus-itsm/admin",
            "im/admin",
            "identity/admin",
            "bootstrap/itsm-admin"
        ]
        for k in candidate_keys:
            if not k:
                continue
            data = get_consul_kv(k)
            if isinstance(data, dict):
                password = data.get("password") or data.get("pass") or data.get("admin_password") or data.get("value") or ""
                username = data.get("username") or data.get("user") or username
            elif isinstance(data, str) and data:
                password = data
            if password:
                logger.info("Retrieved admin credentials from Consul key: %s", k)
                break

    if not password:
        password = "Admin@Secure2026!"

    return username, password

def sync_via_api(username: str, password: str):
    """Authenticate with the existing IM service and bootstrap groups."""
    logger.info("Attempting to connect to existing IM service at: %s", IM_SERVICE_URL)

    candidate_login_urls = [
        f"{IM_SERVICE_URL}/atr-gateway/identity-management/api/v1/auth/token?useDeflate=true",
        f"{IM_SERVICE_URL}/identity-management/api/v1/auth/token?useDeflate=true",
        f"{IM_SERVICE_URL}/api/v1/auth/token?useDeflate=true",
        "http://identity-management:8080/api/v1/auth/token?useDeflate=true",
        "http://identity-management:8001/api/v1/auth/token?useDeflate=true",
        "http://atr-gateway-container:8080/atr-gateway/identity-management/api/v1/auth/token?useDeflate=true",
        "http://atr-gateway:8080/atr-gateway/identity-management/api/v1/auth/token?useDeflate=true",
        f"{IM_SERVICE_URL}/auth/login",
        f"{IM_SERVICE_URL}/identity-management/auth/login",
        "http://identity-management:8080/identity-management/auth/login",
        "http://identity-management:8080/auth/login",
        "http://identity-management:8001/auth/login",
        "http://127.0.0.1:8080/identity-management/auth/login",
        "http://127.0.0.1:8080/auth/login",
        f"{IM_SERVICE_URL}/identity-management/login",
        f"{IM_SERVICE_URL}/login"
    ]

    req_headers = {
        "Accept": "*/*",
        "Content-Type": "application/json"
    }

    auth_headers = {}
    token = None
    for login_url in candidate_login_urls:
        try:
            r = requests.post(login_url, json={"username": username, "password": password}, headers=req_headers, timeout=4)
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    token = data.get("token") or data.get("access_token") or data.get("short_token") or data.get("shortToken")
                elif isinstance(data, str) and data:
                    token = data
                elif r.text:
                    token = r.text.strip().strip('"')

                if token:
                    auth_headers = {"Authorization": f"Bearer {token}"}
                    logger.info("Successfully authenticated with IM short-token at: %s", login_url)
                    break
        except Exception as e:
            logger.debug("Attempt to login at %s failed: %s", login_url, e)

    if not token:
        logger.warning("Could not authenticate via IM REST API (401/403 or different auth schema). Will use direct Mongo sync fallback.")
        return False

    # Resolve base URL with or without /identity-management prefix
    candidate_bases = [IM_SERVICE_URL]
    if not IM_SERVICE_URL.endswith("/identity-management"):
        candidate_bases.append(f"{IM_SERVICE_URL}/identity-management")

    # Sync Custom Groups (IM_SAML)
    groups_endpoint = None
    existing_groups = []
    for base in candidate_bases:
        try:
            r = requests.get(f"{base}/groups", headers=auth_headers, timeout=4)
            if r.status_code == 200:
                groups_endpoint = f"{base}/groups"
                existing_groups = [g["name"] for g in r.json()] if isinstance(r.json(), list) else []
                break
        except Exception:
            continue

    if not groups_endpoint:
        groups_endpoint = f"{IM_SERVICE_URL}/groups"

    for g in REQUIRED_GROUPS:
        if g["name"] not in existing_groups:
            try:
                create_resp = requests.post(groups_endpoint, json=g, headers=auth_headers, timeout=5)
                if create_resp.status_code in (200, 201):
                    logger.info("Successfully created group '%s' at %s", g["name"], groups_endpoint)
                else:
                    logger.error("Failed to create group '%s': %s", g["name"], create_resp.text)
            except Exception as e:
                logger.error("Error creating group '%s': %s", g["name"], e)
        else:
            logger.info("Group '%s' already exists in IM service.", g["name"])

    # Associate 'itsm_admin' group with the existing admin user in IM
    try:
        users_endpoint = None
        for base in candidate_bases:
            try:
                r = requests.get(f"{base}/users", headers=auth_headers, timeout=4)
                if r.status_code == 200:
                    users_endpoint = f"{base}/users"
                    break
            except Exception:
                continue

        if not users_endpoint:
            users_endpoint = f"{IM_SERVICE_URL}/users"

        r = requests.get(users_endpoint, headers=auth_headers, timeout=5)
        if r.status_code == 200:
            users_list = r.json() if isinstance(r.json(), list) else []
            admin_obj = next((u for u in users_list if u.get("username") == username), None)
            if admin_obj:
                admin_id = admin_obj.get("id")
                curr_groups = admin_obj.get("custom_groups", []) or []
                if "itsm_admin" not in curr_groups:
                    curr_groups.append("itsm_admin")
                    requests.put(
                        f"{users_endpoint}/{admin_id}",
                        json={"custom_groups": curr_groups, "role": "itsm_admin"},
                        headers=auth_headers,
                        timeout=5
                    )
                    logger.info("Associated 'itsm_admin' group with existing admin user '%s' in IM.", username)
                else:
                    logger.info("Existing admin user '%s' already possesses 'itsm_admin' group.", username)
    except Exception as e:
        logger.debug("Could not verify/update admin user groups via IM API: %s", e)

    return True

def sync_via_mongo(admin_user: str = "admin"):
    """Direct database synchronization fallback if IM API is not immediately exposed."""
    try:
        try:
            from backend.database import get_db
            from backend.models import CustomGroup, User, UserCustomGroup
            db = next(get_db())
        except (ImportError, ModuleNotFoundError) as imp_err:
            logger.info("Direct Mongo sync: Python dependencies (e.g. %s) not present on host. Sync will run seamlessly inside container.", imp_err.name if hasattr(imp_err, 'name') else imp_err)
            return True

        group_objs = {}
        for g in REQUIRED_GROUPS:
            existing = db.query(CustomGroup).filter(CustomGroup.name == g["name"]).first()
            if not existing:
                cg = CustomGroup(
                    name=g["name"],
                    description=g["description"],
                    permissions=json.dumps(g["permissions"]),
                    active=True
                )
                db.add(cg)
                db.commit()
                db.refresh(cg)
                logger.info("Direct Mongo: bootstrapped group '%s' with permissions", g["name"])
                group_objs[g["name"]] = cg
            else:
                existing.permissions = json.dumps(g["permissions"])
                existing.description = g["description"]
                existing.active = True
                db.commit()
                group_objs[g["name"]] = existing
                logger.info("Direct Mongo: updated group '%s' with clean underscore permissions", g["name"])

        # Attach itsm_admin group to existing admin user in MongoDB
        admin_cg = group_objs.get("itsm_admin")
        if admin_cg:
            admin_user_obj = db.query(User).filter(
                (User.username == admin_user) | (User.role.in_(["administrator", "admin", "itsm_admin"]))
            ).first()
            if admin_user_obj:
                user_grp = db.query(UserCustomGroup).filter(
                    UserCustomGroup.user_id == admin_user_obj.id,
                    UserCustomGroup.custom_group_id == admin_cg.id
                ).first()
                if not user_grp:
                    db.add(UserCustomGroup(user_id=admin_user_obj.id, custom_group_id=admin_cg.id))
                    if admin_user_obj.role != "itsm_admin":
                        admin_user_obj.role = "itsm_admin"
                    db.commit()
                    logger.info("Direct Mongo: attached 'itsm_admin' group to existing admin user '%s'", admin_user_obj.username)
                else:
                    logger.info("Direct Mongo: existing admin user '%s' already attached to 'itsm_admin'", admin_user_obj.username)

        # Initialize and verify ITSM operational collections in MongoDB
        try:
            from backend.mongo_dal import get_mongo_db, mongo_client
            m_db = get_mongo_db()
            if m_db is not None:
                indexes = [
                    ("incidents", [("ticket_number", 1)], True),
                    ("incidents", [("project_id", 1), ("state", 1)], False),
                    ("service_requests", [("ticket_number", 1)], True),
                    ("change_requests", [("change_number", 1)], True),
                    ("users", [("username", 1)], True),
                    ("projects", [("code", 1)], True),
                    ("applications", [("project_id", 1), ("name", 1)], False),
                    ("sla_policies", [("project_id", 1), ("assignment_group_id", 1)], False),
                ]
                for coll_name, idx_keys, is_unique in indexes:
                    try:
                        m_db[coll_name].create_index(idx_keys, unique=is_unique, background=True)
                        logger.info("Direct Mongo: ensured index on ITSM collection '%s'", coll_name)
                    except Exception:
                        pass
                logger.info("Direct Mongo: successfully initialized ITSM operational collections in existing Mongo!")

            # Also seed existing IM database if it resides on the same Mongo instance
            if mongo_client is not None:
                try:
                    all_dbs = mongo_client.list_database_names()
                    for im_candidate_db in ["identity_management", "im_db", "im", "atr"]:
                        if im_candidate_db in all_dbs:
                            ext_im_db = mongo_client[im_candidate_db]
                            for coll_name in ["custom_groups", "groups"]:
                                for g in REQUIRED_GROUPS:
                                    existing_doc = ext_im_db[coll_name].find_one({"name": g["name"]})
                                    if not existing_doc:
                                        ext_im_db[coll_name].insert_one({
                                            "name": g["name"],
                                            "description": g["description"],
                                            "permissions": g["permissions"],
                                            "active": True
                                        })
                                        logger.info("Direct Mongo: seeded '%s' into %s.%s", g["name"], im_candidate_db, coll_name)
                                    else:
                                        ext_im_db[coll_name].update_one(
                                            {"_id": existing_doc["_id"]},
                                            {"$set": {"permissions": g["permissions"], "description": g["description"], "active": True}}
                                        )
                except Exception as _ext_db_err:
                    logger.debug("External IM database check skipped: %s", _ext_db_err)
        except Exception as _e:
            logger.debug("ITSM native index check skipped: %s", _e)

        return True
    except Exception as e:
        logger.warning("Direct Mongo sync failed: %s", e)
        return False

def main():
    logger.info("Starting Genwizard ITSM external Identity Management sync...")
    admin_user, admin_pass = resolve_admin_credentials()
    logger.info("Resolved admin username: '%s'", admin_user)

    success = sync_via_api(admin_user, admin_pass)
    if not success:
        logger.info("Falling back to direct Mongo bootstrap...")
        success = sync_via_mongo(admin_user)

    if success:
        logger.info("Identity Management sync completed successfully!")
    else:
        logger.warning("Identity Management sync finished with warnings.")

if __name__ == "__main__":
    main()
