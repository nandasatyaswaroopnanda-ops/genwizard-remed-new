import json
import yaml
import datetime
import os
import requests
from fastapi import APIRouter, Depends, HTTPException, Header, Response, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from backend.database import get_db
from backend.models import (
    Application, Project, AssignmentGroup, RoutingRule,
    ProjectAssignmentMapping, SLAPolicy, BusinessCalendar,
    ConfigurationAudit, AIConfiguration, User, ClosureTaxonomy, TicketColumnPreference,
    DistributionList, CustomGroup
)
from backend.security import require_admin

router = APIRouter(prefix="/api/admin/config", tags=["admin-config"])

@router.get("/graph")
def get_configuration_graph(db: Session = Depends(get_db)):
    """
    Returns nodes and edges representing the complete configuration hierarchy:
    Application -> Project -> Routing Rules -> Assignment Group -> SLA Policy -> Calendar
    """
    nodes = []
    edges = []

    apps = db.query(Application).filter(Application.active == True).all()
    projects = db.query(Project).filter(Project.active == True).all()
    groups = db.query(AssignmentGroup).filter(AssignmentGroup.active == True).all()
    rules = db.query(RoutingRule).filter(RoutingRule.active == True).all()
    slas = db.query(SLAPolicy).filter(SLAPolicy.active == True).all()

    # Applications
    for a in apps:
        nodes.append({
            "id": f"app_{a.id}",
            "type": "application",
            "label": a.name,
            "subtitle": f"Code: {a.app_id} | Criticality: {a.criticality}",
            "details": a.to_dict()
        })

    # Projects
    for p in projects:
        nodes.append({
            "id": f"proj_{p.id}",
            "type": "project",
            "label": p.name,
            "subtitle": f"PM: {p.project_manager or 'None'} | Env: {p.environment}",
            "details": p.to_dict()
        })
        edges.append({
            "from": f"app_{p.application_id}",
            "to": f"proj_{p.id}",
            "label": "owns project"
        })

    # Groups
    for g in groups:
        nodes.append({
            "id": f"group_{g.id}",
            "type": "group",
            "label": g.name,
            "subtitle": f"Code: {g.group_id} | Mgr: {g.manager.full_name if g.manager else 'None'}",
            "details": g.to_dict()
        })

    # Connect Projects to Default Groups or Mappings
    for p in projects:
        if p.default_assignment_group_id:
            edges.append({
                "from": f"proj_{p.id}",
                "to": f"group_{p.default_assignment_group_id}",
                "label": "default support group"
            })

    # Routing Rules
    for r in rules:
        nodes.append({
            "id": f"rule_{r.id}",
            "type": "routing_rule",
            "label": f"Rule {r.rule_code}: {r.category or 'Any'}",
            "subtitle": f"Priority: {r.priority_order}",
            "details": r.to_dict()
        })
        if r.project_id:
            edges.append({"from": f"proj_{r.project_id}", "to": f"rule_{r.id}", "label": "evaluates"})
        edges.append({"from": f"rule_{r.id}", "to": f"group_{r.assignment_group_id}", "label": "routes to"})

    # SLAs
    for s in slas:
        nodes.append({
            "id": f"sla_{s.id}",
            "type": "sla_policy",
            "label": f"{s.name} v{s.version}",
            "subtitle": f"P1: {s.response_target_mins}m resp / {s.resolution_target_mins}m res",
            "details": s.to_dict()
        })
        if s.assignment_group_id:
            edges.append({
                "from": f"group_{s.assignment_group_id}",
                "to": f"sla_{s.id}",
                "label": "governed by SLA"
            })
        elif s.project_id:
            edges.append({
                "from": f"proj_{s.project_id}",
                "to": f"sla_{s.id}",
                "label": "project SLA"
            })

    return {"nodes": nodes, "edges": edges}

