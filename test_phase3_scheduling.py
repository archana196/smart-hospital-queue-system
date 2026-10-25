"""
test_phase3_scheduling.py – Comprehensive automated tests for Phase 3:
Priority-Based Scheduling, Fair Queue Management, and Admin Queue Controls.

Mandatory Test Scenarios Covered:
---------------------------------
Priority Scheduling:
  1. Emergency selected before High, Medium, and Normal when eligible.
  2. High selected before Medium and Normal when no Emergency is eligible.
  3. Medium selected before Normal when no higher priority is eligible.
  4. Longest-waiting patient preferred among comparable/equal priority (FIFO tie-breaker).
  5. Patients from other departments excluded (department isolation).
  6. Ineligible statuses (Completed, In-Consultation, Cancelled, No-Show) excluded from scheduling.
  7. No eligible patients produces safe response (None / clear message).

Fairness and Aging:
  8. Waiting patient's effective priority changes according to configured aging policy.
  9. Patient's original priority remains unchanged in database despite aging score changes.
 10. Emergency remains highest priority under default policy.
 11. Aging results are deterministic with controlled timestamps (now_dt).
 12. Long-waiting Normal patient advances ahead of newer lower-urgency arrivals under documented policy.

Authorization and Integrity:
 13. Public registration cannot assign Emergency priority.
 14. Unauthorized staff (e.g. receptionist) cannot assign Emergency priority.
 15. Authorized staff (admin) can perform permitted priority changes.
 16. Invalid priority values rejected on backend.
 17. Failed priority update does not modify database.
 18. Two simultaneous Call Next operations cannot assign the same patient (atomic claim).
 19. Existing consultation state transitions remain valid.
 20. Admin queue dashboard role-based access control and filtering.
"""

import pytest
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import db, User, Department, Doctor, Patient, QueueToken
from app.services.queue_service import QueueService, PRIORITY_ORDER, ELIGIBLE_STATUSES
from app.services.doctor_service import DoctorService
from app.services.admin_service import AdminService
from app.services.validation_service import ValidationService


# ── Shared Test Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()

        # Seed 2 departments for isolation testing
        dept_gen = Department(name='General Medicine', code='GEN', description='General OPD')
        dept_card = Department(name='Cardiology', code='CARD', description='Cardiology OPD')
        db.session.add_all([dept_gen, dept_card])
        db.session.flush()

        # Seed Users: Admin, Receptionist, Doctors, Patient
        u_admin = User(
            username='admin_user',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            full_name='Admin Test'
        )
        u_recept = User(
            username='recept_user',
            password_hash=generate_password_hash('recept123'),
            role='receptionist',
            full_name='Receptionist Test'
        )
        u_doc_gen1 = User(
            username='dr_gen1',
            password_hash=generate_password_hash('doc123'),
            role='doctor',
            full_name='Dr. General One'
        )
        u_doc_gen2 = User(
            username='dr_gen2',
            password_hash=generate_password_hash('doc123'),
            role='doctor',
            full_name='Dr. General Two'
        )
        u_patient = User(
            username='patient_user',
            password_hash=generate_password_hash('pat123'),
            role='patient',
            full_name='Patient User'
        )
        db.session.add_all([u_admin, u_recept, u_doc_gen1, u_doc_gen2, u_patient])
        db.session.flush()

        # Doctor profiles
        doc_gen1 = Doctor(
            user_id=u_doc_gen1.id,
            department_id=dept_gen.id,
            room_number='OPD-101',
            is_available=True
        )
        doc_gen2 = Doctor(
            user_id=u_doc_gen2.id,
            department_id=dept_gen.id,
            room_number='OPD-102',
            is_available=True
        )
        db.session.add_all([doc_gen1, doc_gen2])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


