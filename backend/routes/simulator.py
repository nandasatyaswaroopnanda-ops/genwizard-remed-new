import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from backend.database import get_db
from backend.models import Application, Project, AssignmentGroup, SLAPolicy, BusinessCalendar
from backend.routing_engine import RoutingEngine, calculate_priority
from backend.sla_engine import SLAEngine

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

class SimulationRequestSchema(BaseModel):
    application_id: Optional[int] = None
    project_id: Optional[int] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    impact: str = "High"
    urgency: str = "High"
    ticket_type: str = "Incident"
    simulation_time: Optional[datetime.datetime] = None

@router.post("")
def run_simulation(
    payload: SimulationRequestSchema,
    db: Session = Depends(get_db)
):
    sim_time = payload.simulation_time or datetime.datetime.utcnow()

    # 1. Calculated Priority
    priority = calculate_priority(payload.impact, payload.urgency)

    # 2. 6-tier Routing Engine Evaluation
    routing_trace = RoutingEngine.resolve_assignment_group(
        db=db,
        application_id=payload.application_id,
        project_id=payload.project_id,
        category=payload.category,
        subcategory=payload.subcategory
    )

    # 3. SLA Resolution Hierarchy Evaluation
    sla_trace = SLAEngine.resolve_sla_policy(
        db=db,
        priority=priority,
        ticket_type=payload.ticket_type,
        application_id=payload.application_id,
        project_id=payload.project_id,
        assignment_group_id=routing_trace["assignment_group_id"],
        creation_time=sim_time
    )

    policy: Optional[SLAPolicy] = sla_trace.get("policy")
    calendar_name = "24x7 Global Operations"
    calendar_tz = "UTC"
    calendar_hours = "24 Hours"

    if policy and policy.business_calendar:
        calendar_name = policy.business_calendar.name
        calendar_tz = policy.business_calendar.timezone
        calendar_hours = f"{policy.business_calendar.working_hours_start} - {policy.business_calendar.working_hours_end}"

    # Calculate expected response and resolution due dates
    resp_mins = policy.response_target_mins if policy else 60
    res_mins = policy.resolution_target_mins if policy else 240
    cal = policy.business_calendar if policy else None

    resp_due = SLAEngine.calculate_due_date(sim_time, resp_mins, cal)
    res_due = SLAEngine.calculate_due_date(sim_time, res_mins, cal)

    # App and Project details for context
    app_obj = db.query(Application).filter(Application.id == payload.application_id).first() if payload.application_id else None
    proj_obj = db.query(Project).filter(Project.id == payload.project_id).first() if payload.project_id else None

    return {
        "simulation_timestamp": sim_time.isoformat(),
        "input": {
            "application_id": payload.application_id,
            "application_name": app_obj.name if app_obj else "None",
            "project_id": payload.project_id,
            "project_name": proj_obj.name if proj_obj else "None",
            "category": payload.category or "None",
            "subcategory": payload.subcategory or "None",
            "impact": payload.impact,
            "urgency": payload.urgency
        },
        "calculated_priority": priority,
        "selected_assignment_group": {
            "id": routing_trace["assignment_group_id"],
            "name": routing_trace["assignment_group_name"],
            "matched_hierarchy_level": routing_trace["level"],
            "matched_rule_type": routing_trace["matched_rule_type"],
            "rule_code": routing_trace["rule_code"],
            "rule_name": routing_trace["rule_name"],
            "reason": routing_trace["reason"]
        },
        "selected_sla": {
            "id": policy.id if policy else None,
            "policy_code": policy.policy_code if policy else "None",
            "name": policy.name if policy else "No Matching SLA",
            "version": policy.version if policy else 1,
            "matched_hierarchy_level": sla_trace["level"],
            "rule_type": sla_trace["rule_type"],
            "reason": sla_trace["reason"],
            "response_target_mins": resp_mins,
            "resolution_target_mins": res_mins,
            "response_target_formatted": f"{resp_mins} mins" if resp_mins < 60 else f"{resp_mins // 60} hours {resp_mins % 60} mins",
            "resolution_target_formatted": f"{res_mins} mins" if res_mins < 60 else f"{res_mins // 60} hours",
            "simulated_response_due": resp_due.isoformat(),
            "simulated_resolution_due": res_due.isoformat()
        },
        "business_calendar": {
            "name": calendar_name,
            "timezone": calendar_tz,
            "working_hours": calendar_hours
        }
    }
