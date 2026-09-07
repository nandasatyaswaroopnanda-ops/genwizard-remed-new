import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import User, Incident, ServiceRequest, ChangeRequest, SLAInstance, TicketWorkNote, TicketComment, Notification

@pytest.fixture
def client():
    return TestClient(app)

def test_full_incident_lifecycle(client):
    # 1. Employee John Smith (ID: 2) creates Incident
    payload = {
        "caller_id": 2,
        "application_id": 1, # Payment Gateway
        "project_id": 1, # Payment Platform Modernization
        "category": "Application",
        "subcategory": "API",
        "short_description": "Payment checkout tokenization latency spike",
        "description": "Observed 3000ms latency on /v1/tokens endpoint.",
        "impact": "High",
        "urgency": "High"
    }
    create_res = client.post("/api/incidents", json=payload, headers={"X-User-ID": "2"})
    assert create_res.status_code == 200
    inc = create_res.json()

    assert inc["number"].startswith("INC")
    assert inc["priority"] == "P1"
    assert inc["status"] in ("Active", "New")

    inc_id = inc["id"]
    inc_num = inc["number"]

    # 2. Verify SLA instances started
    detail_res = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "2"})
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert len(detail_data["sla_instances"]) >= 2

    # 3. Support Engineer Sarah Johnson (ID: 3) assigns ticket to herself
    assign_res = client.patch(f"/api/incidents/{inc_num}/assign", json={"assigned_to_id": 3}, headers={"X-User-ID": "3"})
    assert assign_res.status_code == 200
    assert assign_res.json()["status"] in ("In Progress", "Assigned")

    # 4. Engineer adds internal work note
    wn_res = client.post(f"/api/incidents/{inc_num}/work-notes", json={"note": "Pods inspected. Threadpool queue size increased."}, headers={"X-User-ID": "3"})
    assert wn_res.status_code == 200

    # 5. STRICT SECURITY VERIFICATION: Employee John Smith CANNOT see internal work notes
    emp_view = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "2"}).json()
    assert len(emp_view["work_notes"]) == 0 # Work notes hidden!

    # Support view CAN see internal work notes
    supp_view = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "3"}).json()
    assert len(supp_view["work_notes"]) >= 1

    # 6. Engineer posts customer-visible comment
    comm_res = client.post(f"/api/incidents/{inc_num}/comments", json={"comment": "We have applied a configuration update and are monitoring."}, headers={"X-User-ID": "3"})
    assert comm_res.status_code == 200

    # Employee views ticket and sees customer comment
    emp_view2 = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "2"}).json()
    assert len(emp_view2["comments"]) >= 1

    # 7. Employee replies with comment
    reply_res = client.post(f"/api/incidents/{inc_num}/comments", json={"comment": "Latency has returned to normal. Thank you!"}, headers={"X-User-ID": "2"})
    assert reply_res.status_code == 200

    # 8. Engineer resolves ticket
    resolve_res = client.patch(f"/api/incidents/{inc_num}/status", json={
        "status": "Resolved",
        "resolution_code": "Solved by Configuration Change",
        "resolution_notes": "Increased connection threadpool to 200."
    }, headers={"X-User-ID": "3"})
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "Resolved"

    # 9. Verify SLA marked achieved
    final_view = client.get(f"/api/incidents/{inc_num}", headers={"X-User-ID": "3"}).json()
    res_sla = [s for s in final_view["sla_instances"] if s["target_type"] == "resolution"][0]
    assert res_sla["stage"] == "achieved"
    assert res_sla["achieved_at"] is not None

def test_change_request_cab_approval_workflow(client):
    # 1. Create Change Request
    payload = {
        "application_id": 1,
        "project_id": 1,
        "change_type": "Normal",
        "category": "Infrastructure",
        "short_description": "Upgrade Redis cluster nodes to v7.2",
        "description": "Patch CVE-2024-xxx security vulnerability on in-memory cache.",
        "business_justification": "Required for compliance audit.",
        "risk": "High",
        "impact": "Medium",
        "priority": "P2"
    }
    res = client.post("/api/changes", json=payload, headers={"X-User-ID": "3"})
    assert res.status_code == 200
    chg = res.json()
    chg_num = chg["number"]
    assert chg["approval_status"] == "Pending"

    # 2. Admin approves Change Request
    appr_res = client.post(f"/api/changes/{chg_num}/approve", json={"decision": "Approved", "comments": "Approved by CAB committee."}, headers={"X-User-ID": "1"})
    assert appr_res.status_code == 200
    assert appr_res.json()["change"]["approval_status"] == "Approved"
    assert appr_res.json()["change"]["change_status"] == "Scheduled"

    # 3. Transition to Implementation -> Completed
    impl_res = client.patch(f"/api/changes/{chg_num}/status", json={"change_status": "Implementation"}, headers={"X-User-ID": "3"})
    assert impl_res.status_code == 200

    val_res = client.patch(f"/api/changes/{chg_num}/status", json={"change_status": "Validation"}, headers={"X-User-ID": "3"})
    assert val_res.status_code == 200

    comp_res = client.patch(f"/api/changes/{chg_num}/status", json={"change_status": "Completed"}, headers={"X-User-ID": "3"})
    assert comp_res.status_code == 200
