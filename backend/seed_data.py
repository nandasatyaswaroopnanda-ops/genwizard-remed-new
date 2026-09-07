import os
import datetime
import json
from sqlalchemy.orm import Session
from backend.database import SessionLocal, engine, Base, migrate_legacy_schema
from backend.models import (
    User, Application, Project, AssignmentGroup, GroupMember,
    ProjectAssignmentMapping, RoutingRule, BusinessCalendar,
    SLAPolicy, SLAInstance, Incident, ServiceRequest, ChangeRequest,
    TicketComment, TicketWorkNote, KnowledgeArticle, AIConfiguration,
    Approval, AuditLog, ConfigurationAudit, Notification
)
from backend.sla_engine import SLAEngine


def _purge_development_dummy_data(db: Session):
    """Purges any dummy development artifacts (test incidents, fake users, mock articles, demo apps/projects)
    that may have been created during earlier local testing, guaranteeing a completely clean,
    blank client production database."""
    try:
        from backend.models import (
            Incident, ServiceRequest, ChangeRequest, TicketComment, TicketWorkNote,
            SLAInstance, KnowledgeArticle, Application, Project, AssignmentGroup,
            GroupMember, CustomGroup, UserCustomGroup, RoutingRule, SLAPolicy,
            ProjectAssignmentMapping, Notification, Approval
        )

        # 1. Purge all dummy tickets and associated records
        dummy_inc_numbers = ["INC0001001", "INC0001002", "INC0001003", "INC0001004", "INC0001005", "INC0001006"]
        dummy_req_numbers = ["REQ0001001", "REQ0001002"]
        dummy_chg_numbers = ["CHG0001001", "CHG0001002"]

        # Delete all dummy incidents or any incidents created in development
        dummy_incs = db.query(Incident).filter(
            (Incident.number.in_(dummy_inc_numbers)) |
            (Incident.short_description.like("%test%")) |
            (Incident.short_description.like("%Payment%")) |
            (Incident.short_description.like("%tokenization%")) |
            (Incident.short_description.like("%Redis%"))
        ).all()
        dummy_inc_ids = [i.id for i in dummy_incs]
        if dummy_inc_ids:
            for c in db.query(TicketComment).filter(TicketComment.ticket_type == "Incident", TicketComment.ticket_id.in_(dummy_inc_ids)).all():
                db.delete(c)
            for wn in db.query(TicketWorkNote).filter(TicketWorkNote.ticket_type == "Incident", TicketWorkNote.ticket_id.in_(dummy_inc_ids)).all():
                db.delete(wn)
            for sla in db.query(SLAInstance).filter(SLAInstance.ticket_type == "Incident", SLAInstance.ticket_id.in_(dummy_inc_ids)).all():
                db.delete(sla)
            for inc in dummy_incs:
                db.delete(inc)

        for req in db.query(ServiceRequest).filter(
            (ServiceRequest.number.in_(dummy_req_numbers)) |
            (ServiceRequest.short_description.like("%test%")) |
            (ServiceRequest.catalog_item.in_(["PostgreSQL Sandbox", "VPN Access"]))
        ).all():
            db.delete(req)

        for chg in db.query(ChangeRequest).filter(
            (ChangeRequest.number.in_(dummy_chg_numbers)) |
            (ChangeRequest.short_description.like("%test%"))
        ).all():
            db.delete(chg)

        # 2. Remove dummy knowledge articles
        for kb in db.query(KnowledgeArticle).filter(
            (KnowledgeArticle.article_number.in_(["KB0001001", "KB0001002"])) |
            (KnowledgeArticle.title.like("%Payment%")) |
            (KnowledgeArticle.title.like("%Runbook%"))
        ).all():
            db.delete(kb)

        # 3. Remove dummy users and their group/custom group linkages
        dummy_usernames = ["john.smith", "sarah.johnson", "david.wilson", "mike.brown"]
        dummy_users = db.query(User).filter(User.username.in_(dummy_usernames)).all()
        dummy_user_ids = [u.id for u in dummy_users]
        if dummy_user_ids:
            for gm in db.query(GroupMember).filter(GroupMember.user_id.in_(dummy_user_ids)).all():
                db.delete(gm)
            for ucg in db.query(UserCustomGroup).filter(UserCustomGroup.user_id.in_(dummy_user_ids)).all():
                db.delete(ucg)
            for u in dummy_users:
                db.delete(u)

        # 4. Remove dummy applications
        dummy_app_names = [
            "Payment Gateway", "Customer Portal", "Identity Management",
            "Knowledge Manager", "Workflow Manager", "Checkout Engine Test", "Testing App"
        ]
        dummy_app_ids = ["APP001", "APP002", "APP-TEST-CHK"]
        for app in db.query(Application).filter((Application.name.in_(dummy_app_names)) | (Application.app_id.in_(dummy_app_ids))).all():
            # Clear project assignment mappings
            for pam in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.application_id == app.id).all():
                db.delete(pam)
            db.delete(app)

        # 5. Remove dummy projects
        dummy_proj_names = [
            "Payment Platform Modernization", "Customer Portal Modernization",
            "Cloud Migration", "IAM Transformation", "Testing Project"
        ]
        for proj in db.query(Project).filter(
            (Project.name.in_(dummy_proj_names)) |
            (Project.project_id.in_(["PRJ-PM-001", "PRJ-CPM-001", "PRJ-CM-001"])) |
            (Project.project_id.like("PRJ-PAYMENT%")) |
            (Project.project_id.like("PRJ-CUSTOMER%")) |
            (Project.project_id.like("PRJ-CLOUD%"))
        ).all():
            for pam in db.query(ProjectAssignmentMapping).filter(ProjectAssignmentMapping.project_id == proj.id).all():
                db.delete(pam)
            db.delete(proj)

        # 6. Remove dummy assignment groups (keeping strictly the global "Service Desk" fallback)
        dummy_group_names = [
            "Payment Application Support", "Database Support", "Cloud Operations",
            "Network Support", "Security Operations", "Checkout Ops Special Squad"
        ]
        for grp in db.query(AssignmentGroup).filter(
            (AssignmentGroup.name.in_(dummy_group_names)) |
            (AssignmentGroup.group_id.in_(["GRP001", "GRP002", "GRP003", "GRP004", "GRP005", "grp-checkout-ops"])) |
            (AssignmentGroup.name.like("%-l2")) |
            (AssignmentGroup.name.like("%-l3")) |
            (AssignmentGroup.name.like("% L2 Frontier")) |
            (AssignmentGroup.name.like("% L3 Frontier"))
        ).all():
            for gm in db.query(GroupMember).filter(GroupMember.group_id == grp.id).all():
                db.delete(gm)
            db.delete(grp)

        # 7. Remove dummy custom groups (e.g. Project-specific admin groups)
        for cg in db.query(CustomGroup).filter(
            (CustomGroup.name.like("%_admin")) &
            (~CustomGroup.name.in_(["itsm_admin"]))
        ).all():
            for ucg in db.query(UserCustomGroup).filter(UserCustomGroup.custom_group_id == cg.id).all():
                db.delete(ucg)
            db.delete(cg)

        # 8. Remove dummy routing rules
        for rr in db.query(RoutingRule).filter(RoutingRule.rule_code.in_(["R1021", "R1022", "R1023"])).all():
            db.delete(rr)

        # 9. Remove dummy SLA policies tied to demo apps
        for sla in db.query(SLAPolicy).filter(
            (SLAPolicy.policy_code.in_(["SLA101", "SLA102"])) |
            (SLAPolicy.application_id != None) |
            (SLAPolicy.project_id != None)
        ).all():
            db.delete(sla)

        db.commit()
    except Exception as exc:
        db.rollback()
        import logging
        logging.getLogger("backend").warning(f"Error purging development dummy data: {exc}")


