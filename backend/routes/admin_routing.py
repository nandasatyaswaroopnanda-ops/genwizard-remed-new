import json
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel

from backend.database import get_db
from backend.models import RoutingRule, User, ConfigurationAudit
from backend.security import require_admin

router = APIRouter(prefix="/api/admin/routing-rules", tags=["admin-routing"])

class RoutingRuleSchema(BaseModel):
    rule_code: str
    name: str
    priority_order: int = 10
    application_id: Optional[int] = None
    project_id: Optional[int] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    assignment_group_id: int
    active: bool = True
    description: Optional[str] = None
    reason: Optional[str] = "Routing rule update"

@router.get("")
def list_rules(db: Session = Depends(get_db)):
    rules = db.query(RoutingRule).order_by(RoutingRule.priority_order.asc()).all()
    return [r.to_dict() for r in rules]

@router.post("")
def create_rule(
    payload: RoutingRuleSchema,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    rule = RoutingRule(
        rule_code=payload.rule_code,
        name=payload.name,
        priority_order=payload.priority_order,
        application_id=payload.application_id,
        project_id=payload.project_id,
        category=payload.category,
        subcategory=payload.subcategory,
        assignment_group_id=payload.assignment_group_id,
        active=payload.active,
        description=payload.description
    )
    db.add(rule)
    db.flush()

    audit = ConfigurationAudit(
        entity_type="RoutingRule",
        entity_id=rule.rule_code,
        user_name=current_user.full_name,
        old_configuration="{}",
        new_configuration=json.dumps(rule.to_dict()),
        reason=payload.reason or "Created new routing rule",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return rule.to_dict()

@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RoutingRuleSchema,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    rule = db.query(RoutingRule).filter(RoutingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found")

    old_cfg = rule.to_dict()
    rule.rule_code = payload.rule_code
    rule.name = payload.name
    rule.priority_order = payload.priority_order
    rule.application_id = payload.application_id
    rule.project_id = payload.project_id
    rule.category = payload.category
    rule.subcategory = payload.subcategory
    rule.assignment_group_id = payload.assignment_group_id
    rule.active = payload.active
    rule.description = payload.description

    new_cfg = rule.to_dict()
    audit = ConfigurationAudit(
        entity_type="RoutingRule",
        entity_id=rule.rule_code,
        user_name=current_user.full_name,
        old_configuration=json.dumps(old_cfg),
        new_configuration=json.dumps(new_cfg),
        reason=payload.reason or "Updated routing rule",
        effective_date=datetime.datetime.utcnow()
    )
    db.add(audit)
    db.commit()
    return rule.to_dict()

@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rule = db.query(RoutingRule).filter(RoutingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    db.delete(rule)
    db.commit()
    return {"message": "Rule deleted"}
