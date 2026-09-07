import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import User
from backend.security import get_current_user as get_authenticated_user, keycloak_enabled, require_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.get("/config")
def get_auth_config():
    """Public SPA configuration; does not expose secrets."""
    issuer = os.getenv("KEYCLOAK_ISSUER", "").rstrip("/")
    realm = issuer.rsplit("/realms/", 1)[-1] if "/realms/" in issuer else ""
    base_url = issuer.rsplit("/realms/", 1)[0] if realm else ""
    return {"enabled": keycloak_enabled(), "url": base_url, "realm": realm, "clientId": os.getenv("KEYCLOAK_CLIENT_ID", "nexus-itsm")}

@router.get("/users")
def get_available_users(db: Session = Depends(get_db), current_user: User = Depends(get_authenticated_user)):
    """Returns list of users for switching personas in the UI."""
    from backend.security import keycloak_enabled, LOCAL_PERSONAS, _ensure_local_persona
    seed_demo = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")
    if seed_demo:
        for uid in LOCAL_PERSONAS:
            _ensure_local_persona(uid, db)

    users = db.query(User).filter(User.active == True).all()
    return [u.to_dict() for u in users]

@router.get("/current")
def get_current_user(
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db)
):
    """
    Returns the authenticated Keycloak user, or the seeded demo administrator
    when SSO has not been configured for local development.
    """
    # Add user's assignment group IDs
    group_ids = [m.group_id for m in current_user.memberships]
    data = current_user.to_dict()
    data["assignment_group_ids"] = group_ids
    from backend.security import get_user_project_boundaries
    data["project_boundaries"] = get_user_project_boundaries(current_user, db)
    return data
