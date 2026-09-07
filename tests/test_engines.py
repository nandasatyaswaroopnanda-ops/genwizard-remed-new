import pytest
import datetime
from backend.mongo_dal import MongoSession, InMemoryDatabase
from backend.models import (
    User, Application, Project, AssignmentGroup, GroupMember,
    ProjectAssignmentMapping, RoutingRule, BusinessCalendar,
    SLAPolicy, SLAInstance, Incident, TicketWorkNote, TicketComment
)
from backend.routing_engine import RoutingEngine, calculate_priority
from backend.sla_engine import SLAEngine
from backend.workflow_engine import WorkflowEngine
from backend.ai_copilot import EnterpriseKnowledgeFallback

@pytest.fixture(scope="function")
def test_db():
    mem_db = InMemoryDatabase("test_engine_db")
    db = MongoSession(mem_db)

    # Seed basic entities for tests
    cal = BusinessCalendar(
        name="Standard India Hours",
        timezone="Asia/Kolkata",
        working_days="[1, 2, 3, 4, 5]",
        working_hours_start="09:00",
        working_hours_end="18:00",
        holidays='["2026-08-15"]'
    )
    db.add(cal)
    db.flush()

    grp_desk = AssignmentGroup(group_id="GRP0", name="Service Desk", active=True)
    grp_app = AssignmentGroup(group_id="GRP1", name="Payment Application Support", active=True)
    grp_db = AssignmentGroup(group_id="GRP2", name="Database Support", active=True)
    db.add_all([grp_desk, grp_app, grp_db])
    db.flush()

    app = Application(
        app_id="APP1",
        name="Payment Gateway",
        default_assignment_group_id=grp_app.id,
        active=True
    )
    db.add(app)
    db.flush()

    proj = Project(
        project_id="PRJ1",
        name="Payment Modernization",
        application_id=app.id,
        default_assignment_group_id=grp_app.id,
        active=True
    )
    db.add(proj)
    db.flush()

    # Explicit routing rule
    rule_db = RoutingRule(
        rule_code="R1021",
        name="Database Category Rule",
        priority_order=10,
        category="Database",
        assignment_group_id=grp_db.id,
        active=True
    )
    db.add(rule_db)

    # SLA Policy v1
    sla_v1 = SLAPolicy(
        policy_code="SLA101",
        name="Critical App SLA",
        version=1,
        priority="P1",
        response_target_mins=15,
        resolution_target_mins=240, # 4h
        business_calendar_id=cal.id,
        effective_from=datetime.datetime(2025, 1, 1),
        effective_to=datetime.datetime(2026, 12, 31),
        active=True
    )
    # SLA Policy v2 (effective from 2027)
    sla_v2 = SLAPolicy(
        policy_code="SLA101",
        name="Critical App SLA",
        version=2,
        priority="P1",
        response_target_mins=15,
        resolution_target_mins=120, # 2h
        business_calendar_id=cal.id,
        effective_from=datetime.datetime(2027, 1, 1),
        effective_to=None,
        active=True
    )
    db.add_all([sla_v1, sla_v2])
    db.commit()

    yield db
    db.close()

def test_priority_matrix_calculation():
    assert calculate_priority("Critical", "Critical") == "P1"
    assert calculate_priority("Critical", "High") == "P1"
    assert calculate_priority("High", "High") == "P1"
    assert calculate_priority("Critical", "Medium") == "P2"
    assert calculate_priority("Medium", "Medium") == "P3"
    assert calculate_priority("Low", "Low") == "P4"

def test_routing_engine_hierarchy(test_db):
    app = test_db.query(Application).first()
    proj = test_db.query(Project).first()

    # Tier 1: Explicit Category Rule (Database -> Database Support)
    res1 = RoutingEngine.resolve_assignment_group(test_db, app.id, proj.id, category="Database")
    assert res1["level"] == 1
    assert res1["assignment_group_name"] == "Database Support"
    assert res1["rule_code"] == "R1021"

    # Tier 4: Project Default when no explicit rule
    res2 = RoutingEngine.resolve_assignment_group(test_db, app.id, proj.id, category="General Inquiry")
    assert res2["level"] == 4
    assert res2["assignment_group_name"] == "Payment Application Support"

    # Tier 6: Global Default Fallback
    res3 = RoutingEngine.resolve_assignment_group(test_db, None, None, category="Unknown")
    assert res3["level"] == 6
    assert "Service Desk" in res3["assignment_group_name"]

def test_sla_versioning_and_effective_dates(test_db):
    # In 2026: should match v1 (4 hours)
    date_2026 = datetime.datetime(2026, 6, 1)
    sla_2026 = SLAEngine.resolve_sla_policy(test_db, priority="P1", creation_time=date_2026)
    assert sla_2026["policy"].version == 1
    assert sla_2026["policy"].resolution_target_mins == 240

    # In 2027: should match v2 (2 hours)
    date_2027 = datetime.datetime(2027, 2, 1)
    sla_2027 = SLAEngine.resolve_sla_policy(test_db, priority="P1", creation_time=date_2027)
    assert sla_2027["policy"].version == 2
    assert sla_2027["policy"].resolution_target_mins == 120

def test_sla_pause_and_resume(test_db):
    policy = test_db.query(SLAPolicy).filter(SLAPolicy.version == 1).first()
    resp_inst, res_inst = SLAEngine.start_sla_instances(test_db, 100, "INC0001001", "Incident", policy)
    assert res_inst.stage == "in_progress"

    # Move to Pending Customer -> pauses resolution SLA
    SLAEngine.handle_status_change(test_db, 100, "Incident", "In Progress", "Pending Customer", "Awaiting user logs")
    assert res_inst.stage == "paused"
    assert res_inst.paused_at is not None

    # Move back to In Progress -> resumes
    SLAEngine.handle_status_change(test_db, 100, "Incident", "Pending Customer", "In Progress", "Logs provided")
    assert res_inst.stage == "in_progress"

    # Move to Resolved -> achieves
    SLAEngine.handle_status_change(test_db, 100, "Incident", "In Progress", "Resolved", "Fixed")
    assert res_inst.stage == "achieved"
    assert res_inst.achieved_at is not None

def test_workflow_engine_transitions():
    valid, _ = WorkflowEngine.validate_transition("Incident", "New", "In Progress")
    assert valid is True

    valid, _ = WorkflowEngine.validate_transition("Incident", "Closed", "In Progress")
    assert valid is False

def test_enterprise_ai_fallback():
    resp, cites = EnterpriseKnowledgeFallback.generate_response(
        "Payment gateway returning 502 bad gateway error",
        {"application": "Payment Gateway", "short_description": "Payment API 502"}
    )
    assert "kubectl get pods" in resp
    assert len(cites) > 0
