import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_end_user_ticket_creation_initial_status_active(client):
    # End user John Smith (ID: 2) creates an incident
    inc_payload = {
        "caller_id": 2,
        "application_id": 1,
        "project_id": 1,
        "category": "Software",
        "short_description": "End user incident creation test",
        "description": "Reporting an issue from end user portal",
        "impact": "Medium",
        "urgency": "Medium"
    }
    res = client.post("/api/incidents", json=inc_payload, headers={"X-User-ID": "2"})
    assert res.status_code == 200
    inc = res.json()
    assert inc["status"] == "Active", f"Expected initial status 'Active' for end-user incident, got {inc['status']}"

    # End user John Smith creates a service request
    req_payload = {
        "catalog_item": "PostgreSQL Sandbox",
        "short_description": "Need DB sandbox for testing",
        "description": "Environment request",
        "priority": "P3",
        "application_id": 1,
        "project_id": 1
    }
    req_res = client.post("/api/service-requests", json=req_payload, headers={"X-User-ID": "2"})
    assert req_res.status_code == 200
    req = req_res.json()
    assert req["status"] == "Active", f"Expected initial status 'Active' for service request, got {req['status']}"

def test_reassignment_auto_status_transitions(client):
    # Admin creates an incident
    inc_payload = {
        "caller_id": 2,
        "application_id": 1,
        "project_id": 1,
        "category": "Application",
        "short_description": "Testing reassignment auto status",
        "description": "Testing reassignment status rules",
        "impact": "Low",
        "urgency": "Low"
    }
    res = client.post("/api/incidents", json=inc_payload, headers={"X-User-ID": "1"})
    assert res.status_code == 200
    inc_id = res.json()["id"]

    # Reassign with only assignment_group_id (no assignee) -> status must become "Active"
    assign_res = client.patch(
        f"/api/incidents/{inc_id}/assign",
        json={"assignment_group_id": 1, "assigned_to_id": None},
        headers={"X-User-ID": "1"}
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["status"] == "Active", f"Expected Active when assigned to group only, got {assign_res.json()['status']}"

    # Reassign with assignment_group_id AND assigned_to_id -> status must become "In Progress"
    assign_user_res = client.patch(
        f"/api/incidents/{inc_id}/assign",
        json={"assignment_group_id": 1, "assigned_to_id": 3},
        headers={"X-User-ID": "1"}
    )
    assert assign_user_res.status_code == 200
    assert assign_user_res.json()["status"] == "In Progress", f"Expected In Progress when assigned to specific user, got {assign_user_res.json()['status']}"

def test_service_request_reassignment_status_transitions(client):
    req_payload = {
        "catalog_item": "VPN Access",
        "short_description": "VPN Access request for contractor",
        "description": "Access provisioning",
        "priority": "P3",
        "application_id": 1,
        "project_id": 1
    }
    req_res = client.post("/api/service-requests", json=req_payload, headers={"X-User-ID": "1"})
    assert req_res.status_code == 200
    req_id = req_res.json()["id"]

    # Reassign with group only -> Active
    assign_res = client.patch(
        f"/api/service-requests/{req_id}/assign",
        json={"assignment_group_id": 1, "assigned_to_id": None},
        headers={"X-User-ID": "1"}
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["status"] == "Active"

    # Reassign with user -> In Progress
    assign_user_res = client.patch(
        f"/api/service-requests/{req_id}/assign",
        json={"assignment_group_id": 1, "assigned_to_id": 3},
        headers={"X-User-ID": "1"}
    )
    assert assign_user_res.status_code == 200
    assert assign_user_res.json()["status"] == "In Progress"

def test_export_column_filtering(client):
    # CSV export with selected columns
    res_csv = client.get(
        "/api/export/incidents?format=csv&columns=Incident Number,Status,Priority",
        headers={"X-User-ID": "1"}
    )
    assert res_csv.status_code == 200
    csv_lines = res_csv.text.strip().splitlines()
    header = csv_lines[0].split(",")
    assert header == ["Incident Number", "Status", "Priority"]
    # Verify rows only have 3 columns
    if len(csv_lines) > 1:
        row = csv_lines[1].split(",")
        assert len(row) == 3

    # JSON export with selected columns
    res_json = client.get(
        "/api/export/incidents?format=json&columns=Incident Number,Status",
        headers={"X-User-ID": "1"}
    )
    assert res_json.status_code == 200
    data = res_json.json()
    assert isinstance(data, list)
    if data:
        assert set(data[0].keys()) == {"Incident Number", "Status"}

def test_group_eligible_assignees_excludes_end_users(client):
    # Fetch assignees for support group 1
    res = client.get("/api/admin/groups/1/assignees", headers={"X-User-ID": "1"})
    assert res.status_code == 200
    assignees = res.json()
    assert isinstance(assignees, list)
    # Ensure end user John Smith (ID 2, role 'employee') is NOT in eligible assignees
    for u in assignees:
        assert u["role"] != "employee", f"End user {u['full_name']} found in eligible assignees"

def test_assignment_groups_filter_by_project_and_application(client):
    import json
    from backend.database import SessionLocal
    from backend.models import Project, Application, AssignmentGroup

    db_session = SessionLocal()
    try:
        # 1. Verify project-based filtering
        res_proj = client.get("/api/assignment-groups?project_name=Payment%20Platform%20Modernization")
        assert res_proj.status_code == 200
        p_groups = res_proj.json()
        group_names = [g["name"] for g in p_groups]
        assert any("Payment Platform Modernization" in name for name in group_names)
        assert not any("Customer Portal Modernization" in name for name in group_names)

        # 2. Setup an application with specific supported assignment group
        proj = db_session.query(Project).filter(Project.name == "Payment Platform Modernization").first()
        app = Application(
            app_id="APP-TEST-CHK",
            name="Checkout Engine Test",
            project_id=proj.id if proj else 1,
            active=True
        )
        db_session.add(app)
        db_session.flush()

        app_group = AssignmentGroup(
            group_id="grp-checkout-ops",
            name="Checkout Ops Special Squad",
            applications_supported=json.dumps(["Checkout Engine Test"]),
            projects_supported=json.dumps(["Payment Platform Modernization"]),
            active=True
        )
        db_session.add(app_group)
        db_session.commit()

        # 3. Query by application_name
        res_app = client.get("/api/assignment-groups?application_name=Checkout%20Engine%20Test")
        assert res_app.status_code == 200
        app_groups = res_app.json()
        app_grp_names = [g["name"] for g in app_groups]
        assert "Checkout Ops Special Squad" in app_grp_names

        # 4. Query by both project_id and application_id
        res_both = client.get(f"/api/assignment-groups?project_id={proj.id}&application_id={app.id}")
        assert res_both.status_code == 200
        both_groups = res_both.json()
        both_names = [g["name"] for g in both_groups]
        assert "Checkout Ops Special Squad" in both_names
        # 5. Query by multiple comma-separated application names
        res_multi = client.get("/api/assignment-groups?application_names=Checkout%20Engine%20Test,NonExistentApp")
        assert res_multi.status_code == 200
        multi_groups = res_multi.json()
        multi_names = [g["name"] for g in multi_groups]
        assert "Checkout Ops Special Squad" in multi_names
    finally:
        db_session.close()

def test_assignment_groups_filter_by_multiple_applications(client):
    res = client.get("/api/assignment-groups?application_names=Customer%20Portal,Payment%20Gateway")
    assert res.status_code == 200
    groups = res.json()
    assert isinstance(groups, list)
    assert len(groups) > 0

def test_public_applications_and_projects_endpoints(client):
    res_apps = client.get("/api/applications")
    assert res_apps.status_code == 200
    apps = res_apps.json()
    assert isinstance(apps, list)
    assert len(apps) > 0
    assert any(a["name"] == "Customer Portal" for a in apps)

    res_projs = client.get("/api/projects")
    assert res_projs.status_code == 200
    projs = res_projs.json()
    assert isinstance(projs, list)
    assert len(projs) > 0



