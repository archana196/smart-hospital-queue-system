"""
doctor_routes.py – Doctor Dashboard routes.

All routes here are protected by:
  1. @login_required  – user must be authenticated
  2. @roles_required('doctor') – user must have the doctor role

These checks happen on the Flask backend on every request, independent
of what is shown or hidden in the HTML.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.models import QueueToken
from app.services.auth_service import roles_required
from app.services.doctor_service import DoctorService
from app.services.queue_service import QueueService

doctor_bp = Blueprint('doctor', __name__, url_prefix='/doctor')


def _get_doctor_or_abort():
    """Helper: return the Doctor profile for the logged-in user or abort 403."""
    doctor = DoctorService.get_doctor_for_user(current_user.id)
    if doctor is None:
        abort(403)
    return doctor


# ── Dashboard ────────────────────────────────────────────────────────────────

@doctor_bp.route('/dashboard')
@login_required
@roles_required('doctor')
def dashboard():
    doctor = _get_doctor_or_abort()

    waiting_queue = QueueService.get_department_queue(doctor.department_id)
    current_token = DoctorService.get_current_consultation(doctor.id)
    called_token = DoctorService.get_called_token(doctor.id)

    return render_template(
        'doctor/dashboard.html',
        doctor=doctor,
        waiting_queue=waiting_queue,
        current_token=current_token,
        called_token=called_token,
    )


# ── Call next patient ─────────────────────────────────────────────────────────

@doctor_bp.route('/call-next', methods=['POST'])
@login_required
@roles_required('doctor')
def call_next():
    doctor = _get_doctor_or_abort()
    token, error = DoctorService.call_next_patient(doctor)
    if error:
        flash(error, 'warning')
    else:
        flash(f'Patient called: {token.token_number}', 'success')
    return redirect(url_for('doctor.dashboard'))


# ── Start consultation ────────────────────────────────────────────────────────

@doctor_bp.route('/start-consultation/<int:token_id>', methods=['POST'])
@login_required
@roles_required('doctor')
def start_consultation(token_id):
    doctor = _get_doctor_or_abort()
    token, error = DoctorService.start_consultation(doctor, token_id)
    if error:
        flash(error, 'warning')
    else:
        flash(f'Consultation started for {token.token_number}.', 'success')
    return redirect(url_for('doctor.dashboard'))


# ── Complete consultation ─────────────────────────────────────────────────────

@doctor_bp.route('/complete-consultation/<int:token_id>', methods=['POST'])
@login_required
@roles_required('doctor')
def complete_consultation(token_id):
    doctor = _get_doctor_or_abort()
    token, error = DoctorService.complete_consultation(doctor, token_id)
    if error:
        flash(error, 'warning')
    else:
        flash(f'Consultation completed for {token.token_number}.', 'success')
    return redirect(url_for('doctor.dashboard'))


# ── No-Show / Return to queue ─────────────────────────────────────────────────

@doctor_bp.route('/no-show/<int:token_id>', methods=['POST'])
@login_required
@roles_required('doctor')
def no_show(token_id):
    doctor = _get_doctor_or_abort()
    # The form sends 'action' = 'No-Show' | 'Waiting'
    action = request.form.get('action', 'No-Show')
    token, error = DoctorService.handle_no_show(doctor, token_id, action)
    if error:
        flash(error, 'warning')
    else:
        label = 'marked as No-Show' if action == 'No-Show' else 'returned to queue'
        flash(f'Token {token.token_number} {label}.', 'info')
    return redirect(url_for('doctor.dashboard'))


# ── Toggle availability ───────────────────────────────────────────────────────

@doctor_bp.route('/toggle-availability', methods=['POST'])
@login_required
@roles_required('doctor')
def toggle_availability():
    doctor = _get_doctor_or_abort()
    doctor = DoctorService.toggle_availability(doctor)
    status = 'Available' if doctor.is_available else 'Unavailable'
    flash(f'Your status is now: {status}.', 'info')
    return redirect(url_for('doctor.dashboard'))