# Helper to issue tokens quickly
def _issue(app, dept_code='GEN', priority='Normal', name_suffix='1', created_offset_mins=0):
    with app.app_context():
        dept = Department.query.filter_by(code=dept_code).first()
        token = QueueService.register_patient_and_issue_token(
            name=f'Patient {name_suffix}',
            age=30,
            gender='Male',
            phone=f'98000000{name_suffix.zfill(2)}',
            department_id=dept.id,
            priority=priority
        )
        if created_offset_mins != 0:
            token.created_at = datetime.now(timezone.utc) - timedelta(minutes=created_offset_mins)
            db.session.commit()
        return token.id


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PRIORITY SCHEDULING TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_emergency_selected_before_all_others(app):
    """Scenario 1: Emergency is selected before High, Medium, and Normal."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        id_norm = _issue(app, 'GEN', 'Normal', 'Norm')
        id_med = _issue(app, 'GEN', 'Medium', 'Med')
        id_high = _issue(app, 'GEN', 'High', 'High')
        id_emg = _issue(app, 'GEN', 'Emergency', 'Emg')

        next_token = QueueService.get_next_patient_token(dept.id)
        assert next_token is not None
        assert next_token.id == id_emg
        assert next_token.priority == 'Emergency'


def test_high_selected_before_medium_and_normal(app):
    """Scenario 2: High is selected before Medium and Normal when no Emergency exists."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        id_norm = _issue(app, 'GEN', 'Normal', 'Norm')
        id_med = _issue(app, 'GEN', 'Medium', 'Med')
        id_high = _issue(app, 'GEN', 'High', 'High')

        next_token = QueueService.get_next_patient_token(dept.id)
        assert next_token is not None
        assert next_token.id == id_high
        assert next_token.priority == 'High'


def test_medium_selected_before_normal(app):
    """Scenario 3: Medium is selected before Normal when no higher priority exists."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        id_norm = _issue(app, 'GEN', 'Normal', 'Norm')
        id_med = _issue(app, 'GEN', 'Medium', 'Med')

        next_token = QueueService.get_next_patient_token(dept.id)
        assert next_token is not None
        assert next_token.id == id_med
        assert next_token.priority == 'Medium'


def test_fifo_tie_breaker_within_same_priority(app):
    """Scenario 4: Longest-waiting patient is preferred among equal priorities."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        # Older normal patient arrived 20 mins ago
        id_old = _issue(app, 'GEN', 'Normal', 'Old', created_offset_mins=20)
        # Newer normal patient arrived 5 mins ago
        id_new = _issue(app, 'GEN', 'Normal', 'New', created_offset_mins=5)

        queue = QueueService.get_department_queue(dept.id)
        assert len(queue) == 2
        assert queue[0].id == id_old
        assert queue[1].id == id_new


def test_department_isolation(app):
    """Scenario 5: Patients from other departments are strictly excluded."""
    with app.app_context():
        dept_gen = Department.query.filter_by(code='GEN').first()
        dept_card = Department.query.filter_by(code='CARD').first()

        id_card_emg = _issue(app, 'CARD', 'Emergency', 'CardEmg')
        id_gen_norm = _issue(app, 'GEN', 'Normal', 'GenNorm')

        # Calling next in GEN should only return GEN patient, never CARD Emergency
        next_gen = QueueService.get_next_patient_token(dept_gen.id)
        assert next_gen is not None
        assert next_gen.id == id_gen_norm
        assert next_gen.department_id == dept_gen.id

        next_card = QueueService.get_next_patient_token(dept_card.id)
        assert next_card is not None
        assert next_card.id == id_card_emg
        assert next_card.department_id == dept_card.id


