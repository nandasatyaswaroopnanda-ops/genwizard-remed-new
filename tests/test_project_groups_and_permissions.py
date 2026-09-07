"""
Tests for Project-Scoped Groups, Child Queues, Direct Routing, and Permissions:
1. Dynamic Creation of <project>-l2, <project>-l3 and <project>-admin, <project>-user, <project>-read.
2. Direct Ticket Routing to <project>-l2 as Level 4 Project Default Assignment Group.
3. Scoped Project Admin restrictions on Applications and Taxonomy.
4. Strict Reassignment and Priority Rights: End-user 403 vs Support/Project Member 200.
5. Ticket Conversation File Attachment uploads and retrieval.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import io

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    User, Project, Application, AssignmentGroup, CustomGroup,
    UserCustomGroup, GroupMember, Incident, ServiceRequest, ChangeRequest,
    Attachment, ClosureTaxonomy
)
from backend.security import get_user_scopes
from backend.routes.admin_projects import setup_project_queues_and_groups

client = TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_setup_project_queues_and_groups(db_session):
    """Verify that setup_project_queues_and_groups auto-provisions -l2, -l3, -admin, -user, -read."""
    proj_name = "TEST-FINANCE"

    with patch("requests.post") as mock_im_post:
        mock_im_post.return_value = MagicMock(status_code=201, text="{}")

        grp_l2, grp_l3 = setup_project_queues_and_groups(db_session, proj_name)

        # 1. Assignment Groups Check
        l2_group = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj_name}-l2").first()
        l3_group = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj_name}-l3").first()

        assert l2_group is not None
        assert l3_group is not None
        assert "Tier-2" in l2_group.description
        assert "Tier-3" in l3_group.description
        assert l2_group.id == grp_l2.id
        assert l3_group.id == grp_l3.id
        assert l2_group.escalation_group_id == l3_group.id

        # 2. Custom Groups Check
        admin_cg = db_session.query(CustomGroup).filter(CustomGroup.name == f"{proj_name}-admin").first()
        user_cg = db_session.query(CustomGroup).filter(CustomGroup.name == f"{proj_name}-user").first()
        read_cg = db_session.query(CustomGroup).filter(CustomGroup.name == f"{proj_name}-read").first()

        assert admin_cg is not None
        assert user_cg is not None
        assert read_cg is not None

        admin_perms = json.loads(admin_cg.permissions)
        assert f"project:{proj_name}:admin" in admin_perms
        assert f"project:{proj_name}:apps" in admin_perms
        assert f"project:{proj_name}:taxonomy" in admin_perms
        assert "tickets:assign" in admin_perms

        user_perms = json.loads(user_cg.permissions)
        assert f"project:{proj_name}:fulfiller" in user_perms
        assert "tickets:assign" in user_perms

        read_perms = json.loads(read_cg.permissions)
        assert f"project:{proj_name}:read" in read_perms


def test_direct_routing_to_project_l2(db_session):
    """Verify that tickets created under project route directly to <project>-l2."""
    proj_name = "TEST-ROUTING-PRJ"

    # Create App and Project
    app_entity = Application(
        app_id="APP-TEST-RT",
        name="Routing Test App",
        criticality="High",
        active=True
    )
    db_session.add(app_entity)
    db_session.flush()

    # Create project via endpoint
    proj_res = client.post("/api/admin/projects", json={
        "project_id": "PRJ-TEST-RT",
        "name": proj_name,
        "application_id": app_entity.id,
        "criticality": "Medium"
    }, headers={"X-User-ID": "1"})
    assert proj_res.status_code == 200
    proj_data = proj_res.json()

    l2_group = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj_name}-l2").first()
    assert l2_group is not None
    assert proj_data["default_assignment_group_id"] == l2_group.id

    # Create Incident under this project without custom rules -> should route directly to l2_group
    inc_res = client.post("/api/incidents", json={
        "application_id": app_entity.id,
        "project_id": proj_data["id"],
        "category": "Application",
        "short_description": "Auto route test",
        "description": "Checking direct L2 queue routing",
        "impact": "Medium",
        "urgency": "Medium"
    }, headers={"X-User-ID": "1"})

    assert inc_res.status_code == 200
    inc_data = inc_res.json()
    assert inc_data["assignment_group_id"] == l2_group.id
    assert inc_data["assignment_group_name"] == f"{proj_name}-l2"

    # Also verify when ticket is created with ONLY application_id (belonging to project) by end user:
    inc_res2 = client.post("/api/incidents", json={
        "application_id": app_entity.id,
        "category": "Application",
        "short_description": "Auto route via app project link",
        "description": "Checking project derivation and L2 queue routing",
        "impact": "Medium",
        "urgency": "Medium"
    }, headers={"X-User-ID": "2"})
    assert inc_res2.status_code == 200
    inc_data2 = inc_res2.json()
    assert inc_data2["project_id"] == proj_data["id"]
    assert inc_data2["assignment_group_id"] == l2_group.id
    assert inc_data2["assignment_group_name"] == f"{proj_name}-l2"


def test_user_scopes_evaluation(db_session):
    """Verify get_user_scopes cleanly distinguishes global admin, project admin, support, and end user."""
    # 1. Global admin
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    scopes = get_user_scopes(admin_user)
    assert scopes["is_global_admin"] is True
    assert scopes["is_end_user"] is False

    # 2. Project admin user
    p_admin_user = User(
        employee_id="EMP-PADMIN-01",
        username="ams_admin_user",
        full_name="AMS Project Admin",
        email="ams.admin@example.com",
        role="employee",
        is_local=True
    )
    db_session.add(p_admin_user)
    db_session.flush()

    ams_admin_grp = CustomGroup(name="AMS-IMS-admin", permissions=json.dumps(["project:AMS-IMS:admin"]))
    db_session.add(ams_admin_grp)
    db_session.flush()

    db_session.add(UserCustomGroup(user_id=p_admin_user.id, custom_group_id=ams_admin_grp.id))
    db_session.commit()

    p_scopes = get_user_scopes(p_admin_user)
    assert p_scopes["is_global_admin"] is False
    assert "AMS-IMS" in p_scopes["admin_projects"]
    assert p_scopes["is_support_member"] is True
    assert p_scopes["is_end_user"] is False

    # 3. Pure end user (IM_SAML)
    saml_user = User(
        employee_id="EMP-SAML-01",
        username="saml_caller",
        full_name="Saml Requester",
        email="saml.user@example.com",
        role="employee",
        is_local=True
    )
    db_session.add(saml_user)
    db_session.flush()

    saml_grp = db_session.query(CustomGroup).filter(CustomGroup.name == "IM_SAML").first()
    if not saml_grp:
        saml_grp = CustomGroup(name="IM_SAML", permissions=json.dumps(["tickets:create", "tickets:read_own"]))
        db_session.add(saml_grp)
        db_session.flush()

    db_session.add(UserCustomGroup(user_id=saml_user.id, custom_group_id=saml_grp.id))
    db_session.commit()

    saml_scopes = get_user_scopes(saml_user)
    assert saml_scopes["is_global_admin"] is False
    assert saml_scopes["admin_projects"] == []
    assert saml_scopes["is_support_member"] is False
    assert saml_scopes["is_end_user"] is True


def test_reassignment_and_priority_permissions(db_session):
    """Verify that end users cannot reassign or change priority, but support members can."""
    # Create incident
    app_entity = db_session.query(Application).first()
    proj_entity = db_session.query(Project).first()
    support_grp = db_session.query(AssignmentGroup).first()

    inc = Incident(
        number="INC9999001",
        caller_id=1,
        application_id=app_entity.id,
        project_id=proj_entity.id,
        category="Application",
        short_description="Permission test incident",
        description="Testing assign and priority permission checks",
        priority="P3",
        status="New",
        assignment_group_id=support_grp.id
    )
    db_session.add(inc)
    db_session.flush()

    # End user
    end_user = User(
        employee_id="EMP-ENDUSER-99",
        username="enduser_tester",
        full_name="End User Tester",
        email="enduser99@example.com",
        role="employee",
        is_local=True
    )
    db_session.add(end_user)
    db_session.flush()

    saml_grp = db_session.query(CustomGroup).filter(CustomGroup.name == "IM_SAML").first()
    if saml_grp:
        db_session.add(UserCustomGroup(user_id=end_user.id, custom_group_id=saml_grp.id))
    db_session.commit()

    # Support user
    sup_user = User(
        employee_id="EMP-SUPPORT-99",
        username="support_tester",
        full_name="Support Tester",
        email="support99@example.com",
        role="support_member",
        is_local=True
    )
    db_session.add(sup_user)
    db_session.flush()
    db_session.add(GroupMember(user_id=sup_user.id, group_id=support_grp.id, role_in_group="member"))
    db_session.commit()

    # 1. End user tries to reassign -> 403
    res_assign_deny = client.patch(
        f"/api/incidents/{inc.id}/assign",
        json={"assigned_to_id": sup_user.id},
        headers={"X-User-ID": str(end_user.id)}
    )
    assert res_assign_deny.status_code == 403
    assert "End users are not permitted to reassign tickets" in res_assign_deny.json()["detail"]

    # 2. End user tries to change priority -> 403
    res_pri_deny = client.patch(
        f"/api/incidents/{inc.id}/priority",
        json={"priority": "P1", "reason": "Self escalation"},
        headers={"X-User-ID": str(end_user.id)}
    )
    assert res_pri_deny.status_code == 403
    assert "End users are not permitted to change ticket priority" in res_pri_deny.json()["detail"]

    # 3. Support user tries to reassign -> 200
    res_assign_ok = client.patch(
        f"/api/incidents/{inc.id}/assign",
        json={"assigned_to_id": sup_user.id},
        headers={"X-User-ID": str(sup_user.id)}
    )
    assert res_assign_ok.status_code == 200
    assert res_assign_ok.json()["assigned_to_id"] == sup_user.id

    # 4. Support user tries to change priority -> 200
    res_pri_ok = client.patch(
        f"/api/incidents/{inc.id}/priority",
        json={"priority": "P2", "reason": "Support escalation"},
        headers={"X-User-ID": str(sup_user.id)}
    )
    assert res_pri_ok.status_code == 200
    assert res_pri_ok.json()["priority"] == "P2"


def test_scoped_project_admin_application_and_taxonomy(db_session):
    """Verify that project admins can only add apps/taxonomy for their project."""
    # Setup project 'ALPHA-PRJ'
    alpha_app = Application(app_id="APP-ALPHA-01", name="Alpha App", criticality="High")
    db_session.add(alpha_app)
    db_session.flush()

    alpha_proj = Project(project_id="PRJ-ALPHA-01", name="ALPHA-PRJ", application_id=alpha_app.id)
    db_session.add(alpha_proj)
    db_session.flush()

    # Setup project 'BETA-PRJ'
    beta_app = Application(app_id="APP-BETA-01", name="Beta App", criticality="Medium")
    db_session.add(beta_app)
    db_session.flush()

    beta_proj = Project(project_id="PRJ-BETA-01", name="BETA-PRJ", application_id=beta_app.id)
    db_session.add(beta_proj)
    db_session.flush()

    # Create Alpha Project Admin
    alpha_admin = User(
        employee_id="EMP-ALPHA-ADM",
        username="alpha_admin",
        full_name="Alpha Admin",
        email="alpha.adm@example.com",
        role="employee",
        is_local=True
    )
    db_session.add(alpha_admin)
    db_session.flush()

    alpha_cg = CustomGroup(name="ALPHA-PRJ-admin", permissions=json.dumps(["project:ALPHA-PRJ:admin"]))
    db_session.add(alpha_cg)
    db_session.flush()
    db_session.add(UserCustomGroup(user_id=alpha_admin.id, custom_group_id=alpha_cg.id))
    db_session.commit()

    # 1. Alpha Admin creates app under ALPHA-PRJ -> 200 OK
    res_app_ok = client.post("/api/admin/applications", json={
        "app_id": "APP-ALPHA-SUB",
        "name": "Alpha Microservice",
        "criticality": "Low",
        "project_id": alpha_proj.id
    }, headers={"X-User-ID": str(alpha_admin.id)})
    assert res_app_ok.status_code == 200

    # 2. Alpha Admin tries to create app under BETA-PRJ -> 403 Forbidden
    res_app_deny = client.post("/api/admin/applications", json={
        "app_id": "APP-BETA-ILLEGAL",
        "name": "Beta Microservice Intrusion",
        "criticality": "Low",
        "project_id": beta_proj.id
    }, headers={"X-User-ID": str(alpha_admin.id)})
    assert res_app_deny.status_code == 403
    assert "You only have project administrator rights for [ALPHA-PRJ]" in res_app_deny.json()["detail"]

    # 3. Alpha Admin creates taxonomy under Alpha App -> 200 OK
    res_tax_ok = client.post("/api/admin/configuration/taxonomy", json={
        "ticket_type": "Incident",
        "category": "Alpha Performance",
        "subcategory": "Slow API",
        "application_id": alpha_app.id
    }, headers={"X-User-ID": str(alpha_admin.id)})
    assert res_tax_ok.status_code == 200

    # 4. Alpha Admin tries to create taxonomy under Beta App -> 403 Forbidden
    res_tax_deny = client.post("/api/admin/configuration/taxonomy", json={
        "ticket_type": "Incident",
        "category": "Beta Breach",
        "subcategory": "Unauthorized",
        "application_id": beta_app.id
    }, headers={"X-User-ID": str(alpha_admin.id)})
    assert res_tax_deny.status_code == 403
    assert "Access denied" in res_tax_deny.json()["detail"]
    assert "ALPHA-PRJ" in res_tax_deny.json()["detail"]


def test_ticket_conversation_file_attachment_upload(db_session):
    """Verify that users can upload files and retrieve them in ticket conversation details."""
    app_entity = db_session.query(Application).first()
    proj_entity = db_session.query(Project).first()

    inc = Incident(
        number="INC9999002",
        caller_id=1,
        application_id=app_entity.id,
        project_id=proj_entity.id,
        category="Application",
        short_description="Attachment test incident",
        description="Testing log upload",
        priority="P3",
        status="New"
    )
    db_session.add(inc)
    db_session.commit()

    file_content = b"Error 500: Database connection timeout in pool-1"
    files = {
        "file": ("system_error.log", io.BytesIO(file_content), "text/plain")
    }
    data = {
        "ticket_type": "Incident",
        "ticket_id": str(inc.id)
    }

    # Upload attachment
    res_up = client.post(
        "/api/attachments",
        data=data,
        files=files,
        headers={"X-User-ID": "1"}
    )
    assert res_up.status_code == 200
    att_data = res_up.json()
    assert att_data["filename"] == "system_error.log"

    # Fetch incident details -> verify attachment is present in data["attachments"]
    res_inc = client.get(f"/api/incidents/{inc.id}", headers={"X-User-ID": "1"})
    assert res_inc.status_code == 200
    inc_details = res_inc.json()
    assert "attachments" in inc_details
    assert any(a["filename"] == "system_error.log" for a in inc_details["attachments"])


def test_end_user_ai_bot_access_and_kb_restriction(db_session):
    """
    Verify:
    1. End users CAN access the AI bot (/api/ai/conversations and /api/ai/chat).
    2. End users CANNOT create, update, or delete knowledgebase articles (403 Forbidden).
    3. Support members / admins CAN create, update, and delete knowledgebase articles (200 OK).
    """
    # 1. End User
    end_user = User(
        employee_id="EMP-KB-AI-01",
        username="kb_ai_enduser",
        full_name="KB AI End User",
        email="kbaie@company.com",
        role="employee",
        is_local=True
    )
    db_session.add(end_user)
    db_session.commit()

    # 1a. AI Bot access: list conversations -> 200 OK
    res_convs = client.get("/api/ai/conversations", headers={"X-User-ID": str(end_user.id)})
    assert res_convs.status_code == 200

    # 1b. Knowledgebase: End User read articles -> 200 OK
    res_read = client.get("/api/knowledge")
    assert res_read.status_code == 200

    # 1c. Knowledgebase: End User CREATE article -> 403 Forbidden
    payload_create = {
        "title": "Unauthorized Article by End User",
        "category": "Troubleshooting",
        "content": "End user attempting article creation",
        "status": "Published"
    }
    res_create_deny = client.post("/api/knowledge", json=payload_create, headers={"X-User-ID": str(end_user.id)})
    assert res_create_deny.status_code == 403
    assert "read-only" in res_create_deny.json()["detail"].lower()

    # 2. Support Member creates article -> 200 OK
    support_user = User(
        employee_id="EMP-KB-SUP-01",
        username="kb_support_member",
        full_name="KB Support Member",
        email="kbsup@company.com",
        role="support_member",
        is_local=True
    )
    db_session.add(support_user)
    db_session.commit()

    res_create_ok = client.post("/api/knowledge", json=payload_create, headers={"X-User-ID": str(support_user.id)})
    assert res_create_ok.status_code == 200
    art_id = res_create_ok.json()["id"]

    # 3. End User UPDATE article -> 403 Forbidden
    payload_update = {
        "title": "Hacked Title",
        "category": "Troubleshooting",
        "content": "Hacked content",
        "status": "Published"
    }
    res_update_deny = client.put(f"/api/knowledge/{art_id}", json=payload_update, headers={"X-User-ID": str(end_user.id)})
    assert res_update_deny.status_code == 403
    assert "read-only" in res_update_deny.json()["detail"].lower()

    # 4. End User DELETE article -> 403 Forbidden
    res_del_deny = client.delete(f"/api/knowledge/{art_id}", headers={"X-User-ID": str(end_user.id)})
    assert res_del_deny.status_code == 403

    # 5. Support Member UPDATE article -> 200 OK
    res_update_ok = client.put(f"/api/knowledge/{art_id}", json=payload_update, headers={"X-User-ID": str(support_user.id)})
    assert res_update_ok.status_code == 200
    assert res_update_ok.json()["title"] == "Hacked Title"

    # 6. Support Member DELETE article -> 200 OK
    res_del_ok = client.delete(f"/api/knowledge/{art_id}", headers={"X-User-ID": str(support_user.id)})
    assert res_del_ok.status_code == 200


def test_assignment_group_support_members_are_project_scoped_admins(db_session):
    """
    Verify:
    1. Support members of respective assignment groups are a type of admin for THAT particular project only.
    2. They can update on-call/escalations and manage their project.
    3. They are FORBIDDEN (403) from administering other projects.
    4. Global admin ('admin') is admin across ALL projects.
    """
    # Create Project Alpha and Project Beta
    app_a = Application(app_id="APP-SCOPED-A", name="App Scoped A", active=True)
    app_b = Application(app_id="APP-SCOPED-B", name="App Scoped B", active=True)
    db_session.add_all([app_a, app_b])
    db_session.commit()

    proj_a = Project(project_id="PRJ-SCOPED-A", name="Project Alpha Ops", application_id=app_a.id, active=True)
    proj_b = Project(project_id="PRJ-SCOPED-B", name="Project Beta Ops", application_id=app_b.id, active=True)
    db_session.add_all([proj_a, proj_b])
    db_session.commit()

    # Assignment Groups: Project Alpha-l2 and Project Beta-l2
    grp_a = AssignmentGroup(group_id="GRP-ALPHA-L2", name="Project Alpha Ops-l2", projects_supported=json.dumps(["Project Alpha Ops"]), active=True)
    grp_b = AssignmentGroup(group_id="GRP-BETA-L2", name="Project Beta Ops-l2", projects_supported=json.dumps(["Project Beta Ops"]), active=True)
    db_session.add_all([grp_a, grp_b])
    db_session.commit()

    # Support Member User in Project Alpha-l2 ONLY
    u_alpha_support = User(
        employee_id="EMP-ALPHA-SUP",
        username="alpha_support_engineer",
        full_name="Alpha Support Engineer",
        email="alpha.support@company.com",
        role="support_member",
        is_local=True
    )
    db_session.add(u_alpha_support)
    db_session.commit()

    # Add user to GroupMember of grp_a
    db_session.add(GroupMember(group_id=grp_a.id, user_id=u_alpha_support.id))
    db_session.commit()

    # Verify scopes
    scopes = get_user_scopes(u_alpha_support, db_session)
    assert scopes["is_global_admin"] is False
    assert "Project Alpha Ops" in scopes["admin_projects"]
    assert "Project Beta Ops" not in scopes["admin_projects"]

    # 1. Update Project Alpha on-call -> 200 OK
    payload = {"l2_on_call_contact": "alpha-oncall@company.com"}
    res_a = client.put(f"/api/admin/projects/{proj_a.id}/on-call", json=payload, headers={"X-User-ID": str(u_alpha_support.id)})
    assert res_a.status_code == 200

    # 2. Update Project Beta on-call -> 403 Forbidden
    payload_b = {"l2_on_call_contact": "hacked-beta@company.com"}
    res_b = client.put(f"/api/admin/projects/{proj_b.id}/on-call", json=payload_b, headers={"X-User-ID": str(u_alpha_support.id)})
    assert res_b.status_code == 403
    assert "Access denied" in res_b.json()["detail"]

    # 3. Global Admin ('admin') updating Project Beta -> 200 OK (admin across ALL)
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    res_admin_b = client.put(f"/api/admin/projects/{proj_b.id}/on-call", json=payload_b, headers={"X-User-ID": str(admin_user.id)})
    assert res_admin_b.status_code == 200


def test_strict_role_scoping_matrix(db_session):
    """
    Verify full matrix:
    - Global admin: can create projects, create/edit apps for any project, edit on-call for any project.
    - Project admin (<proj>_admin / <proj>-admin):
        * CANNOT create projects (403).
        * CAN create/edit applications for their project only.
        * CAN add categories for their project only.
        * CAN edit on-call for their project only.
    - End user (ATR_SAML / IM_SAML / employee):
        * CAN view projects, applications, on-call roster (read-only).
        * CANNOT create projects, apps, edit on-call (403).
        * CAN add comments, worknotes, and upload attachments to their own tickets.
    """
    import io

    # 1. Setup Projects & Applications
    app_gamma = Application(app_id="APP-GAMMA-01", name="Gamma App", criticality="High", active=True)
    app_delta = Application(app_id="APP-DELTA-01", name="Delta App", criticality="Medium", active=True)
    db_session.add_all([app_gamma, app_delta])
    db_session.commit()

    proj_gamma = Project(project_id="PRJ-GAMMA", name="Gamma Project", application_id=app_gamma.id, active=True)
    proj_delta = Project(project_id="PRJ-DELTA", name="Delta Project", application_id=app_delta.id, active=True)
    db_session.add_all([proj_gamma, proj_delta])
    db_session.commit()

    app_gamma.project_id = proj_gamma.id
    app_delta.project_id = proj_delta.id
    db_session.commit()

    # 2. Setup Users
    admin_user = db_session.query(User).filter(User.username == "admin").first()

    # Project admin for Gamma Project via Gamma Project_admin group
    gamma_admin = User(
        employee_id="EMP-GAMMA-ADM",
        username="gamma_admin_user",
        full_name="Gamma Admin User",
        email="gamma.admin@company.com",
        role="support_member",
        is_local=True
    )
    db_session.add(gamma_admin)
    db_session.flush()

    gamma_admin_group = CustomGroup(name="Gamma Project_admin", permissions=json.dumps(["project:Gamma Project:admin"]))
    db_session.add(gamma_admin_group)
    db_session.flush()
    db_session.add(UserCustomGroup(user_id=gamma_admin.id, custom_group_id=gamma_admin_group.id))
    db_session.commit()

    # End user via ATR_SAML SSO group
    sso_end_user = User(
        employee_id="EMP-ATR-SAML-01",
        username="atr_end_user",
        full_name="ATR SAML Requester",
        email="atr.user@company.com",
        role="employee",
        is_local=True
    )
    db_session.add(sso_end_user)
    db_session.flush()

    atr_saml_group = CustomGroup(name="ATR_SAML", permissions=json.dumps(["tickets:create", "tickets:read_own"]))
    db_session.add(atr_saml_group)
    db_session.flush()
    db_session.add(UserCustomGroup(user_id=sso_end_user.id, custom_group_id=atr_saml_group.id))
    db_session.commit()

    # --- TEST 1: Project Creation ---
    # Global admin CAN create projects
    res = client.post("/api/admin/projects", json={
        "project_id": "PRJ-EPSILON",
        "name": "Epsilon Project",
        "application_id": app_gamma.id
    }, headers={"X-User-ID": str(admin_user.id)})
    assert res.status_code == 200

    # Project admin CANNOT create projects (403 Forbidden)
    res_p = client.post("/api/admin/projects", json={
        "project_id": "PRJ-FAIL-P",
        "name": "Failed Project P",
        "application_id": app_gamma.id
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_p.status_code == 403

    # End user CANNOT create projects (403 Forbidden)
    res_e = client.post("/api/admin/projects", json={
        "project_id": "PRJ-FAIL-E",
        "name": "Failed Project E",
        "application_id": app_gamma.id
    }, headers={"X-User-ID": str(sso_end_user.id)})
    assert res_e.status_code == 403

    # --- TEST 2: Application Creation & Editing ---
    # Project admin CAN create app under their project (Gamma)
    res_app_gamma = client.post("/api/admin/applications", json={
        "app_id": "APP-G2",
        "name": "Gamma Microservice 2",
        "project_id": proj_gamma.id
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_app_gamma.status_code == 200
    created_app_id = res_app_gamma.json()["id"]

    # Project admin CANNOT create app under another project (Delta)
    res_app_delta = client.post("/api/admin/applications", json={
        "app_id": "APP-D2",
        "name": "Delta Microservice 2",
        "project_id": proj_delta.id
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_app_delta.status_code == 403

    # Project admin CAN edit app under their project
    res_app_edit_ok = client.put(f"/api/admin/applications/{created_app_id}", json={
        "app_id": "APP-G2",
        "name": "Gamma Microservice 2 Updated",
        "criticality": "Critical"
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_app_edit_ok.status_code == 200

    # Project admin CANNOT edit app under another project (Delta)
    res_app_edit_fail = client.put(f"/api/admin/applications/{app_delta.id}", json={
        "app_id": "APP-DELTA-01",
        "name": "Delta Hacked Name",
        "criticality": "Low"
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_app_edit_fail.status_code == 403

    # End user CANNOT create application
    res_app_eu = client.post("/api/admin/applications", json={
        "app_id": "APP-EU",
        "name": "End User App",
        "project_id": proj_gamma.id
    }, headers={"X-User-ID": str(sso_end_user.id)})
    assert res_app_eu.status_code == 403

    # --- TEST 3: Taxonomy / Categories ---
    # Project admin CAN add taxonomy for their app
    res_tax_ok = client.post("/api/admin/configuration/taxonomy", json={
        "ticket_type": "Incident",
        "category": "Gamma Category",
        "subcategory": "Gamma Subcategory",
        "application_id": app_gamma.id
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_tax_ok.status_code == 200

    # Project admin CANNOT add taxonomy for Delta app
    res_tax_fail = client.post("/api/admin/configuration/taxonomy", json={
        "ticket_type": "Incident",
        "category": "Delta Category",
        "subcategory": "Delta Subcategory",
        "application_id": app_delta.id
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_tax_fail.status_code == 403

    # --- TEST 4: On-Call & Escalations ---
    # Project admin CAN update on-call for their project (Gamma)
    res_oncall_ok = client.put(f"/api/admin/projects/{proj_gamma.id}/on-call", json={
        "l2_on_call_contact": "gamma-l2@company.com"
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_oncall_ok.status_code == 200

    # Project admin CANNOT update on-call for Delta project
    res_oncall_fail = client.put(f"/api/admin/projects/{proj_delta.id}/on-call", json={
        "l2_on_call_contact": "delta-hacked@company.com"
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_oncall_fail.status_code == 403

    # End user CANNOT update on-call
    res_oncall_eu = client.put(f"/api/admin/projects/{proj_gamma.id}/on-call", json={
        "l2_on_call_contact": "eu@company.com"
    }, headers={"X-User-ID": str(sso_end_user.id)})
    assert res_oncall_eu.status_code == 403

    # --- TEST 5: End User Read-Only and Ticket Collaboration ---
    # End user CAN see projects
    res_projs = client.get("/api/projects", headers={"X-User-ID": str(sso_end_user.id)})
    assert res_projs.status_code == 200
    assert len(res_projs.json()) >= 2

    # End user CAN see applications
    res_apps = client.get("/api/applications", headers={"X-User-ID": str(sso_end_user.id)})
    assert res_apps.status_code == 200
    assert len(res_apps.json()) >= 2

    # End user CAN see on-call roster, but can_edit is False
    res_roster = client.get("/api/admin/projects/on-call-roster", headers={"X-User-ID": str(sso_end_user.id)})
    assert res_roster.status_code == 200
    for r in res_roster.json():
        assert r["can_edit"] is False

    # Create an incident as end user
    inc = Incident(
        number="INC-SSO-001",
        caller_id=sso_end_user.id,
        application_id=app_gamma.id,
        project_id=proj_gamma.id,
        category="Application",
        short_description="SSO User Issue",
        priority="P3",
        status="New"
    )
    db_session.add(inc)
    db_session.commit()

    # End user CAN add comments
    res_comment = client.post(f"/api/incidents/{inc.id}/comments", json={
        "comment": "Customer note on issue"
    }, headers={"X-User-ID": str(sso_end_user.id)})
    assert res_comment.status_code == 200

    # End user CAN add work notes to their own incident
    res_worknote = client.post(f"/api/incidents/{inc.id}/work-notes", json={
        "note": "Worknote details from requester"
    }, headers={"X-User-ID": str(sso_end_user.id)})
    assert res_worknote.status_code == 200

    # End user CAN upload attachment to their incident
    file_content = b"Screenshot log test content"
    res_att = client.post(
        "/api/attachments",
        data={"ticket_type": "Incident", "ticket_id": inc.id},
        files={"file": ("error_log.txt", io.BytesIO(file_content), "text/plain")},
        headers={"X-User-ID": str(sso_end_user.id)}
    )
    assert res_att.status_code == 200
    assert res_att.json()["filename"] == "error_log.txt"


def test_project_creation_without_app_and_auto_linking(db_session):
    """Verify that projects can be created without an application, and project admin creating an app links cleanly."""
    admin_user = db_session.query(User).filter(User.username == "admin").first()

    # 1. Global admin creates standalone project with NO application ID
    res_proj = client.post("/api/admin/projects", json={
        "project_id": "PRJ-STANDALONE-001",
        "name": "Gamma Standalone Project",
        "description": "Project created before any applications exist"
    }, headers={"X-User-ID": str(admin_user.id)})
    assert res_proj.status_code == 200
    proj_data = res_proj.json()
    assert proj_data["name"] == "Gamma Standalone Project"
    assert proj_data.get("application_id") is None
    proj_id = proj_data["id"]

    # 2. Setup a project admin user for Gamma Standalone Project
    gamma_admin = User(
        employee_id="EMP-GAMMA-ADM",
        username="gamma_admin",
        full_name="Gamma Admin",
        email="gamma.adm@example.com",
        role="employee",
        is_local=True
    )
    db_session.add(gamma_admin)
    db_session.flush()

    gamma_group = CustomGroup(name="Gamma Standalone Project_admin", permissions=json.dumps(["project:Gamma Standalone Project:admin"]))
    db_session.add(gamma_group)
    db_session.flush()
    db_session.add(UserCustomGroup(user_id=gamma_admin.id, custom_group_id=gamma_group.id))
    db_session.commit()

    # 3. Project admin CANNOT create projects -> 403
    res_deny_proj = client.post("/api/admin/projects", json={
        "project_id": "PRJ-ILLEGAL-999",
        "name": "Illegal Project"
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_deny_proj.status_code == 403

    # 4. Project admin creates application with NO project_id dropdown value passed -> auto-linked to Gamma Standalone Project
    res_app = client.post("/api/admin/applications", json={
        "app_id": "APP-GAMMA-CORE",
        "name": "Gamma Core Service",
        "criticality": "High"
    }, headers={"X-User-ID": str(gamma_admin.id)})
    assert res_app.status_code == 200
    app_data = res_app.json()
    assert app_data["project_id"] == proj_id

    # Refresh project to verify it links to the new application
    proj_db = db_session.query(Project).filter(Project.id == proj_id).first()
    assert proj_db.application_id == app_data["id"]


def test_sarah_and_mike_create_applications_and_uniqueness(db_session):
    """Verify that Sarah Johnson and Mike Brown can create applications under their projects,
    and cross-project duplicate app_id or name is rejected with 409 Conflict."""
    from backend.security import _ensure_local_persona
    _ensure_local_persona(3, db_session)
    _ensure_local_persona(5, db_session)

    sarah = db_session.query(User).filter(User.username == "sarah.johnson").first()
    mike = db_session.query(User).filter(User.username == "mike.brown").first()

    assert sarah is not None, "sarah.johnson persona should exist"
    assert mike is not None, "mike.brown persona should exist"

    # 1. Sarah creates an app under Payment Platform Modernization
    res_sarah = client.post("/api/admin/applications", json={
        "app_id": "APP-PAY-SARAH-01",
        "name": "Payment Gateway Service Alpha",
        "description": "Payment authorization core",
        "criticality": "Critical"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_sarah.status_code == 200, f"Sarah app creation failed: {res_sarah.text}"
    sarah_app = res_sarah.json()
    assert sarah_app["project_name"] == "Payment Platform Modernization"

    # 2. Mike creates an app under Cloud Migration
    res_mike = client.post("/api/admin/applications", json={
        "app_id": "APP-CLOUD-MIKE-01",
        "name": "Cloud Infrastructure Broker Beta",
        "description": "Cloud migration workload broker",
        "criticality": "High"
    }, headers={"X-User-ID": str(mike.id)})
    assert res_mike.status_code == 200, f"Mike app creation failed: {res_mike.text}"
    mike_app = res_mike.json()
    assert mike_app["project_name"] == "Cloud Migration"

    # 3. Cross-project duplicate app_id check: Sarah tries to create an app with Mike's app_id
    res_dup_id = client.post("/api/admin/applications", json={
        "app_id": "APP-CLOUD-MIKE-01",
        "name": "Payment Duplicate Test",
        "criticality": "Low"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_dup_id.status_code == 409
    assert "already exists in project 'Cloud Migration'" in res_dup_id.json()["detail"]

    # 4. Cross-project duplicate name check: Mike tries to create an app with Sarah's app name
    res_dup_name = client.post("/api/admin/applications", json={
        "app_id": "APP-CLOUD-MIKE-DIFF",
        "name": "Payment Gateway Service Alpha",
        "criticality": "Low"
    }, headers={"X-User-ID": str(mike.id)})
    assert res_dup_name.status_code == 409
    assert "already exists in project 'Payment Platform Modernization'" in res_dup_name.json()["detail"]


def test_project_admin_configure_l2_l3_queues_and_ticket_routing(db_session):
    """Verify that project admins can update L2 and L3 queues on their project,
    and tickets created under the project auto-route to the configured Level-2 queue."""
    from backend.security import _ensure_local_persona
    _ensure_local_persona(3, db_session)

    sarah = db_session.query(User).filter(User.username == "sarah.johnson").first()
    pay_proj = db_session.query(Project).filter(Project.name == "Payment Platform Modernization").first()
    assert pay_proj is not None

    # Get the project's L2 and L3 groups
    pay_l2 = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Payment Platform Modernization-l2").first()
    pay_l3 = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Payment Platform Modernization-l3").first()
    assert pay_l2 is not None
    assert pay_l3 is not None

    # Sarah updates the project with explicit L2 and L3 assignment groups
    res_update_proj = client.put(f"/api/admin/projects/{pay_proj.id}", json={
        "project_id": pay_proj.project_id,
        "name": "Payment Platform Modernization",
        "l2_assignment_group_id": pay_l2.id,
        "l3_assignment_group_id": pay_l3.id,
        "description": "Updated by Sarah with explicit L2 and L3 routing queues"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_update_proj.status_code == 200, f"Update project failed: {res_update_proj.text}"
    updated_data = res_update_proj.json()
    assert updated_data["l2_assignment_group_id"] == pay_l2.id
    assert updated_data["l3_assignment_group_id"] == pay_l3.id
    assert updated_data["default_assignment_group_id"] == pay_l2.id

    # Ensure an application exists for the project
    pay_app = db_session.query(Application).filter(Application.project_id == pay_proj.id).first()
    if not pay_app:
        pay_app = Application(app_id="APP-PAY-INC", name="Payment Inc App", project_id=pay_proj.id, active=True)
        db_session.add(pay_app)
        db_session.commit()

    # Create an incident under this project with no assignment group specified
    res_inc = client.post("/api/incidents", json={
        "short_description": "Payment Settlement Processing Failure",
        "description": "Settlement batch failed on primary payment gateway",
        "priority": "P2",
        "application_id": pay_app.id,
        "project_id": pay_proj.id,
        "category": "Software",
        "subcategory": "API / Backend"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_inc.status_code in (200, 201), f"Create incident failed: {res_inc.text}"
    inc_data = res_inc.json()
    # Should automatically route to Level-2 queue of Payment Platform Modernization
    assert inc_data["assignment_group_id"] == pay_l2.id
    assert inc_data["assignment_group_name"] == pay_l2.name


def test_admin_update_application_project_dropdown(db_session):
    """Verify that global admin can change the project dropdown on an application and it persists properly."""
    from backend.security import _ensure_local_persona
    _ensure_local_persona(1, db_session)
    _ensure_local_persona(5, db_session)

    admin_user = db_session.query(User).filter(User.username == "admin").first()
    cloud_proj = db_session.query(Project).filter(Project.name == "Cloud Migration").first()
    assert cloud_proj is not None

    # Create a new standalone application by admin
    res_app = client.post("/api/admin/applications", json={
        "app_id": "APP-ORPHAN-01",
        "name": "Orphan Service Alpha",
        "criticality": "Low"
    }, headers={"X-User-ID": str(admin_user.id)})
    assert res_app.status_code == 200
    app_id = res_app.json()["id"]

    # Admin updates application project dropdown to Cloud Migration
    res_put = client.put(f"/api/admin/applications/{app_id}", json={
        "project_id": cloud_proj.id,
        "project_name": cloud_proj.name
    }, headers={"X-User-ID": str(admin_user.id)})
    assert res_put.status_code == 200
    updated_app = res_put.json()
    assert updated_app["project_id"] == cloud_proj.id
    assert updated_app["project_name"] == cloud_proj.name

    # Fetch app directly from list endpoint and verify project_id and project_name
    res_list = client.get("/api/admin/applications", headers={"X-User-ID": str(admin_user.id)})
    assert res_list.status_code == 200
    matched = next((a for a in res_list.json() if a["id"] == app_id), None)
    assert matched is not None
    assert matched["project_id"] == cloud_proj.id
    assert matched["project_name"] == cloud_proj.name


def test_project_scoped_ticket_visibility_and_actions(db_session):
    """
    Verify strict ServiceNow-grade project isolation and actions:
    1. Incident isolation: Support member for Payment Platform Modernization (Sarah) only sees
       Payment tickets. Support member for Cloud Migration (Mike) only sees Cloud tickets.
       End user (John Smith) only sees tickets where he is caller. Admin sees all and can filter.
    2. Service Request isolation & full action workflow (comments, work notes, reassign, approve).
    3. Change Request isolation & full action workflow (comments, work notes, reassign, approve).
    """
    from backend.security import _ensure_local_persona
    _ensure_local_persona(1, db_session)
    _ensure_local_persona(2, db_session)
    _ensure_local_persona(3, db_session)
    _ensure_local_persona(5, db_session)

    admin = db_session.query(User).filter(User.username == "admin").first()
    john = db_session.query(User).filter(User.username == "john.smith").first()
    sarah = db_session.query(User).filter(User.username == "sarah.johnson").first()
    mike = db_session.query(User).filter(User.username == "mike.brown").first()

    pay_proj = db_session.query(Project).filter(Project.name == "Payment Platform Modernization").first()
    cloud_proj = db_session.query(Project).filter(Project.name == "Cloud Migration").first()
    assert pay_proj is not None and cloud_proj is not None

    pay_app = db_session.query(Application).filter(Application.project_id == pay_proj.id).first()
    if not pay_app:
        pay_app = Application(app_id="APP-PAY-VIS-01", name="Payment Gateway Core", project_id=pay_proj.id, active=True)
        db_session.add(pay_app)
        db_session.commit()

    cloud_app = db_session.query(Application).filter(Application.project_id == cloud_proj.id).first()
    if not cloud_app:
        cloud_app = Application(app_id="APP-CLOUD-VIS-01", name="Cloud Infrastructure Core", project_id=cloud_proj.id, active=True)
        db_session.add(cloud_app)
        db_session.commit()

    pay_l2 = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Payment Platform Modernization-l2").first()
    cloud_l2 = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Cloud Migration-l2").first()

    # --- 1. INCIDENTS ---
    pay_inc = Incident(
        number="INC8880001",
        short_description="Payment processing latency spike",
        description="Payment queue depth increasing",
        priority="P2",
        status="New",
        caller_id=john.id,
        project_id=pay_proj.id,
        application_id=pay_app.id,
        assignment_group_id=pay_l2.id if pay_l2 else None
    )
    cloud_inc = Incident(
        number="INC8880002",
        short_description="Cloud cluster scale-out failure",
        description="Node autoscaler timeout",
        priority="P2",
        status="New",
        caller_id=admin.id,
        project_id=cloud_proj.id,
        application_id=cloud_app.id,
        assignment_group_id=cloud_l2.id if cloud_l2 else None
    )
    db_session.add(pay_inc)
    db_session.add(cloud_inc)
    db_session.commit()

    # Sarah (Payment support) lists incidents
    res_sarah_inc = client.get("/api/incidents", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_inc.status_code == 200
    sarah_inc_numbers = [i["number"] for i in res_sarah_inc.json()]
    assert "INC8880001" in sarah_inc_numbers
    assert "INC8880002" not in sarah_inc_numbers

    # Mike (Cloud support) lists incidents
    res_mike_inc = client.get("/api/incidents", headers={"X-User-ID": str(mike.id)})
    assert res_mike_inc.status_code == 200
    mike_inc_numbers = [i["number"] for i in res_mike_inc.json()]
    assert "INC8880002" in mike_inc_numbers
    assert "INC8880001" not in mike_inc_numbers

    # Direct GET by wrong support member returns 403
    res_sarah_get_cloud = client.get("/api/incidents/INC8880002", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_get_cloud.status_code == 403

    # Direct GET by right support member returns 200
    res_sarah_get_pay = client.get("/api/incidents/INC8880001", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_get_pay.status_code == 200

    # End user (John Smith) lists incidents: only his own
    res_john_inc = client.get("/api/incidents", headers={"X-User-ID": str(john.id)})
    assert res_john_inc.status_code == 200
    john_inc_numbers = [i["number"] for i in res_john_inc.json()]
    assert "INC8880001" in john_inc_numbers
    assert "INC8880002" not in john_inc_numbers

    # Admin lists incidents: sees both, and can filter by project_id
    res_admin_inc = client.get("/api/incidents", headers={"X-User-ID": str(admin.id)})
    assert res_admin_inc.status_code == 200
    admin_inc_numbers = [i["number"] for i in res_admin_inc.json()]
    assert "INC8880001" in admin_inc_numbers
    assert "INC8880002" in admin_inc_numbers

    # --- 2. SERVICE REQUESTS ---
    pay_req = ServiceRequest(
        number="REQ8880001",
        short_description="Request new API credential for Payment Gateway",
        description="Need production credentials",
        priority="P3",
        status="Submitted",
        requested_by_id=john.id,
        project_id=pay_proj.id,
        application_id=pay_app.id,
        assignment_group_id=pay_l2.id if pay_l2 else None
    )
    cloud_req = ServiceRequest(
        number="REQ8880002",
        short_description="Request additional AWS subnet",
        description="VPC expansion",
        priority="P3",
        status="Submitted",
        requested_by_id=admin.id,
        project_id=cloud_proj.id,
        application_id=cloud_app.id,
        assignment_group_id=cloud_l2.id if cloud_l2 else None
    )
    db_session.add(pay_req)
    db_session.add(cloud_req)
    db_session.commit()

    # Sarah lists service requests
    res_sarah_req = client.get("/api/service-requests", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_req.status_code == 200
    sarah_req_numbers = [r["number"] for r in res_sarah_req.json()]
    assert "REQ8880001" in sarah_req_numbers
    assert "REQ8880002" not in sarah_req_numbers

    # Mike lists service requests
    res_mike_req = client.get("/api/service-requests", headers={"X-User-ID": str(mike.id)})
    assert res_mike_req.status_code == 200
    mike_req_numbers = [r["number"] for r in res_mike_req.json()]
    assert "REQ8880002" in mike_req_numbers
    assert "REQ8880001" not in mike_req_numbers

    # Cross-project direct GET returns 403
    res_sarah_get_cloud_req = client.get("/api/service-requests/REQ8880002", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_get_cloud_req.status_code == 403

    # Sarah adds comments, work notes, reassigns, and approves payment request
    res_comment = client.post(f"/api/service-requests/{pay_req.id}/comments", json={
        "comment": "Verification with requester in progress"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_comment.status_code == 200

    res_work_note = client.post(f"/api/service-requests/{pay_req.id}/work-notes", json={
        "note": "Internal: Verified API secret vault key rotation"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_work_note.status_code == 200

    res_assign = client.put(f"/api/service-requests/{pay_req.id}/assign", json={
        "priority": "P2",
        "assigned_to_id": sarah.id
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_assign.status_code == 200
    assert res_assign.json()["priority"] == "P2"
    assert res_assign.json()["assigned_to_id"] == sarah.id

    res_approve = client.post(f"/api/service-requests/{pay_req.id}/approve", json={
        "decision": "Approved",
        "comments": "Security compliance verified"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_approve.status_code == 200
    assert res_approve.json()["request"]["approval_status"] == "Approved"

    # --- 3. CHANGE REQUESTS ---
    pay_chg = ChangeRequest(
        number="CHG8880001",
        short_description="Deploy Payment Service Hotfix 2.1",
        description="Hotfix for transaction latency",
        business_justification="Improve payment throughput",
        change_type="Standard",
        priority="P2",
        change_status="Draft",
        requested_by_id=john.id,
        project_id=pay_proj.id,
        application_id=pay_app.id,
        assignment_group_id=pay_l2.id if pay_l2 else None
    )
    cloud_chg = ChangeRequest(
        number="CHG8880002",
        short_description="Upgrade Kubernetes cluster to 1.28",
        description="Cluster upgrade for Cloud project",
        business_justification="Security patches and reliability",
        change_type="Normal",
        priority="P2",
        change_status="Draft",
        requested_by_id=admin.id,
        project_id=cloud_proj.id,
        application_id=cloud_app.id,
        assignment_group_id=cloud_l2.id if cloud_l2 else None
    )
    db_session.add(pay_chg)
    db_session.add(cloud_chg)
    db_session.commit()

    # Sarah lists change requests
    res_sarah_chg = client.get("/api/changes", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_chg.status_code == 200
    sarah_chg_numbers = [c["number"] for c in res_sarah_chg.json()]
    assert "CHG8880001" in sarah_chg_numbers
    assert "CHG8880002" not in sarah_chg_numbers

    # Mike lists change requests
    res_mike_chg = client.get("/api/changes", headers={"X-User-ID": str(mike.id)})
    assert res_mike_chg.status_code == 200
    mike_chg_numbers = [c["number"] for c in res_mike_chg.json()]
    assert "CHG8880002" in mike_chg_numbers
    assert "CHG8880001" not in mike_chg_numbers

    # Cross-project direct GET returns 403
    res_sarah_get_cloud_chg = client.get("/api/changes/CHG8880002", headers={"X-User-ID": str(sarah.id)})
    assert res_sarah_get_cloud_chg.status_code == 403

    # Sarah adds comments, work notes, reassigns, and approves payment change
    res_chg_comment = client.post(f"/api/changes/{pay_chg.id}/comments", json={
        "comment": "Pre-deployment checks passed"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_chg_comment.status_code == 200

    res_chg_work_note = client.post(f"/api/changes/{pay_chg.id}/work-notes", json={
        "note": "Internal: Rollback plan validated with backup database snapshot"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_chg_work_note.status_code == 200

    res_chg_assign = client.put(f"/api/changes/{pay_chg.id}/assign", json={
        "priority": "P1",
        "assigned_to_id": sarah.id
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_chg_assign.status_code == 200
    assert res_chg_assign.json()["priority"] == "P1"
    assert res_chg_assign.json()["assigned_to_id"] == sarah.id

    res_chg_approve = client.post(f"/api/changes/{pay_chg.id}/approve", json={
        "decision": "Approved",
        "comments": "CAB approved change"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_chg_approve.status_code == 200
    assert res_chg_approve.json()["change"]["cab_approval"] == "Approved"


def test_cross_project_reassignment_and_queue_visibility(db_session):
    """
    Verify ServiceNow-grade cross-project reassignment and visibility:
    1. Sarah (Payment Platform support) reassigns a Payment incident to Cloud Migration-l2.
    2. Mike (Cloud Migration support) can now see the Payment incident in his queue and access it via GET.
    3. Reassigning service request and change request to another project's group also provides
       immediate queue visibility to the target team.
    4. End user (John Smith) remains strictly isolated to tickets he requested.
    """
    from backend.security import _ensure_local_persona
    _ensure_local_persona(1, db_session)
    _ensure_local_persona(2, db_session)
    _ensure_local_persona(3, db_session)
    _ensure_local_persona(5, db_session)

    john = db_session.query(User).filter(User.username == "john.smith").first()
    sarah = db_session.query(User).filter(User.username == "sarah.johnson").first()
    mike = db_session.query(User).filter(User.username == "mike.brown").first()

    pay_proj = db_session.query(Project).filter(Project.name == "Payment Platform Modernization").first()
    cloud_proj = db_session.query(Project).filter(Project.name == "Cloud Migration").first()
    pay_l2 = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Payment Platform Modernization-l2").first()
    cloud_l2 = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Cloud Migration-l2").first()

    pay_app = db_session.query(Application).filter(Application.project_id == pay_proj.id).first()
    if not pay_app:
        pay_app = Application(app_id="APP-PAY-REASSIGN", name="Payment Core Service", project_id=pay_proj.id, active=True)
        db_session.add(pay_app)
        db_session.commit()

    cloud_app = db_session.query(Application).filter(Application.project_id == cloud_proj.id).first()
    if not cloud_app:
        cloud_app = Application(app_id="APP-CLOUD-REASSIGN", name="Cloud Cluster Service", project_id=cloud_proj.id, active=True)
        db_session.add(cloud_app)
        db_session.commit()

    # 1. Incident Cross-Project Reassignment
    inc = Incident(
        number="INC9990001",
        short_description="Cloud infrastructure timeout during payment processing",
        description="Originates in Payment Platform Modernization, needs Cloud Migration team triage",
        priority="P2",
        status="New",
        caller_id=john.id,
        project_id=pay_proj.id,
        application_id=pay_app.id,
        assignment_group_id=pay_l2.id
    )
    db_session.add(inc)
    db_session.commit()

    # Before transfer: Mike (Cloud support) cannot see Payment incident
    res_mike_before = client.get("/api/incidents", headers={"X-User-ID": str(mike.id)})
    assert "INC9990001" not in [i["number"] for i in res_mike_before.json()]

    # Sarah reassigns incident to Cloud Migration-l2 (transferring to Cloud team)
    res_transfer = client.patch(f"/api/incidents/{inc.id}/assign", json={
        "assignment_group_id": cloud_l2.id,
        "priority": "P2"
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_transfer.status_code == 200

    # After transfer: Mike (Cloud support) CAN see the incident in his queue!
    res_mike_after = client.get("/api/incidents", headers={"X-User-ID": str(mike.id)})
    assert "INC9990001" in [i["number"] for i in res_mike_after.json()]

    # Mike can also directly GET the incident
    res_mike_get = client.get(f"/api/incidents/{inc.number}", headers={"X-User-ID": str(mike.id)})
    assert res_mike_get.status_code == 200

    # 2. Service Request Cross-Project Reassignment
    req = ServiceRequest(
        number="REQ9990001",
        short_description="Provision AWS Kubernetes namespace for Payment Platform",
        description="Needs Cloud Migration team fulfillment",
        priority="P3",
        status="Submitted",
        requested_by_id=john.id,
        project_id=pay_proj.id,
        application_id=pay_app.id,
        assignment_group_id=pay_l2.id
    )
    db_session.add(req)
    db_session.commit()

    # Sarah transfers service request to Cloud Migration-l2
    res_req_transfer = client.patch(f"/api/service-requests/{req.id}/assign", json={
        "assignment_group_id": cloud_l2.id
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_req_transfer.status_code == 200

    # Mike now sees the service request in his queue and can GET it
    res_mike_req = client.get("/api/service-requests", headers={"X-User-ID": str(mike.id)})
    assert "REQ9990001" in [r["number"] for r in res_mike_req.json()]
    res_mike_req_get = client.get(f"/api/service-requests/{req.number}", headers={"X-User-ID": str(mike.id)})
    assert res_mike_req_get.status_code == 200

    # 3. Change Request Cross-Project Reassignment
    chg = ChangeRequest(
        number="CHG9990001",
        short_description="Migrate payment DB replica to AWS RDS",
        description="Requires Cloud Migration team execution",
        business_justification="Infrastructure modernization",
        change_type="Normal",
        priority="P2",
        change_status="Draft",
        requested_by_id=john.id,
        project_id=pay_proj.id,
        application_id=pay_app.id,
        assignment_group_id=pay_l2.id
    )
    db_session.add(chg)
    db_session.commit()

    # Sarah transfers change request to Cloud Migration-l2
    res_chg_transfer = client.patch(f"/api/changes/{chg.id}/assign", json={
        "assignment_group_id": cloud_l2.id
    }, headers={"X-User-ID": str(sarah.id)})
    assert res_chg_transfer.status_code == 200

    # Mike sees the change request in his queue and can GET it
    res_mike_chg = client.get("/api/changes", headers={"X-User-ID": str(mike.id)})
    assert "CHG9990001" in [c["number"] for c in res_mike_chg.json()]
    res_mike_chg_get = client.get(f"/api/changes/{chg.number}", headers={"X-User-ID": str(mike.id)})
    assert res_mike_chg_get.status_code == 200

    # 4. End user isolation: John only sees tickets where he is requester
    res_john_inc = client.get("/api/incidents", headers={"X-User-ID": str(john.id)})
    assert "INC9990001" in [i["number"] for i in res_john_inc.json()]


def test_project_specific_dashboard_and_filtering(db_session):
    """
    Verify that the dashboard metrics and analytics endpoints support project-specific telemetry
    when queried with project_name or project_id.
    """
    from backend.security import _ensure_local_persona
    _ensure_local_persona(1, db_session)
    _ensure_local_persona(3, db_session)

    admin = db_session.query(User).filter(User.username == "admin").first()
    sarah = db_session.query(User).filter(User.username == "sarah.johnson").first()

    pay_proj = db_session.query(Project).filter(Project.name == "Payment Platform Modernization").first()
    cloud_proj = db_session.query(Project).filter(Project.name == "Cloud Migration").first()
    assert pay_proj is not None and cloud_proj is not None

    # 1. Query dashboard scoped to Payment Platform Modernization
    res_pay = client.get(
        f"/api/dashboard?project_name={pay_proj.name}",
        headers={"X-User-ID": str(sarah.id)}
    )
    assert res_pay.status_code == 200
    data_pay = res_pay.json()
    assert data_pay["selected_project"] is not None
    assert data_pay["selected_project"]["id"] == pay_proj.id
    assert data_pay["selected_project"]["name"] == pay_proj.name
    assert "summary" in data_pay
    assert "open_incidents" in data_pay["summary"]

    # 2. Query dashboard scoped to Cloud Migration
    res_cloud = client.get(
        f"/api/dashboard?project_id={cloud_proj.id}",
        headers={"X-User-ID": str(admin.id)}
    )
    assert res_cloud.status_code == 200
    data_cloud = res_cloud.json()
    assert data_cloud["selected_project"] is not None
    assert data_cloud["selected_project"]["id"] == cloud_proj.id
    assert data_cloud["selected_project"]["name"] == cloud_proj.name

    # 3. Query analytics scoped to Payment Platform Modernization
    res_analytics = client.get(
        f"/api/dashboard/analytics?project_name={pay_proj.name}&time_period=30d",
        headers={"X-User-ID": str(admin.id)}
    )
    assert res_analytics.status_code == 200
    data_analytics = res_analytics.json()
    assert "summary" in data_analytics
    assert "total_tickets" in data_analytics["summary"]





