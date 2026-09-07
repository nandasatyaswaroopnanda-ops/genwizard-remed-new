import pytest
import json
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    User, Project, Application, CustomGroup, UserCustomGroup,
    ConfigurationAudit, AssignmentGroup
)

client = TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_only_admin_can_delete_project(db_session):
    """
    Verify:
    1. Project support members / project admins (e.g. in <project>-admin) CANNOT delete projects (403).
    2. Regular end users CANNOT delete projects (403).
    3. Only global admin user has privilege to delete project (200).
    """
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    assert admin_user is not None

    proj_name = "ProjDelTest"
    proj_code = "PRJ_DEL_001"
    test_proj = Project(
        project_id=proj_code,
        name=proj_name,
        description="Test project for deletion RBAC",
        environment="Production",
        criticality="High"
    )
    db_session.add(test_proj)
    db_session.commit()
    db_session.refresh(test_proj)

    # Setup project-admin group and project admin user
    proj_admin_group = CustomGroup(name=f"{proj_name}-admin", description=f"Admins for {proj_name}")
    db_session.add(proj_admin_group)
    db_session.commit()
    db_session.refresh(proj_admin_group)

    proj_admin_user = User(
        employee_id="EMP-TEST-DEL-01",
        username="del_proj_lead",
        email="del_proj_lead@example.com",
        full_name="Project Lead User",
        role="employee",
        is_local=True
    )
    db_session.add(proj_admin_user)
    db_session.commit()
    db_session.refresh(proj_admin_user)

    membership = UserCustomGroup(user_id=proj_admin_user.id, custom_group_id=proj_admin_group.id)
    db_session.add(membership)
    db_session.commit()

    regular_user = User(
        employee_id="EMP-TEST-DEL-02",
        username="del_regular_user",
        email="del_regular@example.com",
        full_name="Regular End User",
        role="employee",
        is_local=True
    )
    db_session.add(regular_user)
    db_session.commit()
    db_session.refresh(regular_user)

    try:
        # A. Regular end user attempts to delete project -> 403 Forbidden
        res_regular = client.delete(
            f"/api/admin/projects/{test_proj.id}",
            headers={"X-User-ID": str(regular_user.id)}
        )
        assert res_regular.status_code == 403, f"Expected 403 for regular user, got {res_regular.status_code}: {res_regular.text}"

        # B. Project support member part of <project>-admin attempts to delete project -> 403 Forbidden
        res_proj_admin = client.delete(
            f"/api/admin/projects/{test_proj.id}",
            headers={"X-User-ID": str(proj_admin_user.id)}
        )
        assert res_proj_admin.status_code == 403, f"Expected 403 for project admin, got {res_proj_admin.status_code}: {res_proj_admin.text}"
        assert "Only system administrator can delete projects" in res_proj_admin.json()["detail"]

        # Also verify public alias /api/projects/{id}
        res_proj_alias = client.delete(
            f"/api/projects/{test_proj.id}",
            headers={"X-User-ID": str(proj_admin_user.id)}
        )
        assert res_proj_alias.status_code == 403

        # C. Global admin user deletes project -> 200 OK
        res_admin = client.delete(
            f"/api/admin/projects/{test_proj.id}",
            headers={"X-User-ID": str(admin_user.id)}
        )
        assert res_admin.status_code == 200, f"Expected 200 for global admin, got {res_admin.status_code}: {res_admin.text}"
        assert f"Project '{proj_name}'" in res_admin.json()["message"]
        assert "deleted successfully" in res_admin.json()["message"]

        # Verify project is deleted in DB
        db_proj = db_session.query(Project).filter(Project.id == test_proj.id).first()
        assert db_proj is None, "Project should be deleted from DB"

        # Verify audit record created
        audit = db_session.query(ConfigurationAudit).filter(
            ConfigurationAudit.entity_type == "Project",
            ConfigurationAudit.entity_id == proj_code
        ).first()
        assert audit is not None
        assert "Deleted project" in audit.reason

    finally:
        # Cleanup users/groups
        for ucg in db_session.query(UserCustomGroup).filter(UserCustomGroup.user_id == proj_admin_user.id).all():
            db_session.delete(ucg)
        for u in db_session.query(User).filter(User.id.in_([proj_admin_user.id, regular_user.id])).all():
            db_session.delete(u)
        for cg in db_session.query(CustomGroup).filter(CustomGroup.id == proj_admin_group.id).all():
            db_session.delete(cg)
        for p in db_session.query(Project).filter(Project.id == test_proj.id).all():
            db_session.delete(p)
        db_session.commit()


