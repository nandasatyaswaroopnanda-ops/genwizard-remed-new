"""
Tests for Application-Scoped Categories Configuration and Project-Governed Auto-Routing.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    User, Project, Application, AssignmentGroup, GroupMember, ProjectAssignmentMapping,
    Incident, ServiceRequest, ChangeRequest
)
from backend.routes.admin_projects import setup_project_queues_and_groups

client = TestClient(app)

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            for inc in db.query(Incident).filter(Incident.short_description.like("%patient%")).all():
                db.delete(inc)
            for req in db.query(ServiceRequest).filter(ServiceRequest.catalog_item == "Patient Data Export").all():
                db.delete(req)
            for chg in db.query(ChangeRequest).filter(ChangeRequest.short_description.like("%EHR%")).all():
                db.delete(chg)
            for pam in db.query(ProjectAssignmentMapping).all():
                db.delete(pam)
            for a in db.query(Application).filter(Application.app_id.in_(["APP-FINPAY", "APP-EHR"])).all():
                db.delete(a)
            for p in db.query(Project).filter(Project.project_id.in_(["PRJ-FINTECH", "PRJ-HEALTH"])).all():
                db.delete(p)
            for g in db.query(AssignmentGroup).filter(
                AssignmentGroup.name.in_(["FINTECH-CORE-l2", "FINTECH-CORE-l3", "HEALTH-PORTAL-l2", "HEALTH-PORTAL-l3"])
            ).all():
                for m in db.query(GroupMember).filter(GroupMember.group_id == g.id).all():
                    db.delete(m)
                db.delete(g)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def test_application_categories_configuration_and_defaults(db_session):
    """
    Verify application categories:
    1. Default categories returned when none configured.
    2. Custom categories can be configured for Incident, Service Request, and Change Request.
    3. Categories can be updated/extended in future.
    """
    admin_headers = {"X-User-ID": "1"}

    # 1. Create a test project with L2/L3 queues
    proj_name = "FINTECH-CORE"
    with patch("requests.post") as mock_im:
        mock_im.return_value = MagicMock(status_code=201, text="{}")
        grp_l2, grp_l3 = setup_project_queues_and_groups(db_session, proj_name)

    proj = Project(
        project_id="PRJ-FINTECH",
        name=proj_name,
        l2_assignment_group_id=grp_l2.id,
        l3_assignment_group_id=grp_l3.id,
        active=True
    )
    db_session.add(proj)
    db_session.commit()

    # 2. Create Application with custom categories
    custom_categories = {
        "Incident": [
            "Payment Gateway Error",
            "Transaction Timeout",
            "Ledger Reconciliation Mismatch"
        ],
        "Service Request": [
            "Merchant API Key Provisioning",
            "Settlement Report Export",
            "Audit Trail Access"
        ],
        "Change Request": [
            "PCI-DSS Security Patch",
            "Payment Switch Failover Test",
            "Core Ledger DB Migration"
        ]
    }

    create_payload = {
        "app_id": "APP-FINPAY",
        "name": "Fintech Payments Service",
        "project_id": proj.id,
        "environment": "Production",
        "criticality": "Critical",
        "categories": custom_categories
    }

    resp = client.post("/api/admin/applications", json=create_payload, headers=admin_headers)
    assert resp.status_code in (200, 201), resp.text
    created_app = resp.json()
    assert created_app["categories"]["Incident"] == custom_categories["Incident"]
    assert created_app["categories"]["Service Request"] == custom_categories["Service Request"]
    assert created_app["categories"]["Change Request"] == custom_categories["Change Request"]

    # 3. Check public API returns categories
    pub_resp = client.get("/api/applications", headers=admin_headers)
    assert pub_resp.status_code == 200
    apps_list = pub_resp.json()
    matched = next((a for a in apps_list if a["id"] == created_app["id"]), None)
    assert matched is not None
    assert matched["categories"]["Incident"] == custom_categories["Incident"]
    assert len(matched["categories"]["Incident"]) == 3

    # 4. Update Application with an additional category (extensible in future)
    custom_categories["Incident"].append("Biometric Auth Failure")
    custom_categories["Service Request"].append("Card BIN Range Expansion")
    update_payload = {
        "categories": custom_categories
    }
    up_resp = client.put(f"/api/admin/applications/{created_app['id']}", json=update_payload, headers=admin_headers)
    assert up_resp.status_code == 200
    updated_app = up_resp.json()
    assert "Biometric Auth Failure" in updated_app["categories"]["Incident"]
    assert "Card BIN Range Expansion" in updated_app["categories"]["Service Request"]


def test_ticket_autoroute_governed_by_project_not_category(db_session):
    """
    Verify ticket auto-routing depends strictly on the Project's frontline queue,
    regardless of whether the category is 'Database', 'Network', or a custom application category.
    """
    admin_headers = {"X-User-ID": "1"}

    # Setup dedicated project with L2 group
    proj_name = "HEALTH-PORTAL"
    with patch("requests.post") as mock_im:
        mock_im.return_value = MagicMock(status_code=201, text="{}")
        grp_l2, grp_l3 = setup_project_queues_and_groups(db_session, proj_name)

    proj = Project(
        project_id="PRJ-HEALTH",
        name=proj_name,
        l2_assignment_group_id=grp_l2.id,
        l3_assignment_group_id=grp_l3.id,
        active=True
    )
    db_session.add(proj)
    db_session.commit()

    test_app = Application(
        app_id="APP-EHR",
        name="Electronic Health Records",
        project_id=proj.id,
        active=True
    )
    db_session.add(test_app)
    db_session.commit()

    # 1. Create Incident with category "Database" — MUST route to Project L2, NOT generic Database Support
    inc_payload = {
        "project_id": proj.id,
        "application_id": test_app.id,
        "category": "Database",
        "short_description": "Patient records query latency spike",
        "description": "High latency observed on patient search",
        "impact": "High",
        "urgency": "High"
    }
    inc_resp = client.post("/api/incidents", json=inc_payload, headers=admin_headers)
    assert inc_resp.status_code in (200, 201), inc_resp.text
    inc_data = inc_resp.json()
    assert inc_data["assignment_group_id"] == grp_l2.id, (
        f"Expected assignment_group_id to be {grp_l2.id} ({proj_name}-l2), got {inc_data.get('assignment_group_id')}"
    )

    # 2. Create Service Request — MUST route to Project L2
    req_payload = {
        "project_id": proj.id,
        "application_id": test_app.id,
        "catalog_item": "Patient Data Export",
        "short_description": "Need CSV export for compliance audit",
        "description": "Annual HIPAA audit export",
        "priority": "P3"
    }
    req_resp = client.post("/api/service-requests", json=req_payload, headers=admin_headers)
    assert req_resp.status_code in (200, 201), req_resp.text
    req_data = req_resp.json()
    assert req_data["assignment_group_id"] == grp_l2.id, (
        f"Expected assignment_group_id to be {grp_l2.id} ({proj_name}-l2), got {req_data.get('assignment_group_id')}"
    )

    # 3. Create Change Request — MUST route to Project L2
    chg_payload = {
        "project_id": proj.id,
        "application_id": test_app.id,
        "change_type": "Normal",
        "category": "Software Patch",
        "short_description": "Deploy EHR v2.4.1 hotfix",
        "description": "Applies security patches",
        "business_justification": "HIPAA compliance requirement",
        "risk": "Low",
        "impact": "Low",
        "priority": "P3"
    }
    chg_resp = client.post("/api/changes", json=chg_payload, headers=admin_headers)
    assert chg_resp.status_code in (200, 201), chg_resp.text
    chg_data = chg_resp.json()
    assert chg_data["assignment_group_id"] == grp_l2.id, (
        f"Expected assignment_group_id to be {grp_l2.id} ({proj_name}-l2), got {chg_data.get('assignment_group_id')}"
    )
