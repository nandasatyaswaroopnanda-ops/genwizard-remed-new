import os
import datetime
import json
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float
)
from sqlalchemy.orm import relationship
from backend.database import Base

def utc_now():
    return datetime.datetime.utcnow()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    keycloak_subject = Column(String(255), unique=True, index=True, nullable=True)
    employee_id = Column(String(50), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    first_name = Column(String(75), nullable=True)
    last_name = Column(String(75), nullable=True)
    email = Column(String(150), unique=True, index=True, nullable=False)
    phone = Column(String(50), nullable=True)
    department = Column(String(100), nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    location = Column(String(100), nullable=True)
    role = Column(String(50), default="employee", nullable=False) # employee, support_member, group_manager, administrator, itsm_admin, itsm_user, itsm_read
    password_hash = Column(String(255), nullable=True)
    is_local = Column(Boolean, default=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    memberships = relationship("GroupMember", back_populates="user", cascade="all, delete-orphan", foreign_keys="GroupMember.user_id")
    notifications = relationship("Notification", back_populates="recipient", cascade="all, delete-orphan", foreign_keys="Notification.recipient_id")
    custom_groups = relationship("UserCustomGroup", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self):
        c_groups = [cg.custom_group.name for cg in self.custom_groups if cg.custom_group] if hasattr(self, "custom_groups") and self.custom_groups else []

        def _strip_suffix(name: str, suffix: str) -> str:
            for sep in ("-", "_"):
                if name.lower().endswith(sep + suffix):
                    return name[:-(len(sep) + len(suffix))].strip()
            return ""

        def _strip_tier(name: str) -> str:
            """Strip -l2 / -l3 / _l2 / _l3 from a group name."""
            for sfx in ("-l2", "-l3", "_l2", "_l3"):
                if name.lower().endswith(sfx):
                    return name[:-len(sfx)].strip()
            return name

        admin_projects = []
        support_projects = []
        platform_admin_groups = {"itsm-admin", "itsm_admin", "itsm-admins", "itsm_admins"}

        for cg in c_groups:
            cg_lower = cg.lower()
            if cg_lower in platform_admin_groups:
                continue
            # -admin / _admin → Project Administrator
            if cg_lower.endswith("-admin") or cg_lower.endswith("_admin"):
                p_name = _strip_suffix(cg, "admin")
                if not p_name:
                    continue
                base_p = _strip_tier(p_name)
                for proj in set(filter(None, [p_name, base_p])):
                    if proj not in admin_projects:
                        admin_projects.append(proj)
                    if proj not in support_projects:
                        support_projects.append(proj)
            # -user / _user → Fulfiller only (NOT admin)
            elif cg_lower.endswith("-user") or cg_lower.endswith("_user"):
                if cg_lower in ("itsm-user", "itsm_user"):
                    continue
                p_name = _strip_suffix(cg, "user")
                if not p_name:
                    continue
                base_p = _strip_tier(p_name)
                for proj in set(filter(None, [p_name, base_p])):
                    if proj not in support_projects:
                        support_projects.append(proj)
            # -read / _read → read-only (no admin or fulfiller escalation here)

        # Assignment groups membership projects (only grants admin_projects — members of a
        # project's assignment group have full project admin authority)
        if hasattr(self, "memberships") and self.memberships:
            for m in self.memberships:
                if getattr(m, "group", None):
                    ag = m.group
                    try:
                        p_list = json.loads(ag.projects_supported or "[]")
                        for p in p_list:
                            if p and p not in admin_projects:
                                admin_projects.append(p)
                            if p and p not in support_projects:
                                support_projects.append(p)
                    except Exception:
                        pass
                    if ag.name and (ag.name.endswith("-l2") or ag.name.endswith("-l3")):
                        cand = ag.name[:-3].strip()
                        if cand and cand not in admin_projects:
                            admin_projects.append(cand)
                        if cand and cand not in support_projects:
                            support_projects.append(cand)

        # Local personas fallback (only fires when explicitly in testing mode with SEED_DEMO_DATA enabled and no groups are linked)
        seed_demo = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")
        if not admin_projects and not support_projects and seed_demo:
            if self.username == "sarah.johnson":
                admin_projects.append("Payment Platform Modernization")
                support_projects.append("Payment Platform Modernization")
            elif self.username == "david.wilson":
                admin_projects.append("Customer Portal Modernization")
                support_projects.append("Customer Portal Modernization")
            elif self.username == "mike.brown":
                admin_projects.append("Cloud Migration")
                support_projects.append("Cloud Migration")
            elif self.username == "john.smith":
                support_projects.append("Customer Portal Modernization")

        is_global_admin = (self.username == "admin") or (self.role in ["administrator", "itsm_admin"])
        is_end_user = (self.role in ["employee", "itsm_read"]) or (self.username == "john.smith")
        has_project_privileges = bool(admin_projects or support_projects)
        has_assignment_group = len(self.memberships) > 0 if hasattr(self, "memberships") and self.memberships else False
        is_support = not is_end_user and (is_global_admin or has_project_privileges or has_assignment_group or (self.role in ["support_member", "group_manager", "itsm_user"]) or any(cg in ["itsm_user", "Service Desk", "ITSM-Fulfillers", "Tier1-Support", "ITSM-Admins"] for cg in c_groups))

        return {
            "id": self.id,
            "keycloak_subject": self.keycloak_subject,
            "employee_id": self.employee_id,
            "username": self.username,
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "department": self.department,
            "manager_id": self.manager_id,
            "location": self.location,
            "role": self.role,
            "is_local": self.is_local,
            "is_end_user": is_end_user,
            "is_global_admin": is_global_admin,
            "admin_projects": admin_projects,
            "support_projects": support_projects,
            "custom_groups": c_groups,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    business_owner = Column(String(150), nullable=True)
    technical_owner = Column(String(150), nullable=True)
    default_assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=True)
    support_hours = Column(String(100), default="24x7", nullable=True)
    environment = Column(String(50), default="Production", nullable=True)
    criticality = Column(String(50), default="High", nullable=True)
    business_service = Column(String(100), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    on_call_contact = Column(String(150), nullable=True)
    first_escalation_contact = Column(String(150), nullable=True)
    second_escalation_contact = Column(String(150), nullable=True)
    categories = Column(Text, default="{}", nullable=True)
    custom_fields = Column(Text, default="{}")
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    projects = relationship("Project", back_populates="application", foreign_keys="Project.application_id")
    project = relationship("Project", foreign_keys=[project_id], post_update=True)
    default_assignment_group = relationship("AssignmentGroup", foreign_keys=[default_assignment_group_id])

    def to_dict(self):
        try:
            custom_fields = json.loads(self.custom_fields or "{}")
        except Exception:
            custom_fields = {}

        # Default standard category sets for applications
        default_categories = {
            "Incident": [
                "Application Outage / Error",
                "Performance / High Latency",
                "Frontend & UI Glitch",
                "Database & Data Integrity",
                "Authentication & Login Failure",
                "API & Integration Exception",
                "Network & Gateway Timeout"
            ],
            "Service Request": [
                "User Access & Role Grant",
                "Configuration Update Request",
                "Data Export & Custom Report",
                "Sandbox / Test Environment Setup",
                "Software License & Tool Provisioning",
                "General Technical Assistance"
            ],
            "Change Request": [
                "Software Patch & Hotfix Release",
                "Database Migration & DDL Schema Change",
                "Cloud Infrastructure & Kubernetes Scaling",
                "Configuration & Environment Update",
                "Security Patch & Firewall Rule Update"
            ]
        }
        categories_dict = {k: list(v) for k, v in default_categories.items()}
        if hasattr(self, "categories") and self.categories:
            try:
                raw_cats = json.loads(self.categories) if isinstance(self.categories, str) else self.categories
                if isinstance(raw_cats, dict):
                    for k in ["Incident", "Service Request", "Change Request"]:
                        if k in raw_cats and isinstance(raw_cats[k], list) and len(raw_cats[k]) > 0:
                            categories_dict[k] = raw_cats[k]
                elif isinstance(raw_cats, list) and len(raw_cats) > 0:
                    categories_dict["Incident"] = raw_cats
                    categories_dict["Service Request"] = raw_cats
                    categories_dict["Change Request"] = raw_cats
            except Exception:
                pass

        proj_id = getattr(self, "project_id", None)
        proj_name = None
        if hasattr(self, "project") and self.project:
            proj_name = self.project.name
            if not proj_id:
                proj_id = self.project.id
        elif hasattr(self, "projects") and self.projects:
            p = self.projects[0] if self.projects else None
            if p:
                proj_name = p.name
                if not proj_id:
                    proj_id = p.id
        if proj_id and not proj_name:
            try:
                from backend.database import SessionLocal
                s = SessionLocal()
                p_found = s.query(Project).filter(Project.id == proj_id).first()
                if p_found:
                    proj_name = p_found.name
                s.close()
            except Exception:
                pass
        return {
            "id": self.id,
            "app_id": self.app_id,
            "name": self.name,
            "description": self.description,
            "project_id": proj_id,
            "project_name": proj_name,
            "on_call_contact": getattr(self, "on_call_contact", None),
            "first_escalation_contact": getattr(self, "first_escalation_contact", None),
            "second_escalation_contact": getattr(self, "second_escalation_contact", None),
            "business_owner": self.business_owner,
            "technical_owner": self.technical_owner,
            "default_assignment_group_id": self.default_assignment_group_id,
            "default_assignment_group_name": self.default_assignment_group.name if self.default_assignment_group else None,
            "support_hours": self.support_hours,
            "environment": self.environment,
            "criticality": self.criticality,
            "business_service": self.business_service,
            "categories": categories_dict,
            "custom_fields": custom_fields,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    project_manager = Column(String(150), nullable=True)
    business_owner = Column(String(150), nullable=True)
    technical_owner = Column(String(150), nullable=True)
    default_assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=True)
    l2_assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=True)
    l3_assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=True)
    default_sla_policy_id = Column(Integer, ForeignKey("sla_policies.id"), nullable=True)
    support_hours = Column(String(100), default="Standard Business Hours", nullable=True)
    environment = Column(String(50), default="Production", nullable=True)
    criticality = Column(String(50), default="Medium", nullable=True)
    l2_on_call_contact = Column(String(150), nullable=True)
    l3_on_call_contact = Column(String(150), nullable=True)
    first_escalation_contact = Column(String(150), nullable=True)
    second_escalation_contact = Column(String(150), nullable=True)
    custom_fields = Column(Text, default="{}")
    active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(DateTime, default=utc_now)
    effective_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    application = relationship("Application", back_populates="projects", foreign_keys=[application_id])
    mappings = relationship("ProjectAssignmentMapping", back_populates="project", cascade="all, delete-orphan", foreign_keys="ProjectAssignmentMapping.project_id")
    default_assignment_group = relationship("AssignmentGroup", foreign_keys=[default_assignment_group_id])
    l2_assignment_group = relationship("AssignmentGroup", foreign_keys=[l2_assignment_group_id])
    l3_assignment_group = relationship("AssignmentGroup", foreign_keys=[l3_assignment_group_id])
    default_sla_policy = relationship("SLAPolicy", foreign_keys=[default_sla_policy_id])

    def to_dict(self):
        try:
            custom_fields = json.loads(self.custom_fields or "{}")
        except Exception:
            custom_fields = {}
        def_grp = self.default_assignment_group or self.l2_assignment_group
        l2_grp = self.l2_assignment_group or self.default_assignment_group
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else None,
            "project_manager": self.project_manager,
            "business_owner": self.business_owner,
            "technical_owner": self.technical_owner,
            "default_assignment_group_id": def_grp.id if def_grp else None,
            "default_assignment_group_name": def_grp.name if def_grp else None,
            "l2_assignment_group_id": l2_grp.id if l2_grp else None,
            "l2_assignment_group_name": l2_grp.name if l2_grp else None,
            "l3_assignment_group_id": self.l3_assignment_group.id if self.l3_assignment_group else None,
            "l3_assignment_group_name": self.l3_assignment_group.name if self.l3_assignment_group else None,
            "default_sla_policy_id": self.default_sla_policy_id,
            "default_sla_policy_name": self.default_sla_policy.name if self.default_sla_policy else None,
            "support_hours": self.support_hours,
            "environment": self.environment,
            "criticality": self.criticality,
            "l2_on_call_contact": getattr(self, "l2_on_call_contact", None),
            "l3_on_call_contact": getattr(self, "l3_on_call_contact", None),
            "first_escalation_contact": getattr(self, "first_escalation_contact", None),
            "second_escalation_contact": getattr(self, "second_escalation_contact", None),
            "custom_fields": custom_fields,
            "active": self.active,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class AssignmentGroup(Base):
    __tablename__ = "assignment_groups"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    applications_supported = Column(Text, default="[]")
    projects_supported = Column(Text, default="[]")
    default_sla_policy_id = Column(Integer, ForeignKey("sla_policies.id"), nullable=True)
    business_calendar_id = Column(Integer, ForeignKey("business_calendars.id"), nullable=True)
    escalation_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=True)
    on_call_contact = Column(String(150), nullable=True)
    first_escalation_contact = Column(String(150), nullable=True)
    second_escalation_contact = Column(String(150), nullable=True)
    custom_fields = Column(Text, default="{}")
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan", foreign_keys="GroupMember.group_id")
    manager = relationship("User", foreign_keys=[manager_id])
    default_sla_policy = relationship("SLAPolicy", foreign_keys=[default_sla_policy_id])
    business_calendar = relationship("BusinessCalendar", foreign_keys=[business_calendar_id])
    escalation_group = relationship("AssignmentGroup", foreign_keys=[escalation_group_id], remote_side=[id])
    distribution_lists = relationship("GroupDistributionList", back_populates="group", cascade="all, delete-orphan", foreign_keys="GroupDistributionList.group_id")

    def to_dict(self):
        apps = []
        try:
            apps = json.loads(self.applications_supported or "[]")
        except Exception:
            pass
        projs = []
        try:
            projs = json.loads(self.projects_supported or "[]")
        except Exception:
            pass
        try:
            custom_fields = json.loads(self.custom_fields or "{}")
        except Exception:
            custom_fields = {}
        return {
            "id": self.id,
            "group_id": self.group_id,
            "name": self.name,
            "description": self.description,
            "manager_id": self.manager_id,
            "manager_name": self.manager.full_name if self.manager else None,
            "applications_supported": apps,
            "projects_supported": projs,
            "default_sla_policy_id": self.default_sla_policy_id,
            "default_sla_policy_name": self.default_sla_policy.name if self.default_sla_policy else None,
            "business_calendar_id": self.business_calendar_id,
            "business_calendar_name": self.business_calendar.name if self.business_calendar else None,
            "escalation_group_id": self.escalation_group_id,
            "escalation_group_name": self.escalation_group.name if self.escalation_group else None,
            "on_call_contact": self.on_call_contact,
            "first_escalation_contact": self.first_escalation_contact,
            "second_escalation_contact": self.second_escalation_contact,
            "custom_fields": custom_fields,
            "active": self.active,
            "member_count": len(self.members) if self.members else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_in_group = Column(String(50), default="member")
    created_at = Column(DateTime, default=utc_now)

    group = relationship("AssignmentGroup", back_populates="members", foreign_keys=[group_id])
    user = relationship("User", back_populates="memberships", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "group_id": self.group_id,
            "user_id": self.user_id,
            "user_name": self.user.full_name if self.user else None,
            "user_email": self.user.email if self.user else None,
            "role_in_group": self.role_in_group
        }

class DistributionList(Base):
    __tablename__ = "distribution_lists"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    display_name = Column(String(150), nullable=True)
    privilege = Column(String(50), default="support", nullable=False) # support or administrator
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    group_mappings = relationship("GroupDistributionList", back_populates="distribution_list", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "email": self.email, "display_name": self.display_name,
                "privilege": self.privilege, "active": self.active}

class GroupDistributionList(Base):
    __tablename__ = "group_distribution_lists"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False, index=True)
    distribution_list_id = Column(Integer, ForeignKey("distribution_lists.id"), nullable=False, index=True)
    notification_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    group = relationship("AssignmentGroup", back_populates="distribution_lists", foreign_keys=[group_id])
    distribution_list = relationship("DistributionList", back_populates="group_mappings")

    def to_dict(self):
        data = self.distribution_list.to_dict() if self.distribution_list else {}
        return {"id": self.id, "group_id": self.group_id, "notification_enabled": self.notification_enabled, **data}

class ProjectAssignmentMapping(Base):
    __tablename__ = "project_assignment_mappings"

    id = Column(Integer, primary_key=True, index=True)
    mapping_id = Column(String(50), unique=True, index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False)
    category = Column(String(100), nullable=True)
    priority_override = Column(String(10), nullable=True)
    sla_policy_override_id = Column(Integer, ForeignKey("sla_policies.id"), nullable=True)
    routing_priority = Column(Integer, default=100)
    active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(DateTime, default=utc_now)
    effective_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="mappings", foreign_keys=[project_id])
    assignment_group = relationship("AssignmentGroup", foreign_keys=[assignment_group_id])
    application = relationship("Application", foreign_keys=[application_id])
    sla_policy_override = relationship("SLAPolicy", foreign_keys=[sla_policy_override_id])

    def to_dict(self):
        return {
            "id": self.id,
            "mapping_id": self.mapping_id,
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else None,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else None,
            "assignment_group_id": self.assignment_group_id,
            "assignment_group_name": self.assignment_group.name if self.assignment_group else None,
            "category": self.category,
            "priority_override": self.priority_override,
            "sla_policy_override_id": self.sla_policy_override_id,
            "sla_policy_override_name": self.sla_policy_override.name if self.sla_policy_override else None,
            "routing_priority": self.routing_priority,
            "active": self.active,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=False)
    priority_order = Column(Integer, default=10, nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    category = Column(String(100), nullable=True)
    subcategory = Column(String(100), nullable=True)
    assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    description = Column(Text, nullable=True)
    effective_from = Column(DateTime, default=utc_now)
    effective_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    assignment_group = relationship("AssignmentGroup", foreign_keys=[assignment_group_id])
    project = relationship("Project", foreign_keys=[project_id])
    application = relationship("Application", foreign_keys=[application_id])

    def to_dict(self):
        return {
            "id": self.id,
            "rule_code": self.rule_code,
            "name": self.name,
            "priority_order": self.priority_order,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else "Any",
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else "Any",
            "category": self.category or "Any",
            "subcategory": self.subcategory or "Any",
            "assignment_group_id": self.assignment_group_id,
            "assignment_group_name": self.assignment_group.name if self.assignment_group else None,
            "active": self.active,
            "description": self.description,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class BusinessCalendar(Base):
    __tablename__ = "business_calendars"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    timezone = Column(String(50), default="Asia/Kolkata", nullable=False)
    working_days = Column(Text, default="[1, 2, 3, 4, 5]", nullable=False)
    working_hours_start = Column(String(10), default="09:00", nullable=False)
    working_hours_end = Column(String(10), default="18:00", nullable=False)
    holidays = Column(Text, default="[]", nullable=False)
    exceptions = Column(Text, default="[]", nullable=False)
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        w_days = [1, 2, 3, 4, 5]
        hols = []
        excs = []
        try:
            w_days = json.loads(self.working_days or "[1,2,3,4,5]")
            hols = json.loads(self.holidays or "[]")
            excs = json.loads(self.exceptions or "[]")
        except Exception:
            pass
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "timezone": self.timezone,
            "working_days": w_days,
            "working_hours_start": self.working_hours_start,
            "working_hours_end": self.working_hours_end,
            "holidays": hols,
            "exceptions": excs,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    id = Column(Integer, primary_key=True, index=True)
    policy_code = Column(String(50), index=True, nullable=False)
    name = Column(String(150), nullable=False)
    version = Column(Integer, default=1, nullable=False)
    description = Column(Text, nullable=True)
    ticket_type = Column(String(50), default="Incident", nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=True)
    priority = Column(String(10), nullable=False)
    response_target_mins = Column(Integer, nullable=False)
    resolution_target_mins = Column(Integer, nullable=False)
    business_calendar_id = Column(Integer, ForeignKey("business_calendars.id"), nullable=True)
    pause_conditions = Column(Text, default='["Pending Customer", "Awaiting Approval", "Awaiting Vendor"]')
    escalation_rules = Column(Text, default='[{"threshold_pct": 50, "notify": "Assignment Group"}, {"threshold_pct": 75, "notify": "Group Manager"}, {"threshold_pct": 90, "notify": "Application Owner"}, {"threshold_pct": 100, "notify": "IT Operations Manager"}]')
    warning_threshold_pct = Column(Integer, default=75, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(DateTime, default=utc_now)
    effective_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    application = relationship("Application", foreign_keys=[application_id])
    project = relationship("Project", foreign_keys=[project_id])
    assignment_group = relationship("AssignmentGroup", foreign_keys=[assignment_group_id])
    business_calendar = relationship("BusinessCalendar", foreign_keys=[business_calendar_id])

    def to_dict(self):
        pauses = ["Pending Customer", "Awaiting Approval", "Awaiting Vendor"]
        escalations = []
        try:
            pauses = json.loads(self.pause_conditions or "[]")
            escalations = json.loads(self.escalation_rules or "[]")
        except Exception:
            pass
        def _fmt_mins(m):
            if not m and m != 0:
                return "0m"
            h = m // 60
            rem = m % 60
            if h >= 24 and rem == 0 and (h % 24 == 0):
                days = h // 24
                return f"{h}h ({days}d)"
            if h > 0:
                return f"{h}h {rem}m" if rem > 0 else f"{h}h"
            return f"{m}m"

        resp_mins = self.response_target_mins or 0
        reso_mins = self.resolution_target_mins or 0

        return {
            "id": self.id,
            "policy_code": self.policy_code,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "ticket_type": self.ticket_type,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else "Any",
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else "Any",
            "assignment_group_id": self.assignment_group_id,
            "assignment_group_name": self.assignment_group.name if self.assignment_group else "Any",
            "priority": self.priority,
            "response_target_mins": resp_mins,
            "resolution_target_mins": reso_mins,
            "response_target_hours": round(resp_mins / 60.0, 2),
            "resolution_target_hours": round(reso_mins / 60.0, 2),
            "response_target_display": _fmt_mins(resp_mins),
            "resolution_target_display": _fmt_mins(reso_mins),
            "business_calendar_id": self.business_calendar_id,
            "business_calendar_name": self.business_calendar.name if self.business_calendar else "24x7 Operations",
            "pause_conditions": pauses,
            "escalation_rules": escalations,
            "warning_threshold_pct": self.warning_threshold_pct,
            "active": self.active,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class SLAInstance(Base):
    __tablename__ = "sla_instances"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, nullable=False, index=True)
    ticket_type = Column(String(50), default="Incident", nullable=False)
    ticket_number = Column(String(50), index=True, nullable=False)
    sla_policy_id = Column(Integer, ForeignKey("sla_policies.id"), nullable=False)
    target_type = Column(String(20), nullable=False)
    target_duration_mins = Column(Integer, nullable=False)
    elapsed_business_mins = Column(Float, default=0.0, nullable=False)
    start_time = Column(DateTime, default=utc_now, nullable=False)
    paused_at = Column(DateTime, nullable=True)
    achieved_at = Column(DateTime, nullable=True)
    breached_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=True)
    stage = Column(String(30), default="in_progress")
    current_escalation_level = Column(Integer, default=0)
    pause_history = Column(Text, default="[]")
    created_at = Column(DateTime, default=utc_now)

    sla_policy = relationship("SLAPolicy", foreign_keys=[sla_policy_id])

    def to_dict(self):
        ph = []
        try:
            ph = json.loads(self.pause_history or "[]")
        except Exception:
            pass
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "ticket_type": self.ticket_type,
            "ticket_number": self.ticket_number,
            "sla_policy_id": self.sla_policy_id,
            "sla_policy_name": self.sla_policy.name if self.sla_policy else "Unknown",
            "sla_version": self.sla_policy.version if self.sla_policy else 1,
            "target_type": self.target_type,
            "target_duration_mins": self.target_duration_mins,
            "target_duration_hours": round((self.target_duration_mins or 0) / 60.0, 2),
            "target_duration_display": f"{round((self.target_duration_mins or 0) / 60.0, 1)} hrs ({(self.target_duration_mins or 0)} mins)",
            "elapsed_business_mins": round(self.elapsed_business_mins, 1),
            "elapsed_business_hours": round((self.elapsed_business_mins or 0) / 60.0, 2),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "achieved_at": self.achieved_at.isoformat() if self.achieved_at else None,
            "breached_at": self.breached_at.isoformat() if self.breached_at else None,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "stage": self.stage,
            "current_escalation_level": self.current_escalation_level,
            "pause_history": ph
        }

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True, nullable=False)
    caller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requested_for_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    opened_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    category = Column(String(100), default="Application", nullable=False)
    subcategory = Column(String(100), nullable=True)
    short_description = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    impact = Column(String(20), default="High", nullable=False)
    urgency = Column(String(20), default="High", nullable=False)
    priority = Column(String(10), default="P1", nullable=False)
    assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    environment = Column(String(50), default="Production")
    location = Column(String(100), default="Global")
    contact_type = Column(String(50), default="Web Portal")
    status = Column(String(50), default="New", nullable=False)
    resolution_code = Column(String(100), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    close_category = Column(String(100), nullable=True) # Bug, Configuration Issue, Application Limitation, Infrastructure Limitation
    close_subcategory = Column(String(100), nullable=True)
    ado_number = Column(String(100), nullable=True) # Azure DevOps Work Item # (if Bug)
    close_application_name = Column(String(150), nullable=True)
    matched_routing_rule = Column(String(100), nullable=True)
    matched_sla_policy = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    caller = relationship("User", foreign_keys=[caller_id])
    requested_for = relationship("User", foreign_keys=[requested_for_id])
    opened_by = relationship("User", foreign_keys=[opened_by_id])
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    application = relationship("Application", foreign_keys=[application_id])
    project = relationship("Project", foreign_keys=[project_id])
    assignment_group = relationship("AssignmentGroup", foreign_keys=[assignment_group_id])

    def to_dict(self):
        return {
            "id": self.id,
            "number": self.number,
            "caller_id": self.caller_id,
            "caller_name": self.caller.full_name if self.caller else None,
            "caller_email": self.caller.email if self.caller else None,
            "requested_for_id": self.requested_for_id,
            "opened_by_id": self.opened_by_id,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else None,
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else None,
            "category": self.category,
            "subcategory": self.subcategory,
            "short_description": self.short_description,
            "description": self.description,
            "impact": self.impact,
            "urgency": self.urgency,
            "priority": self.priority,
            "assignment_group_id": self.assignment_group_id,
            "assignment_group_name": self.assignment_group.name if self.assignment_group else None,
            "assigned_to_id": self.assigned_to_id,
            "assigned_to_name": self.assigned_to.full_name if self.assigned_to else "Unassigned",
            "environment": self.environment,
            "location": self.location,
            "contact_type": self.contact_type,
            "status": self.status,
            "resolution_code": self.resolution_code,
            "resolution_notes": self.resolution_notes,
            "close_category": self.close_category,
            "close_subcategory": self.close_subcategory,
            "ado_number": self.ado_number,
            "close_application_name": self.close_application_name or (self.application.name if self.application else None),
            "matched_routing_rule": self.matched_routing_rule,
            "matched_sla_policy": self.matched_sla_policy,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None
        }

class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True, nullable=False)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requested_for_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    catalog_item = Column(String(150), nullable=False)
    category = Column(String(100), default="Service Request", nullable=False)
    short_description = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String(10), default="P3", nullable=False)
    assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(50), default="New", nullable=False)
    approval_status = Column(String(50), default="Approved", nullable=False)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    requested_by = relationship("User", foreign_keys=[requested_by_id])
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    application = relationship("Application", foreign_keys=[application_id])
    project = relationship("Project", foreign_keys=[project_id])
    assignment_group = relationship("AssignmentGroup", foreign_keys=[assignment_group_id])

    def to_dict(self):
        return {
            "id": self.id,
            "number": self.number,
            "requested_by_id": self.requested_by_id,
            "requested_by_name": self.requested_by.full_name if self.requested_by else None,
            "catalog_item": self.catalog_item,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else None,
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else None,
            "category": self.category,
            "short_description": self.short_description,
            "description": self.description,
            "priority": self.priority,
            "assignment_group_id": self.assignment_group_id,
            "assignment_group_name": self.assignment_group.name if self.assignment_group else None,
            "assigned_to_id": self.assigned_to_id,
            "assigned_to_name": self.assigned_to.full_name if self.assigned_to else "Unassigned",
            "status": self.status,
            "approval_status": self.approval_status,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True, nullable=False)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    change_type = Column(String(50), default="Normal", nullable=False)
    category = Column(String(100), default="Software", nullable=False)
    short_description = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    business_justification = Column(Text, nullable=False)
    risk = Column(String(20), default="Medium", nullable=False)
    impact = Column(String(20), default="Medium", nullable=False)
    priority = Column(String(10), default="P3", nullable=False)
    assignment_group_id = Column(Integer, ForeignKey("assignment_groups.id"), nullable=False)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    planned_start = Column(DateTime, nullable=True)
    planned_end = Column(DateTime, nullable=True)
    implementation_plan = Column(Text, nullable=True)
    backout_plan = Column(Text, nullable=True)
    test_plan = Column(Text, nullable=True)
    validation_plan = Column(Text, nullable=True)
    approval_status = Column(String(50), default="Pending", nullable=False)
    change_status = Column(String(50), default="Draft", nullable=False)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    closure_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    requested_by = relationship("User", foreign_keys=[requested_by_id])
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    application = relationship("Application", foreign_keys=[application_id])
    project = relationship("Project", foreign_keys=[project_id])
    assignment_group = relationship("AssignmentGroup", foreign_keys=[assignment_group_id])

    def to_dict(self):
        return {
            "id": self.id,
            "number": self.number,
            "requested_by_id": self.requested_by_id,
            "requested_by_name": self.requested_by.full_name if self.requested_by else None,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else None,
            "project_id": self.project_id,
            "project_name": self.project.name if self.project else None,
            "change_type": self.change_type,
            "category": self.category,
            "short_description": self.short_description,
            "description": self.description,
            "business_justification": self.business_justification,
            "risk": self.risk,
            "impact": self.impact,
            "priority": self.priority,
            "assignment_group_id": self.assignment_group_id,
            "assignment_group_name": self.assignment_group.name if self.assignment_group else None,
            "assigned_to_id": self.assigned_to_id,
            "assigned_to_name": self.assigned_to.full_name if self.assigned_to else "Unassigned",
            "planned_start": self.planned_start.isoformat() if self.planned_start else None,
            "planned_end": self.planned_end.isoformat() if self.planned_end else None,
            "implementation_plan": self.implementation_plan,
            "backout_plan": self.backout_plan,
            "test_plan": self.test_plan,
            "validation_plan": self.validation_plan,
            "approval_status": self.approval_status,
            "cab_approval": self.approval_status,
            "change_status": self.change_status,
            "actual_start": self.actual_start.isoformat() if self.actual_start else None,
            "actual_end": self.actual_end.isoformat() if self.actual_end else None,
            "closure_notes": self.closure_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_type = Column(String(50), nullable=False)
    ticket_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_type": self.ticket_type,
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "user_name": self.user.full_name if self.user else "System",
            "user_role": self.user.role if self.user else "system",
            "comment": self.comment,
            "type": "customer_comment",
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class TicketWorkNote(Base):
    __tablename__ = "ticket_work_notes"

    id = Column(Integer, primary_key=True, index=True)
    ticket_type = Column(String(50), nullable=False)
    ticket_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_type": self.ticket_type,
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "user_name": self.user.full_name if self.user else "System",
            "user_role": self.user.role if self.user else "support",
            "note": self.note,
            "type": "internal_work_note",
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_type = Column(String(50), nullable=False)
    ticket_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_type": self.ticket_type,
            "ticket_id": self.ticket_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "uploaded_by_id": self.uploaded_by_id,
            "uploaded_by_name": self.uploaded_by.full_name if self.uploaded_by else "User",
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    ticket_type = Column(String(50), nullable=False)
    ticket_id = Column(Integer, nullable=False, index=True)
    ticket_number = Column(String(50), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(50), default="Pending")
    comments = Column(Text, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    approver = relationship("User", foreign_keys=[approver_id])

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_type": self.ticket_type,
            "ticket_id": self.ticket_id,
            "ticket_number": self.ticket_number,
            "approver_id": self.approver_id,
            "approver_name": self.approver.full_name if self.approver else None,
            "status": self.status,
            "comments": self.comments,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id = Column(Integer, primary_key=True, index=True)
    article_number = Column(String(50), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    category = Column(String(100), default="Troubleshooting", nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(50), default="Published")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    application = relationship("Application", foreign_keys=[application_id])
    author = relationship("User", foreign_keys=[author_id])

    def to_dict(self):
        return {
            "id": self.id,
            "article_number": self.article_number,
            "title": self.title,
            "category": self.category,
            "application_id": self.application_id,
            "application_name": self.application.name if self.application else "General",
            "content": self.content,
            "author_id": self.author_id,
            "author_name": self.author.full_name if self.author else "Author",
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    entity_number = Column(String(50), nullable=True)
    action = Column(String(50), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_by_name = Column(String(150), nullable=True)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        ov = {}
        nv = {}
        try:
            ov = json.loads(self.old_values or "{}")
            nv = json.loads(self.new_values or "{}")
        except Exception:
            pass
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_number": self.entity_number,
            "action": self.action,
            "changed_by_id": self.changed_by_id,
            "changed_by_name": self.changed_by_name,
            "old_values": ov,
            "new_values": nv,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class ConfigurationAudit(Base):
    __tablename__ = "configuration_audits"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(100), nullable=False)
    user_name = Column(String(150), nullable=False)
    old_configuration = Column(Text, nullable=True)
    new_configuration = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    effective_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        oc = {}
        nc = {}
        try:
            oc = json.loads(self.old_configuration or "{}")
            nc = json.loads(self.new_configuration or "{}")
        except Exception:
            pass
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "user_name": self.user_name,
            "old_configuration": oc,
            "new_configuration": nc,
            "reason": self.reason,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticket_id = Column(Integer, nullable=True)
    ticket_number = Column(String(50), nullable=True)
    ticket_type = Column(String(50), nullable=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50), default="info")
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    recipient = relationship("User", back_populates="notifications", foreign_keys=[recipient_id])

    def to_dict(self):
        return {
            "id": self.id,
            "recipient_id": self.recipient_id,
            "ticket_id": self.ticket_id,
            "ticket_number": self.ticket_number,
            "ticket_type": self.ticket_type,
            "title": self.title,
            "message": self.message,
            "type": self.type,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class AIConfiguration(Base):
    __tablename__ = "ai_configurations"

    id = Column(Integer, primary_key=True, index=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    assistant_name = Column(String(100), default="GenWizard Support Copilot", nullable=False)
    welcome_message = Column(Text, default="Hello! I am your GenWizard Support Copilot. Ask me anything about your applications, runbooks, or troubleshooting procedures.")
    km_base_url = Column(String(255), default="https://internal-km.company.local")
    api_endpoint = Column(String(255), default="/api/chat/completions")
    auth_type = Column(String(50), default="Bearer")
    auth_token = Column(String(255), default="env:KM_API_TOKEN")
    km_im_token_endpoint = Column(String(255), nullable=True)
    km_im_client_id = Column(String(150), nullable=True)
    km_im_client_secret = Column(String(255), nullable=True)
    km_im_token_json_path = Column(String(100), default="access_token")
    km_im_payload_template = Column(Text, default='{"grant_type":"client_credentials","client_id":"{{client_id}}","client_secret":"{{client_secret}}"}')
    username = Column(String(100), nullable=True)
    password = Column(String(255), nullable=True)
    km_index = Column(String(100), default="itsm-kb", nullable=True)
    timeout_seconds = Column(Integer, default=30)
    http_method = Column(String(10), default="POST")
    headers_template = Column(Text, default='{"Content-Type": "application/json"}')
    payload_template = Column(Text, default='''{
  "model": "internal-km-v1",
  "messages": [
    {
      "role": "system",
      "content": "You are an enterprise ITSM Knowledge Assistant. Context: Application={{application}}, Project={{project}}, Ticket={{ticket_number}}, Priority={{priority}}, Details={{ticket_context}}"
    },
    {
      "role": "user",
      "content": "{{question}}"
    }
  ],
  "temperature": 0.2
}''')
    response_json_path = Column(String(100), default="choices[0].message.content")
    error_json_path = Column(String(100), default="error.message")
    allow_app_context = Column(Boolean, default=True)
    allow_project_context = Column(Boolean, default=True)
    allow_ticket_context = Column(Boolean, default=True)
    allow_history = Column(Boolean, default=True)
    pii_filtering = Column(Boolean, default=True)
    audit_enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "is_enabled": self.is_enabled,
            "assistant_name": self.assistant_name,
            "welcome_message": self.welcome_message,
            "km_base_url": self.km_base_url,
            "api_endpoint": self.api_endpoint,
            "auth_type": self.auth_type,
            "auth_token": self.auth_token,
            "km_index": self.km_index or "itsm-kb",
            "username": self.username,
            "km_im_token_endpoint": self.km_im_token_endpoint,
            "km_im_client_id": self.km_im_client_id,
            "km_im_token_json_path": self.km_im_token_json_path,
            "km_im_payload_template": self.km_im_payload_template,
            "timeout_seconds": self.timeout_seconds,
            "http_method": self.http_method,
            "headers_template": self.headers_template,
            "payload_template": self.payload_template,
            "response_json_path": self.response_json_path,
            "error_json_path": self.error_json_path,
            "allow_app_context": self.allow_app_context,
            "allow_project_context": self.allow_project_context,
            "allow_ticket_context": self.allow_ticket_context,
            "allow_history": self.allow_history,
            "pii_filtering": self.pii_filtering,
            "audit_enabled": self.audit_enabled,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id = Column(String(50), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), default="New Support Conversation", nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    ticket_number = Column(String(50), nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    messages = relationship("AIMessage", back_populates="conversation", cascade="all, delete-orphan", foreign_keys="AIMessage.conversation_id")
    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.full_name if self.user else None,
            "title": self.title,
            "application_id": self.application_id,
            "project_id": self.project_id,
            "ticket_number": self.ticket_number,
            "status": self.status,
            "message_count": len(self.messages) if self.messages else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class AIMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(50), ForeignKey("ai_conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    citations = Column(Text, default="[]")
    token_usage = Column(Text, default="{}")
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    conversation = relationship("AIConversation", back_populates="messages", foreign_keys=[conversation_id])

    def to_dict(self):
        cites = []
        usage = {}
        try:
            cites = json.loads(self.citations or "[]")
            usage = json.loads(self.token_usage or "{}")
        except Exception:
            pass
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "citations": cites,
            "token_usage": usage,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class AIAuditLog(Base):
    __tablename__ = "ai_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(String(50), nullable=True)
    question = Column(Text, nullable=False)
    ticket_number = Column(String(50), nullable=True)
    application = Column(String(100), nullable=True)
    project = Column(String(100), nullable=True)
    endpoint = Column(String(255), nullable=True)
    http_status = Column(Integer, default=200)
    response_time_ms = Column(Integer, default=0)
    token_count = Column(Integer, default=0)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user.full_name if self.user else "User",
            "conversation_id": self.conversation_id,
            "question": self.question,
            "ticket_number": self.ticket_number,
            "application": self.application,
            "project": self.project,
            "endpoint": self.endpoint,
            "http_status": self.http_status,
            "response_time_ms": self.response_time_ms,
            "token_count": self.token_count,
            "success": self.success,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class ClosureTaxonomy(Base):
    """Admin-managed options used when closing Incidents, SRs, and Changes."""
    __tablename__ = "closure_taxonomy"

    id = Column(Integer, primary_key=True, index=True)
    ticket_type = Column(String(50), nullable=False, default="Incident")
    category = Column(String(100), nullable=False)
    subcategory = Column(String(150), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    application = relationship("Application", foreign_keys=[application_id])

    def to_dict(self):
        return {
            "id": self.id, "ticket_type": self.ticket_type, "category": self.category,
            "subcategory": self.subcategory, "application_id": self.application_id,
            "application_name": self.application.name if self.application else "All applications",
            "active": self.active
        }


class TicketColumnPreference(Base):
    """Per-ticket list-column configuration; no deployment is required to change it."""
    __tablename__ = "ticket_column_preferences"

    id = Column(Integer, primary_key=True, index=True)
    ticket_type = Column(String(50), nullable=False)
    column_key = Column(String(100), nullable=False)
    label = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=100, nullable=False)

    def to_dict(self):
        return {"id": self.id, "ticket_type": self.ticket_type, "column_key": self.column_key,
                "label": self.label, "enabled": self.enabled, "display_order": self.display_order}


class CustomGroup(Base):
    """Custom security and authorization groups with fine-grained permissions."""
    __tablename__ = "custom_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(String(255), nullable=True)
    permissions = Column(Text, default="[]", nullable=False) # JSON list of permission strings
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    users = relationship("UserCustomGroup", back_populates="custom_group", cascade="all, delete-orphan")

    def to_dict(self):
        try:
            perms = json.loads(self.permissions or "[]")
        except Exception:
            perms = []
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": perms,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "member_count": len(self.users) if hasattr(self, "users") and self.users else 0
        }


class UserCustomGroup(Base):
    """Many-to-many junction between Users and Custom Groups."""
    __tablename__ = "user_custom_groups"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    custom_group_id = Column(Integer, ForeignKey("custom_groups.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", back_populates="custom_groups")
    custom_group = relationship("CustomGroup", back_populates="users")


class ADGroupMapping(Base):
    """Maps Enterprise Active Directory / LDAP groups to ITSM Roles and Custom Groups."""
    __tablename__ = "ad_group_mappings"

    id = Column(Integer, primary_key=True, index=True)
    ad_group_name = Column(String(255), unique=True, index=True, nullable=False) # e.g. CN=ITSM-Admins,OU=Groups,DC=corp
    target_role = Column(String(50), nullable=True) # itsm_admin, itsm_user, itsm_read
    custom_group_id = Column(Integer, ForeignKey("custom_groups.id"), nullable=True)
    description = Column(String(255), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    custom_group = relationship("CustomGroup")

    def to_dict(self):
        return {
            "id": self.id,
            "ad_group_name": self.ad_group_name,
            "target_role": self.target_role,
            "custom_group_id": self.custom_group_id,
            "custom_group_name": self.custom_group.name if self.custom_group else None,
            "description": self.description,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class SSOProviderConfig(Base):
    """B2B and B2C Single Sign-On and SAML 2.0 / OIDC provider configuration."""
    __tablename__ = "sso_provider_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False) # e.g. Corporate SAML, Azure AD B2C
    provider_type = Column(String(20), default="saml", nullable=False) # saml, oidc
    b2b_or_b2c = Column(String(10), default="b2b", nullable=False) # b2b, b2c
    entity_id = Column(String(255), nullable=True)
    sso_url = Column(String(500), nullable=True)
    client_id = Column(String(255), nullable=True)
    client_secret = Column(String(255), nullable=True)
    discovery_url = Column(String(500), nullable=True)
    metadata_xml = Column(Text, nullable=True)
    certificate = Column(Text, nullable=True)
    eso_app_id = Column(String(255), nullable=True)
    claims_email_path = Column(String(100), default="email", nullable=True)
    claims_group_path = Column(String(100), default="groups", nullable=True)
    claims_name_path = Column(String(100), default="name", nullable=True)
    default_role = Column(String(50), default="itsm_user", nullable=False)
    auto_provision = Column(Boolean, default=True, nullable=False)
    role_mapping_rules = Column(Text, default="{}", nullable=True)
    custom_group_mapping_rules = Column(Text, default="{}", nullable=True)
    assignment_group_mapping_rules = Column(Text, default="{}", nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        rmr = {}
        cgmr = {}
        agmr = {}
        try:
            rmr = json.loads(self.role_mapping_rules or "{}") if isinstance(self.role_mapping_rules, str) else (self.role_mapping_rules or {})
            cgmr = json.loads(self.custom_group_mapping_rules or "{}") if isinstance(self.custom_group_mapping_rules, str) else (self.custom_group_mapping_rules or {})
            agmr = json.loads(self.assignment_group_mapping_rules or "{}") if isinstance(self.assignment_group_mapping_rules, str) else (self.assignment_group_mapping_rules or {})
        except Exception:
            pass

        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "b2b_or_b2c": self.b2b_or_b2c,
            "entity_id": self.entity_id,
            "sso_url": self.sso_url,
            "client_id": self.client_id,
            "discovery_url": self.discovery_url,
            "eso_app_id": self.eso_app_id,
            "claims_email_path": self.claims_email_path,
            "claims_group_path": self.claims_group_path,
            "claims_name_path": self.claims_name_path,
            "default_role": self.default_role,
            "auto_provision": self.auto_provision,
            "role_mapping_rules": rmr,
            "custom_group_mapping_rules": cgmr,
            "assignment_group_mapping_rules": agmr,
            "has_metadata_xml": bool(self.metadata_xml),
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
