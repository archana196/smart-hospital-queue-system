"""
admin_service.py – Admin queue-management business logic.

Responsible for:
  - Building filtered queue views across departments
  - Authorizing and delegating priority updates to QueueService
  - Providing department stats for the admin overview

Authorization rules are enforced HERE (server-side), not in HTML.
"""

from datetime import datetime, timezone

from app.models import db, Department, QueueToken, Doctor
from app.services.queue_service import QueueService, ELIGIBLE_STATUSES, PRIORITY_ORDER


class AdminService:

    # ── Queue overview ───────────────────────────────────────────────────────

    @staticmethod
    def get_all_departments():
        return Department.query.order_by(Department.name).all()

    @staticmethod
    def get_filtered_queue(dept_id=None, status_filter=None, priority_filter=None,
                           now_dt=None):
        """
        Return tokens matching the given filters, ordered by priority score then
        registration time.

        Parameters
        ----------
        dept_id        : int | None  – filter to one department; None = all
        status_filter  : str | None  – e.g. 'Waiting'; None = all active statuses
        priority_filter: str | None  – e.g. 'Emergency'; None = all priorities
        now_dt         : datetime | None – for deterministic testing

        Returns
        -------
        list[QueueToken]
        """
        # Active statuses shown in admin view (exclude terminal by default)
        ACTIVE_STATUSES = ['Waiting', 'Checked-In', 'Called', 'In-Consultation']

        query = QueueToken.query

        if dept_id:
            query = query.filter(QueueToken.department_id == dept_id)

        if status_filter and status_filter in ACTIVE_STATUSES:
            query = query.filter(QueueToken.status == status_filter)
        else:
            query = query.filter(QueueToken.status.in_(ACTIVE_STATUSES))

        if priority_filter and priority_filter in PRIORITY_ORDER:
            query = query.filter(QueueToken.priority == priority_filter)

        tokens = query.all()

        # Recompute effective scores for sorting (eligible statuses only)
        for t in tokens:
            if t.status in ELIGIBLE_STATUSES:
                t.priority_score = QueueService.calculate_effective_priority_score(
                    t, now_dt=now_dt
                )

        # Sort: score DESC, then created_at ASC
        def _sort_key(t):
            dt = t.created_at
            if dt is not None and dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return (-t.priority_score, dt or datetime.min)

        tokens.sort(key=_sort_key)
        return tokens

    @staticmethod
    def get_department_stats():
        """Return a list of dicts with per-department queue stats for the dashboard."""
        departments = Department.query.order_by(Department.name).all()
        stats = []
        for dept in departments:
            waiting = QueueToken.query.filter_by(
                department_id=dept.id, status='Waiting'
            ).count()
            checked_in = QueueToken.query.filter_by(
                department_id=dept.id, status='Checked-In'
            ).count()
            in_consult = QueueToken.query.filter_by(
                department_id=dept.id, status='In-Consultation'
            ).count()
            called = QueueToken.query.filter_by(
                department_id=dept.id, status='Called'
            ).count()
            stats.append({
                'id':            dept.id,
                'name':          dept.name,
                'code':          dept.code,
                'waiting':       waiting,
                'checked_in':    checked_in,
                'in_consult':    in_consult,
                'called':        called,
                'total_active':  waiting + checked_in + in_consult + called,
            })
        return stats

    # ── Priority management ──────────────────────────────────────────────────

    @staticmethod
    def change_patient_priority(token_id, new_priority, allow_emergency=False):
        """
        Delegate to QueueService.update_token_priority with authorization flag.

        Returns (token, None) on success, (None, error_str) on failure.
        Database is NOT modified on failure.
        """
        return QueueService.update_token_priority(
            token_id=token_id,
            new_priority=new_priority,
            allow_emergency=allow_emergency,
        )
