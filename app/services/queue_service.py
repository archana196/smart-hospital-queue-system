"""
queue_service.py – Core Queue Engine.

RESPONSIBILITY:
  - Token generation (patient code, token number, secure QR hash)
  - Patient registration and token issuance
  - Priority scoring with configurable aging/fairness mechanism
  - Determining which eligible patient is next (get_next_patient_token)
  - Updating a patient's priority (authorized callers only)

STRICT SEPARATION:
  - This service does NOT decide ML waiting-time predictions (Phase 4).
  - This service does NOT enforce doctor-level consultation guards
    (that is DoctorService's responsibility).

═══════════════════════════════════════════════════════════════
AGING / FAIRNESS ALGORITHM  (documented here, single source of truth)
═══════════════════════════════════════════════════════════════

Priority base scores (from config.py PRIORITY_SCORES):
  Emergency : 1000
  High      :  500
  Medium    :  200
  Normal    :  100

Aging rule:
  Every AGING_INTERVAL_MINS minutes a patient waits, they earn
  AGING_BONUS_POINTS added to their effective scheduling score.

  effective_score = base_score + floor(minutes_waited / AGING_INTERVAL_MINS)
                                 * AGING_BONUS_POINTS

Default values (config.py):
  AGING_INTERVAL_MINS = 15  minutes
  AGING_BONUS_POINTS  = 10  points per interval

Example:
  A Normal patient (base 100) who has waited 45 minutes:
    effective_score = 100 + (45 // 15) * 10 = 100 + 30 = 130

  A High patient (base 500) who just arrived:
    effective_score = 500

  → Normal patient (130) < High patient (500), so High is still first.
  → Normal patient after ~60 hours of waiting: 100 + 240*10 = 2500
    → This would exceed High (500) but never exceeds Emergency (1000)
    unless waiting > (1000 - 100) / 10 * 15 minutes = 1350 minutes ≈ 22.5 hours.

SAFETY NOTE ON EMERGENCY:
  Emergency's base score of 1000 means a Normal patient would need to wait
  ≈ 22.5 hours before aging raises their score above Emergency's BASE score.
  This is an intentional safety default. Emergency patients ALWAYS take precedence
  in any realistic hospital scenario.

  LIMITATION: If Emergency patients arrive continuously and without gap,
  Normal-priority patients could theoretically be postponed beyond 22.5 hours
  before aging would mathematically push them above the Emergency base score.
  In practice, Emergency queues are managed by clinical staff who would
  intervene. The aging mechanism prevents starvation under normal mixed-priority
  workloads.

  The original priority stored in the database is NEVER modified by aging.
  Aging only affects the in-memory scheduling score used by get_department_queue.
═══════════════════════════════════════════════════════════════
"""

from datetime import datetime, timezone
from flask import current_app
from app.models import db, Department, Patient, QueueToken
from app.services.qr_service import QRService

# Canonical priority order (highest → lowest) used for display/validation
PRIORITY_ORDER = ['Emergency', 'High', 'Medium', 'Normal']

# Default base scores (overridden by config.py values at runtime)
_DEFAULT_PRIORITY_SCORES = {
    'Emergency': 1000,
    'High':       500,
    'Medium':     200,
    'Normal':     100,
}

# Terminal statuses — never eligible for scheduling
TERMINAL_STATUSES = {'Completed', 'No-Show', 'Cancelled'}

# Statuses eligible to be called next
ELIGIBLE_STATUSES = {'Waiting', 'Checked-In'}


def _priority_scores():
    """Return priority base scores from app config, falling back to defaults."""
    try:
        return current_app.config.get('PRIORITY_SCORES', _DEFAULT_PRIORITY_SCORES)
    except RuntimeError:
        return _DEFAULT_PRIORITY_SCORES


def _aging_config():
    """Return (interval_mins, bonus_points) from app config."""
    try:
        interval = current_app.config.get('AGING_INTERVAL_MINS', 15)
        bonus    = current_app.config.get('AGING_BONUS_POINTS',  10)
    except RuntimeError:
        interval, bonus = 15, 10
    return interval, bonus


