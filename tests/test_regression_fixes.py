"""
test_regression_fixes.py – Regression tests for post-audit fixes.

Covers:
  1. Public token API (/api/v1/token/<token>) must NOT expose patient_name,
     appointment_date, or appointment_time (PII privacy).
  2. Admin service get_filtered_queue sorts correctly using its datetime/timezone
     imports (regression for missing import bug).
  3. Auth role-based redirect: admin redirects to /admin/queue, not /.
  4. Receptionist login redirects to /admin/queue.
"""

import pytest
import json
from datetime import date, time
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import db, User, Department, Doctor, QueueToken, Patient
from app.services.queue_service import QueueService
from app.services.admin_service import AdminService


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()

        dept = Department(name='General Medicine', code='GEN', description='Test Dept')
        db.session.add(dept)
        db.session.flush()

        # Admin user
        admin_user = User(
            username='reg_admin',
            password_hash=generate_password_hash('adminpass'),
            role='admin',
            full_name='Admin Regression [SAMPLE DATA]',
        )
        # Receptionist user
        recept_user = User(
            username='reg_recept',
            password_hash=generate_password_hash('receptpass'),
            role='receptionist',
            full_name='Receptionist Regression [SAMPLE DATA]',
        )
        # Doctor user
        dr_user = User(
            username='reg_doctor',
            password_hash=generate_password_hash('docpass'),
            role='doctor',
            full_name='Dr. Regression [SAMPLE DATA]',
        )
        db.session.add_all([admin_user, recept_user, dr_user])
        db.session.flush()

        doctor = Doctor(
            user_id=dr_user.id,
            department_id=dept.id,
            room_number='R-01',
            is_available=True,
            avg_consultation_mins=10.0
        )
        db.session.add(doctor)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. API Privacy – token endpoint must NOT expose PII
# ═══════════════════════════════════════════════════════════════════════════════

def test_public_token_api_does_not_expose_patient_name(client, app):
    """
    Regression: /api/v1/token/<token_number> must NOT include 'patient_name' field.
    Full patient name is PII and must be omitted from the public unauthenticated API.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Privacy Test Patient',
            age=35,
            gender='Male',
            phone='9800000001',
            department_id=dept.id,
            priority='Normal',
        )
        token_num = token.token_number

    resp = client.get(f'/api/v1/token/{token_num}')
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))

    # These fields MUST NOT be present (PII exposure)
    assert 'patient_name' not in data, "FAIL: patient_name exposed in public token API"
    assert 'patient_phone' not in data, "FAIL: patient_phone exposed in public token API"

    # These non-PII fields MUST be present
    assert 'token_number' in data
    assert 'department' in data
    assert 'priority' in data
    assert 'status' in data
    assert 'waiting_duration_mins' in data


def test_public_token_api_does_not_expose_appointment_pii(client, app):
    """
    Regression: appointment_date and appointment_time must be omitted for online tokens.
    These fields contain scheduling PII that should not be exposed publicly.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Online Appointment Patient',
            age=40,
            gender='Female',
            phone='9800000002',
            department_id=dept.id,
            registration_type='Online',
            appointment_date=date(2026, 11, 1),
            appointment_time=time(10, 30),
            priority='High',
        )
        token_num = token.token_number

    resp = client.get(f'/api/v1/token/{token_num}')
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))

    # appointment_date and appointment_time must NOT appear
    assert 'appointment_date' not in data, "FAIL: appointment_date exposed in public token API"
    assert 'appointment_time' not in data, "FAIL: appointment_time exposed in public token API"


def test_public_token_api_returns_404_for_unknown_token(client):
    """Non-existent token returns 404."""
    resp = client.get('/api/v1/token/NONEXISTENT-TOKEN-000')
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AdminService.get_filtered_queue – datetime/timezone import regression
# ═══════════════════════════════════════════════════════════════════════════════

