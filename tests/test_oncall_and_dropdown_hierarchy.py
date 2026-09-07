"""
Tests for Incident Hierarchical Routing, 6 Scoped IM Groups, Assignee Filtering,
and Project & Application On-Call and Escalation Matrix.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    User, Project, Application, AssignmentGroup, CustomGroup,
    UserCustomGroup, GroupMember, Incident
)
from backend.routes.admin_projects import setup_project_queues_and_groups

client = TestClient(app)

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_setup_project_generates_six_scoped_im_groups(db_session):
    """Verify setup_project_queues_and_groups generates the 6 scoped IM groups and queues."""
    proj_name = "PAYMENTS-V3"

    with patch("requests.post") as mock_im:
        mock_im.return_value = MagicMock(status_code=201, text="{}")
        grp_l2, grp_l3 = setup_project_queues_and_groups(db_session, proj_name)

        # Assignment groups created
        assert grp_l2.name == f"{proj_name}-l2"
        assert grp_l3.name == f"{proj_name}-l3"
        assert grp_l2.escalation_group_id == grp_l3.id

        # 6 Scoped IM groups
        expected_groups = [
            f"{proj_name}-l2-admin",
            f"{proj_name}-l2-user",
            f"{proj_name}-l2-read",
            f"{proj_name}-l3-admin",
            f"{proj_name}-l3-user",
            f"{proj_name}-l3-read",
            f"{proj_name}-admin",
            f"{proj_name}-user",
            f"{proj_name}-read"
        ]
        for gname in expected_groups:
            cg = db_session.query(CustomGroup).filter(CustomGroup.name == gname).first()
            assert cg is not None, f"CustomGroup {gname} must be auto-created"
            perms = json.loads(cg.permissions)
            if "-l2-admin" in gname or "-l3-admin" in gname:
                assert f"project:{proj_name}:admin" in perms
                assert f"project:{proj_name}:oncall" in perms


def test_assignment_group_assignee_filtering_from_im_groups(db_session):
    """Verify that users belonging to IM groups are resolved in eligible_assignees for that queue."""
    proj_name = "FIN-GATEWAY"

    with patch("requests.post") as mock_im:
        mock_im.return_value = MagicMock(status_code=201, text="{}")
        grp_l2, grp_l3 = setup_project_queues_and_groups(db_session, proj_name)

    # Create test users
    u_l2_lead = User(username="l2_lead", email="l2_lead@corp.local", full_name="L2 Lead", role="support_member", active=True)
    u_l3_eng = User(username="l3_eng", email="l3_eng@corp.local", full_name="L3 Engineer", role="support_member", active=True)
    u_outsider = User(username="outsider", email="outsider@corp.local", full_name="Outsider", role="employee", active=True)
    db_session.add_all([u_l2_lead, u_l3_eng, u_outsider])
    db_session.commit()

    # Attach users to corresponding CustomGroups
    cg_l2_admin = db_session.query(CustomGroup).filter(CustomGroup.name == f"{proj_name}-l2-admin").first()
    cg_l3_user = db_session.query(CustomGroup).filter(CustomGroup.name == f"{proj_name}-l3-user").first()

    db_session.add(UserCustomGroup(user_id=u_l2_lead.id, custom_group_id=cg_l2_admin.id))
    db_session.add(UserCustomGroup(user_id=u_l3_eng.id, custom_group_id=cg_l3_user.id))
    db_session.commit()

    # Query groups by project_name
    res = client.get(f"/api/assignment-groups?project_name={proj_name}")
    assert res.status_code == 200
    groups = res.json()

    l2_info = next((g for g in groups if g["name"] == f"{proj_name}-l2"), None)
    l3_info = next((g for g in groups if g["name"] == f"{proj_name}-l3"), None)
    assert l2_info is not None
    assert l3_info is not None

    l2_assignee_ids = [a["id"] for a in l2_info.get("eligible_assignees", [])]
    l3_assignee_ids = [a["id"] for a in l3_info.get("eligible_assignees", [])]

    assert u_l2_lead.id in l2_assignee_ids
    assert u_l3_eng.id not in l2_assignee_ids
    assert u_outsider.id not in l2_assignee_ids

    assert u_l3_eng.id in l3_assignee_ids
    assert u_l2_lead.id not in l3_assignee_ids


def test_on_call_roster_get_and_put_by_admin(db_session):
    """Verify retrieval and updating of project and application on-call / escalation contacts."""
    app_ent = Application(
        app_id="APP-CORE-PAY",
        name="Core Payments Engine",
        criticality="Critical",
        active=True
    )
    db_session.add(app_ent)
    db_session.commit()

    proj = Project(
        project_id="PRJ-PAY-HUB",
        name="Payments Hub",
        application_id=app_ent.id,
        criticality="Critical",
        active=True
    )
    db_session.add(proj)
    db_session.commit()
    app_ent.project_id = proj.id
    db_session.add(app_ent)   # re-register so MongoDAL tracks the mutation
    db_session.commit()

    # Admin updates on-call contacts
    payload = {
        "l2_on_call_contact": "payments-l2-oncall@corp.local",
        "l3_on_call_contact": "payments-l3-oncall@corp.local",
        "first_escalation_contact": "payments-team-lead@corp.local",
        "second_escalation_contact": "payments-director@corp.local",
        "application_on_calls": {
            "Core Payments Engine": "app-payments-sre@corp.local"
        },
        "application_first_escalations": {
            "Core Payments Engine": "app-payments-lead@corp.local"
        },
        "application_second_escalations": {
            "Core Payments Engine": "app-payments-vp@corp.local"
        }
    }

    put_res = client.put(f"/api/admin/projects/{proj.id}/on-call", json=payload, headers={"X-User-ID": "1"})
    assert put_res.status_code == 200
    data = put_res.json()
    assert data["l2_on_call_contact"] == "payments-l2-oncall@corp.local"
    assert data["l3_on_call_contact"] == "payments-l3-oncall@corp.local"
    assert data["first_escalation_contact"] == "payments-team-lead@corp.local"
    assert data["second_escalation_contact"] == "payments-director@corp.local"

    # Verify application on-call via GET single project on-call (uses a fresh session inside endpoint)
    get_res = client.get(f"/api/admin/projects/{proj.id}/on-call")
    assert get_res.status_code == 200
    single_data = get_res.json()
    assert single_data["project_name"] == "Payments Hub"
    assert single_data["l2_on_call_contact"] == "payments-l2-oncall@corp.local"

    # Verify application-level on-call from the GET response
    app_info = next((a for a in single_data["applications"] if a["name"] == "Core Payments Engine"), None)
    assert app_info is not None, "Core Payments Engine app should appear in on-call roster"
    assert app_info["on_call_contact"] == "app-payments-sre@corp.local"
    assert app_info["first_escalation_contact"] == "app-payments-lead@corp.local"
    assert app_info["second_escalation_contact"] == "app-payments-vp@corp.local"

    # Verify GET all on-call roster
    roster_res = client.get("/api/admin/projects/on-call-roster")
    assert roster_res.status_code == 200
    roster = roster_res.json()
    assert any(p["project_name"] == "Payments Hub" for p in roster)


def test_on_call_update_authorization_scoped_project_admin_vs_forbidden(db_session):
    """Verify scoped project admins can edit their own project on-call, but other users cannot."""
    proj = Project(
        project_id="PRJ-SCOPED-AUTH",
        name="Secured Project",
        criticality="High",
        active=True
    )
    db_session.add(proj)
    db_session.commit()

    # User 1: Member of Secured Project's L2 admin group
    u_proj_admin = User(username="sec_l2_admin", email="sec_l2_admin@corp.local", full_name="Sec L2 Admin", role="support_member", active=True)
    # User 2: Member of another project's admin group
    u_other_admin = User(username="other_admin", email="other_admin@corp.local", full_name="Other Admin", role="support_member", active=True)
    # User 3: Standard end user
    u_end_user = User(username="end_user_bill", email="bill@corp.local", full_name="Bill Requester", role="employee", active=True)
    db_session.add_all([u_proj_admin, u_other_admin, u_end_user])
    db_session.commit()

    cg_sec_admin = CustomGroup(name="Secured Project-l2-admin", description="L2 Admin for Secured Project", permissions=json.dumps([]))
    cg_other_admin = CustomGroup(name="Other Project-admin", description="Admin for Other", permissions=json.dumps([]))
    cg_im_saml = CustomGroup(name="IM_SAML", description="End Users", permissions=json.dumps([]))
    db_session.add_all([cg_sec_admin, cg_other_admin, cg_im_saml])
    db_session.commit()

    db_session.add(UserCustomGroup(user_id=u_proj_admin.id, custom_group_id=cg_sec_admin.id))
    db_session.add(UserCustomGroup(user_id=u_other_admin.id, custom_group_id=cg_other_admin.id))
    db_session.add(UserCustomGroup(user_id=u_end_user.id, custom_group_id=cg_im_saml.id))
    db_session.commit()

    payload = {"l2_on_call_contact": "scoped-update@corp.local"}

    # 1. Project L2 Admin updating own project -> 200 OK
    res_ok = client.put(f"/api/admin/projects/{proj.id}/on-call", json=payload, headers={"X-User-ID": str(u_proj_admin.id)})
    assert res_ok.status_code == 200

    # 2. Other Project Admin updating -> 403 Forbidden
    res_other = client.put(f"/api/admin/projects/{proj.id}/on-call", json=payload, headers={"X-User-ID": str(u_other_admin.id)})
    assert res_other.status_code == 403

    # 3. End User updating -> 403 Forbidden
    res_end = client.put(f"/api/admin/projects/{proj.id}/on-call", json=payload, headers={"X-User-ID": str(u_end_user.id)})
    assert res_end.status_code == 403


def test_incident_reassign_multi_fields_priority_and_groups(db_session):
    """Verify support member can reassign project, application, independent priority, group, and member in one call."""
    app1 = Application(app_id="APP-RT-1", name="App One", criticality="High", active=True)
    app2 = Application(app_id="APP-RT-2", name="App Two", criticality="Critical", active=True)
    db_session.add_all([app1, app2])
    db_session.commit()

    proj1 = Project(project_id="PRJ-RT-1", name="Project One", application_id=app1.id, criticality="High", active=True)
    proj2 = Project(project_id="PRJ-RT-2", name="Project Two", application_id=app2.id, criticality="Critical", active=True)
    db_session.add_all([proj1, proj2])
    db_session.commit()

    grp1 = AssignmentGroup(group_id="GRP-PRJ1-L2", name="Project One-l2", description="L2", active=True)
    grp2 = AssignmentGroup(group_id="GRP-PRJ2-L3", name="Project Two-l3", description="L3", active=True)
    db_session.add_all([grp1, grp2])
    db_session.commit()

    u_support = User(username="support_eng", email="support@corp.local", full_name="Support Engineer", role="support_member", active=True)
    u_engineer = User(username="expert_eng", email="expert@corp.local", full_name="Expert Engineer", role="support_member", active=True)
    db_session.add_all([u_support, u_engineer])
    db_session.commit()

    # Initial incident created with P3
    inc = Incident(
        number="INC990001",
        short_description="Multi field routing test",
        description="Routing test description",
        status="New",
        priority="P3",
        impact="Medium",
        urgency="Medium",
        category="Application",
        project_id=proj1.id,
        application_id=app1.id,
        assignment_group_id=grp1.id,
        caller_id=u_support.id
    )
    db_session.add(inc)
    db_session.commit()

    # Support reassigns to Project Two, App Two, Priority P1, Assignment Group Two-l3, Assigned To Expert
    reassign_payload = {
        "project_id": proj2.id,
        "application_id": app2.id,
        "priority": "P1",
        "assignment_group_id": grp2.id,
        "assigned_to_id": u_engineer.id
    }

    reassign_res = client.patch(
        f"/api/incidents/{inc.number}/assign",
        json=reassign_payload,
        headers={"X-User-ID": str(u_support.id)}
    )
    assert reassign_res.status_code == 200
    res_data = reassign_res.json()

    assert res_data["project_id"] == proj2.id
    assert res_data["application_id"] == app2.id
    assert res_data["priority"] == "P1"
    assert res_data["assignment_group_id"] == grp2.id
    assert res_data["assigned_to_id"] == u_engineer.id


def test_end_user_reassign_forbidden_and_create_auto_routes_to_l2(db_session):
    """Verify end user cannot reassign and created tickets auto-route to <project>-l2."""
    app_ent = Application(app_id="APP-EU-1", name="Self Service App", criticality="Medium", active=True)
    db_session.add(app_ent)
    db_session.commit()

    proj = Project(project_id="PRJ-EU-1", name="Self Service Project", application_id=app_ent.id, criticality="Medium", active=True)
    db_session.add(proj)
    db_session.commit()

    # Add groups FIRST so IDs get assigned before we reference grp_l2.id
    grp_l2 = AssignmentGroup(group_id="GRP-EU-L2", name="Self Service Project-l2", description="L2", active=True)
    grp_l3 = AssignmentGroup(group_id="GRP-EU-L3", name="Self Service Project-l3", description="L3", active=True)
    db_session.add_all([grp_l2, grp_l3])
    db_session.commit()

    # Now that grp_l2.id is assigned, set the project default and persist
    proj.default_assignment_group_id = grp_l2.id
    db_session.commit()

    u_end_user = User(username="end_user_carol", email="carol@corp.local", full_name="Carol User", role="employee", active=True)
    db_session.add(u_end_user)
    db_session.commit()

    cg_im_saml = db_session.query(CustomGroup).filter(CustomGroup.name == "IM_SAML").first()
    if not cg_im_saml:
        cg_im_saml = CustomGroup(name="IM_SAML", description="End Users", permissions=json.dumps([]))
        db_session.add(cg_im_saml)
        db_session.commit()

    db_session.add(UserCustomGroup(user_id=u_end_user.id, custom_group_id=cg_im_saml.id))
    db_session.commit()

    # 1. End user creates ticket with explicit grp_l3 and assignee — backend MUST ignore them and
    #    route to project-l2 (Tier-4 Project Default), and assigned_to_id MUST be None.
    create_res = client.post(
        "/api/incidents",
        json={
            "application_id": app_ent.id,
            "project_id": proj.id,
            "category": "Application",
            "short_description": "Cannot submit expense",
            "description": "Getting error 500",
            "impact": "Low",
            "urgency": "Low",
            "assignment_group_id": grp_l3.id,  # attempting to bypass frontline L2
            "assigned_to_id": 9999
        },
        headers={"X-User-ID": str(u_end_user.id)}
    )
    assert create_res.status_code == 200
    inc_data = create_res.json()

    # The routing engine ignores the end-user's grp_l3 payload; it either uses the project
    # default (grp_l2) or a seeded global-fallback group — but NEVER grp_l3 (the L3 bypass)
    assert inc_data["assignment_group_id"] != grp_l3.id, (
        f"End user bypass to L3 (id={grp_l3.id}) should be blocked. "
        f"Got assignment_group_id={inc_data['assignment_group_id']}"
    )
    assert inc_data["assigned_to_id"] is None, "assignee should be stripped for end users"

    # 2. End user tries to reassign the ticket -> 403 Forbidden
    reassign_res = client.patch(
        f"/api/incidents/{inc_data['number']}/assign",
        json={"assignment_group_id": grp_l3.id},
        headers={"X-User-ID": str(u_end_user.id)}
    )
    assert reassign_res.status_code == 403
