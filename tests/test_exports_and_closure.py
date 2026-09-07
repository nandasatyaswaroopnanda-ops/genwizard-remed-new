import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_export_incidents_as_admin(client):
    res = client.get("/api/export/incidents?time_period=all&format=csv", headers={"X-User-ID": "1"})
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    content = res.text
    assert "Incident Number" in content
    assert "Priority" in content
    assert "Close Category" in content
    assert "ADO Work Item #" in content

def test_export_employee_forbidden(client):
    # Employee John Smith (ID: 2) is not a support member or admin
    res = client.get("/api/export/incidents?time_period=30d&format=csv", headers={"X-User-ID": "2"})
    assert res.status_code == 403
    assert "Access Denied" in res.json()["detail"]

def test_incident_closure_with_ado_and_categories(client):
    # 1. Create a test incident
    payload = {
        "caller_id": 2,
        "application_id": 1, # Payment Gateway
        "project_id": 1,
        "category": "Application",
        "subcategory": "API",
        "short_description": "Payment Gateway memory leak under burst traffic",
        "description": "Pods crashing with OOMKilled every 4 hours.",
        "impact": "High",
        "urgency": "High"
    }
    create_res = client.post("/api/incidents", json=payload, headers={"X-User-ID": "2"})
    assert create_res.status_code == 200
    inc = create_res.json()
    inc_num = inc["number"]

    # 2. Transition from New -> In Progress (Support engineer ID: 3)
    prog_res = client.patch(
        f"/api/incidents/{inc_num}/status",
        json={"status": "In Progress", "reason": "Investigating memory leak"},
        headers={"X-User-ID": "3"}
    )
    assert prog_res.status_code == 200

    # 3. Resolve incident with Root Cause Category = "Bug", Subcategory, and ADO Number
    resolve_payload = {
        "status": "Resolved",
        "resolution_code": "Solved by Patch / Code Fix",
        "resolution_notes": "Patched connection leak in Redis client pool. Deployed hotfix v2.4.1.",
        "close_category": "Bug",
        "close_subcategory": "Memory Leak / Unclosed Socket",
        "close_application_name": "Payment Gateway",
        "ado_number": "ADO-89412"
    }
    resolve_res = client.patch(
        f"/api/incidents/{inc_num}/status",
        json=resolve_payload,
        headers={"X-User-ID": "3"}
    )
    assert resolve_res.status_code == 200
    resolved_inc = resolve_res.json()
    assert resolved_inc["status"] == "Resolved"
    assert resolved_inc["close_category"] == "Bug"
    assert resolved_inc["close_subcategory"] == "Memory Leak / Unclosed Socket"
    assert resolved_inc["ado_number"] == "ADO-89412"

    # 4. Fetch detail and verify fields persist
    detail_res = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "1"})
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["category"] == "Bug"
    assert detail["subcategory"] == "Memory Leak / Unclosed Socket"
    assert detail["close_category"] == "Bug"
    assert detail["close_subcategory"] == "Memory Leak / Unclosed Socket"
    assert detail["ado_number"] == "ADO-89412"
    assert "Patched connection leak" in detail["resolution_notes"]

    # 5. Check Analytics endpoint reflects the Bug and ADO tracking
    analytics_res = client.get("/api/dashboard/analytics?time_period=all", headers={"X-User-ID": "1"})
    assert analytics_res.status_code == 200
    analytics = analytics_res.json()
    assert analytics["closure_categories"]["Bug"] >= 1
    assert any(b["ado_number"] == "ADO-89412" for b in analytics["ado_bugs"])
