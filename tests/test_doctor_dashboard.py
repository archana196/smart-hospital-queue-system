"""
test_doctor_dashboard.py – Phase 2 tests for doctor dashboard actions.

Covers:
- Call Next Patient (Waiting → Called)
- Start Consultation (Called → In-Consultation)
- Complete Consultation (In-Consultation → Completed)
- No-Show (Called → No-Show)
- Return to Queue (Called → Waiting)
- Invalid transition prevention
- Concurrency guard (cannot call two patients at once)
"""
import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from app.models import db, User, Department, Doctor, QueueToken
from app.services.queue_service import QueueService
from app.services.doctor_service import DoctorService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()

        dept = Department(name='General Medicine', code='GEN', description='Test dept')
        db.session.add(dept)
        db.session.flush()

        dr_user = User(
            username='dash_doctor',
            password_hash=generate_password_hash('dashpass'),
            role='doctor',
            full_name='Dashboard Doctor [SAMPLE DATA]',
        )
        db.session.add(dr_user)
        db.session.flush()

        doctor = Doctor(
            user_id=dr_user.id,
            department_id=dept.id,
            room_number='D-01',
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


def _login(client):
    client.post('/auth/login', data={'username': 'dash_doctor', 'password': 'dashpass'})


def _register_patient(app, priority='Normal'):
    """Helper: register a sample patient token in the test app context."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        return QueueService.register_patient_and_issue_token(
            name=f'Test Patient {priority} [SAMPLE DATA]',
            age=30,
            gender='Male',
            phone=f'8{priority[:3].upper()}00001',
            department_id=dept.id,
            priority=priority
        )


# ── Dashboard loads ───────────────────────────────────────────────────────────

def test_dashboard_loads(client, app):
    _login(client)
    resp = client.get('/doctor/dashboard')
    assert resp.status_code == 200
    assert b'Dashboard' in resp.data


# ── Call Next ─────────────────────────────────────────────────────────────────

def test_call_next_transitions_to_called(client, app):
    """Posting call-next moves a Waiting token to Called."""
    _register_patient(app)
    _login(client)

    resp = client.post('/doctor/call-next', follow_redirects=True)
    assert resp.status_code == 200
    assert b'called' in resp.data.lower()

    with app.app_context():
        doctor = Doctor.query.first()
        token = QueueToken.query.filter_by(doctor_id=doctor.id, status='Called').first()
        assert token is not None


def test_call_next_when_empty_queue(client, app):
    """Calling next on empty queue shows a warning."""
    _login(client)
    resp = client.post('/doctor/call-next', follow_redirects=True)
    assert resp.status_code == 200
    assert b'No patients' in resp.data or b'waiting' in resp.data.lower()


def test_cannot_call_next_while_patient_already_called(client, app):
    """Calling next while a patient is already in Called state shows an error."""
    _register_patient(app, priority='Normal')
    _register_patient(app, priority='High')
    _login(client)

    # First call succeeds
    client.post('/doctor/call-next')

    # Second call should fail with a guard message
    resp = client.post('/doctor/call-next', follow_redirects=True)
    assert resp.status_code == 200
    assert b'already been called' in resp.data or b'Start' in resp.data


# ── Start Consultation ────────────────────────────────────────────────────────

def test_start_consultation(client, app):
    """Called → In-Consultation transition works."""
    _register_patient(app)
    _login(client)

    client.post('/doctor/call-next')

    with app.app_context():
        doctor = Doctor.query.first()
        token = QueueToken.query.filter_by(doctor_id=doctor.id, status='Called').first()
        assert token is not None
        token_id = token.id

    resp = client.post(f'/doctor/start-consultation/{token_id}', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        token = db.session.get(QueueToken, token_id)
        assert token.status == 'In-Consultation'


# ── Complete Consultation ─────────────────────────────────────────────────────

def test_complete_consultation(client, app):
    """In-Consultation → Completed transition works."""
    _register_patient(app)
    _login(client)
    client.post('/doctor/call-next')

    with app.app_context():
        doctor = Doctor.query.first()
        token = QueueToken.query.filter_by(doctor_id=doctor.id, status='Called').first()
        token_id = token.id

    client.post(f'/doctor/start-consultation/{token_id}')
    resp = client.post(f'/doctor/complete-consultation/{token_id}', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        token = db.session.get(QueueToken, token_id)
        assert token.status == 'Completed'
        assert token.completed_at is not None


# ── No-Show ───────────────────────────────────────────────────────────────────

def test_no_show(client, app):
    """Called → No-Show transition works."""
    _register_patient(app)
    _login(client)
    client.post('/doctor/call-next')

    with app.app_context():
        doctor = Doctor.query.first()
        token = QueueToken.query.filter_by(doctor_id=doctor.id, status='Called').first()
        token_id = token.id

    resp = client.post(f'/doctor/no-show/{token_id}',
                       data={'action': 'No-Show'}, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        token = db.session.get(QueueToken, token_id)
        assert token.status == 'No-Show'


def test_return_to_queue(client, app):
    """Called → Waiting (return to queue) transition works."""
    _register_patient(app)
    _login(client)
    client.post('/doctor/call-next')

    with app.app_context():
        doctor = Doctor.query.first()
        token = QueueToken.query.filter_by(doctor_id=doctor.id, status='Called').first()
        token_id = token.id

    resp = client.post(f'/doctor/no-show/{token_id}',
                       data={'action': 'Waiting'}, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        token = db.session.get(QueueToken, token_id)
        assert token.status == 'Waiting'
        assert token.doctor_id is None   # cleared when returned to queue


# ── Invalid transition prevention ─────────────────────────────────────────────

def test_cannot_complete_waiting_token(app):
    """Completing a Waiting token (invalid transition) raises an error message."""
    _register_patient(app)
    with app.app_context():
        doctor = Doctor.query.first()
        token = QueueToken.query.filter_by(status='Waiting').first()
        token.doctor_id = doctor.id
        db.session.commit()
        token_id = token.id

        _, error = DoctorService.complete_consultation(doctor, token_id)
        assert error is not None
        assert 'Completed' in error or 'Cannot' in error


# ── Availability toggle ───────────────────────────────────────────────────────

def test_toggle_availability(client, app):
    """Doctor can toggle their availability status."""
    _login(client)

    with app.app_context():
        doctor = Doctor.query.first()
        original = doctor.is_available

    resp = client.post('/doctor/toggle-availability', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        doctor = Doctor.query.first()
        assert doctor.is_available == (not original)
