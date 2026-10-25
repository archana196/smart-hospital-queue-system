"""
patient_routes.py – Patient-facing registration, token view and queue status pages.

All inputs are validated by ValidationService before being passed to QueueService.
Backend validation is authoritative; frontend JS validation is a convenience only.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
import time as _time_module

from app.models import db, Department, QueueToken, Patient
from app.services.queue_service import QueueService
from app.services.qr_service import QRService
from app.services.validation_service import ValidationService

patient_bp = Blueprint('patient', __name__, url_prefix='/patient')


@patient_bp.route('/register', methods=['GET', 'POST'])
def register():
    departments = Department.query.all()

    if request.method == 'POST':
        # ── Collect raw form data ────────────────────────────────────────────
        form_data = {
            'name':              request.form.get('name', ''),
            'age':               request.form.get('age', ''),
            'gender':            request.form.get('gender', ''),
            'phone':             request.form.get('phone', ''),
            'department_id':     request.form.get('department_id', ''),
            'registration_type': request.form.get('registration_type', 'Walk-in'),
            'priority':          request.form.get('priority', 'Normal'),
            'appointment_date':  request.form.get('appointment_date', ''),
            'appointment_time':  request.form.get('appointment_time', ''),
        }

        # ── Determine whether Emergency priority is allowed ──────────────────
        # Logged-in staff (admin / receptionist / doctor) may assign any priority.
        allow_emergency = (
            current_user.is_authenticated
            and current_user.role in ('admin', 'receptionist', 'doctor')
        )

        # ── Backend validation ───────────────────────────────────────────────
        errors = ValidationService.validate_registration(
            form_data, allow_emergency=allow_emergency
        )

        if errors:
            # Show the first-field error as a flash summary; field-level errors
            # are rendered inline by the template using the `errors` dict.
            flash('Please correct the errors below and try again.', 'danger')
            return render_template(
                'patient/register.html',
                departments=departments,
                errors=errors,
                form=form_data,       # repopulate the form
            )

        # ── All inputs are valid — normalize and parse ───────────────────────
        name   = ValidationService.normalize_name(form_data['name'])
        age    = int(form_data['age'])
        gender = form_data['gender'].strip()
        phone  = form_data['phone'].strip()
        dept_id = int(form_data['department_id'])
        reg_type = form_data['registration_type'].strip()
        priority = form_data['priority'].strip()

        appt_date = None
        appt_time = None
        if reg_type == 'Online':
            appt_date = datetime.strptime(form_data['appointment_date'], '%Y-%m-%d').date()
            appt_time = datetime.strptime(form_data['appointment_time'], '%H:%M').time()

        # ── Issue token ──────────────────────────────────────────────────────
        try:
            token = QueueService.register_patient_and_issue_token(
                name=name,
                age=age,
                gender=gender,
                phone=phone,
                department_id=dept_id,
                registration_type=reg_type,
                appointment_date=appt_date,
                appointment_time=appt_time,
                priority=priority,
            )
            flash(
                f'Registration successful! Your token is: {token.token_number}',
                'success'
            )
            return redirect(url_for('patient.view_token', token_number=token.token_number))
        except Exception as e:
            flash(f'Error issuing token: {str(e)}', 'danger')
            return render_template(
                'patient/register.html',
                departments=departments,
                errors={},
                form=form_data,
            )

    # GET — blank form
    return render_template(
        'patient/register.html',
        departments=departments,
        errors={},
        form={},
    )


@patient_bp.route('/token/<token_number>')
def view_token(token_number):
    token = QueueToken.query.filter_by(token_number=token_number).first_or_404()
    qr_image_data = QRService.generate_qr_base64(token.qr_code_hash)

    queue = QueueService.get_department_queue(token.department_id)
    position = None
    for idx, t in enumerate(queue):
        if t.id == token.id:
            position = idx + 1
            break

    return render_template(
        'patient/token_view.html',
        token=token,
        qr_image_data=qr_image_data,
        position=position,
    )


@patient_bp.route('/status')
def status():
    departments = Department.query.all()
    selected_dept_id = request.args.get('dept_id', type=int)

    selected_dept = None
    queue = []

    if selected_dept_id:
        selected_dept = db.session.get(Department, selected_dept_id)
        if selected_dept:
            queue = QueueService.get_department_queue(selected_dept_id)

    return render_template(
        'patient/status.html',
        departments=departments,
        selected_dept=selected_dept,
        queue=queue,
        now_ts=_time_module.time(),
    )
