"""Keycloak bearer-token validation and role-to-access mapping."""
import os
import json
from functools import lru_cache
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, DistributionList

bearer = HTTPBearer(auto_error=False)
# Keycloak groups may be assigned these roles directly or through composite
# organisation-specific roles. Keep custom role composition in the IdP rather
# than hard-coding a new application deployment for every group.
ADMIN_ROLES = {"administrator", "admin", "itsm-admin", "itsm_admin"}
SUPPORT_ROLES = {"support_member", "support", "itsm-support", "group_manager", "itsm_user"}
READ_ROLES = {"itsm_read", "itsm-read", "read_only", "read-only"}

def keycloak_enabled() -> bool:
    return bool(os.getenv("KEYCLOAK_ISSUER"))

@lru_cache(maxsize=1)
def jwks() -> Dict[str, Any]:
    issuer = os.environ["KEYCLOAK_ISSUER"].rstrip("/")
    url = f"{issuer}/protocol/openid-connect/certs"
    try:
        return httpx.get(url, timeout=5).json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Keycloak signing keys are unavailable") from exc

def _roles(claims: Dict[str, Any]) -> set[str]:
    realm = claims.get("realm_access", {}).get("roles", [])
    client_id = os.getenv("KEYCLOAK_CLIENT_ID", "nexus-itsm")
    client = claims.get("resource_access", {}).get(client_id, {}).get("roles", [])
    return {str(role).lower() for role in [*realm, *client]}

def _distribution_list_memberships(claims: Dict[str, Any]) -> set[str]:
    """Read DL membership emitted by Keycloak's group/claim mappers."""
    values = claims.get("distribution_lists", claims.get("groups", []))
    if isinstance(values, str):
        values = [values]
    return {str(value).lstrip("/").lower() for value in values or []}

def _user_role(claims: Dict[str, Any], db: Optional[Session] = None) -> str:
    roles = _roles(claims)
    if roles & ADMIN_ROLES:
        return "administrator"
    if db:
        memberships = _distribution_list_memberships(claims)
        configured = db.query(DistributionList).filter(DistributionList.active == True).all()
        # Configure Keycloak's groups mapper to emit the DL's email address,
        # e.g. /payments-support@accenture.com.
        if any(dl.privilege == "administrator" and dl.email.lower() in memberships for dl in configured):
            return "administrator"
    if roles & SUPPORT_ROLES:
        return "support_member"
    if roles & READ_ROLES:
        return "employee"
    if db and any(dl.privilege == "support" and dl.email.lower() in _distribution_list_memberships(claims)
                  for dl in db.query(DistributionList).filter(DistributionList.active == True).all()):
        return "support_member"
    return "employee"

def _validate_token(token: str) -> Dict[str, Any]:
    issuer = os.environ["KEYCLOAK_ISSUER"].rstrip("/")
    audience = os.getenv("KEYCLOAK_AUDIENCE", os.getenv("KEYCLOAK_CLIENT_ID", "nexus-itsm"))
    try:
        header = jwt.get_unverified_header(token)
        key = next(key for key in jwks()["keys"] if key["kid"] == header["kid"])
        return jwt.decode(token, jwt.algorithms.RSAAlgorithm.from_jwk(key), algorithms=["RS256"], audience=audience, issuer=issuer)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired Keycloak access token") from exc

LOCAL_PERSONAS: Dict[int, Dict[str, Any]] = {
    1: {
        "employee_id": "EMP001",
        "username": "admin",
        "full_name": "Admin User",
        "first_name": "Admin",
        "last_name": "User",
        "email": "admin@company.com",
        "role": "itsm_admin",
        "department": "IT Operations",
        "location": "HQ",
        "is_local": True,
        "active": True
    },
    2: {
        "employee_id": "EMP002",
        "username": "john.smith",
        "full_name": "John Smith",
        "first_name": "John",
        "last_name": "Smith",
        "email": "john.smith@company.com",
        "role": "employee",
        "department": "Sales & Operations",
        "location": "HQ",
        "is_local": True,
        "active": True
    },
    3: {
        "employee_id": "EMP003",
        "username": "sarah.johnson",
        "full_name": "Sarah Johnson",
        "first_name": "Sarah",
        "last_name": "Johnson",
        "email": "sarah.johnson@company.com",
        "role": "support_member",
        "department": "Payment Application Support",
        "location": "HQ",
        "is_local": True,
        "active": True
    },
    4: {
        "employee_id": "EMP004",
        "username": "david.wilson",
        "full_name": "David Wilson",
        "first_name": "David",
        "last_name": "Wilson",
        "email": "david.wilson@company.com",
        "role": "group_manager",
        "department": "Database Support",
        "location": "HQ",
        "is_local": True,
        "active": True
    },
    5: {
        "employee_id": "EMP005",
        "username": "mike.brown",
        "full_name": "Mike Brown",
        "first_name": "Mike",
        "last_name": "Brown",
        "email": "mike.brown@company.com",
        "role": "support_member",
        "department": "Cloud Operations",
        "location": "HQ",
        "is_local": True,
        "active": True
    }
}

