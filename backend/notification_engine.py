import re
import os
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from backend.models import Notification, User

logger = logging.getLogger("notification_engine")

EMAIL_TEMPLATES = {
    "ticket_created": {
        "subject": "[{{ticket_number}}] New Ticket Created: {{short_description}}",
        "body": """Hello {{caller_name}},

Your ticket {{ticket_number}} has been created successfully.

Ticket Details:
- Application: {{application}}
- Project: {{project}}
- Priority: {{priority}}
- Status: {{status}}
- Assignment Group: {{assignment_group}}

Short Description:
{{short_description}}

View ticket: {{ticket_url}}

Thank you,
IT Support Team"""
    },
    "ticket_assigned": {
        "subject": "[{{ticket_number}}] Assigned to you: {{short_description}}",
        "body": """Hello {{assigned_to}},

Ticket {{ticket_number}} has been assigned to you.

- Priority: {{priority}}
- Application: {{application}}
- Project: {{project}}
- Caller: {{caller_name}}

View ticket: {{ticket_url}}"""
    },
    "customer_comment_added": {
        "subject": "[{{ticket_number}}] Customer added a new comment",
        "body": """Hello Support Team,

Caller {{caller_name}} has added a comment to ticket {{ticket_number}}:

"{{comment}}"

Ticket Status: {{status}}
Priority: {{priority}}
Application: {{application}}
Project: {{project}}

View ticket: {{ticket_url}}"""
    },
    "support_comment_added": {
        "subject": "[{{ticket_number}}] New comment added to your ticket",
        "body": """Hello {{caller_name}},

A support engineer has updated your ticket {{ticket_number}}:

"{{comment}}"

Current Status: {{status}}
Priority: {{priority}}
Application: {{application}}

View ticket: {{ticket_url}}"""
    },
    "ticket_resolved": {
        "subject": "[{{ticket_number}}] Ticket Resolved: {{short_description}}",
        "body": """Hello {{caller_name}},

Your ticket {{ticket_number}} has been marked as Resolved.

Resolution Notes:
{{comment}}

If your issue is not resolved, you may reply to reopen the ticket.

View ticket: {{ticket_url}}"""
    },
    "sla_warning": {
        "subject": "[WARNING] SLA Threshold Reached for {{ticket_number}}",
        "body": """Attention {{assignment_group}} / {{assigned_to}},

Ticket {{ticket_number}} (Priority: {{priority}}) has reached {{threshold}}% of its SLA target.
Please take immediate action to avoid an SLA breach.

View ticket: {{ticket_url}}"""
    },
    "sla_breached": {
        "subject": "[CRITICAL] SLA BREACHED: {{ticket_number}}",
        "body": """Attention IT Operations Management,

Ticket {{ticket_number}} (Priority: {{priority}}, Application: {{application}}, Project: {{project}}) has BREACHED its SLA target.

View ticket: {{ticket_url}}"""
    },
    "change_approval_requested": {
        "subject": "[APPROVAL REQUIRED] Change Request {{ticket_number}}",
        "body": """Hello Approver,

Change Request {{ticket_number}} requires your review and approval.

Summary: {{short_description}}
Risk: {{risk}}
Application: {{application}}

View change request: {{ticket_url}}"""
    }
}

class NotificationEngine:
    @staticmethod
    def render_template(template_str: str, context: Dict[str, Any]) -> str:
        for key, val in context.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(key) + r"\s*\}\}")
            template_str = pattern.sub(str(val or ""), template_str)
        return template_str

    @staticmethod
    def notify(
        db: Session,
        event_type: str,
        recipient_id: int,
        context: Dict[str, Any],
        ticket_id: Optional[int] = None,
        ticket_number: Optional[str] = None,
        ticket_type: Optional[str] = "Incident",
        notification_type: str = "info"
    ):
        """
        Creates in-app notification and logs email send.
        STRICT BUSINESS RULE:
        Internal work notes must NEVER trigger notification to requesters.
        """
        template = EMAIL_TEMPLATES.get(event_type)
        if not template:
            subject = f"[{ticket_number or 'ITSM'}] Update Notification"
            body = f"An update has occurred on ticket {ticket_number}."
        else:
            subject = NotificationEngine.render_template(template["subject"], context)
            body = NotificationEngine.render_template(template["body"], context)

        notif = Notification(
            recipient_id=recipient_id,
            ticket_id=ticket_id,
            ticket_number=ticket_number,
            ticket_type=ticket_type,
            title=subject,
            message=body,
            type=notification_type,
            is_read=False
        )
        db.add(notif)
        db.flush()

        logger.info(f"Notification queued for User ID {recipient_id}: {subject}")
        return notif