@router.get("/validation")
def validate_configuration(db: Session = Depends(get_db)):
    """
    Scans platform entities and detects configuration gaps, conflicts, and risks.
    """
    issues = []
    now = datetime.datetime.utcnow()

    # 1. Projects with missing default assignment groups
    projects = db.query(Project).filter(Project.active == True).all()
    for p in projects:
        if not p.default_assignment_group_id:
            issues.append({
                "level": "warning",
                "entity": "Project",
                "entity_name": p.name,
                "code": "MISSING_DEFAULT_GROUP",
                "message": f"Project '{p.name}' does not have a default Assignment Group configured."
            })
        if not p.default_sla_policy_id:
            issues.append({
                "level": "warning",
                "entity": "Project",
                "entity_name": p.name,
                "code": "MISSING_DEFAULT_SLA",
                "message": f"Project '{p.name}' does not have a default SLA policy configured."
            })

    # 2. Assignment Groups with missing default SLA
    groups = db.query(AssignmentGroup).filter(AssignmentGroup.active == True).all()
    for g in groups:
        if not g.default_sla_policy_id and not g.business_calendar_id:
            issues.append({
                "level": "info",
                "entity": "AssignmentGroup",
                "entity_name": g.name,
                "code": "MISSING_GROUP_SLA",
                "message": f"Assignment Group '{g.name}' does not have an explicit SLA or calendar (falling back to global)."
            })

    # 3. Duplicate routing rules (same app + project + category)
    rules = db.query(RoutingRule).filter(RoutingRule.active == True).all()
    seen_combos = set()
    for r in rules:
        combo = (r.application_id, r.project_id, (r.category or "").lower())
        if combo in seen_combos:
            issues.append({
                "level": "warning",
                "entity": "RoutingRule",
                "entity_name": r.rule_code,
                "code": "DUPLICATE_ROUTING_RULE",
                "message": f"Routing Rule '{r.rule_code}' conflicts with another rule having the same Application, Project, and Category scope."
            })
        seen_combos.add(combo)

    # 4. Expired SLA policies
    slas = db.query(SLAPolicy).all()
    for s in slas:
        if s.effective_to and s.effective_to < now and s.active:
            issues.append({
                "level": "error",
                "entity": "SLAPolicy",
                "entity_name": f"{s.name} v{s.version}",
                "code": "EXPIRED_SLA_POLICY",
                "message": f"SLA Policy '{s.name} v{s.version}' has passed its effective end date ({s.effective_to.strftime('%Y-%m-%d')}) but is still marked active."
            })
        if not s.resolution_target_mins or s.resolution_target_mins <= 0:
            issues.append({
                "level": "error",
                "entity": "SLAPolicy",
                "entity_name": f"{s.name} v{s.version}",
                "code": "INVALID_RESOLUTION_TARGET",
                "message": f"SLA Policy '{s.name} v{s.version}' has no resolution target specified."
            })

    return {
        "status": "issues_found" if issues else "clean",
        "total_issues": len(issues),
        "issues": issues
    }

@router.get("/export")
def export_configuration(format: str = "json", db: Session = Depends(get_db)):
    """
    Exports the complete platform configuration (Applications, Projects, Groups, Rules, SLAs, Calendars, DLs, KM).
    """
    km_cfg = db.query(AIConfiguration).first()
    km_data = {
        "base_url": km_cfg.km_base_url if km_cfg else "https://internal-km.company.local",
        "endpoint": km_cfg.api_endpoint if km_cfg else "/api/chat/completions",
        "username": km_cfg.username if km_cfg else "",
        "index": km_cfg.km_index if (km_cfg and km_cfg.km_index) else "itsm-kb",
        "auth_token": km_cfg.auth_token if km_cfg else "env:KM_API_TOKEN"
    }

    export_data = {
        "metadata": {
            "platform": "Enterprise ITSM Control Plane",
            "version": "1.0.0",
            "exported_at": datetime.datetime.utcnow().isoformat(),
            "format": format
        },
        "applications": [a.to_dict() for a in db.query(Application).all()],
        "projects": [p.to_dict() for p in db.query(Project).all()],
        "assignment_groups": [g.to_dict() for g in db.query(AssignmentGroup).all()],
        "distribution_lists": [dl.to_dict() for dl in db.query(DistributionList).filter(DistributionList.active == True).all()],
        "routing_rules": [r.to_dict() for r in db.query(RoutingRule).all()],
        "project_mappings": [m.to_dict() for m in db.query(ProjectAssignmentMapping).all()],
        "sla_policies": [s.to_dict() for s in db.query(SLAPolicy).all()],
        "business_calendars": [c.to_dict() for c in db.query(BusinessCalendar).all()],
        "closure_taxonomy": [c.to_dict() for c in db.query(ClosureTaxonomy).all()],
        "ticket_columns": [c.to_dict() for c in db.query(TicketColumnPreference).all()],
        "custom_groups": [cg.to_dict() for cg in db.query(CustomGroup).filter(CustomGroup.active == True).all()],
        "km_config": km_data
    }

    if format.lower() == "yaml":
        yaml_content = yaml.dump(export_data, default_flow_style=False)
        return Response(content=yaml_content, media_type="application/x-yaml")
    else:
        return export_data