def _ensure_local_persona(user_id: int, db: Session) -> Optional[User]:
    """In local testing environments where SEED_DEMO_DATA is explicitly enabled,
    ensures requested test persona exists and support personas are linked to assignment groups.
    In production (default), returns None to guarantee a 100% clean, blank state."""
    seed_demo = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")
    if not seed_demo:
        return None
    if user_id not in LOCAL_PERSONAS:
        return None
    pdata = LOCAL_PERSONAS[user_id]
    user = db.query(User).filter(User.username == pdata["username"]).first()
    if not user:
        # If requested user_id is free, assign it; otherwise let auto-increment assign next id
        conflict_user = db.query(User).filter(User.id == user_id).first()
        if conflict_user:
            user = User(**pdata)
        else:
            user = User(id=user_id, **pdata)
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            user = db.query(User).filter(User.username == pdata["username"]).first()

    # Ensure support persona GroupMember linkage, project queues and project_admin groups
    if user and pdata.get("role") in ("support_member", "group_manager"):
        try:
            from backend.models import GroupMember, AssignmentGroup, CustomGroup, UserCustomGroup, Project
            from backend.routes.admin_projects import setup_project_queues_and_groups
            persona_proj_map = {
                "sarah.johnson": "Payment Platform Modernization",
                "david.wilson": "Customer Portal Modernization",
                "mike.brown": "Cloud Migration",
            }
            p_name = persona_proj_map.get(pdata["username"])
            if p_name:
                grp_l2, grp_l3 = setup_project_queues_and_groups(db, p_name)
                proj = db.query(Project).filter(Project.name == p_name).first()
                if not proj:
                    clean_pid = f"PRJ-{p_name.upper().replace(' ', '-')[:12]}"
                    proj = Project(
                        project_id=clean_pid,
                        name=p_name,
                        description=f"Operational project for {p_name}",
                        default_assignment_group_id=grp_l2.id,
                        l2_assignment_group_id=grp_l2.id,
                        l3_assignment_group_id=grp_l3.id,
                        active=True
                    )
                    db.add(proj)
                    db.flush()

                # Link project admin custom group
                cg_name = f"{p_name}_admin"
                cg = db.query(CustomGroup).filter(CustomGroup.name == cg_name).first()
                if not cg:
                    cg = CustomGroup(name=cg_name, permissions=json.dumps([f"project:{p_name}:admin"]), active=True)
                    db.add(cg)
                    db.flush()

                if not db.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id, UserCustomGroup.custom_group_id == cg.id).first():
                    db.add(UserCustomGroup(user_id=user.id, custom_group_id=cg.id))
                    db.flush()

                # Link L2 group membership
                if not db.query(GroupMember).filter(GroupMember.user_id == user.id, GroupMember.group_id == grp_l2.id).first():
                    db.add(GroupMember(user_id=user.id, group_id=grp_l2.id))
                    db.flush()

                db.commit()
        except Exception:
            db.rollback()

    if user and user.username == "john.smith":
        try:
            from backend.models import CustomGroup, UserCustomGroup
            for s_name in ["IM_SAML", "ATR_SAML"]:
                saml_cg = db.query(CustomGroup).filter(CustomGroup.name == s_name).first()
                if not saml_cg:
                    saml_cg = CustomGroup(name=s_name, permissions=json.dumps(["employee"]), active=True)
                    db.add(saml_cg)
                    db.flush()
                if not db.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id, UserCustomGroup.custom_group_id == saml_cg.id).first():
                    db.add(UserCustomGroup(user_id=user.id, custom_group_id=saml_cg.id))
            db.commit()
        except Exception:
            db.rollback()

    return user


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_user_id: Optional[str] = Header(None),
    x_user_name: Optional[str] = Header(None),
    x_remote_user: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Validate bearer token from Identity Service, external IM, or Keycloak SSO, or proxy headers."""
    if credentials and credentials.credentials:
        token = credentials.credentials
        # 1. Try decoding as Identity Service JWT token
        jwt_secret = os.getenv("JWT_SECRET", os.getenv("ITSM_JWT_SECRET", "nexus-itsm-super-secure-jwt-token-key-2026"))
        try:
            claims = jwt.decode(token, jwt_secret, algorithms=["HS256"], issuer="nexus-itsm-identity")
            user_id = int(claims.get("sub", 0))
            user = db.query(User).filter(User.id == user_id, User.active == True).first()
            if user:
                return user
        except Exception:
            pass

        # 2. Try decoding token claims from external IM / Gateway token
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            ext_uname = unverified.get("preferred_username") or unverified.get("username") or unverified.get("sub")
            ext_mail = unverified.get("email")
            ext_name = unverified.get("name")
            if ext_uname and not str(ext_uname).isdigit():
                user = db.query(User).filter(
                    (User.username.ilike(str(ext_uname).strip())) |
                    (User.email.ilike(str(ext_mail).strip()) if ext_mail else False)
                ).first()
                if not user:
                    user = User(
                        username=str(ext_uname).strip(),
                        full_name=str(ext_name or ext_uname).replace(".", " ").title(),
                        email=str(ext_mail) if ext_mail else f"{ext_uname}@enterprise.corp",
                        role="itsm_read",
                        active=True
                    )
                    db.add(user)
                    db.commit()
                    db.refresh(user)
                if user:
                    return user
        except Exception:
            pass

        # 2. Try Keycloak if enabled
        if keycloak_enabled():
            claims = _validate_token(token)
            email = (claims.get("email") or "").lower()
            domain = os.getenv("ACCENTURE_EMAIL_DOMAIN", "accenture.com").lower()
            if not email or not email.endswith(f"@{domain}"):
                raise HTTPException(status_code=403, detail="Only Accenture SSO accounts may access this portal")

            subject = str(claims["sub"])
            user = db.query(User).filter(User.keycloak_subject == subject).first()
            full_name = claims.get("name") or " ".join(filter(None, [claims.get("given_name"), claims.get("family_name")])) or email
            if not user:
                user = User(
                    keycloak_subject=subject,
                    employee_id=claims.get("employee_id") or claims.get("preferred_username") or subject,
                    username=claims.get("preferred_username") or email.split("@", 1)[0],
                    full_name=full_name,
                    first_name=claims.get("given_name"), last_name=claims.get("family_name"), email=email,
                    department=claims.get("department"), location=claims.get("location"), role=_user_role(claims, db), active=True,
                )
                db.add(user)
            else:
                user.full_name, user.email, user.role, user.active = full_name, email, _user_role(claims, db), True
            db.commit()
            db.refresh(user)

            # Sync IM group memberships from JWT claims → UserCustomGroup table
            # Keycloak emits groups as ["/<group-name>", ...] or ["/project-name-admin", ...]
            try:
                from backend.models import UserCustomGroup, CustomGroup
                raw_groups = claims.get("groups", claims.get("im_groups", claims.get("distribution_lists", [])))
                if isinstance(raw_groups, str):
                    raw_groups = [raw_groups]
                jwt_group_names = {str(g).lstrip("/").strip() for g in (raw_groups or []) if g}
                if jwt_group_names:
                    # Resolve existing CustomGroup records and sync UserCustomGroup rows
                    for gname in jwt_group_names:
                        cg_obj = db.query(CustomGroup).filter(CustomGroup.name == gname).first()
                        if not cg_obj:
                            # Auto-create the CustomGroup record for this IM group
                            cg_obj = CustomGroup(name=gname, description=f"IM group: {gname}", permissions="[]", active=True)
                            db.add(cg_obj)
                            db.flush()
                        existing_ucg = db.query(UserCustomGroup).filter(
                            UserCustomGroup.user_id == user.id,
                            UserCustomGroup.custom_group_id == cg_obj.id
                        ).first()
                        if not existing_ucg:
                            db.add(UserCustomGroup(user_id=user.id, custom_group_id=cg_obj.id))
                    # Remove stale UserCustomGroup rows for groups the user no longer belongs to
                    current_ucgs = db.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id).all()
                    for ucg in current_ucgs:
                        cg_obj = db.query(CustomGroup).filter(CustomGroup.id == ucg.custom_group_id).first()
                        if cg_obj and cg_obj.name not in jwt_group_names:
                            db.delete(ucg)
                    db.commit()
                    db.refresh(user)
            except Exception:
                pass

            return user

    # 3. Check for external IM proxy headers (X-User-Name, X-Remote-User, X-User-Email)
    ext_username = (x_user_name or x_remote_user or "").strip()
    ext_email = (x_user_email or "").strip().lower()
    if ext_username or ext_email:
        user = None
        if ext_username:
            user = db.query(User).filter(User.username.ilike(ext_username)).first()
        if not user and ext_email:
            user = db.query(User).filter(User.email.ilike(ext_email)).first()
        if not user and ext_username:
            # Auto-provision user from external IM
            user = User(
                username=ext_username,
                full_name=ext_username.replace(".", " ").title(),
                email=ext_email if ext_email else f"{ext_username}@enterprise.corp",
                role="itsm_read",
                active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            try:
                from backend.models import CustomGroup, UserCustomGroup
                for s_name in ["IM_SAML", "ATR_SAML"]:
                    saml_cg = db.query(CustomGroup).filter(CustomGroup.name == s_name).first()
                    if saml_cg and not db.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id, UserCustomGroup.custom_group_id == saml_cg.id).first():
                        db.add(UserCustomGroup(user_id=user.id, custom_group_id=saml_cg.id))
                db.commit()
                db.refresh(user)
            except Exception:
                pass
        if user:
            return user

    if x_user_id and str(x_user_id).isdigit():
        uid = int(x_user_id)
        user = db.query(User).filter(User.id == uid).first()
        seed_demo = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")
        if not user and seed_demo and uid in LOCAL_PERSONAS:
            user = _ensure_local_persona(uid, db)
        if user and seed_demo:
            for pid, pinfo in LOCAL_PERSONAS.items():
                if user.username == pinfo["username"]:
                    _ensure_local_persona(pid, db)
                    break
        if user:
            return user

    if not keycloak_enabled():
        # Deliberately isolated to local mode; admin APIs do not use this
        # fallback when Keycloak is configured.
        user = db.query(User).filter(User.id == 1).first() or db.query(User).first()
        if not user:
            raise HTTPException(status_code=404, detail="No users found in system")
        return user

def get_session_user(db: Session, x_user_id: Optional[str] = None) -> User:
    user_id = 1
    if x_user_id and str(x_user_id).isdigit():
        user_id = int(x_user_id)
    user = db.query(User).filter(User.id == user_id).first()
    seed_demo = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")
    if not user and seed_demo:
        user = _ensure_local_persona(user_id, db)
    return user or db.query(User).first()

def get_user_scopes(user: User, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Evaluates user scopes across global admin, project-scoped admin, project-scoped user, and end-user:
    - is_global_admin: True if user is the platform administrator (only local admin or global itsm_admin)
    - admin_projects: list of project names the user has admin rights for (e.g. ['AMS-IMS'])
    - support_projects: list of project names the user is a fulfiller for (e.g. ['AMS-IMS'])
    - is_support_member: True if user belongs to any support DL or has fulfiller/admin permissions
    - is_end_user: True if user only has end-user permissions (IM_SAML / requester)
    """
    c_groups = [cg.custom_group.name for cg in user.custom_groups if cg.custom_group] if hasattr(user, "custom_groups") and user.custom_groups else []
    if not c_groups and hasattr(user, "id") and user.id:
        try:
            from backend.database import SessionLocal
            from backend.models import UserCustomGroup, CustomGroup
            s = db or SessionLocal()
            ucgs = s.query(UserCustomGroup).filter(UserCustomGroup.user_id == user.id).all()
            for ucg in ucgs:
                cg_obj = s.query(CustomGroup).filter(CustomGroup.id == ucg.custom_group_id).first()
                if cg_obj and cg_obj.name not in c_groups:
                    c_groups.append(cg_obj.name)
            if not db:
                s.close()
        except Exception:
            pass

    # 1. Global Admin Check: only the fixed local admin or platform itsm_admin
    is_global_admin = (user.username == "admin") or (getattr(user, "is_local", False) and user.role in ["administrator", "itsm_admin"]) or ("itsm_admin" in c_groups and not any(cg.endswith("-admin") for cg in c_groups))

    # 2. Project Admin Scopes: extract projects from IM groups
    # Rules:
    #   <project>-admin  or <project>_admin  -> Project Administrator (full project admin)
    #   <project>-l2-admin / <project>-l3-admin -> same, with tier context
    #   <project>-user   or <project>_user   -> Project Fulfiller / Support Engineer (support_projects only, NOT admin)
    #   <project>-read   or <project>_read   -> Read-only (no admin, no fulfiller)
    admin_projects = []
    support_projects = []

    def _strip_suffix(name: str, suffix: str) -> str:
        """Strip -suffix or _suffix from a group name, return base project name."""
        for sep in ("-", "_"):
            if name.lower().endswith(sep + suffix):
                return name[:-(len(sep) + len(suffix))].strip()
        return ""

    for cg in c_groups:
        cg_lower = cg.lower()
        # Skip platform-level admin groups — these are handled by is_global_admin
        if cg_lower in ("itsm-admin", "itsm_admin", "itsm-admins", "itsm_admins", "itsm admins"):
            continue

        # -admin / _admin  →  Project Administrator
        if cg_lower.endswith("-admin") or cg_lower.endswith("_admin"):
            p_name = _strip_suffix(cg, "admin")
            if not p_name:
                continue
            # Strip optional tier suffix: <project>-l2-admin → <project>
            base_p = p_name
            if base_p.lower().endswith("-l2") or base_p.lower().endswith("-l3") or \
               base_p.lower().endswith("_l2") or base_p.lower().endswith("_l3"):
                base_p = base_p[:-3].strip()
            for proj in set(filter(None, [p_name, base_p])):
                if proj not in admin_projects:
                    admin_projects.append(proj)
                if proj not in support_projects:
                    support_projects.append(proj)

        # -user / _user  →  Fulfiller / Support Engineer (NOT admin)
        elif cg_lower.endswith("-user") or cg_lower.endswith("_user"):
            if cg_lower in ("itsm-user", "itsm_user"):
                continue
            p_name = _strip_suffix(cg, "user")
            if not p_name:
                continue
            base_p = p_name
            if base_p.lower().endswith("-l2") or base_p.lower().endswith("-l3") or \
               base_p.lower().endswith("_l2") or base_p.lower().endswith("_l3"):
                base_p = base_p[:-3].strip()
            for proj in set(filter(None, [p_name, base_p])):
                if proj not in support_projects:
                    support_projects.append(proj)
            # NOTE: -user does NOT grant admin_projects

        # -read / _read  →  Read-only (no fulfiller or admin rights granted via this path)
        # (user will still be recognised as a support member, but with read-only scope)


    # 2.5 Respective project support members of respective assignment groups are admins of that particular project only
    if not is_global_admin and (user.role in ["support_member", "group_manager", "itsm_user"] or hasattr(user, "memberships") or getattr(user, "id", None)):
        try:
            from backend.database import SessionLocal
            from backend.models import GroupMember, AssignmentGroup, Project, ProjectAssignmentMapping
            s = db or SessionLocal()
            grp_ids = []
            if hasattr(user, "memberships") and user.memberships:
                grp_ids.extend([m.group_id for m in user.memberships if getattr(m, "group_id", None)])
            if getattr(user, "id", None):
                member_records = s.query(GroupMember).filter(GroupMember.user_id == user.id).all()
                grp_ids.extend([m.group_id for m in member_records if m.group_id])
                managed_groups = s.query(AssignmentGroup).filter(AssignmentGroup.manager_id == user.id).all()
                grp_ids.extend([g.id for g in managed_groups])

            grp_ids = list(set(grp_ids))
            for gid in grp_ids:
                ag = s.query(AssignmentGroup).filter(AssignmentGroup.id == gid).first()
                if not ag:
                    continue
                # a. Projects directly listed in projects_supported
                try:
                    p_list = json.loads(ag.projects_supported or "[]")
                    for p in p_list:
                        if isinstance(p, str) and p.strip() and p.strip() not in admin_projects:
                            admin_projects.append(p.strip())
                            if p.strip() not in support_projects:
                                support_projects.append(p.strip())
                except Exception:
                    pass

                # b. Group name convention: <project>-l2, <project>-l3
                g_name = ag.name.strip()
                if g_name.lower().endswith("-l2") or g_name.lower().endswith("-l3"):
                    p_cand = g_name[:-3].strip()
                    if p_cand and p_cand not in admin_projects:
                        admin_projects.append(p_cand)
                        if p_cand not in support_projects:
                            support_projects.append(p_cand)

                # c. Default assignment group on Project
                projs = s.query(Project).filter(Project.default_assignment_group_id == ag.id).all()
                for p in projs:
                    if p.name and p.name not in admin_projects:
                        admin_projects.append(p.name)
                        if p.name not in support_projects:
                            support_projects.append(p.name)

                # d. ProjectAssignmentMapping
                maps = s.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.assignment_group_id == ag.id).all()
                for m in maps:
                    if m.project and m.project.name and m.project.name not in admin_projects:
                        admin_projects.append(m.project.name)
                        if m.project.name not in support_projects:
                            support_projects.append(m.project.name)

            if not db:
                s.close()
        except Exception:
            pass

    # Fallback for local personas when DB has not linked groups yet
    if not is_global_admin and not admin_projects and not support_projects:
        u_name = getattr(user, "username", "")
        if u_name == "sarah.johnson":
            admin_projects.append("Payment Platform Modernization")
            support_projects.append("Payment Platform Modernization")
        elif u_name == "david.wilson":
            admin_projects.append("Customer Portal Modernization")
            support_projects.append("Customer Portal Modernization")
        elif u_name == "mike.brown":
            admin_projects.append("Cloud Migration")
            support_projects.append("Cloud Migration")
        elif u_name == "john.smith":
            support_projects.append("Customer Portal Modernization")

    # 3. Support Member / Fulfiller Check
    has_assignment_group = len(user.memberships) > 0 if hasattr(user, "memberships") and user.memberships else False
    has_saml_enduser = any(cg.upper() in ["IM_SAML", "ATR_SAML"] for cg in c_groups)

    if is_global_admin or bool(admin_projects):
        is_end_user = False
        is_support_member = True
    elif getattr(user, "username", "") == "john.smith" or getattr(user, "role", "") in ["employee", "itsm_read", "im_saml", "atr_saml"] or (has_saml_enduser and not has_assignment_group):
        is_end_user = True
        is_support_member = False
    else:
        is_support_member = (
            user.role in ["support_member", "group_manager", "itsm_user"] or
            bool(support_projects) or
            has_assignment_group or
            any(cg in ["itsm_user", "Service Desk", "ITSM-Fulfillers", "Tier1-Support", "ITSM-Admins"] for cg in c_groups)
        )
        is_end_user = not is_support_member

    return {
        "is_global_admin": is_global_admin,
        "admin_projects": admin_projects,
        "support_projects": support_projects,
        "is_support_member": is_support_member,
        "is_end_user": is_end_user,
        "custom_groups": c_groups
    }