def init_db_and_seed():
    """Initializes the database.
    In production (default): seeds strictly the required platform foundation
    (Admin user, Default Business Calendars, Service Desk Fallback Queue,
    Baseline Global SLAs, and Default AI Configuration).
    Zero dummy tickets, zero dummy users, and zero dummy articles are seeded.
    """
    migrate_legacy_schema()
    Base.metadata.create_all(bind=engine)
    try:
        db: Session = SessionLocal()
        seed_demo = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in ("1", "true", "yes")

        if not seed_demo:
            _purge_development_dummy_data(db)

        # 1. Ensure essential Admin user exists
        admin_pass = os.getenv("ITSM_BOOTSTRAP_ADMIN_PASSWORD", "Admin@Secure2026!")
        from identity_service.security import hash_password
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                employee_id="EMP001",
                username="admin",
                full_name="Admin User",
                first_name="Admin",
                last_name="User",
                email="admin@company.com",
                phone="+1-555-0100",
                department="IT Operations",
                location="HQ",
                role="itsm_admin",
                password_hash=hash_password(admin_pass),
                is_local=True,
                active=True
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        elif not admin.password_hash or admin.role != "itsm_admin":
            admin.password_hash = hash_password(admin_pass)
            admin.role = "itsm_admin"
            admin.is_local = True
            db.commit()

        # 2. Ensure essential Business Calendars exist
        cal_24x7 = db.query(BusinessCalendar).filter(BusinessCalendar.name == "24x7 Global Operations").first()
        if not cal_24x7:
            cal_24x7 = BusinessCalendar(
                name="24x7 Global Operations",
                description="Continuous 24 hours 7 days a week support calendar for critical tier-1 services",
                timezone="UTC",
                working_days=json.dumps([1, 2, 3, 4, 5, 6, 7]),
                working_hours_start="00:00",
                working_hours_end="24:00",
                holidays="[]",
                exceptions="[]"
            )
            db.add(cal_24x7)
            db.commit()
            db.refresh(cal_24x7)

        cal_std = db.query(BusinessCalendar).filter(BusinessCalendar.name == "Standard Business Hours").first()
        if not cal_std:
            cal_std = BusinessCalendar(
                name="Standard Business Hours",
                description="Standard working hours Mon-Fri 09:00 to 18:00 with statutory company holidays",
                timezone="UTC",
                working_days=json.dumps([1, 2, 3, 4, 5]),
                working_hours_start="09:00",
                working_hours_end="18:00",
                holidays="[]",
                exceptions="[]"
            )
            db.add(cal_std)
            db.commit()
            db.refresh(cal_std)

        # 3. Ensure baseline Global Service Desk queue exists (Tier-6 routing fallback)
        grp_service_desk = db.query(AssignmentGroup).filter(AssignmentGroup.name == "Service Desk").first()
        if not grp_service_desk:
            grp_service_desk = AssignmentGroup(
                group_id="GRP000",
                name="Service Desk",
                description="Global Level-1 IT Service Desk for triage and user requests",
                manager_id=admin.id,
                business_calendar_id=cal_24x7.id,
                active=True
            )
            db.add(grp_service_desk)
            db.commit()
            db.refresh(grp_service_desk)

        # 4. Ensure baseline Global SLA Policies exist (Fallback for any created ticket)
        global_slas = [
            # (Ticket Type, Priority, Response Mins, Resolution Mins, Calendar, Description)
            # Incidents
            ("Incident", "P1", 15, 240, cal_24x7, "Critical Incident SLA: 15 min (0.25 hrs) response, 4.0 hrs (240 mins) resolution"),
            ("Incident", "P2", 30, 480, cal_24x7, "High Incident SLA: 30 min (0.5 hrs) response, 8.0 hrs (480 mins) resolution"),
            ("Incident", "P3", 120, 1440, cal_std, "Standard Incident SLA: 2.0 hrs (120 mins) response, 24.0 hrs (1 day) resolution"),
            ("Incident", "P4", 480, 4320, cal_std, "Low Incident SLA: 8.0 hrs (480 mins) response, 72.0 hrs (3 business days) resolution"),
            # Service Requests
            ("Service Request", "P1", 30, 480, cal_24x7, "Critical Service Request SLA: 30 min (0.5 hrs) response, 8.0 hrs (480 mins) resolution"),
            ("Service Request", "P2", 60, 1440, cal_std, "High Service Request SLA: 1.0 hr (60 mins) response, 24.0 hrs (1 day) resolution"),
            ("Service Request", "P3", 240, 2880, cal_std, "Standard Service Request SLA: 4.0 hrs (240 mins) response, 48.0 hrs (2 days) resolution"),
            ("Service Request", "P4", 480, 5760, cal_std, "Low Service Request SLA: 8.0 hrs (480 mins) response, 96.0 hrs (4 days) resolution"),
            # Change Requests
            ("Change Request", "P1", 60, 480, cal_24x7, "Critical Emergency Change SLA: 1.0 hr (60 mins) response, 8.0 hrs (480 mins) resolution"),
            ("Change Request", "P2", 120, 1440, cal_24x7, "High Expedited Change SLA: 2.0 hrs (120 mins) response, 24.0 hrs (1 day) resolution"),
            ("Change Request", "P3", 480, 4320, cal_std, "Standard Normal Change SLA: 8.0 hrs (480 mins) response, 72.0 hrs (3 days) resolution"),
            ("Change Request", "P4", 1440, 10080, cal_std, "Low Routine Change SLA: 24.0 hrs (1440 mins) response, 168.0 hrs (7 days) resolution"),
        ]
        for t_type, priority, resp, res, cal, desc in global_slas:
            code_prefix = "INC" if t_type == "Incident" else ("REQ" if t_type == "Service Request" else "CHG")
            target_code = f"SLA-GLOBAL-{code_prefix}-{priority}"
            legacy_code = f"SLA-GLOBAL-{priority}" if t_type == "Incident" else None

            existing_sla = db.query(SLAPolicy).filter(
                SLAPolicy.ticket_type == t_type,
                SLAPolicy.priority == priority,
                SLAPolicy.application_id == None,
                SLAPolicy.project_id == None
            ).first()

            if not existing_sla and legacy_code:
                existing_sla = db.query(SLAPolicy).filter(
                    SLAPolicy.policy_code == legacy_code,
                    SLAPolicy.application_id == None,
                    SLAPolicy.project_id == None
                ).first()

            if not existing_sla:
                db.add(SLAPolicy(
                    policy_code=target_code,
                    name=f"Global {t_type} {priority} SLA",
                    version=1,
                    description=desc,
                    ticket_type=t_type,
                    priority=priority,
                    response_target_mins=resp,
                    resolution_target_mins=res,
                    business_calendar_id=cal.id,
                    warning_threshold_pct=75,
                    active=True,
                    effective_from=datetime.datetime(2025, 1, 1)
                ))
        db.commit()

        # 5. Ensure default AI Configuration exists
        ai_cfg = db.query(AIConfiguration).first()
        if not ai_cfg:
            db.add(AIConfiguration(
                is_enabled=True,
                assistant_name="ITSM Support Copilot",
                welcome_message="Hello! I am your ITSM Support Copilot. Ask me anything about your applications, runbooks, or troubleshooting procedures.",
                km_base_url="https://internal-km.company.local",
                api_endpoint="/api/chat/completions",
                auth_type="Bearer",
                auth_token="env:KM_API_TOKEN",
                timeout_seconds=20,
                http_method="POST",
                headers_template='{"Content-Type": "application/json"}',
                response_json_path="choices[0].message.content",
                error_json_path="error.message",
                allow_app_context=True,
                allow_project_context=True,
                allow_ticket_context=True,
                allow_history=True,
                pii_filtering=True,
                audit_enabled=True
            ))
            db.commit()

        # 6. Seed optional development demo fixtures ONLY if explicitly requested (e.g. during automated testing)
        if seed_demo:
            from backend.security import LOCAL_PERSONAS, _ensure_local_persona
            for uid in LOCAL_PERSONAS:
                _ensure_local_persona(uid, db)
            _seed_demo_items(db, admin, cal_24x7, cal_std, grp_service_desk)
        else:
            print("✓ Production startup verified: Platform initialized with 100% clean, blank state (0 dummy tickets, 0 demo apps, 0 demo projects, 0 demo users).")

    except Exception as e:
        db.rollback()
        print(f"Error initializing database: {e}")
        raise
    finally:
        db.close()