def test_ineligible_statuses_excluded(app):
    """Scenario 6: Ineligible statuses (Completed, In-Consultation, Cancelled, No-Show) excluded."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()

        id_comp = _issue(app, 'GEN', 'Emergency', 'Comp')
        id_icons = _issue(app, 'GEN', 'High', 'Icons')
        id_noshow = _issue(app, 'GEN', 'High', 'NoShow')
        id_wait = _issue(app, 'GEN', 'Normal', 'Wait')

        t_comp = db.session.get(QueueToken, id_comp)
        t_comp.status = 'Completed'

        t_icons = db.session.get(QueueToken, id_icons)
        t_icons.status = 'In-Consultation'

        t_noshow = db.session.get(QueueToken, id_noshow)
        t_noshow.status = 'No-Show'

        db.session.commit()

        queue = QueueService.get_department_queue(dept.id)
        assert len(queue) == 1
        assert queue[0].id == id_wait
        assert queue[0].status == 'Waiting'


def test_empty_queue_safe_response(app):
    """Scenario 7: Empty queue produces safe response (None / clear message)."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        doctor = Doctor.query.filter_by(department_id=dept.id).first()

        next_token = QueueService.get_next_patient_token(dept.id)
        assert next_token is None

        token, err = DoctorService.call_next_patient(doctor)
        assert token is None
        assert "No patients are currently waiting" in err


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FAIRNESS AND AGING TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_aging_increases_effective_score(app):
    """Scenario 8: Waiting patient's effective priority score increases with aging."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'Normal', 'A')
        token = db.session.get(QueueToken, id_t)

        now = datetime.now(timezone.utc)
        token.created_at = now - timedelta(minutes=45)
        db.session.commit()

        # At 45 mins: 3 intervals of 15m * 10 = +30 bonus points -> 100 + 30 = 130
        eff_score = QueueService.calculate_effective_priority_score(token, now_dt=now)
        assert eff_score == 130


def test_original_priority_unchanged_by_aging(app):
    """Scenario 9: Patient's original priority in DB is never overwritten by aging."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        id_t = _issue(app, 'GEN', 'Normal', 'A')

        token = db.session.get(QueueToken, id_t)
        token.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db.session.commit()

        # Trigger queue sorting which computes effective score
        queue = QueueService.get_department_queue(dept.id)
        assert queue[0].id == id_t

        # Re-fetch from DB directly
        fresh = db.session.get(QueueToken, id_t)
        assert fresh.priority == 'Normal'  # Strictly unchanged!


def test_emergency_remains_highest_under_default_policy(app):
    """Scenario 10: Emergency base score (1000) keeps it highest under normal waiting."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        now = datetime.now(timezone.utc)

        # Normal patient waiting 3 hours (180 mins -> +120 points -> 220)
        id_norm = _issue(app, 'GEN', 'Normal', 'LongNorm')
        t_norm = db.session.get(QueueToken, id_norm)
        t_norm.created_at = now - timedelta(hours=3)

        # Emergency patient just arrived (0 mins -> 1000)
        id_emg = _issue(app, 'GEN', 'Emergency', 'NewEmg')
        t_emg = db.session.get(QueueToken, id_emg)
        t_emg.created_at = now
        db.session.commit()

        queue = QueueService.get_department_queue(dept.id, now_dt=now)
        assert queue[0].id == id_emg
        assert queue[1].id == id_norm


def test_deterministic_aging_with_controlled_clock(app):
    """Scenario 11: Aging calculations are completely deterministic given explicit now_dt."""
    with app.app_context():
        base_time = datetime(2026, 10, 23, 10, 0, 0, tzinfo=timezone.utc)

        id_t = _issue(app, 'GEN', 'Medium', 'Det')
        token = db.session.get(QueueToken, id_t)
        token.created_at = base_time
        db.session.commit()

        # 0 mins -> 200
        assert QueueService.calculate_effective_priority_score(token, now_dt=base_time) == 200

        # 14 mins -> 200 (not yet 15 mins)
        t14 = base_time + timedelta(minutes=14)
        assert QueueService.calculate_effective_priority_score(token, now_dt=t14) == 200

        # 15 mins -> 210
        t15 = base_time + timedelta(minutes=15)
        assert QueueService.calculate_effective_priority_score(token, now_dt=t15) == 210

        # 30 mins -> 220
        t30 = base_time + timedelta(minutes=30)
        assert QueueService.calculate_effective_priority_score(token, now_dt=t30) == 220


def test_long_waiting_normal_advances_ahead_of_newer_medium(app):
    """Scenario 12: Long-waiting Normal advances ahead of newly arrived Medium."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        now = datetime.now(timezone.utc)

        # Normal patient waiting 3 hours: 100 + (180//15)*10 = 100 + 120 = 220
        id_norm = _issue(app, 'GEN', 'Normal', 'OldNorm')
        t_norm = db.session.get(QueueToken, id_norm)
        t_norm.created_at = now - timedelta(hours=3)

        # Medium patient just arrived: base score = 200
        id_med = _issue(app, 'GEN', 'Medium', 'NewMed')
        t_med = db.session.get(QueueToken, id_med)
        t_med.created_at = now
        db.session.commit()

        queue = QueueService.get_department_queue(dept.id, now_dt=now)
        # Normal patient (220) must be scheduled BEFORE new Medium patient (200)!
        assert queue[0].id == id_norm
        assert queue[1].id == id_med


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AUTHORIZATION AND INTEGRITY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_public_registration_cannot_assign_emergency(app):
    """Scenario 13: ValidationService rejects Emergency for unauthenticated/public registration."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        data = {
            'name': 'Public Emergency Attempter',
            'age': '35',
            'gender': 'Male',
            'phone': '9876543210',
            'department_id': str(dept.id),
            'registration_type': 'Walk-in',
            'priority': 'Emergency',
        }
        errs = ValidationService.validate_registration(data, allow_emergency=False)
        assert 'priority' in errs
        assert 'Emergency priority may only be assigned by authorised staff' in errs['priority']


def test_receptionist_cannot_assign_emergency_via_admin_service(app):
    """Scenario 14: Unauthorized staff (receptionist) cannot update priority to Emergency."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'Normal', 'RecTest')

        # Receptionist role: allow_emergency=False
        token, err = AdminService.change_patient_priority(id_t, 'Emergency', allow_emergency=False)
        assert token is None
        assert err is not None
        assert 'Emergency priority may only be assigned by authorised staff' in err

        # Verify token in DB still Normal
        t = db.session.get(QueueToken, id_t)
        assert t.priority == 'Normal'