def test_admin_get_filtered_queue_sorts_without_error(app):
    """
    Regression: AdminService.get_filtered_queue() was using datetime and timezone
    without importing them. This should not raise a NameError.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        # Create two tokens with different priorities
        t1 = QueueService.register_patient_and_issue_token(
            name='Admin Sort Patient A',
            age=30,
            gender='Male',
            phone='9800000010',
            department_id=dept.id,
            priority='Normal',
        )
        t2 = QueueService.register_patient_and_issue_token(
            name='Admin Sort Patient B',
            age=50,
            gender='Female',
            phone='9800000011',
            department_id=dept.id,
            priority='High',
        )

        # This call should NOT raise NameError for datetime/timezone
        try:
            tokens = AdminService.get_filtered_queue()
            assert len(tokens) == 2
            # High priority should appear first
            assert tokens[0].priority == 'High'
        except NameError as e:
            pytest.fail(f"NameError in get_filtered_queue (missing import): {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Auth redirects by role
# ═══════════════════════════════════════════════════════════════════════════════

def test_admin_login_redirects_to_admin_queue(client, app):
    """Admin login should redirect to /admin/queue dashboard."""
    resp = client.post('/auth/login', data={
        'username': 'reg_admin',
        'password': 'adminpass',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/admin/queue' in resp.headers.get('Location', '')


def test_receptionist_login_redirects_to_admin_queue(client, app):
    """Receptionist login should redirect to /admin/queue dashboard."""
    resp = client.post('/auth/login', data={
        'username': 'reg_recept',
        'password': 'receptpass',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/admin/queue' in resp.headers.get('Location', '')


def test_doctor_login_redirects_to_doctor_dashboard(client, app):
    """Doctor login should redirect to /doctor/dashboard."""
    resp = client.post('/auth/login', data={
        'username': 'reg_doctor',
        'password': 'docpass',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/doctor/dashboard' in resp.headers.get('Location', '')


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Queue API still includes non-PII fields
# ═══════════════════════════════════════════════════════════════════════════════

def test_queue_api_contains_estimated_wait_and_waiting_duration(client, app):
    """
    /api/v1/queue/<dept_id> must include estimated_wait_mins and waiting_duration_mins
    for each token (advisory only – not altering queue order).
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        QueueService.register_patient_and_issue_token(
            name='API Queue Check Patient',
            age=28,
            gender='Other',
            phone='9800000020',
            department_id=dept.id,
            priority='Normal',
        )
        dept_id = dept.id

    resp = client.get(f'/api/v1/queue/{dept_id}')
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))

    assert 'tokens' in data
    assert len(data['tokens']) >= 1
    token_entry = data['tokens'][0]
    assert 'waiting_duration_mins' in token_entry
    assert 'estimated_wait_mins' in token_entry
    # token_number should be present (not PII)
    assert 'token_number' in token_entry
    # patient_name must NOT appear in the queue listing either
    assert 'patient_name' not in token_entry


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Dashboard UI – Estimated Waiting Time displayed, internal columns hidden
# ═══════════════════════════════════════════════════════════════════════════════

def test_patient_status_dashboard_shows_estimated_wait_and_hides_unneeded_columns(client, app):
    """
    Requirements:
    1. Display the existing Est. Additional Wait value clearly as Estimated Waiting Time in minutes.
    2. Hide Elapsed Wait, Eff. Score, and Registration Time columns from dashboard table.
    3. Keep Token Number, queue position (# Pos), Priority, Type, and Status.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        QueueService.register_patient_and_issue_token(
            name='Dashboard Check Patient',
            age=32,
            gender='Female',
            phone='9812345678',
            department_id=dept.id,
            priority='High',
        )
        dept_id = dept.id

    resp = client.get(f'/patient/status?dept_id={dept_id}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # 1. Estimated Waiting Time clearly labelled
    assert "Estimated Waiting Time" in html
    # 2. Hidden columns MUST NOT be present as table headers
    assert "<th>Elapsed Wait</th>" not in html
    assert "<th>Eff. Score</th>" not in html
    assert "<th>Registration Time</th>" not in html
    # 3. Retained columns MUST be present
    assert "# Pos" in html
    assert "Token Number" in html
    assert "Priority" in html
    assert "Type" in html
    assert "Status" in html


def test_doctor_dashboard_shows_estimated_wait_and_hides_unneeded_columns(client, app):
    """
    Verify doctor dashboard waiting queue table displays Estimated Waiting Time
    and hides Elapsed Wait, Eff. Score, and Registration Time (Registered At).
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        QueueService.register_patient_and_issue_token(
            name='Doctor View Patient',
            age=40,
            gender='Male',
            phone='9812345679',
            department_id=dept.id,
            priority='Normal',
        )

    # Login as doctor
    client.post('/auth/login', data={'username': 'reg_doctor', 'password': 'docpass'})
    resp = client.get('/doctor/dashboard')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Estimated Waiting Time" in html
    assert "<th>Elapsed Wait</th>" not in html
    assert "<th>Eff. Score</th>" not in html
    assert "<th>Registered At</th>" not in html
    assert "Token" in html
    assert "Priority" in html
    assert "Type" in html
    assert "Status" in html


def test_admin_queue_dashboard_shows_estimated_wait_and_hides_unneeded_columns(client, app):
    """
    Verify admin queue dashboard table displays Estimated Waiting Time
    and hides Elapsed Wait, Eff. Score, and Registration Time (Registered At).
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        QueueService.register_patient_and_issue_token(
            name='Admin View Patient',
            age=55,
            gender='Male',
            phone='9812345680',
            department_id=dept.id,
            priority='Medium',
        )

    # Login as admin
    client.post('/auth/login', data={'username': 'reg_admin', 'password': 'adminpass'})
    resp = client.get('/admin/queue')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Estimated Waiting Time" in html
    assert "<th>Elapsed Wait</th>" not in html
    assert "<th>Eff. Score</th>" not in html
    assert "<th>Registered At</th>" not in html
    assert "Token" in html
    assert "Original Priority" in html
    assert "Status" in html

