"""
admin_routes.py – Admin queue-management dashboard.

All routes require:
  1. @login_required     – user must be authenticated
  2. @roles_required('admin', 'receptionist')  – backend-enforced

The admin/receptionist can:
  - View filtered queue across all departments
  - Change a patient's priority (Emergency restricted to admin only)
  - See per-department stats

Patient PII is kept minimal — only token number, department, priority,
status, waiting duration, and effective score are shown.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.models import QueueToken
from app.services.auth_service import roles_required
from app.services.admin_service import AdminService
from app.services.queue_service import PRIORITY_ORDER, QueueService

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/queue')
@login_required
@roles_required('admin', 'receptionist')
def queue_dashboard():
    """
    Admin queue management dashboard.
    Supports filtering by department, status, and priority.
    """
    dept_id_raw    = request.args.get('dept_id', type=int)
    status_filter  = request.args.get('status', '').strip() or None
    priority_filter = request.args.get('priority', '').strip() or None

    departments = AdminService.get_all_departments()
    dept_stats  = AdminService.get_department_stats()
    tokens      = AdminService.get_filtered_queue(
        dept_id=dept_id_raw,
        status_filter=status_filter,
        priority_filter=priority_filter,
    )

    # Attach waiting duration (minutes) for display
    token_rows = []
    for t in tokens:
        mins = QueueService.get_waiting_duration_mins(t)
        token_rows.append({
            'token':          t,
            'waiting_mins':   int(mins),
            'effective_score': t.priority_score,   # updated by get_filtered_queue
        })

    # Determine selected department name for display
    selected_dept = None
    if dept_id_raw:
        selected_dept = next((d for d in departments if d.id == dept_id_raw), None)

    return render_template(
        'admin/queue_dashboard.html',
        departments=departments,
        dept_stats=dept_stats,
        token_rows=token_rows,
        selected_dept=selected_dept,
        status_filter=status_filter or '',
        priority_filter=priority_filter or '',
        priority_order=PRIORITY_ORDER,
        active_statuses=['Waiting', 'Checked-In', 'Called', 'In-Consultation'],
    )


@admin_bp.route('/queue/update-priority/<int:token_id>', methods=['POST'])
@login_required
@roles_required('admin', 'receptionist')
def update_priority(token_id):
    """
    Change a patient token's priority.
    Emergency priority is restricted to admin role only (not receptionist).
    """
    new_priority = request.form.get('new_priority', '').strip()

    # Only admins may assign Emergency
    allow_emergency = (current_user.role == 'admin')

    token, error = AdminService.change_patient_priority(
        token_id=token_id,
        new_priority=new_priority,
        allow_emergency=allow_emergency,
    )

    if error:
        flash(f'Priority update failed: {error}', 'danger')
    else:
        flash(
            f'Priority for token {token.token_number} changed to {token.priority}.',
            'success'
        )

    # Return to queue dashboard, preserving current filters
    return redirect(request.referrer or url_for('admin.queue_dashboard'))