def get_user_project_boundaries(user: User, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Evaluates project scoping boundaries for querying and viewing tickets:
    - is_global_admin: True for global admin user -> sees all tickets across all projects.
    - is_end_user: True for end user -> sees ONLY own tickets (caller_id == user.id or requested_by_id == user.id).
    - is_support_member: True for project support engineers / group admins.
    - project_ids: list of project primary key IDs the user belongs to / supports.
    - project_names: list of project names the user belongs to / supports.
    - application_ids: list of application IDs belonging to those projects.
    """
    scopes = get_user_scopes(user, db)
    if scopes["is_global_admin"]:
        return {
            "is_global_admin": True,
            "is_end_user": False,
            "is_support_member": True,
            "project_ids": [],
            "project_names": [],
            "application_ids": []
        }

    if scopes["is_end_user"]:
        return {
            "is_global_admin": False,
            "is_end_user": True,
            "is_support_member": False,
            "project_ids": [],
            "project_names": [],
            "application_ids": []
        }

    from backend.models import Project, Application, AssignmentGroup, GroupMember, ProjectAssignmentMapping
    from sqlalchemy import or_

    close_s = False
    s = db
    if not s:
        from backend.database import SessionLocal
        s = SessionLocal()
        close_s = True

    try:
        user_p_names = list(set(scopes.get("admin_projects", []) + scopes.get("support_projects", [])))
        user_group_ids = [m.group_id for m in user.memberships if getattr(m, "group_id", None)] if hasattr(user, "memberships") and user.memberships else []
        if getattr(user, "id", None):
            for gm in s.query(GroupMember).filter(GroupMember.user_id == user.id).all():
                if gm.group_id and gm.group_id not in user_group_ids:
                    user_group_ids.append(gm.group_id)
            for mg in s.query(AssignmentGroup).filter(AssignmentGroup.manager_id == user.id).all():
                if mg.id not in user_group_ids:
                    user_group_ids.append(mg.id)

        for gid in user_group_ids:
            ag = s.query(AssignmentGroup).filter(AssignmentGroup.id == gid).first()
            if ag:
                try:
                    p_list = json.loads(ag.projects_supported or "[]")
                    for p in p_list:
                        if p and p not in user_p_names:
                            user_p_names.append(p)
                except Exception:
                    pass
                if ag.name and (ag.name.endswith("-l2") or ag.name.endswith("-l3")):
                    cand = ag.name[:-3].strip()
                    if cand and cand not in user_p_names:
                        user_p_names.append(cand)
                for p in s.query(Project).filter(or_(
                    Project.default_assignment_group_id == ag.id,
                    Project.l2_assignment_group_id == ag.id,
                    Project.l3_assignment_group_id == ag.id
                )).all():
                    if p.name and p.name not in user_p_names:
                        user_p_names.append(p.name)
                for m in s.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.assignment_group_id == ag.id).all():
                    if m.project and m.project.name and m.project.name not in user_p_names:
                        user_p_names.append(m.project.name)

        projs = s.query(Project).filter(Project.name.in_(user_p_names)).all() if user_p_names else []
        proj_ids = [p.id for p in projs]
        proj_names = [p.name for p in projs]

        apps = s.query(Application).filter(or_(
            Application.project_id.in_(proj_ids),
            Application.name.in_(proj_names)
        )).all() if (proj_ids or proj_names) else []
        app_ids = [a.id for a in apps]

        return {
            "is_global_admin": False,
            "is_end_user": False,
            "is_support_member": True,
            "project_ids": proj_ids,
            "project_names": proj_names,
            "application_ids": app_ids
        }
    finally:
        if close_s:
            s.close()

def require_admin(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    scopes = get_user_scopes(current_user, db)
    if not (scopes["is_global_admin"] or bool(scopes["admin_projects"])):
        raise HTTPException(status_code=403, detail="Administrator role is required")
    return current_user

def require_global_admin(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    scopes = get_user_scopes(current_user, db)
    if not scopes["is_global_admin"]:
        raise HTTPException(status_code=403, detail="Global platform administrator access is required")
    return current_user

def can_edit_project_oncall(user: User, project_name: str, db: Optional[Session] = None) -> bool:
    """
    Checks if a user is permitted to update On-Call and Escalations for a given project:
    - Global admin (admin / itsm_admin): can edit across ALL projects.
    - Project admins: members with <project>-l2-admin, <project>-l3-admin, <project>-admin, or <project>_admin.
    """
    scopes = get_user_scopes(user, db)
    if scopes["is_global_admin"]:
        return True
    
    clean_p = project_name.strip().lower()
    allowed_lowers = [p.lower() for p in scopes["admin_projects"]]
    if clean_p in allowed_lowers:
        return True
    
    c_groups = [g.lower() for g in scopes["custom_groups"]]
    if any(
        cg in c_groups for cg in [
            f"{clean_p}-l2-admin", f"{clean_p}_l2_admin",
            f"{clean_p}-l3-admin", f"{clean_p}_l3_admin",
            f"{clean_p}-admin", f"{clean_p}_admin"
        ]
    ):
        return True
    
    return False