def test_delete_project_cascades_to_respective_apps_and_assignment_groups(db_session):
    """
    Verify:
    When a project is deleted:
    1. All respective applications under it are also deleted.
    2. All respective assignment groups (<project>-l2, <project>-l3, etc.) under it are also deleted.
    3. Custom / IM groups (<project>-admin, <project>-user) are also deleted.
    4. The global fallback 'Service Desk' queue is preserved and NOT deleted.
    5. The project itself is deleted.
    """
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    assert admin_user is not None

    # Ensure Service Desk baseline exists
    sd_group = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Service Desk").first()
    if not sd_group:
        sd_group = AssignmentGroup(group_id="GRP-SD", name="Service Desk", description="Global Fallback", active=True)
        db_session.add(sd_group)
        db_session.commit()
        db_session.refresh(sd_group)

    # 1. Create Project
    proj_name = "CascadeProject"
    proj_code = "PRJ_CAS_001"
    proj = Project(
        project_id=proj_code,
        name=proj_name,
        description="Project to test full cascading deletion of apps and groups",
        environment="Production",
        criticality="High"
    )
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    # 2. Create Assignment Groups for this project (Level-2 and Level-3)
    grp_l2 = AssignmentGroup(
        group_id="GRP-CAS-L2",
        name=f"{proj_name}-l2",
        description=f"L2 queue for {proj_name}",
        projects_supported=json.dumps([proj_name]),
        active=True
    )
    grp_l3 = AssignmentGroup(
        group_id="GRP-CAS-L3",
        name=f"{proj_name}-l3",
        description=f"L3 queue for {proj_name}",
        projects_supported=json.dumps([proj_name]),
        active=True
    )
    db_session.add_all([grp_l2, grp_l3])
    db_session.commit()
    db_session.refresh(grp_l2)
    db_session.refresh(grp_l3)

    # Link groups to project
    proj.l2_assignment_group_id = grp_l2.id
    proj.l3_assignment_group_id = grp_l3.id
    proj.default_assignment_group_id = grp_l2.id
    db_session.add(proj)
    db_session.commit()

    # 3. Create Applications under this project
    app1 = Application(
        app_id="APP_CAS_1",
        name="CascadeAppCore",
        project_id=proj.id,
        default_assignment_group_id=grp_l2.id,
        criticality="Critical"
    )
    app2 = Application(
        app_id="APP_CAS_2",
        name="CascadeAppPortal",
        project_id=proj.id,
        default_assignment_group_id=grp_l2.id,
        criticality="High"
    )
    db_session.add_all([app1, app2])
    db_session.commit()
    db_session.refresh(app1)
    db_session.refresh(app2)

    # 4. Create Custom / IM groups for this project
    cg_admin = CustomGroup(name=f"{proj_name}-admin", description=f"{proj_name} Admins")
    cg_user = CustomGroup(name=f"{proj_name}-user", description=f"{proj_name} Users")
    db_session.add_all([cg_admin, cg_user])
    db_session.commit()
    db_session.refresh(cg_admin)
    db_session.refresh(cg_user)

    try:
        # 5. Global Admin deletes the project
        res = client.delete(
            f"/api/admin/projects/{proj.id}",
            headers={"X-User-ID": str(admin_user.id)}
        )
        assert res.status_code == 200, f"Delete failed: {res.text}"
        data = res.json()

        assert "deleted successfully" in data["message"]
        assert "CascadeAppCore" in data.get("deleted_applications", [])
        assert "CascadeAppPortal" in data.get("deleted_applications", [])
        assert f"{proj_name}-l2" in data.get("deleted_assignment_groups", [])
        assert f"{proj_name}-l3" in data.get("deleted_assignment_groups", [])

        # 6. Verify Project is deleted
        assert db_session.query(Project).filter(Project.id == proj.id).first() is None

        # 7. Verify all respective Applications under this project are deleted
        assert db_session.query(Application).filter(Application.id.in_([app1.id, app2.id])).first() is None

        # 8. Verify all respective Assignment Groups under this project are deleted
        assert db_session.query(AssignmentGroup).filter(AssignmentGroup.id.in_([grp_l2.id, grp_l3.id])).first() is None

        # 9. Verify Custom / IM groups are deleted
        assert db_session.query(CustomGroup).filter(CustomGroup.id.in_([cg_admin.id, cg_user.id])).first() is None

        # 10. Verify global 'Service Desk' group is NOT deleted
        sd_check = db_session.query(AssignmentGroup).filter(AssignmentGroup.name == "Service Desk").first()
        assert sd_check is not None, "Global Service Desk group must be preserved!"

    finally:
        # Fallback cleanup in case assertions failed
        for cg in db_session.query(CustomGroup).filter(CustomGroup.id.in_([cg_admin.id, cg_user.id])).all():
            db_session.delete(cg)
        for a in db_session.query(Application).filter(Application.id.in_([app1.id, app2.id])).all():
            db_session.delete(a)
        for g in db_session.query(AssignmentGroup).filter(AssignmentGroup.id.in_([grp_l2.id, grp_l3.id])).all():
            db_session.delete(g)
        for p in db_session.query(Project).filter(Project.id == proj.id).all():
            db_session.delete(p)
        db_session.commit()


