"""
doctor_service.py – Doctor dashboard business logic.

Responsible for all queue-state transitions invoked by a doctor:
  Waiting / Checked-In  →  Called
  Called                →  In-Consultation
  In-Consultation       →  Completed
  Called                →  Waiting   (No-Show: patient returned to queue)
  Called                →  No-Show   (if policy is to permanently remove)

This module does NOT decide who comes next (that is QueueService's job)
and does NOT call the ML predictor (that is MLService's job in Phase 4).
"""

from datetime import datetime, timezone
from app.models import db, QueueToken, Doctor, QueueCallEvent
from app.services.queue_service import QueueService

# ── Valid status transitions ────────────────────────────────────────────────
# Format: current_status → list of allowed target statuses
VALID_TRANSITIONS = {
    'Waiting':         ['Called'],
    'Checked-In':      ['Called'],
    'Called':          ['In-Consultation', 'Waiting', 'No-Show'],
    'In-Consultation': ['Completed'],
    # Terminal statuses — no further transitions allowed
    'Completed':  [],
    'No-Show':    [],
    'Cancelled':  [],
}


class DoctorService:

    @staticmethod
    def get_doctor_for_user(user_id):
        """Return the Doctor profile linked to the given user_id, or None."""
        return Doctor.query.filter_by(user_id=user_id).first()

    @staticmethod
    def get_current_consultation(doctor_id):
        """Return the single token currently In-Consultation for this doctor."""
        return QueueToken.query.filter_by(
            doctor_id=doctor_id,
            status='In-Consultation'
        ).first()

    @staticmethod
    def get_called_token(doctor_id):
        """Return the single token currently in Called state for this doctor."""
        return QueueToken.query.filter_by(
            doctor_id=doctor_id,
            status='Called'
        ).first()

    @classmethod
    def call_next_patient(cls, doctor):
        """
        Picks the next waiting patient via the Queue Engine and transitions
        their token to 'Called'.  Returns (token, error_message).

        Guards:
        - Doctor must be marked available.
        - No other patient may already be in Called or In-Consultation state
          for this doctor (prevents double-calling).
        """
        if not doctor.is_available:
            return None, "You are currently marked as unavailable."

        # Prevent calling a second patient while one is already active
        if cls.get_current_consultation(doctor.id):
            return None, "You already have a patient in consultation. Complete it first."
        if cls.get_called_token(doctor.id):
            return None, "A patient has already been called. Start their consultation first."

        next_token = QueueService.get_next_patient_token(doctor.department_id, doctor.id)
        if not next_token:
            return None, "No patients are currently waiting in your department."

        # Validate the transition atomically in the same session
        allowed = VALID_TRANSITIONS.get(next_token.status, [])
        if 'Called' not in allowed:
            return None, f"Token {next_token.token_number} cannot be called from status '{next_token.status}'."

        # Atomically claim the patient so two concurrent requests cannot call the same patient
        call_time = datetime.now(timezone.utc)
        updated_rows = QueueToken.query.filter(
            QueueToken.id == next_token.id,
            QueueToken.status.in_(['Waiting', 'Checked-In'])
        ).update({
            'status': 'Called',
            'doctor_id': doctor.id,
            'called_at': call_time
        }, synchronize_session='fetch')

        if updated_rows == 0:
            db.session.rollback()
            return None, "Patient was already claimed by another doctor. Please try again."

        # Create persistent call event for IoT edge devices and live displays
        call_event = QueueCallEvent(
            department_id=doctor.department_id,
            doctor_id=doctor.id,
            token_id=next_token.id,
            token_number=next_token.token_number,
            called_at=call_time
        )
        db.session.add(call_event)

        db.session.commit()
        db.session.refresh(next_token)
        return next_token, None

    @classmethod
    def start_consultation(cls, doctor, token_id):
        """
        Transitions a Called token to In-Consultation.
        Returns (token, error_message).
        """
        token = db.session.get(QueueToken, token_id)
        if token is None:
            return None, "Token not found."
        if token.doctor_id != doctor.id:
            return None, "This token does not belong to your queue."

        allowed = VALID_TRANSITIONS.get(token.status, [])
        if 'In-Consultation' not in allowed:
            return None, f"Cannot start consultation for token in status '{token.status}'."

        token.status = 'In-Consultation'
        token.consultation_started_at = datetime.now(timezone.utc)
        db.session.commit()
        return token, None

    @classmethod
    def complete_consultation(cls, doctor, token_id):
        """
        Transitions an In-Consultation token to Completed.
        Returns (token, error_message).
        """
        token = db.session.get(QueueToken, token_id)
        if token is None:
            return None, "Token not found."
        if token.doctor_id != doctor.id:
            return None, "This token does not belong to your queue."

        allowed = VALID_TRANSITIONS.get(token.status, [])
        if 'Completed' not in allowed:
            return None, f"Cannot complete token in status '{token.status}'."

        token.status = 'Completed'
        token.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return token, None

    @classmethod
    def handle_no_show(cls, doctor, token_id, action='No-Show'):
        """
        Handles a no-show patient.
        action='No-Show'  → permanently removes patient from today's queue.
        action='Waiting'  → returns patient to the waiting queue.
        Returns (token, error_message).
        """
        if action not in ('No-Show', 'Waiting'):
            return None, "Invalid no-show action."

        token = db.session.get(QueueToken, token_id)
        if token is None:
            return None, "Token not found."
        if token.doctor_id != doctor.id:
            return None, "This token does not belong to your queue."

        allowed = VALID_TRANSITIONS.get(token.status, [])
        if action not in allowed:
            return None, f"Cannot transition token from '{token.status}' to '{action}'."

        token.status = action
        # If returning to queue, clear the called_at timestamp so aging restarts fairly
        if action == 'Waiting':
            token.doctor_id = None
        db.session.commit()
        return token, None

    @staticmethod
    def toggle_availability(doctor):
        """Toggles doctor available ↔ unavailable. Returns updated doctor."""
        doctor.is_available = not doctor.is_available
        db.session.commit()
        return doctor