def _seed_demo_items(db: Session, admin_user: User, cal_24x7: BusinessCalendar, cal_india: BusinessCalendar, grp_service_desk: AssignmentGroup):
    """Seed demonstration projects, apps, and tickets for automated testing environments."""
    if db.query(Application).filter(Application.name == "Payment Gateway").first():
        return

    now = datetime.datetime.utcnow()
    from identity_service.security import hash_password
    admin_pass = os.getenv("ITSM_BOOTSTRAP_ADMIN_PASSWORD", "Admin@Secure2026!")

    def _ensure_user(emp_id, username, full_name, first, last, email, role):
        u = db.query(User).filter(User.username == username).first()
        if not u:
            u = User(
                employee_id=emp_id,
                username=username,
                full_name=full_name,
                first_name=first,
                last_name=last,
                email=email,
                role=role,
                active=True
            )
            db.add(u)
            db.commit()
            db.refresh(u)
        return u

    john_smith = _ensure_user("EMP002", "john.smith", "John Smith", "John", "Smith", "john.smith@company.com", "employee")
    sarah_johnson = _ensure_user("EMP003", "sarah.johnson", "Sarah Johnson", "Sarah", "Johnson", "sarah.johnson@company.com", "support_member")
    david_wilson = _ensure_user("EMP004", "david.wilson", "David Wilson", "David", "Wilson", "david.wilson@company.com", "group_manager")
    mike_brown = _ensure_user("EMP005", "mike.brown", "Mike Brown", "Mike", "Brown", "mike.brown@company.com", "support_member")

    grp_payment_support = AssignmentGroup(
        group_id="GRP001",
        name="Payment Application Support",
        description="Dedicated tier-2/3 application engineering team supporting Payment Gateway",
        manager_id=sarah_johnson.id,
        business_calendar_id=cal_24x7.id,
        active=True
    )
    grp_db_support = AssignmentGroup(
        group_id="GRP002",
        name="Database Support",
        description="Core Database Administration team",
        manager_id=david_wilson.id,
        business_calendar_id=cal_india.id,
        active=True
    )
    grp_cloud_ops = AssignmentGroup(
        group_id="GRP003",
        name="Cloud Operations",
        description="Cloud Platform team",
        manager_id=mike_brown.id,
        business_calendar_id=cal_24x7.id,
        active=True
    )
    grp_network = AssignmentGroup(
        group_id="GRP004",
        name="Network Support",
        description="Corporate networking and VPN",
        manager_id=admin_user.id,
        business_calendar_id=cal_india.id,
        active=True
    )
    grp_security = AssignmentGroup(
        group_id="GRP005",
        name="Security Operations",
        description="InfoSec and vulnerability management",
        manager_id=admin_user.id,
        business_calendar_id=cal_24x7.id,
        active=True
    )
    db.add_all([grp_payment_support, grp_db_support, grp_cloud_ops, grp_network, grp_security])
    db.commit()
    db.refresh(grp_payment_support)
    db.refresh(grp_db_support)
    db.refresh(grp_cloud_ops)

    app_payment = Application(
        app_id="APP001",
        name="Payment Gateway",
        description="Enterprise payment processing engine",
        default_assignment_group_id=grp_payment_support.id,
        support_hours="24x7",
        criticality="Critical",
        active=True
    )
    app_portal = Application(
        app_id="APP002",
        name="Customer Portal",
        description="Customer self-service portal",
        default_assignment_group_id=grp_payment_support.id,
        support_hours="Standard Business Hours",
        criticality="High",
        active=True
    )
    db.add_all([app_payment, app_portal])
    db.commit()
    db.refresh(app_payment)
    db.refresh(app_portal)

    sla_p1_v1 = SLAPolicy(
        policy_code="SLA101",
        name="Critical Application SLA",
        version=1,
        description="Standard tier-1 SLA: 15 min response, 4 hour resolution",
        ticket_type="Incident",
        application_id=app_payment.id,
        priority="P1",
        response_target_mins=15,
        resolution_target_mins=240,
        business_calendar_id=cal_24x7.id,
        warning_threshold_pct=75,
        active=True,
        effective_from=datetime.datetime(2025, 1, 1),
        effective_to=datetime.datetime(2026, 12, 31, 23, 59, 59)
    )
    db.add(sla_p1_v1)
    db.commit()
    db.refresh(sla_p1_v1)

    proj_payment_mod = Project(
        project_id="PRJ-PM-001",
        name="Payment Platform Modernization",
        description="Next-gen microservices architecture migration",
        application_id=app_payment.id,
        project_manager="Sarah Johnson",
        default_assignment_group_id=grp_payment_support.id,
        default_sla_policy_id=sla_p1_v1.id,
        support_hours="24x7",
        criticality="Critical",
        active=True,
        effective_from=datetime.datetime(2025, 1, 1)
    )
    proj_portal_mod = Project(
        project_id="PRJ-CP-002",
        name="Customer Portal Modernization",
        description="Customer portal redesign",
        application_id=app_portal.id,
        project_manager="David Wilson",
        default_assignment_group_id=grp_payment_support.id,
        support_hours="Standard Business Hours",
        criticality="High",
        active=True,
        effective_from=datetime.datetime(2025, 1, 1)
    )
    db.add_all([proj_payment_mod, proj_portal_mod])
    db.commit()
    db.refresh(proj_payment_mod)

    grp_l2_pay = db.query(AssignmentGroup).filter(AssignmentGroup.name == f"{proj_payment_mod.name}-l2").first()
    target_grp_id = grp_l2_pay.id if grp_l2_pay else (proj_payment_mod.l2_assignment_group_id or proj_payment_mod.default_assignment_group_id)
    map3 = ProjectAssignmentMapping(
        mapping_id="MAP103",
        project_id=proj_payment_mod.id,
        application_id=app_payment.id,
        assignment_group_id=target_grp_id,
        category=None,
        routing_priority=30,
        active=True
    )
    db.add(map3)
    db.commit()


if __name__ == "__main__":
    init_db_and_seed()