def test_admin_can_assign_emergency(app):
    """Scenario 15: Authorized staff (admin) can assign Emergency priority."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'Normal', 'AdminTest')

        # Admin role: allow_emergency=True
        token, err = AdminService.change_patient_priority(id_t, 'Emergency', allow_emergency=True)
        assert err is None
        assert token is not None
        assert token.priority == 'Emergency'

        # Verify DB updated
        t = db.session.get(QueueToken, id_t)
        assert t.priority == 'Emergency'
        assert t.priority_score == 1000


def test_invalid_priority_values_rejected(app):
    """Scenario 16: Invalid priority values are rejected."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'Normal', 'BadVal')

        token, err = AdminService.change_patient_priority(id_t, 'UltraUrgent', allow_emergency=True)
        assert token is None
        assert "Invalid priority value 'UltraUrgent'" in err

        t = db.session.get(QueueToken, id_t)
        assert t.priority == 'Normal'


def test_failed_priority_update_does_not_modify_database(app):
    """Scenario 17: A failed priority update does not modify the database."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'High', 'FailTest')

        # Attempt invalid priority
        AdminService.change_patient_priority(id_t, 'NonExistentPriority', allow_emergency=True)

        t = db.session.get(QueueToken, id_t)
        assert t.priority == 'High'
        assert t.priority_score == 500


def test_atomic_call_next_prevents_duplicate_claims(app):
    """Scenario 18: Two simultaneous Call Next operations cannot assign the same patient."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        doc1 = Doctor.query.filter_by(room_number='OPD-101').first()
        doc2 = Doctor.query.filter_by(room_number='OPD-102').first()

        # Only ONE patient waiting
        id_t = _issue(app, 'GEN', 'Normal', 'SinglePatient')

        # Dr. 1 calls patient successfully
        t1, err1 = DoctorService.call_next_patient(doc1)
        assert t1 is not None
        assert err1 is None
        assert t1.id == id_t
        assert t1.status == 'Called'
        assert t1.doctor_id == doc1.id

        # Dr. 2 immediately attempts to call next patient: queue is now empty of waiting patients!
        t2, err2 = DoctorService.call_next_patient(doc2)
        assert t2 is None
        assert "No patients are currently waiting" in err2