def test_project_support_members_can_delete_applications_of_their_project(db_session):
    """
    Verify:
    1. Project support members who are part of <project>-admin CAN delete applications belonging to their project (200).
    2. They CANNOT delete applications belonging to other projects (403).
    3. Regular end-users CANNOT delete applications (403).
    4. Global admin CAN delete any application (200).
    """
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    assert admin_user is not None

    # Create Project Alpha and Project Beta
    proj_alpha = Project(project_id="PRJ_ALPHA", name="AlphaProj", environment="Production", criticality="High")
    proj_beta = Project(project_id="PRJ_BETA", name="BetaProj", environment="Production", criticality="High")
    db_session.add_all([proj_alpha, proj_beta])
    db_session.commit()
    db_session.refresh(proj_alpha)
    db_session.refresh(proj_beta)

    # Create App for Alpha and App for Beta
    app_alpha = Application(
        app_id="APP_ALPHA",
        name="AlphaApp",
        project_id=proj_alpha.id,
        criticality="High",
        support_hours="24x7"
    )
    app_beta = Application(
        app_id="APP_BETA",
        name="BetaApp",
        project_id=proj_beta.id,
        criticality="High",
        support_hours="24x7"
    )
    db_session.add_all([app_alpha, app_beta])
    db_session.commit()
    db_session.refresh(app_alpha)
    db_session.refresh(app_beta)

    # Create Alpha Project Admin Group & Member
    group_alpha_admin = CustomGroup(name=f"{proj_alpha.name}-admin", description="Alpha Admins")
    db_session.add(group_alpha_admin)
    db_session.commit()
    db_session.refresh(group_alpha_admin)

    alpha_member = User(
        employee_id="EMP-TEST-DEL-ALPHA",
        username="alpha_team_lead",
        email="alpha_lead@example.com",
        full_name="Alpha Team Lead",
        role="employee",
        is_local=True
    )
    db_session.add(alpha_member)
    db_session.commit()
    db_session.refresh(alpha_member)

    membership_alpha = UserCustomGroup(user_id=alpha_member.id, custom_group_id=group_alpha_admin.id)
    db_session.add(membership_alpha)
    db_session.commit()

    # Create regular user
    reg_user = User(
        employee_id="EMP-TEST-DEL-REG",
        username="app_reg_user",
        email="app_reg@example.com",
        full_name="Regular User",
        role="employee",
        is_local=True
    )
    db_session.add(reg_user)
    db_session.commit()
    db_session.refresh(reg_user)

    try:
        # A. Regular user tries to delete AlphaApp -> 403 Forbidden
        res_reg = client.delete(
            f"/api/admin/applications/{app_alpha.id}",
            headers={"X-User-ID": str(reg_user.id)}
        )
        assert res_reg.status_code == 403

        # B. Alpha member tries to delete BetaApp (belongs to BetaProj) -> 403 Forbidden
        res_cross = client.delete(
            f"/api/admin/applications/{app_beta.id}",
            headers={"X-User-ID": str(alpha_member.id)}
        )
        assert res_cross.status_code == 403, f"Expected 403 for cross-project app deletion, got {res_cross.status_code}: {res_cross.text}"
        assert "You can only delete applications belonging to your project(s)" in res_cross.json()["detail"]

        # C. Alpha member deletes AlphaApp (belongs to AlphaProj) -> 200 OK
        res_alpha_del = client.delete(
            f"/api/admin/applications/{app_alpha.id}",
            headers={"X-User-ID": str(alpha_member.id)}
        )
        assert res_alpha_del.status_code == 200, f"Expected 200 for Alpha member deleting AlphaApp, got {res_alpha_del.status_code}: {res_alpha_del.text}"
        assert f"Application '{app_alpha.name}' deleted successfully" in res_alpha_del.json()["message"]

        # Verify AlphaApp is deleted from DB
        db_app_alpha = db_session.query(Application).filter(Application.id == app_alpha.id).first()
        assert db_app_alpha is None

        # Verify audit log for application deletion
        audit = db_session.query(ConfigurationAudit).filter(
            ConfigurationAudit.entity_type == "Application",
            ConfigurationAudit.entity_id == app_alpha.app_id
        ).first()
        assert audit is not None
        assert "Deleted application" in audit.reason

        # D. Global admin deletes BetaApp -> 200 OK
        res_beta_del = client.delete(
            f"/api/admin/applications/{app_beta.id}",
            headers={"X-User-ID": str(admin_user.id)}
        )
        assert res_beta_del.status_code == 200
        assert f"Application '{app_beta.name}' deleted successfully" in res_beta_del.json()["message"]

        db_app_beta = db_session.query(Application).filter(Application.id == app_beta.id).first()
        assert db_app_beta is None

    finally:
        for ucg in db_session.query(UserCustomGroup).filter(UserCustomGroup.user_id == alpha_member.id).all():
            db_session.delete(ucg)
        for u in db_session.query(User).filter(User.id.in_([alpha_member.id, reg_user.id])).all():
            db_session.delete(u)
        for cg in db_session.query(CustomGroup).filter(CustomGroup.id == group_alpha_admin.id).all():
            db_session.delete(cg)
        for a in db_session.query(Application).filter(Application.id.in_([app_alpha.id, app_beta.id])).all():
            db_session.delete(a)
        for p in db_session.query(Project).filter(Project.id.in_([proj_alpha.id, proj_beta.id])).all():
            db_session.delete(p)
        db_session.commit()
