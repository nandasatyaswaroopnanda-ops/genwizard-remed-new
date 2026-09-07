"""
Tests for SLA Policy Management, Response & Resolution SLA Editing,
and Role-Based Scoped Permissions for Global Admin, Group/Project Admins, and End Users.
"""
import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    User, Project, Application, AssignmentGroup, CustomGroup,
    UserCustomGroup, SLAPolicy
)

client = TestClient(app)

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_sla_admin_permissions_and_editing(db_session):
    """
    Test that:
    1. Global admin can view all SLAs and edit any SLA.
    2. Group / Project admin can view SLAs and edit response & resolution SLA for their own project/group.
    3. Group / Project admin is blocked (403) from editing SLAs of other projects.
    4. End user is blocked (403) from updating SLAs.
    5. Versioned updates create a new version while preserving the old version.
    """
    # 1. Setup entities
    app_ent = Application(app_id="APP-SLA-TEST", name="SLA Test App", criticality="High", active=True)
    db_session.add(app_ent)
    db_session.commit()

    proj_alpha = Project(project_id="PRJ-ALPHA", name="Project Alpha", application_id=app_ent.id, criticality="High", active=True)
    proj_beta = Project(project_id="PRJ-BETA", name="Project Beta", application_id=app_ent.id, criticality="High", active=True)
    db_session.add_all([proj_alpha, proj_beta])
    db_session.commit()

    grp_alpha_l2 = AssignmentGroup(group_id="GRP-ALPHA-L2", name="Project Alpha-l2", active=True)
    grp_beta_l2 = AssignmentGroup(group_id="GRP-BETA-L2", name="Project Beta-l2", active=True)
    db_session.add_all([grp_alpha_l2, grp_beta_l2])
    db_session.commit()

    # Create SLAs: one for Project Alpha, one for Project Beta
    sla_alpha = SLAPolicy(
        policy_code="SLA-ALPHA-P1",
        name="Alpha Critical SLA",
        version=1,
        priority="P1",
        project_id=proj_alpha.id,
        assignment_group_id=grp_alpha_l2.id,
        response_target_mins=15,
        resolution_target_mins=120,
        active=True
    )
    sla_beta = SLAPolicy(
        policy_code="SLA-BETA-P1",
        name="Beta Critical SLA",
        version=1,
        priority="P1",
        project_id=proj_beta.id,
        assignment_group_id=grp_beta_l2.id,
        response_target_mins=20,
        resolution_target_mins=240,
        active=True
    )
    db_session.add_all([sla_alpha, sla_beta])
    db_session.commit()

    # 2. Setup Users:
    # User 1: Global Admin
    u_admin = db_session.query(User).filter(User.username == "admin").first()
    if not u_admin:
        u_admin = User(username="admin", email="admin@corp.local", full_name="System Admin", role="administrator", active=True)
        db_session.add(u_admin)
        db_session.commit()

    # User 2: Project Alpha Group Admin (member of Project Alpha-l2-admin)
    u_alpha_admin = User(username="alpha_lead", email="alpha_lead@corp.local", full_name="Alpha Lead Admin", role="support_member", active=True)
    db_session.add(u_alpha_admin)
    db_session.commit()

    cg_alpha_admin = CustomGroup(name="Project Alpha-l2-admin", description="Admin for Alpha L2", permissions=json.dumps(["project:Project Alpha:admin"]))
    db_session.add(cg_alpha_admin)
    db_session.commit()
    db_session.add(UserCustomGroup(user_id=u_alpha_admin.id, custom_group_id=cg_alpha_admin.id))
    db_session.commit()

    # User 3: End user (IM_SAML)
    u_end_user = User(username="sla_enduser", email="sla_enduser@corp.local", full_name="Regular End User", role="employee", active=True)
    db_session.add(u_end_user)
    db_session.commit()
    cg_im_saml = db_session.query(CustomGroup).filter(CustomGroup.name == "IM_SAML").first()
    if not cg_im_saml:
        cg_im_saml = CustomGroup(name="IM_SAML", description="End Users", permissions=json.dumps([]))
        db_session.add(cg_im_saml)
        db_session.commit()
    db_session.add(UserCustomGroup(user_id=u_end_user.id, custom_group_id=cg_im_saml.id))
    db_session.commit()

    # --- Test 1: GET /api/admin/slas ---
    # Global admin sees all SLAs with can_edit=True
    res_admin = client.get("/api/admin/slas", headers={"X-User-ID": str(u_admin.id)})
    assert res_admin.status_code == 200
    admin_slas = res_admin.json()
    alpha_item_for_admin = next(s for s in admin_slas if s["id"] == sla_alpha.id)
    beta_item_for_admin = next(s for s in admin_slas if s["id"] == sla_beta.id)
    assert alpha_item_for_admin["can_edit"] is True
    assert beta_item_for_admin["can_edit"] is True

    # Alpha Admin sees SLAs, but only can_edit=True for Alpha, can_edit=False for Beta
    res_alpha = client.get("/api/admin/slas", headers={"X-User-ID": str(u_alpha_admin.id)})
    assert res_alpha.status_code == 200
    alpha_user_slas = res_alpha.json()
    alpha_item = next((s for s in alpha_user_slas if s["id"] == sla_alpha.id), None)
    assert alpha_item is not None
    assert alpha_item["can_edit"] is True

    beta_item = next((s for s in alpha_user_slas if s["id"] == sla_beta.id), None)
    if beta_item:
        assert beta_item["can_edit"] is False

    # End user gets 403 on GET
    res_end = client.get("/api/admin/slas", headers={"X-User-ID": str(u_end_user.id)})
    assert res_end.status_code == 403

    # --- Test 2: Alpha Admin updates Response and Resolution SLA for Project Alpha in-place ---
    update_payload = {
        "policy_code": sla_alpha.policy_code,
        "name": "Alpha Critical SLA - Expedited",
        "priority": "P1",
        "project_id": proj_alpha.id,
        "response_target_mins": 10,       # updated from 15
        "resolution_target_mins": 60,      # updated from 120 (1 hour)
        "warning_threshold_pct": 80,
        "active": True,
        "reason": "Expedited response SLA agreed with stakeholders",
        "create_new_version": False
    }
    put_res = client.put(
        f"/api/admin/slas/{sla_alpha.id}",
        json=update_payload,
        headers={"X-User-ID": str(u_alpha_admin.id)}
    )
    assert put_res.status_code == 200
    updated_data = put_res.json()
    assert updated_data["response_target_mins"] == 10
    assert updated_data["resolution_target_mins"] == 60
    assert updated_data["name"] == "Alpha Critical SLA - Expedited"
    assert updated_data["version"] == 1
    assert updated_data["can_edit"] is True

    # --- Test 3: Alpha Admin tries to update Project Beta SLA -> 403 Forbidden ---
    put_beta_res = client.put(
        f"/api/admin/slas/{sla_beta.id}",
        json={
            "policy_code": sla_beta.policy_code,
            "name": "Hacked Beta SLA",
            "priority": "P1",
            "project_id": proj_beta.id,
            "response_target_mins": 5,
            "resolution_target_mins": 30,
            "reason": "Unauthorized modification"
        },
        headers={"X-User-ID": str(u_alpha_admin.id)}
    )
    assert put_beta_res.status_code == 403
    assert "not authorised to modify this SLA policy" in put_beta_res.json()["detail"]

    # --- Test 4: End User tries to update SLA -> 403 Forbidden ---
    put_end_res = client.put(
        f"/api/admin/slas/{sla_alpha.id}",
        json=update_payload,
        headers={"X-User-ID": str(u_end_user.id)}
    )
    assert put_end_res.status_code == 403

    # --- Test 5: Alpha Admin creates new version of Alpha SLA ---
    version_payload = dict(update_payload)
    version_payload["create_new_version"] = True
    version_payload["response_target_mins"] = 8
    version_payload["resolution_target_mins"] = 45
    version_payload["reason"] = "Creating v2 for next quarter"

    v2_res = client.put(
        f"/api/admin/slas/{sla_alpha.id}",
        json=version_payload,
        headers={"X-User-ID": str(u_alpha_admin.id)}
    )
    assert v2_res.status_code == 200
    v2_data = v2_res.json()
    assert v2_data["version"] == 2
    assert v2_data["response_target_mins"] == 8
    assert v2_data["resolution_target_mins"] == 45
    assert v2_data["can_edit"] is True

    # Check that v1 is now archived/deactivated
    fresh_session = SessionLocal()
    old_sla = fresh_session.query(SLAPolicy).filter(SLAPolicy.id == sla_alpha.id).first()
    assert old_sla.active is False
    fresh_session.close()

    # --- Test 6: Alpha Admin creates a new SLA policy for Project Alpha -> 201 ---
    create_payload = {
        "policy_code": "SLA-ALPHA-P2",
        "name": "Alpha High Priority SLA",
        "priority": "P2",
        "project_id": proj_alpha.id,
        "response_target_mins": 30,
        "resolution_target_mins": 240,
        "reason": "Initial P2 setup for Project Alpha"
    }
    create_res = client.post(
        "/api/admin/slas",
        json=create_payload,
        headers={"X-User-ID": str(u_alpha_admin.id)}
    )
    assert create_res.status_code == 201
    created_sla = create_res.json()
    assert created_sla["policy_code"] == "SLA-ALPHA-P2"
    assert created_sla["response_target_mins"] == 30
    assert created_sla["resolution_target_mins"] == 240
    assert created_sla["can_edit"] is True

    # --- Test 7: Alpha Admin tries to create SLA for Project Beta -> 403 ---
    create_beta_payload = dict(create_payload)
    create_beta_payload["policy_code"] = "SLA-BETA-P2"
    create_beta_payload["project_id"] = proj_beta.id
    create_bad_res = client.post(
        "/api/admin/slas",
        json=create_beta_payload,
        headers={"X-User-ID": str(u_alpha_admin.id)}
    )
    assert create_bad_res.status_code == 403


