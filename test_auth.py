"""
test_auth.py – Phase 2 tests for authentication and RBAC.

Covers:
- Login with valid credentials (all roles)
- Login with bad credentials
- Logout
- Unauthenticated access redirects to login
- Role-based access: doctor-only routes return 403 for non-doctors
"""
import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from app.models import db, User, Department, Doctor


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()

        # Seed one department
        dept = Department(name='General Medicine', code='GEN', description='Test dept')
        db.session.add(dept)
        db.session.flush()

        # Doctor user + profile
        dr_user = User(
            username='test_doctor',
            password_hash=generate_password_hash('docpass'),
            role='doctor',
            full_name='Test Doctor [SAMPLE DATA]',
        )
        db.session.add(dr_user)
        db.session.flush()

        doctor = Doctor(
            user_id=dr_user.id,
            department_id=dept.id,
            room_number='T-01',
            is_available=True,
            avg_consultation_mins=10.0
        )
        db.session.add(doctor)

        # Admin user
        admin_user = User(
            username='test_admin',
            password_hash=generate_password_hash('adminpass'),
            role='admin',
            full_name='Test Admin [SAMPLE DATA]',
        )
        db.session.add(admin_user)

        # Receptionist user
        recept_user = User(
            username='test_recept',
            password_hash=generate_password_hash('receptpass'),
            role='receptionist',
            full_name='Test Receptionist [SAMPLE DATA]',
        )
        db.session.add(recept_user)

        db.session.commit()
        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


# ── Login tests ───────────────────────────────────────────────────────────────

def test_login_page_loads(client):
    """GET /auth/login returns 200."""
    response = client.get('/auth/login')
    assert response.status_code == 200
    assert b'Login' in response.data


def test_login_valid_doctor(client):
    """Doctor can log in and gets redirected."""
    response = client.post('/auth/login', data={
        'username': 'test_doctor',
        'password': 'docpass',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Welcome back' in response.data or b'Dashboard' in response.data


def test_login_valid_admin(client):
    """Admin can log in successfully."""
    response = client.post('/auth/login', data={
        'username': 'test_admin',
        'password': 'adminpass',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Welcome back' in response.data


def test_login_wrong_password(client):
    """Wrong password shows error, does not log in."""
    response = client.post('/auth/login', data={
        'username': 'test_doctor',
        'password': 'wrongpassword',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Invalid username or password' in response.data


def test_login_unknown_user(client):
    """Unknown username shows same generic error (no enumeration)."""
    response = client.post('/auth/login', data={
        'username': 'ghost_user',
        'password': 'anypassword',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Invalid username or password' in response.data


def test_login_missing_fields(client):
    """Empty form submission shows a validation warning."""
    response = client.post('/auth/login', data={
        'username': '',
        'password': '',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'required' in response.data.lower()


# ── Logout tests ──────────────────────────────────────────────────────────────

def test_logout(client):
    """Logged-in user can log out."""
    client.post('/auth/login', data={'username': 'test_doctor', 'password': 'docpass'})
    response = client.get('/auth/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b'logged out' in response.data.lower()


def test_logout_requires_login(client):
    """Unauthenticated user hitting /auth/logout is redirected to login."""
    response = client.get('/auth/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b'Login' in response.data


# ── Unauthenticated access tests ──────────────────────────────────────────────

def test_doctor_dashboard_redirects_unauthenticated(client):
    """GET /doctor/dashboard without login redirects to login page."""
    response = client.get('/doctor/dashboard', follow_redirects=True)
    assert response.status_code == 200
    assert b'Login' in response.data


# ── RBAC tests ────────────────────────────────────────────────────────────────

def test_admin_cannot_access_doctor_dashboard(client):
    """Admin role gets 403 on doctor-only routes."""
    client.post('/auth/login', data={'username': 'test_admin', 'password': 'adminpass'})
    response = client.get('/doctor/dashboard')
    assert response.status_code == 403


def test_receptionist_cannot_access_doctor_dashboard(client):
    """Receptionist role gets 403 on doctor-only routes."""
    client.post('/auth/login', data={'username': 'test_recept', 'password': 'receptpass'})
    response = client.get('/doctor/dashboard')
    assert response.status_code == 403


def test_doctor_can_access_doctor_dashboard(client):
    """Doctor role can access the doctor dashboard."""
    client.post('/auth/login', data={'username': 'test_doctor', 'password': 'docpass'})
    response = client.get('/doctor/dashboard')
    assert response.status_code == 200
    assert b'Dashboard' in response.data
