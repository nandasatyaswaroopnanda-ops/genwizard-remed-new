import os
import pytest
from backend.models import User, Project, Application, Incident, ServiceRequest, ChangeRequest, AssignmentGroup
from backend.seed_data import init_db_and_seed
from backend.database import SessionLocal

def test_production_initializes_clean_and_blank():
    """Verify that when SEED_DEMO_DATA is false (production mode), the database
    is completely clean and blank with zero demo tickets, zero demo apps,
    zero demo projects, zero demo users (only admin), and zero fake queues."""
    old_env = os.environ.get("SEED_DEMO_DATA")
    try:
        os.environ["SEED_DEMO_DATA"] = "false"
        init_db_and_seed()
        db = SessionLocal()
        try:
            users = db.query(User).all()
            projs = db.query(Project).all()
            apps = db.query(Application).all()
            incs = db.query(Incident).all()
            reqs = db.query(ServiceRequest).all()
            chgs = db.query(ChangeRequest).all()
            groups = db.query(AssignmentGroup).all()

            # Only admin user exists
            assert len(users) == 1, f"Expected 1 user, got {len(users)}"
            assert users[0].username == "admin", f"Expected admin, got {users[0].username}"

            # Projects and Applications must be 100% blank
            assert len(projs) == 0, f"Expected 0 projects, got {len(projs)}"
            assert len(apps) == 0, f"Expected 0 applications, got {len(apps)}"

            # Tickets must be 100% blank
            assert len(incs) == 0, f"Expected 0 incidents, got {len(incs)}"
            assert len(reqs) == 0, f"Expected 0 service requests, got {len(reqs)}"
            assert len(chgs) == 0, f"Expected 0 change requests, got {len(chgs)}"

            # Only baseline global Service Desk fallback queue exists
            assert len(groups) == 1, f"Expected 1 fallback group, got {len(groups)}"
            assert groups[0].name == "Service Desk", f"Expected 'Service Desk', got {groups[0].name}"
        finally:
            db.close()
    finally:
        os.environ["SEED_DEMO_DATA"] = "true"
        init_db_and_seed()
        if old_env is not None and old_env != "true":
            os.environ["SEED_DEMO_DATA"] = old_env
