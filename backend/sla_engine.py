import datetime
import json
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from backend.models import (
    SLAPolicy, SLAInstance, BusinessCalendar, Incident, Project, Application, AssignmentGroup
)

class SLAEngine:
    @staticmethod
    def resolve_sla_policy(
        db: Session,
        priority: str,
        ticket_type: str = "Incident",
        application_id: Optional[int] = None,
        project_id: Optional[int] = None,
        assignment_group_id: Optional[int] = None,
        creation_time: Optional[datetime.datetime] = None
    ) -> Dict[str, Any]:
        """
        SLA Resolution Hierarchy:
        1. Project + Assignment Group + Priority
        2. Project + Priority
        3. Assignment Group + Priority
        4. Application + Priority
        5. Global Priority
        Respecting effective dates (effective_from <= creation_time <= effective_to).
        """
        target_time = creation_time or datetime.datetime.utcnow()

        base_query = db.query(SLAPolicy).filter(
            SLAPolicy.priority == priority,
            SLAPolicy.ticket_type == ticket_type,
            SLAPolicy.active == True,
            (SLAPolicy.effective_from <= target_time),
            ((SLAPolicy.effective_to.is_(None)) | (SLAPolicy.effective_to >= target_time))
        ).order_by(SLAPolicy.version.desc())

        # 1. Project + Assignment Group + Priority
        if project_id and assignment_group_id:
            policy = base_query.filter(
                SLAPolicy.project_id == project_id,
                SLAPolicy.assignment_group_id == assignment_group_id
            ).first()
            if policy:
                return {
                    "policy": policy,
                    "level": 1,
                    "rule_type": "Project + Group + Priority SLA",
                    "reason": f"Matched specific SLA '{policy.name} v{policy.version}' for Project + Group + {priority}"
                }

        # 2. Project + Priority
        if project_id:
            policy = base_query.filter(
                SLAPolicy.project_id == project_id,
                SLAPolicy.assignment_group_id.is_(None)
            ).first()
            if policy:
                return {
                    "policy": policy,
                    "level": 2,
                    "rule_type": "Project + Priority SLA",
                    "reason": f"Matched Project SLA '{policy.name} v{policy.version}' for {priority}"
                }

        # 3. Assignment Group + Priority
        if assignment_group_id:
            policy = base_query.filter(
                SLAPolicy.assignment_group_id == assignment_group_id,
                SLAPolicy.project_id.is_(None)
            ).first()
            if policy:
                return {
                    "policy": policy,
                    "level": 3,
                    "rule_type": "Assignment Group + Priority SLA",
                    "reason": f"Matched Group SLA '{policy.name} v{policy.version}' for {priority}"
                }

        # 4. Application + Priority
        if application_id:
            policy = base_query.filter(
                SLAPolicy.application_id == application_id,
                SLAPolicy.project_id.is_(None),
                SLAPolicy.assignment_group_id.is_(None)
            ).first()
            if policy:
                return {
                    "policy": policy,
                    "level": 4,
                    "rule_type": "Application + Priority SLA",
                    "reason": f"Matched Application SLA '{policy.name} v{policy.version}' for {priority}"
                }

        # 5. Global Priority SLA
        policy = base_query.filter(
            SLAPolicy.project_id.is_(None),
            SLAPolicy.assignment_group_id.is_(None),
            SLAPolicy.application_id.is_(None)
        ).first()

        if policy:
            return {
                "policy": policy,
                "level": 5,
                "rule_type": "Global Priority SLA",
                "reason": f"Matched Global Priority SLA '{policy.name} v{policy.version}' for {priority}"
            }

        # Fallback to any active policy for this priority
        fallback = db.query(SLAPolicy).filter(
            SLAPolicy.priority == priority,
            SLAPolicy.active == True
        ).order_by(SLAPolicy.version.desc()).first()

        return {
            "policy": fallback,
            "level": 6,
            "rule_type": "Fallback SLA",
            "reason": f"Fallback to active SLA for priority {priority}" if fallback else "No SLA policy configured"
        }

    @staticmethod
    def calculate_business_minutes(
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        calendar: Optional[BusinessCalendar] = None
    ) -> float:
        """
        Calculates business minutes elapsed between start_time and end_time based on BusinessCalendar.
        If calendar is None or 24x7, calculates real elapsed minutes.
        """
        if not start_time or not end_time or end_time <= start_time:
            return 0.0

        if not calendar:
            return (end_time - start_time).total_seconds() / 60.0

        # Parse calendar attributes
        working_days = [1, 2, 3, 4, 5]
        holidays = []
        try:
            working_days = json.loads(calendar.working_days or "[1,2,3,4,5]")
            holidays = json.loads(calendar.holidays or "[]")
        except Exception:
            pass

        try:
            start_hour, start_min = map(int, calendar.working_hours_start.split(":"))
            end_hour, end_min = map(int, calendar.working_hours_end.split(":"))
        except Exception:
            start_hour, start_min = 9, 0
            end_hour, end_min = 18, 0

        # Iterate minute by minute or interval
        # For efficiency, iterate day by day
        total_mins = 0.0
        curr = start_time
        # Round up current to next minute boundary
        curr = curr.replace(second=0, microsecond=0)

        step = datetime.timedelta(minutes=5)
        while curr < end_time:
            next_step = min(curr + step, end_time)
            mins = (next_step - curr).total_seconds() / 60.0

            # Check if curr date is a working day
            # Python weekday: Mon=0, Sun=6 -> calendar stores 1=Mon, 7=Sun
            day_num = curr.weekday() + 1
            date_str = curr.strftime("%Y-%m-%d")

            if day_num in working_days and date_str not in holidays:
                curr_minutes = curr.hour * 60 + curr.minute
                work_start_minutes = start_hour * 60 + start_min
                work_end_minutes = end_hour * 60 + end_min

                if work_start_minutes <= curr_minutes < work_end_minutes:
                    total_mins += mins

            curr = next_step

        return total_mins

    @staticmethod
    def calculate_due_date(
        start_time: datetime.datetime,
        duration_mins: int,
        calendar: Optional[BusinessCalendar] = None
    ) -> datetime.datetime:
        """
        Calculates when an SLA target is due, stepping forward through business hours.
        """
        if not calendar:
            return start_time + datetime.timedelta(minutes=duration_mins)

        working_days = [1, 2, 3, 4, 5]
        holidays = []
        try:
            working_days = json.loads(calendar.working_days or "[1,2,3,4,5]")
            holidays = json.loads(calendar.holidays or "[]")
        except Exception:
            pass

        try:
            start_hour, start_min = map(int, calendar.working_hours_start.split(":"))
            end_hour, end_min = map(int, calendar.working_hours_end.split(":"))
        except Exception:
            start_hour, start_min = 9, 0
            end_hour, end_min = 18, 0

        daily_work_mins = max(1, (end_hour * 60 + end_min) - (start_hour * 60 + start_min))

        curr = start_time
        remaining_mins = float(duration_mins)

        while remaining_mins > 0:
            day_num = curr.weekday() + 1
            date_str = curr.strftime("%Y-%m-%d")

            is_workday = (day_num in working_days) and (date_str not in holidays)
            if not is_workday:
                # advance to next day morning start
                curr = (curr + datetime.timedelta(days=1)).replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
                continue

            curr_mins = curr.hour * 60 + curr.minute
            work_start_mins = start_hour * 60 + start_min
            work_end_mins = end_hour * 60 + end_min

            if curr_mins < work_start_mins:
                curr = curr.replace(hour=start_hour, minute=start_min, second=0)
                curr_mins = work_start_mins
            elif curr_mins >= work_end_mins:
                curr = (curr + datetime.timedelta(days=1)).replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
                continue

            available_today = work_end_mins - curr_mins
            if remaining_mins <= available_today:
                curr = curr + datetime.timedelta(minutes=remaining_mins)
                remaining_mins = 0
            else:
                remaining_mins -= available_today
                curr = (curr + datetime.timedelta(days=1)).replace(hour=start_hour, minute=start_min, second=0, microsecond=0)

        return curr

    @staticmethod
    def start_sla_instances(
        db: Session,
        ticket_id: int,
        ticket_number: str,
        ticket_type: str,
        sla_policy: SLAPolicy
    ) -> Tuple[SLAInstance, SLAInstance]:
        """
        Creates and starts Response and Resolution SLA instances for a ticket.
        """
        now = datetime.datetime.utcnow()
        calendar = sla_policy.business_calendar

        # Response SLA
        resp_due = SLAEngine.calculate_due_date(now, sla_policy.response_target_mins, calendar)
        resp_inst = SLAInstance(
            ticket_id=ticket_id,
            ticket_type=ticket_type,
            ticket_number=ticket_number,
            sla_policy_id=sla_policy.id,
            target_type="response",
            target_duration_mins=sla_policy.response_target_mins,
            elapsed_business_mins=0.0,
            start_time=now,
            due_at=resp_due,
            stage="in_progress",
            current_escalation_level=0,
            pause_history="[]"
        )

        # Resolution SLA
        res_due = SLAEngine.calculate_due_date(now, sla_policy.resolution_target_mins, calendar)
        res_inst = SLAInstance(
            ticket_id=ticket_id,
            ticket_type=ticket_type,
            ticket_number=ticket_number,
            sla_policy_id=sla_policy.id,
            target_type="resolution",
            target_duration_mins=sla_policy.resolution_target_mins,
            elapsed_business_mins=0.0,
            start_time=now,
            due_at=res_due,
            stage="in_progress",
            current_escalation_level=0,
            pause_history="[]"
        )

        db.add(resp_inst)
        db.add(res_inst)
        db.flush()
        return resp_inst, res_inst

    @staticmethod
    def handle_status_change(
        db: Session,
        ticket_id: int,
        ticket_type: str,
        old_status: str,
        new_status: str,
        reason: Optional[str] = None
    ):
        """
        Updates SLA instances upon ticket status changes (pause, resume, achieve, breach).
        """
        now = datetime.datetime.utcnow()
        instances = db.query(SLAInstance).filter(
            SLAInstance.ticket_id == ticket_id,
            SLAInstance.ticket_type == ticket_type
        ).all()

        for inst in instances:
            policy = inst.sla_policy
            if not policy:
                continue

            pause_conditions = []
            try:
                pause_conditions = json.loads(policy.pause_conditions or "[]")
            except Exception:
                pass

            # 1. Response SLA Achievement: on Assigned or In Progress
            if inst.target_type == "response" and inst.stage == "in_progress":
                if new_status in ["Assigned", "In Progress", "Pending", "Resolved", "Closed"]:
                    inst.achieved_at = now
                    inst.stage = "achieved"

            # 2. Resolution SLA Achievement: on Resolved, Fulfilled, Closed
            if inst.target_type == "resolution" and inst.stage in ["in_progress", "paused"]:
                if new_status in ["Resolved", "Fulfilled", "Closed"]:
                    inst.achieved_at = now
                    inst.stage = "achieved"
                    continue

            # 3. Handle Pausing
            if new_status in pause_conditions and inst.stage == "in_progress":
                inst.stage = "paused"
                inst.paused_at = now
                history = []
                try:
                    history = json.loads(inst.pause_history or "[]")
                except Exception:
                    pass
                history.append({
                    "paused_at": now.isoformat(),
                    "reason": reason or f"Ticket status changed to {new_status}"
                })
                inst.pause_history = json.dumps(history)

            # 4. Handle Resuming from Pause
            elif old_status in pause_conditions and new_status not in pause_conditions and inst.stage == "paused":
                inst.stage = "in_progress"
                history = []
                try:
                    history = json.loads(inst.pause_history or "[]")
                except Exception:
                    pass
                if history and "resumed_at" not in history[-1]:
                    history[-1]["resumed_at"] = now.isoformat()
                inst.pause_history = json.dumps(history)
                inst.paused_at = None

        db.flush()

    @staticmethod
    def handle_priority_change(
        db: Session,
        ticket_id: int,
        ticket_type: str,
        old_priority: str,
        new_priority: str,
    ):
        """
        Recalculates SLA deadlines when a ticket's priority changes.
        Adjusts all in-progress SLA instances based on the new priority's target times.
        """
        if old_priority == new_priority:
            return

        now = datetime.datetime.utcnow()
        instances = db.query(SLAInstance).filter(
            SLAInstance.ticket_id == ticket_id,
            SLAInstance.ticket_type == ticket_type
        ).all()

        for inst in instances:
            # Skip already achieved or breached instances
            if inst.stage in ("achieved", "breached"):
                continue

            policy = inst.sla_policy
            if not policy:
                continue

            # Recalculate the target window based on new priority
            p_targets = {}
            try:
                p_targets = json.loads(policy.priority_targets or "{}")
            except Exception:
                pass

            new_targets = p_targets.get(new_priority) or p_targets.get(new_priority.lower())
            if not new_targets:
                continue

            target_key = "response_target_hours" if inst.target_type == "response" else "resolution_target_hours"
            new_hours = new_targets.get(target_key)
            if not new_hours:
                continue

            # Adjust the deadline from now, preserving elapsed time logic
            elapsed = datetime.timedelta(0)
            if inst.started_at and inst.stage == "in_progress":
                elapsed = now - inst.started_at

            new_deadline = now + datetime.timedelta(hours=float(new_hours)) - elapsed
            inst.target_time = new_deadline

        db.flush()
