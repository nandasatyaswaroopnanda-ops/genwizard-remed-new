from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from backend.models import RoutingRule, ProjectAssignmentMapping, Project, Application, AssignmentGroup
import datetime

PRIORITY_MATRIX = {
    ("Critical", "Critical"): "P1",
    ("Critical", "High"): "P1",
    ("High", "Critical"): "P1",
    ("High", "High"): "P1",
    ("Critical", "Medium"): "P2",
    ("High", "Medium"): "P2",
    ("Medium", "Critical"): "P2",
    ("Medium", "High"): "P2",
    ("Medium", "Medium"): "P3",
    ("High", "Low"): "P3",
    ("Low", "Critical"): "P3",
    ("Low", "High"): "P3",
    ("Medium", "Low"): "P4",
    ("Low", "Medium"): "P4",
    ("Low", "Low"): "P4",
}

def calculate_priority(impact: str, urgency: str) -> str:
    key = (impact or "Medium", urgency or "Medium")
    return PRIORITY_MATRIX.get(key, "P3")

class RoutingEngine:
    @staticmethod
    def resolve_assignment_group(
        db: Session,
        application_id: Optional[int],
        project_id: Optional[int],
        category: Optional[str] = None,
        subcategory: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates the 6-tier routing hierarchy:
        1. Explicit routing rule (Category/Subcategory + App/Project)
        2. Application + Project + Category mapping
        3. Application + Project mapping
        4. Project default Assignment Group
        5. Application default Assignment Group
        6. Global default Assignment Group (Service Desk)
        """
        now = datetime.datetime.utcnow()

        # Derive project_id from application if not explicitly provided
        if application_id and not project_id:
            app_obj = db.query(Application).filter(Application.id == application_id).first()
            if app_obj and getattr(app_obj, "project_id", None):
                project_id = app_obj.project_id

        # 1. Explicit Routing Rules (Ordered by priority_order ascending)
        rules_query = db.query(RoutingRule).filter(RoutingRule.active == True)
        if application_id:
            rules_query = rules_query.filter(
                (RoutingRule.application_id == application_id) | (RoutingRule.application_id.is_(None))
            )
        if project_id:
            rules_query = rules_query.filter(
                (RoutingRule.project_id == project_id) | (RoutingRule.project_id.is_(None))
            )

        active_rules = rules_query.order_by(RoutingRule.priority_order.asc()).all()

        for rule in active_rules:
            # Check effective dates if present
            if rule.effective_from and rule.effective_from > now:
                continue
            if rule.effective_to and rule.effective_to < now:
                continue

            match = True
            if rule.application_id and rule.application_id != application_id:
                match = False
            if rule.project_id and rule.project_id != project_id:
                match = False
            if rule.category and rule.category.strip().lower() != (category or "").strip().lower():
                match = False
            if rule.subcategory and rule.subcategory.strip().lower() != (subcategory or "").strip().lower():
                match = False

            if match:
                group = db.query(AssignmentGroup).filter(AssignmentGroup.id == rule.assignment_group_id, AssignmentGroup.active == True).first()
                if group:
                    return {
                        "assignment_group_id": group.id,
                        "assignment_group_name": group.name,
                        "level": 1,
                        "matched_rule_type": "Explicit Routing Rule",
                        "rule_code": rule.rule_code,
                        "rule_name": rule.name,
                        "reason": f"Matched explicit routing rule #{rule.rule_code} ('{rule.name}')"
                    }

        # 2. Application + Project + Category Mapping
        if application_id and project_id and category:
            cat_mapping = db.query(ProjectAssignmentMapping).filter(
                ProjectAssignmentMapping.application_id == application_id,
                ProjectAssignmentMapping.project_id == project_id,
                ProjectAssignmentMapping.category == category,
                ProjectAssignmentMapping.active == True
            ).order_by(ProjectAssignmentMapping.routing_priority.asc()).first()

            if cat_mapping:
                if (not cat_mapping.effective_from or cat_mapping.effective_from <= now) and \
                   (not cat_mapping.effective_to or cat_mapping.effective_to >= now):
                    group = db.query(AssignmentGroup).filter(AssignmentGroup.id == cat_mapping.assignment_group_id, AssignmentGroup.active == True).first()
                    if group:
                        return {
                            "assignment_group_id": group.id,
                            "assignment_group_name": group.name,
                            "level": 2,
                            "matched_rule_type": "App + Project + Category Mapping",
                            "rule_code": cat_mapping.mapping_id,
                            "rule_name": f"Mapping {cat_mapping.mapping_id}",
                            "reason": f"Matched App + Project + Category mapping #{cat_mapping.mapping_id}"
                        }

        # 3. Project Default Assignment Group (Level-2 Support Queue)
        if project_id:
            project = db.query(Project).filter(Project.id == project_id, Project.active == True).first()
            if project:
                target_gid = getattr(project, "l2_assignment_group_id", None) or project.default_assignment_group_id
                if target_gid:
                    group = db.query(AssignmentGroup).filter(AssignmentGroup.id == target_gid, AssignmentGroup.active == True).first()
                    if group:
                        return {
                            "assignment_group_id": group.id,
                            "assignment_group_name": group.name,
                            "level": 4,
                            "matched_rule_type": "Project Level-2 Default",
                            "rule_code": f"PROJ-{project.project_id}",
                            "rule_name": f"Default Level-2 Queue for {project.name}",
                            "reason": f"Routed to Level-2 Assignment Group configured for Project '{project.name}'"
                        }
                # Fallback to <project>-l2 queue by convention
                l2_name = f"{project.name.strip()}-l2"
                l2_group = db.query(AssignmentGroup).filter(
                    AssignmentGroup.name.ilike(l2_name),
                    AssignmentGroup.active == True
                ).first()
                if l2_group:
                    return {
                        "assignment_group_id": l2_group.id,
                        "assignment_group_name": l2_group.name,
                        "level": 4,
                        "matched_rule_type": "Project Level-2 Queue",
                        "rule_code": f"PROJ-{project.project_id}-L2",
                        "rule_name": l2_group.name,
                        "reason": f"Auto-routed to Level-2 Assignment Group for Project '{project.name}'"
                    }

        # 4. Application + Project Mapping (Fallback custom mapping)
        if application_id and project_id:
            proj_mapping = db.query(ProjectAssignmentMapping).filter(
                ProjectAssignmentMapping.application_id == application_id,
                ProjectAssignmentMapping.project_id == project_id,
                (ProjectAssignmentMapping.category.is_(None) | (ProjectAssignmentMapping.category == "")),
                ProjectAssignmentMapping.active == True
            ).order_by(ProjectAssignmentMapping.routing_priority.asc()).first()

            if proj_mapping:
                if (not proj_mapping.effective_from or proj_mapping.effective_from <= now) and \
                   (not proj_mapping.effective_to or proj_mapping.effective_to >= now):
                    group = db.query(AssignmentGroup).filter(AssignmentGroup.id == proj_mapping.assignment_group_id, AssignmentGroup.active == True).first()
                    if group:
                        return {
                            "assignment_group_id": group.id,
                            "assignment_group_name": group.name,
                            "level": 3,
                            "matched_rule_type": "App + Project Mapping",
                            "rule_code": proj_mapping.mapping_id,
                            "rule_name": f"Mapping {proj_mapping.mapping_id}",
                            "reason": f"Matched App + Project mapping #{proj_mapping.mapping_id}"
                        }

        # 5. Application Default Assignment Group
        if application_id:
            app = db.query(Application).filter(Application.id == application_id, Application.active == True).first()
            if app and app.default_assignment_group_id:
                group = db.query(AssignmentGroup).filter(AssignmentGroup.id == app.default_assignment_group_id, AssignmentGroup.active == True).first()
                if group:
                    return {
                        "assignment_group_id": group.id,
                        "assignment_group_name": group.name,
                        "level": 5,
                        "matched_rule_type": "Application Default",
                        "rule_code": f"APP-{app.app_id}",
                        "rule_name": f"Default for {app.name}",
                        "reason": f"Used default Assignment Group configured for Application '{app.name}'"
                    }

        # 6. Global Default Assignment Group
        global_group = db.query(AssignmentGroup).filter(
            AssignmentGroup.name.ilike("%Service Desk%"),
            AssignmentGroup.active == True
        ).first()

        if not global_group:
            global_group = db.query(AssignmentGroup).filter(AssignmentGroup.active == True).first()

        return {
            "assignment_group_id": global_group.id if global_group else 1,
            "assignment_group_name": global_group.name if global_group else "Global Service Desk",
            "level": 6,
            "matched_rule_type": "Global Default",
            "rule_code": "GLOBAL-FALLBACK",
            "rule_name": "Global Service Desk Fallback",
            "reason": "No specific routing rules or defaults matched; routed to Global Service Desk"
        }