@router.get("/consul-status")
def get_consul_status():
    """Check Consul connectivity and configuration status."""
    address = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
    token = os.getenv("CONSUL_HTTP_TOKEN", "")
    if not address:
        return {
            "configured": False,
            "connected": False,
            "message": "CONSUL_HTTP_ADDR environment variable is not configured",
            "address": None
        }
    headers = {"X-Consul-Token": token} if token else {}
    try:
        resp = requests.get(f"{address}/v1/status/leader", headers=headers, timeout=3)
        connected = resp.status_code == 200
        return {
            "configured": True,
            "connected": connected,
            "address": address,
            "leader": resp.text.strip('"') if connected else None,
            "message": "Connected to Consul" if connected else f"Consul responded with HTTP {resp.status_code}"
        }
    except Exception as e:
        return {
            "configured": True,
            "connected": False,
            "address": address,
            "message": f"Could not connect to Consul: {str(e)}"
        }


@router.put("/sync-consul")
def sync_configuration_to_consul(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Mirror all configurable UI entities and KM parameters to Consul KV."""
    address = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
    token = os.getenv("CONSUL_HTTP_TOKEN", "")
    if not address:
        raise HTTPException(status_code=503, detail="CONSUL_HTTP_ADDR environment variable is not configured")
    
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Consul-Token"] = token
    snapshot = export_configuration(format="json", db=db)
    synced_keys = []

    try:
        # 1. Write full snapshot
        r = requests.put(
            f"{address}/v1/kv/nexus-itsm/config/snapshot.json",
            headers=headers,
            data=json.dumps(snapshot),
            timeout=5
        )
        r.raise_for_status()
        synced_keys.append("nexus-itsm/config/snapshot.json")

        # 2. Write individual entity trees for granular Consul management
        granular_mappings = [
            ("nexus-itsm/config/applications", snapshot.get("applications", [])),
            ("nexus-itsm/config/projects", snapshot.get("projects", [])),
            ("nexus-itsm/config/assignment_groups", snapshot.get("assignment_groups", [])),
            ("nexus-itsm/config/distribution_lists", snapshot.get("distribution_lists", [])),
            ("nexus-itsm/config/closure_taxonomy", snapshot.get("closure_taxonomy", [])),
            ("nexus-itsm/config/ticket_columns", snapshot.get("ticket_columns", [])),
            ("nexus-itsm/config/routing_rules", snapshot.get("routing_rules", [])),
            ("nexus-itsm/config/sla_policies", snapshot.get("sla_policies", [])),
            ("nexus-itsm/config/km_config", snapshot.get("km_config", {})),
        ]
        for key_path, data in granular_mappings:
            requests.put(
                f"{address}/v1/kv/{key_path}",
                headers=headers,
                data=json.dumps(data),
                timeout=4
            )
            synced_keys.append(key_path)

    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Could not write configuration to Consul: {str(exc)}") from exc

    return {
        "message": "All configurable UI entities and KM parameters mirrored to Consul KV",
        "synced_keys": synced_keys,
        "total_keys": len(synced_keys)
    }


@router.post("/load-consul")
def load_configuration_from_consul(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Load and apply configuration snapshot from Consul KV into the platform database."""
    address = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
    token = os.getenv("CONSUL_HTTP_TOKEN", "")
    if not address:
        raise HTTPException(status_code=503, detail="CONSUL_HTTP_ADDR environment variable is not configured")
    
    headers = {"X-Consul-Token": token} if token else {}
    try:
        resp = requests.get(f"{address}/v1/kv/nexus-itsm/config/snapshot.json", params={"raw": ""}, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch configuration from Consul: {str(exc)}")

    # Delegate to import_configuration logic
    import_result = import_configuration(data, db=db)
    return {
        "message": "Configuration successfully loaded and restored from Consul KV",
        "import_result": import_result
    }


@router.get("/audits")
def list_configuration_audits(db: Session = Depends(get_db)):
    audits = db.query(ConfigurationAudit).order_by(desc(ConfigurationAudit.created_at)).limit(100).all()
    return [a.to_dict() for a in audits]