def test_sla_editing_across_types_and_priorities(db_session):
    """
    Verify that:
    1. SLAs can be queried with ticket_type and priority filters.
    2. Response and resolution targets can be configured and edited for P1, P2, P3, P4
       across Incident, Service Request, and Change Request.
    3. Serialized outputs return hours (response_target_hours, resolution_target_hours)
       and human-readable strings (response_target_display, resolution_target_display).
    4. Both in-place and versioned edits update the targets properly.
    """
    # 1. Fetch Global Admin user
    admin = db_session.query(User).filter(User.username == "admin").first()
    assert admin is not None
    admin_headers = {"X-User-ID": str(admin.id)}

    # 2. Query all SLAs for Service Request
    res = client.get("/api/admin/slas?ticket_type=Service+Request", headers=admin_headers)
    assert res.status_code == 200
    req_slas = res.json()
    assert len(req_slas) >= 4  # P1, P2, P3, P4 baseline

    # Verify P1-P4 priorities exist
    req_priorities = {s["priority"] for s in req_slas}
    assert {"P1", "P2", "P3", "P4"}.issubset(req_priorities)

    # 3. Query all SLAs for Change Request
    res_chg = client.get("/api/admin/slas?ticket_type=Change+Request", headers=admin_headers)
    assert res_chg.status_code == 200
    chg_slas = res_chg.json()
    assert len(chg_slas) >= 4
    chg_priorities = {s["priority"] for s in chg_slas}
    assert {"P1", "P2", "P3", "P4"}.issubset(chg_priorities)

    # 4. In-place edit of Service Request P2 SLA
    sr_p2 = next(s for s in req_slas if s["priority"] == "P2")
    sr_p2_id = sr_p2["id"]

    edit_sr_payload = {
        "policy_code": sr_p2["policy_code"],
        "name": "Custom Service Request P2 SLA",
        "ticket_type": "Service Request",
        "priority": "P2",
        "response_target_mins": 45,       # 0.75 hrs
        "resolution_target_mins": 1440,   # 24.0 hrs (1 day)
        "warning_threshold_pct": 80,
        "reason": "Updated Service Request P2 SLA to 45m response and 24h resolution",
        "create_new_version": False
    }
    put_res = client.put(f"/api/admin/slas/{sr_p2_id}", json=edit_sr_payload, headers=admin_headers)
    assert put_res.status_code == 200
    updated_sr = put_res.json()
    assert updated_sr["response_target_mins"] == 45
    assert updated_sr["resolution_target_mins"] == 1440
    assert updated_sr["response_target_hours"] == 0.75
    assert updated_sr["resolution_target_hours"] == 24.0
    assert updated_sr["resolution_target_display"] == "24h (1d)"

    # 5. Versioned edit of Change Request P1 SLA
    chg_p1 = next(s for s in chg_slas if s["priority"] == "P1")
    chg_p1_id = chg_p1["id"]

    version_chg_payload = {
        "policy_code": chg_p1["policy_code"],
        "name": "Expedited Emergency Change SLA",
        "ticket_type": "Change Request",
        "priority": "P1",
        "response_target_mins": 30,       # 0.5 hrs
        "resolution_target_mins": 240,    # 4.0 hrs
        "warning_threshold_pct": 70,
        "reason": "Tightened Emergency Change resolution SLA to 4 hours",
        "create_new_version": True
    }
    v_res = client.put(f"/api/admin/slas/{chg_p1_id}", json=version_chg_payload, headers=admin_headers)
    assert v_res.status_code == 200
    v2_chg = v_res.json()
    assert v2_chg["version"] == chg_p1["version"] + 1
    assert v2_chg["response_target_mins"] == 30
    assert v2_chg["resolution_target_mins"] == 240
    assert v2_chg["response_target_hours"] == 0.5
    assert v2_chg["resolution_target_hours"] == 4.0
    assert v2_chg["active"] is True

    # 6. Verify old version of Change Request P1 is inactive
    old_p1_res = db_session.query(SLAPolicy).filter(SLAPolicy.id == chg_p1_id).first()
    assert old_p1_res.active is False

