"""
validation_service.py – Server-side input validation for patient registration.

All rules here are AUTHORITATIVE. Frontend validation is a convenience only;
any bypassed or malformed submission is rejected here before hitting the database.

Validation rules:
  - Name:       2–100 chars, letters + spaces + hyphens + apostrophes only.
  - Phone:      Exactly 10 digits (Indian mobile numbers).
  - Age:        Integer 1–120 (configurable via AGE_MIN / AGE_MAX).
  - Gender:     One of the allowed set defined by the application.
  - Department: Must be an integer ID that exists in the departments table.
  - Priority:   Public registrations restricted to Normal / Medium / High only.
                Emergency requires an authorised workflow (receptionist/admin).
  - Reg. type:  Walk-in or Online.
  - Appt date/time: Required (and must be valid) when type == 'Online'.
"""

import re
from datetime import datetime

from app.models import db, Department

# ── Constants ────────────────────────────────────────────────────────────────

NAME_MIN = 2
NAME_MAX = 100
AGE_MIN = 1
AGE_MAX = 120

ALLOWED_GENDERS = {'Male', 'Female', 'Other'}
ALLOWED_PRIORITIES = {'Normal', 'Medium', 'High', 'Emergency'}
# Priorities patients can self-select on the public form (Emergency is staff-only)
PUBLIC_ALLOWED_PRIORITIES = {'Normal', 'Medium', 'High'}
ALLOWED_REG_TYPES = {'Walk-in', 'Online'}

# Letters (Unicode), spaces, hyphens, apostrophes — nothing else
_NAME_RE = re.compile(r"^[\u0041-\u005A\u0061-\u007A\u00C0-\u024F\u0900-\u097F\u0980-\u09FF "
                      r"\u0A00-\u0A7F\u0B00-\u0B7F\u0C00-\u0C7F\u0D00-\u0D7F\s'\-]+$",
                      re.UNICODE)
# Simple readable alternative for Indian + Latin names
_NAME_SIMPLE_RE = re.compile(r"^[A-Za-z\u00C0-\u024F\u0900-\u097F\s'\-]+$", re.UNICODE)

# Exactly 10 digits
_PHONE_RE = re.compile(r"^\d{10}$")


# ── Public API ───────────────────────────────────────────────────────────────

class ValidationService:
    """
    Validate patient registration inputs.
    Returns a dict: { field_name: error_message }.
    Empty dict means all inputs are valid.
    """

    @classmethod
    def validate_registration(cls, data: dict, allow_emergency: bool = False) -> dict:
        """
        Validate a patient registration payload.

        Parameters
        ----------
        data : dict
            Keys: name, age, gender, phone, department_id,
                  registration_type, priority,
                  appointment_date (str|None), appointment_time (str|None)
        allow_emergency : bool
            True only for staff-initiated registrations (receptionist/admin).

        Returns
        -------
        dict  – { field_name: "human-readable error" }
                Empty dict means valid.
        """
        errors = {}

        # ── Full Name ────────────────────────────────────────────────────────
        name = (data.get('name') or '').strip()
        if not name:
            errors['name'] = 'Full name is required.'
        elif len(name) < NAME_MIN:
            errors['name'] = f'Name must be at least {NAME_MIN} characters.'
        elif len(name) > NAME_MAX:
            errors['name'] = f'Name must not exceed {NAME_MAX} characters.'
        elif not _NAME_SIMPLE_RE.match(name):
            errors['name'] = ('Name may only contain letters, spaces, hyphens, '
                              'and apostrophes — no digits or special characters.')

        # ── Age ──────────────────────────────────────────────────────────────
        age_raw = data.get('age')
        age = None
        if age_raw is None or str(age_raw).strip() == '':
            errors['age'] = 'Age is required.'
        else:
            try:
                age = int(age_raw)
                if age < AGE_MIN or age > AGE_MAX:
                    errors['age'] = f'Age must be between {AGE_MIN} and {AGE_MAX}.'
            except (ValueError, TypeError):
                errors['age'] = 'Age must be a whole number.'

        # ── Gender ───────────────────────────────────────────────────────────
        gender = (data.get('gender') or '').strip()
        if not gender:
            errors['gender'] = 'Please select a gender.'
        elif gender not in ALLOWED_GENDERS:
            errors['gender'] = f'Gender must be one of: {", ".join(sorted(ALLOWED_GENDERS))}.'

        # ── Phone ────────────────────────────────────────────────────────────
        phone = (data.get('phone') or '').strip()
        if not phone:
            errors['phone'] = 'Phone number is required.'
        elif not _PHONE_RE.match(phone):
            errors['phone'] = ('Phone number must be exactly 10 digits '
                               '(Indian mobile number, e.g. 9876543210).')

        # ── Department ───────────────────────────────────────────────────────
        dept_id_raw = data.get('department_id')
        if dept_id_raw is None or str(dept_id_raw).strip() == '':
            errors['department_id'] = 'Please select a department.'
        else:
            try:
                dept_id = int(dept_id_raw)
                dept = db.session.get(Department, dept_id)
                if dept is None:
                    errors['department_id'] = 'Selected department does not exist.'
            except (ValueError, TypeError):
                errors['department_id'] = 'Invalid department selection.'

        # ── Registration Type ────────────────────────────────────────────────
        reg_type = (data.get('registration_type') or '').strip()
        if reg_type not in ALLOWED_REG_TYPES:
            errors['registration_type'] = 'Registration type must be Walk-in or Online.'

        # ── Priority ─────────────────────────────────────────────────────────
        priority = (data.get('priority') or 'Normal').strip()
        if priority not in ALLOWED_PRIORITIES:
            errors['priority'] = f'Invalid priority value.'
        elif priority == 'Emergency' and not allow_emergency:
            # Security rule: public form cannot self-assign Emergency.
            # Silently demote to High to avoid leaking information, OR reject.
            # We REJECT here so staff know their request was blocked.
            errors['priority'] = ('Emergency priority may only be assigned by '
                                  'authorised staff, not through the public form.')

        # ── Appointment date/time (required only for Online) ─────────────────
        if reg_type == 'Online' and 'registration_type' not in errors:
            appt_date_str = (data.get('appointment_date') or '').strip()
            appt_time_str = (data.get('appointment_time') or '').strip()
            if not appt_date_str:
                errors['appointment_date'] = 'Appointment date is required for Online registration.'
            else:
                try:
                    datetime.strptime(appt_date_str, '%Y-%m-%d')
                except ValueError:
                    errors['appointment_date'] = 'Invalid date format (expected YYYY-MM-DD).'

            if not appt_time_str:
                errors['appointment_time'] = 'Appointment time is required for Online registration.'
            else:
                try:
                    datetime.strptime(appt_time_str, '%H:%M')
                except ValueError:
                    errors['appointment_time'] = 'Invalid time format (expected HH:MM).'

        return errors

    @classmethod
    def normalize_name(cls, name: str) -> str:
        """Strip leading/trailing whitespace and collapse internal runs of spaces."""
        return ' '.join(name.strip().split())
