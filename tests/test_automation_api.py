"""Tests for Ticket Automation & Auto-Closure APIs:
1. Incident automated resolution and auto-closure batch endpoint.
2. Service Request automated fulfillment and auto-closure batch endpoint.
3. Change Request automated completion and closure.
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_incident_direct_auto_resolution(client):
    """External automation bot creates an incident and immediately auto-resolves it."""
    # 1. External monitoring tool logs an incident
    create_res = client.post("/api/incidents", json={
        "caller_id": 2,
        "application_id": 1,
        "project_id": 1,
        "category": "Application",
        "short_description": "Auto-detected high memory on pod-svc-payment",
        "description": "Triggered by Prometheus alert memory > 90%",
        "impact": "Medium",
        "urgency": "High"
    }, headers={"X-User-ID": "1"})
    assert create_res.status_code == 200
    inc = create_res.json()
    inc_num = inc["number"]
    assert inc["status"] == "New"

    # 2. Auto-remediation script restarts pod and resolves incident directly
    resolve_res = client.patch(f"/api/incidents/{inc_num}/status", json={
        "status": "Resolved",
        "resolution_code": "Automated Remediation",
        "resolution_notes": "Pod restarted automatically by Kubernetes operator. Memory usage returned to 22%.",
        "close_category": "Infrastructure Limitation"
    }, headers={"X-User-ID": "1"})
    assert resolve_res.status_code == 200
    resolved = resolve_res.json()
    assert resolved["status"] == "Resolved"
    assert resolved["resolution_code"] == "Automated Remediation"
    assert "restarted automatically" in resolved["resolution_notes"]

    # 3. Add automated work note
    note_res = client.post(f"/api/incidents/{inc_num}/work-notes", json={
        "note": "Operator trace ID: k8s-exec-89127391. Health check confirmed 200 OK."
    }, headers={"X-User-ID": "1"})
    assert note_res.status_code == 200


def test_incident_auto_close_batch_api(client):
    """External scheduler/cron calls the auto-close endpoint to close resolved tickets."""
    # 1. Create and resolve an incident
    create_res = client.post("/api/incidents", json={
        "caller_id": 2,
        "application_id": 1,
        "project_id": 1,
        "category": "Application",
        "short_description": "Network latency spike",
        "description": "Transient latency observed in eu-west-1",
        "impact": "Low",
        "urgency": "Low"
    }, headers={"X-User-ID": "1"})
    assert create_res.status_code == 200
    inc_num = create_res.json()["number"]

    # Resolve it
    client.patch(f"/api/incidents/{inc_num}/status", json={
        "status": "Resolved",
        "resolution_code": "Self-Corrected",
        "resolution_notes": "AWS network issue resolved"
    }, headers={"X-User-ID": "1"})

    # 2. Invoke batch auto-close with 0 hours (immediate test)
    autoclose_res = client.post("/api/incidents/auto-close", json={
        "hours_in_resolved": 0,
        "close_notes": "Automatically closed by nightly IT automation job",
        "dry_run": False
    }, headers={"X-User-ID": "1"})
    assert autoclose_res.status_code == 200
    res_data = autoclose_res.json()
    assert res_data["status"] == "success"
    assert res_data["auto_closed_count"] >= 1
    assert inc_num in res_data["auto_closed_tickets"]

    # 3. Verify incident is now Closed
    get_res = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "1"})
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "Closed"


def test_service_request_auto_fulfillment_and_closure(client):
    """External IAM automation bot fulfills access request and auto-closes it."""
    # 1. User requests database read access
    create_res = client.post("/api/service-requests", json={
        "catalog_item": "Standard Developer Tools",
        "short_description": "Request IDE License",
        "description": "Need VSCode plugin license",
        "application_id": 1,
        "project_id": 1,
        "priority": "P3"
    }, headers={"X-User-ID": "2"})
    assert create_res.status_code == 200
    req = create_res.json()
    req_num = req["number"]

    # 2. External automation provisions license and marks Fulfilled
    fulfill_res = client.patch(f"/api/service-requests/{req_num}/status", json={
        "status": "Fulfilled",
        "reason": "License provisioned automatically via License Manager API"
    }, headers={"X-User-ID": "1"})
    assert fulfill_res.status_code == 200
    assert fulfill_res.json()["status"] == "Fulfilled"

    # 3. Batch auto-close fulfilled requests
    autoclose_res = client.post("/api/service-requests/auto-close", json={
        "hours_in_fulfilled": 0,
        "close_notes": "Auto-closed after fulfillment"
    }, headers={"X-User-ID": "1"})
    assert autoclose_res.status_code == 200
    assert req_num in autoclose_res.json()["auto_closed_tickets"]

    # 4. Confirm ticket status is Closed
    get_res = client.get(f"/api/service-requests/{req_num}", headers={"X-User-ID": "1"})
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "Closed"


def test_change_request_automated_progression(client):
    """CI/CD automation pipeline updates change request through implementation to Closed."""
    # 1. Create standard change
    create_res = client.post("/api/changes", json={
        "application_id": 1,
        "project_id": 1,
        "change_type": "Standard",
        "category": "Software",
        "short_description": "Automated deployment v3.2.1 to production",
        "description": "Release pipeline triggered by git tag v3.2.1",
        "business_justification": "Routine sprint release",
        "risk": "Low",
        "impact": "Low",
        "priority": "P3"
    }, headers={"X-User-ID": "1"})
    assert create_res.status_code == 200
    chg = create_res.json()
    chg_num = chg["number"]
    assert chg["change_status"] == "Scheduled"

    # 2. CI/CD pipeline starts: moves to Implementation
    client.patch(f"/api/changes/{chg_num}/status", json={
        "change_status": "Implementation",
        "reason": "GitLab CI runner deployed manifest"
    }, headers={"X-User-ID": "1"})

    # 3. Post-deployment smoke tests succeed: moves directly to Completed
    client.patch(f"/api/changes/{chg_num}/status", json={
        "change_status": "Completed",
        "reason": "Synthetic smoke tests 100% passed"
    }, headers={"X-User-ID": "1"})

    # 4. CI/CD pipeline closes change
    close_res = client.patch(f"/api/changes/{chg_num}/status", json={
        "change_status": "Closed",
        "reason": "Automated deployment lifecycle finished successfully"
    }, headers={"X-User-ID": "1"})
    assert close_res.status_code == 200
    assert close_res.json()["change_status"] == "Closed"
