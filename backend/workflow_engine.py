from typing import List, Tuple, Dict, Any

VALID_TRANSITIONS = {
    "Incident": {
        "New": ["Active", "Assigned", "In Progress", "On Hold", "Pending", "Resolved", "Cancelled", "Canceled"],
        "Active": ["In Progress", "On Hold", "Pending", "Assigned", "Resolved", "Closed", "Cancelled", "Canceled"],
        "Assigned": ["Active", "In Progress", "On Hold", "Pending", "Resolved", "Cancelled", "Canceled"],
        "In Progress": ["Active", "On Hold", "Pending", "Resolved", "Closed", "Cancelled", "Canceled"],
        "On Hold": ["Active", "In Progress", "Resolved", "Cancelled", "Canceled"],
        "Pending": ["Active", "In Progress", "Resolved", "Cancelled", "Canceled"],
        "Pending Customer": ["Active", "In Progress", "Resolved", "Cancelled", "Canceled"],
        "Resolved": ["Closed", "In Progress", "Active"], # Re-open or close
        "Closed": [], # Terminal state
        "Cancelled": [], # Terminal state
        "Canceled": []
    },
    "Service Request": {
        "Submitted": ["Active", "New", "Assigned", "In Progress", "Pending Approval", "Approved", "In Fulfillment", "Cancelled", "Canceled"],
        "New": ["Active", "Assigned", "In Progress", "Pending Approval", "Approved", "In Fulfillment", "Fulfilled", "Completed", "Cancelled", "Canceled"],
        "Active": ["In Progress", "Assigned", "Pending Approval", "Approved", "In Fulfillment", "Fulfilled", "Completed", "Closed", "Cancelled", "Canceled"],
        "Assigned": ["Active", "In Progress", "Pending Approval", "Approved", "In Fulfillment", "Fulfilled", "Cancelled", "Canceled"],
        "In Progress": ["Active", "Pending Approval", "Approved", "In Fulfillment", "Fulfilled", "Completed", "Closed", "Cancelled", "Canceled"],
        "Pending Approval": ["Approved", "In Progress", "Active", "Cancelled", "Canceled"],
        "Pending": ["Active", "In Progress", "Fulfilled", "Completed", "Cancelled", "Canceled"],
        "Approved": ["In Fulfillment", "In Progress", "Active", "Cancelled", "Canceled"],
        "In Fulfillment": ["Fulfilled", "Completed", "In Progress", "Active", "Closed", "Cancelled", "Canceled"],
        "Fulfilled": ["Closed", "Completed", "In Progress", "Active"],
        "Completed": ["Closed", "In Progress", "Active"],
        "Closed": [],
        "Cancelled": [],
        "Canceled": []
    },
    "Change Request": {
        "Draft": ["Active", "Assess", "Assessment", "Authorize", "Approval", "Scheduled", "Cancelled", "Canceled"],
        "Active": ["Draft", "Assess", "Assessment", "Authorize", "Approval", "Scheduled", "Implement", "Implementation", "Cancelled", "Canceled"],
        "Assess": ["Active", "Authorize", "Approval", "Draft", "Cancelled", "Canceled"],
        "Assessment": ["Active", "Authorize", "Approval", "Draft", "Cancelled", "Canceled"],
        "Authorize": ["Active", "Scheduled", "Assess", "Assessment", "Draft", "Cancelled", "Canceled"],
        "Approval": ["Active", "Scheduled", "Draft", "Cancelled", "Canceled"],
        "Scheduled": ["Active", "Implement", "Implementation", "Cancelled", "Canceled"],
        "Implement": ["Active", "Review", "Validation", "Completed", "Closed", "Cancelled", "Canceled"],
        "Implementation": ["Active", "Review", "Validation", "Completed", "Closed", "Cancelled", "Canceled"],
        "Review": ["Active", "Completed", "Closed", "Implement", "Implementation", "Cancelled", "Canceled"],
        "Validation": ["Active", "Completed", "Closed", "Implementation", "Implement"],
        "Completed": ["Closed", "Active", "Review"],
        "Closed": [],
        "Cancelled": [],
        "Canceled": []
    }
}

class WorkflowEngine:
    @staticmethod
    def get_allowed_transitions(ticket_type: str, current_status: str) -> List[str]:
        type_transitions = VALID_TRANSITIONS.get(ticket_type, {})
        return type_transitions.get(current_status, [])

    @staticmethod
    def validate_transition(ticket_type: str, current_status: str, new_status: str) -> Tuple[bool, str]:
        if current_status == new_status:
            return True, "No status change"

        allowed = WorkflowEngine.get_allowed_transitions(ticket_type, current_status)
        if new_status in allowed:
            return True, "Valid transition"

        return False, f"Cannot transition {ticket_type} from '{current_status}' to '{new_status}'. Allowed: {', '.join(allowed) or 'None (Terminal state)'}"