class QueueService:
    """
    Core Queue Engine Service.

    Decides patient priority order, generates tokens, calculates aging scores,
    and determines which waiting patient is called next.

    Does NOT call the ML predictor (that is MLService's responsibility in Phase 4).
    """

    # ── Token / code generation ──────────────────────────────────────────────

    @staticmethod
    def generate_patient_code():
        """Generates sequential patient ID code like PAT-YYYYMMDD-0001."""
        today_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        prefix = f"PAT-{today_str}-"

        last_patient = Patient.query.filter(
            Patient.patient_code.like(f"{prefix}%")
        ).order_by(Patient.id.desc()).first()

        new_seq = (int(last_patient.patient_code.split('-')[-1]) + 1) if last_patient else 1
        return f"{prefix}{new_seq:04d}"

    @staticmethod
    def generate_token_number(department_id):
        """Generates sequential departmental token like GEN-YYYYMMDD-001."""
        dept = db.session.get(Department, department_id)
        if not dept:
            raise ValueError("Department not found")

        today_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        prefix = f"{dept.code}-{today_str}-"

        last_token = QueueToken.query.filter(
            QueueToken.department_id == department_id,
            QueueToken.token_number.like(f"{prefix}%")
        ).order_by(QueueToken.id.desc()).first()

        new_seq = (int(last_token.token_number.split('-')[-1]) + 1) if last_token else 1
        return f"{prefix}{new_seq:03d}"

    # ── Scoring / aging ──────────────────────────────────────────────────────

    @staticmethod
    def calculate_effective_priority_score(token, now_dt=None):
        """
        Calculate the effective scheduling score for a token.

        Parameters
        ----------
        token   : QueueToken
        now_dt  : datetime | None
            Reference time. Pass an explicit datetime (timezone-aware or naive,
            matching token.created_at) to make tests deterministic.
            Defaults to datetime.utcnow() for backward compatibility with
            existing tests that use naive datetimes.

        Returns
        -------
        int  – effective score (higher = called sooner)

        The patient's database priority field is NEVER modified.
        """
        scores = _priority_scores()
        base_score = scores.get(token.priority, scores.get('Normal', 100))

        if token.status in ELIGIBLE_STATUSES and token.created_at:
            created_at_dt = token.created_at
            if now_dt is None:
                if created_at_dt.tzinfo is None:
                    ref_now = datetime.utcnow()
                else:
                    ref_now = datetime.now(timezone.utc)
            else:
                ref_now = now_dt
                if created_at_dt.tzinfo is None and ref_now.tzinfo is not None:
                    ref_now = ref_now.astimezone(timezone.utc).replace(tzinfo=None)
                elif created_at_dt.tzinfo is not None and ref_now.tzinfo is None:
                    ref_now = ref_now.replace(tzinfo=timezone.utc)

            mins_waited = (ref_now - created_at_dt).total_seconds() / 60.0
            interval, bonus = _aging_config()
            aging_points = int(max(0.0, mins_waited) // interval) * bonus
            return base_score + aging_points

        # Non-eligible tokens: return stored score or base
        return token.priority_score if token.priority_score else base_score

    # ── Department queue (ordered) ───────────────────────────────────────────

    @classmethod
    def get_department_queue(cls, department_id, now_dt=None):
        """
        Return eligible waiting/checked-in tokens for a department,
        ordered strictly by the Queue Engine rules:

        1. Effective priority score  (descending — higher score first)
        2. created_at               (ascending  — longer wait first within same score)

        Parameters
        ----------
        department_id : int
        now_dt        : datetime | None – for deterministic testing

        Returns
        -------
        list[QueueToken]
        """
        tokens = QueueToken.query.filter(
            QueueToken.department_id == department_id,
            QueueToken.status.in_(ELIGIBLE_STATUSES)
        ).all()

        # Compute effective scores (in-memory only — DB not mutated)
        for t in tokens:
            t.priority_score = cls.calculate_effective_priority_score(t, now_dt=now_dt)

        # Sort: score DESC, created_at ASC (longest wait first as tie-breaker)
        def _sort_key(t):
            dt = t.created_at
            if dt is not None and dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return (-t.priority_score, dt or datetime.min)

        tokens.sort(key=_sort_key)
        return tokens

    @classmethod
    def get_next_patient_token(cls, department_id, doctor_id=None, now_dt=None):
        """
        Return the single best candidate for Call Next in the given department.

        Returns the top token from get_department_queue, or None.
        """
        queue = cls.get_department_queue(department_id, now_dt=now_dt)
        return queue[0] if queue else None

    # ── Patient registration ─────────────────────────────────────────────────

    @classmethod
    def register_patient_and_issue_token(
        cls, name, age, gender, phone, department_id,
        registration_type='Walk-in',
        appointment_date=None, appointment_time=None,
        priority='Normal'
    ):
        """
        Register/find a patient and issue a new queue token with secure non-PII QR code.

        Raises ValueError for invalid inputs (caller must handle).
        """
        # Validate priority against the canonical set
        if priority not in PRIORITY_ORDER:
            raise ValueError(f"Invalid priority '{priority}'. "
                             f"Must be one of: {', '.join(PRIORITY_ORDER)}")

        # Find or create patient record
        patient = Patient.query.filter_by(phone=phone, name=name).first()
        if not patient:
            patient = Patient(
                patient_code=cls.generate_patient_code(),
                name=name, age=age, gender=gender, phone=phone
            )
            db.session.add(patient)
            db.session.flush()

        # Appointment validation
        if registration_type == 'Online':
            if not appointment_date or not appointment_time:
                raise ValueError("Appointment Date and Time are required for Online registration.")
        else:
            appointment_date = None
            appointment_time = None

        scores = _priority_scores()
        base_priority_score = scores.get(priority, 100)
        token_number = cls.generate_token_number(department_id)
        secure_qr_hash = QRService.generate_secure_token_hash()

        token = QueueToken(
            token_number=token_number,
            patient_id=patient.id,
            department_id=department_id,
            registration_type=registration_type,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            priority=priority,
            priority_score=base_priority_score,
            status='Waiting',
            qr_code_hash=secure_qr_hash,
        )

        db.session.add(token)
        db.session.commit()
        return token

    # ── Priority management (staff-only) ─────────────────────────────────────

    @classmethod
    def update_token_priority(cls, token_id, new_priority, allow_emergency=False):
        """
        Update the priority of a waiting/checked-in token.

        Parameters
        ----------
        token_id       : int
        new_priority   : str  – must be in PRIORITY_ORDER
        allow_emergency: bool – True only for authorized staff roles

        Returns
        -------
        (QueueToken, None)    on success
        (None,       str)     on error — database is NOT modified

        Rules
        -----
        - Only Waiting or Checked-In tokens can be updated.
        - Emergency priority requires allow_emergency=True.
        - Invalid priority values are rejected.
        - Failures do NOT modify the token record.
        """
        if new_priority not in PRIORITY_ORDER:
            return None, f"Invalid priority value '{new_priority}'."

        if new_priority == 'Emergency' and not allow_emergency:
            return None, ("Emergency priority may only be assigned by authorised staff, "
                          "not through the public form.")

        token = db.session.get(QueueToken, token_id)
        if token is None:
            return None, "Token not found."

        if token.status not in ELIGIBLE_STATUSES:
            return None, (f"Priority can only be changed for Waiting or Checked-In patients. "
                          f"Current status: '{token.status}'.")

        scores = _priority_scores()
        token.priority = new_priority
        token.priority_score = scores.get(new_priority, 100)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return None, f"Database error: {str(e)}"

        return token, None

    # ── Utility helpers ──────────────────────────────────────────────────────

    @staticmethod
    def get_waiting_duration_mins(token, now_dt=None):
        """Return how many minutes the patient has been waiting (float)."""
        if not token.created_at:
            return 0.0
        created = token.created_at
        if now_dt is None:
            if created.tzinfo is None:
                ref_now = datetime.utcnow()
            else:
                ref_now = datetime.now(timezone.utc)
        else:
            ref_now = now_dt
            if created.tzinfo is None and ref_now.tzinfo is not None:
                ref_now = ref_now.astimezone(timezone.utc).replace(tzinfo=None)
            elif created.tzinfo is not None and ref_now.tzinfo is None:
                ref_now = ref_now.replace(tzinfo=timezone.utc)
        return max(0.0, (ref_now - created).total_seconds() / 60.0)