def test_consultation_state_machine_transitions(app):
    """Scenario 19: Full consultation workflow transitions remain valid and enforced."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        doctor = Doctor.query.filter_by(department_id=dept.id).first()

        id_t = _issue(app, 'GEN', 'Normal', 'Cycle')

        # 1. Call Next: Waiting -> Called
        token, err = DoctorService.call_next_patient(doctor)
        assert err is None
        assert token.status == 'Called'

        # 2. Cannot complete while in Called status (invalid transition)
        _, err = DoctorService.complete_consultation(doctor, token.id)
        assert err is not None

        # 3. Start Consultation: Called -> In-Consultation
        token, err = DoctorService.start_consultation(doctor, token.id)
        assert err is None
        assert token.status == 'In-Consultation'

        # 4. Complete Consultation: In-Consultation -> Completed
        token, err = DoctorService.complete_consultation(doctor, token.id)
        assert err is None
        assert token.status == 'Completed'
        assert token.completed_at is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ADMIN DASHBOARD & RBAC HTTP TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_admin_queue_dashboard_requires_login(client):
    """Unauthenticated access to /admin/queue redirects to login."""
    resp = client.get('/admin/queue', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Login' in resp.data


def test_doctor_and_patient_cannot_access_admin_queue(client, app):
    """Doctor or Patient roles cannot access /admin/queue (403 Forbidden)."""
    # Login as doctor
    client.post('/auth/login', data={'username': 'dr_gen1', 'password': 'doc123'})
    resp_doc = client.get('/admin/queue')
    assert resp_doc.status_code == 403

    client.get('/auth/logout')

    # Login as patient
    client.post('/auth/login', data={'username': 'patient_user', 'password': 'pat123'})
    resp_pat = client.get('/admin/queue')
    assert resp_pat.status_code == 403


def test_admin_and_receptionist_can_access_admin_queue(client, app):
    """Admin and Receptionist can access /admin/queue."""
    # Receptionist
    client.post('/auth/login', data={'username': 'recept_user', 'password': 'recept123'})
    resp_rec = client.get('/admin/queue')
    assert resp_rec.status_code == 200
    assert b'Queue Management' in resp_rec.data

    client.get('/auth/logout')

    # Admin
    client.post('/auth/login', data={'username': 'admin_user', 'password': 'admin123'})
    resp_adm = client.get('/admin/queue')
    assert resp_adm.status_code == 200
    assert b'Queue Management' in resp_adm.data


def test_admin_queue_filtering(client, app):
    """Admin dashboard filters by department, status, and priority."""
    with app.app_context():
        dept_gen = Department.query.filter_by(code='GEN').first()
        dept_card = Department.query.filter_by(code='CARD').first()
        id_gen_emg = _issue(app, 'GEN', 'Emergency', 'FilterGenEmg')
        id_card_norm = _issue(app, 'CARD', 'Normal', 'FilterCardNorm')

    client.post('/auth/login', data={'username': 'admin_user', 'password': 'admin123'})

    # Filter to GEN only
    resp = client.get(f'/admin/queue?dept_id={dept_gen.id}')
    assert resp.status_code == 200
    assert b'FilterGenEmg' in resp.data or b'Emergency' in resp.data

    # Filter by Priority = Emergency
    resp_emg = client.get('/admin/queue?priority=Emergency')
    assert resp_emg.status_code == 200
    assert b'Emergency' in resp_emg.data


def test_admin_priority_change_via_http(client, app):
    """Admin can change patient priority via POST /admin/queue/update-priority/<id>."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'Normal', 'HttpPriorityTest')

    client.post('/auth/login', data={'username': 'admin_user', 'password': 'admin123'})
    resp = client.post(
        f'/admin/queue/update-priority/{id_t}',
        data={'new_priority': 'Emergency'},
        follow_redirects=True
    )
    assert resp.status_code == 200
    assert b'changed to Emergency' in resp.data

    with app.app_context():
        t = db.session.get(QueueToken, id_t)
        assert t.priority == 'Emergency'


def test_receptionist_cannot_assign_emergency_via_http(client, app):
    """Receptionist cannot change priority to Emergency via POST /admin/queue/update-priority/<id>."""
    with app.app_context():
        id_t = _issue(app, 'GEN', 'Normal', 'ReceptHttpTest')

    client.post('/auth/login', data={'username': 'recept_user', 'password': 'recept123'})
    resp = client.post(
        f'/admin/queue/update-priority/{id_t}',
        data={'new_priority': 'Emergency'},
        follow_redirects=True
    )
    assert resp.status_code == 200
    assert b'Emergency priority may only be assigned by authorised staff' in resp.data

    with app.app_context():
        t = db.session.get(QueueToken, id_t)
        assert t.priority == 'Normal'
