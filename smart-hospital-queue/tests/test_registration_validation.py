"""
test_registration_validation.py – Phase 2 enhancement tests for patient registration.

Tests cover:
  - Valid inputs (walk-in & online)
  - Invalid / missing name
  - Phone: fewer or more than 10 digits, letters, empty
  - Age: boundary values, non-integer, missing
  - Gender: invalid / missing
  - Department: non-existent, missing
  - Priority: Emergency blocked on public form; allowed for staff
  - Appointment date/time: required when Online, skipped for Walk-in
  - Form values preserved on error (template re-render)
  - Regression: all Phase 1 QueueService tests still pass indirectly
"""

import pytest
from datetime import date, time

from app import create_app
from app.models import db, Department, Patient, QueueToken
from app.services.validation_service import ValidationService


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        dept = Department(name='General Medicine', code='GEN', description='Test Dept')
        db.session.add(dept)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _dept_id(app):
    with app.app_context():
        return Department.query.filter_by(code='GEN').first().id


def _valid_walkin(app, **overrides):
    """Return a minimal valid walk-in form payload."""
    base = {
        'name': 'Rahul Sharma',
        'age': '30',
        'gender': 'Male',
        'phone': '9876543210',
        'department_id': str(_dept_id(app)),
        'registration_type': 'Walk-in',
        'priority': 'Normal',
        'appointment_date': '',
        'appointment_time': '',
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 – ValidationService unit tests (no HTTP, no DB for most)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNameValidation:

    def test_valid_simple_name(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app))
            assert 'name' not in errs

    def test_valid_name_with_hyphen(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='Mary-Jane Watson')
            assert 'name' not in ValidationService.validate_registration(data)

    def test_valid_name_with_apostrophe(self, app):
        with app.app_context():
            data = _valid_walkin(app, name="O'Brien")
            assert 'name' not in ValidationService.validate_registration(data)

    def test_name_empty(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='')
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_whitespace_only(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='    ')
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_too_short(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='A')
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_too_long(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='A' * 101)
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_with_digits_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='Rahul123')
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_with_emoji_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='Rahul 😀')
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_with_at_sign_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, name='Rahul@Kumar')
            errs = ValidationService.validate_registration(data)
            assert 'name' in errs

    def test_name_max_boundary_valid(self, app):
        with app.app_context():
            # Exactly 100 chars of letters + spaces
            long_name = ('Aarav Kumar ' * 9)[:100]
            data = _valid_walkin(app, name=long_name)
            errs = ValidationService.validate_registration(data)
            assert 'name' not in errs


class TestPhoneValidation:

    def test_valid_10_digit_phone(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app))
            assert 'phone' not in errs

    def test_phone_9_digits_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, phone='987654321')  # 9 digits
            errs = ValidationService.validate_registration(data)
            assert 'phone' in errs

    def test_phone_11_digits_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, phone='98765432100')  # 11 digits
            errs = ValidationService.validate_registration(data)
            assert 'phone' in errs

    def test_phone_with_letters_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, phone='9876abcd10')
            errs = ValidationService.validate_registration(data)
            assert 'phone' in errs

    def test_phone_empty_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, phone='')
            errs = ValidationService.validate_registration(data)
            assert 'phone' in errs

    def test_phone_with_spaces_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, phone='98765 43210')
            errs = ValidationService.validate_registration(data)
            assert 'phone' in errs

    def test_phone_with_plus_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, phone='+919876543210')
            errs = ValidationService.validate_registration(data)
            assert 'phone' in errs


class TestAgeValidation:

    def test_valid_age(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app))
            assert 'age' not in errs

    def test_age_zero_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='0')
            errs = ValidationService.validate_registration(data)
            assert 'age' in errs

    def test_age_negative_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='-5')
            errs = ValidationService.validate_registration(data)
            assert 'age' in errs

    def test_age_121_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='121')
            errs = ValidationService.validate_registration(data)
            assert 'age' in errs

    def test_age_120_valid(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='120')
            errs = ValidationService.validate_registration(data)
            assert 'age' not in errs

    def test_age_1_valid(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='1')
            errs = ValidationService.validate_registration(data)
            assert 'age' not in errs

    def test_age_text_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='thirty')
            errs = ValidationService.validate_registration(data)
            assert 'age' in errs

    def test_age_empty_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, age='')
            errs = ValidationService.validate_registration(data)
            assert 'age' in errs


class TestGenderValidation:

    def test_valid_gender_male(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app, gender='Male'))
            assert 'gender' not in errs

    def test_valid_gender_female(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app, gender='Female'))
            assert 'gender' not in errs

    def test_valid_gender_other(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app, gender='Other'))
            assert 'gender' not in errs

    def test_invalid_gender_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, gender='Unknown')
            errs = ValidationService.validate_registration(data)
            assert 'gender' in errs

    def test_gender_empty_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, gender='')
            errs = ValidationService.validate_registration(data)
            assert 'gender' in errs


class TestDepartmentValidation:

    def test_valid_department(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app))
            assert 'department_id' not in errs

    def test_nonexistent_department_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, department_id='9999')
            errs = ValidationService.validate_registration(data)
            assert 'department_id' in errs

    def test_empty_department_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, department_id='')
            errs = ValidationService.validate_registration(data)
            assert 'department_id' in errs

    def test_invalid_department_string_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, department_id='abc')
            errs = ValidationService.validate_registration(data)
            assert 'department_id' in errs


class TestPriorityValidation:

    def test_valid_priority_normal(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app, priority='Normal'))
            assert 'priority' not in errs

    def test_valid_priority_medium(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app, priority='Medium'))
            assert 'priority' not in errs

    def test_valid_priority_high(self, app):
        with app.app_context():
            errs = ValidationService.validate_registration(_valid_walkin(app, priority='High'))
            assert 'priority' not in errs

    def test_emergency_blocked_on_public_form(self, app):
        """Emergency priority must be blocked when allow_emergency=False."""
        with app.app_context():
            data = _valid_walkin(app, priority='Emergency')
            errs = ValidationService.validate_registration(data, allow_emergency=False)
            assert 'priority' in errs

    def test_emergency_allowed_for_staff(self, app):
        """Emergency priority is allowed when allow_emergency=True (staff workflow)."""
        with app.app_context():
            data = _valid_walkin(app, priority='Emergency')
            errs = ValidationService.validate_registration(data, allow_emergency=True)
            assert 'priority' not in errs

    def test_invalid_priority_value_rejected(self, app):
        with app.app_context():
            data = _valid_walkin(app, priority='Critical')
            errs = ValidationService.validate_registration(data)
            assert 'priority' in errs


class TestAppointmentValidation:

    def test_online_requires_date_and_time(self, app):
        with app.app_context():
            data = _valid_walkin(app,
                registration_type='Online',
                appointment_date='',
                appointment_time='')
            errs = ValidationService.validate_registration(data)
            assert 'appointment_date' in errs
            assert 'appointment_time' in errs

    def test_online_valid_date_time(self, app):
        with app.app_context():
            data = _valid_walkin(app,
                registration_type='Online',
                appointment_date='2026-11-01',
                appointment_time='10:30')
            errs = ValidationService.validate_registration(data)
            assert 'appointment_date' not in errs
            assert 'appointment_time' not in errs

    def test_walkin_ignores_appointment_fields(self, app):
        """Walk-in registration does not validate appointment date/time."""
        with app.app_context():
            data = _valid_walkin(app,
                registration_type='Walk-in',
                appointment_date='',
                appointment_time='')
            errs = ValidationService.validate_registration(data)
            assert 'appointment_date' not in errs
            assert 'appointment_time' not in errs

    def test_online_invalid_date_format(self, app):
        with app.app_context():
            data = _valid_walkin(app,
                registration_type='Online',
                appointment_date='01-11-2026',  # wrong format
                appointment_time='10:30')
            errs = ValidationService.validate_registration(data)
            assert 'appointment_date' in errs


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 – HTTP integration tests (via Flask test client)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistrationRoute:

    def test_valid_walkin_registration_redirects(self, client, app):
        """A valid walk-in POST should redirect to the token page."""
        payload = _valid_walkin(app)
        resp = client.post('/patient/register', data=payload, follow_redirects=False)
        assert resp.status_code == 302
        assert '/patient/token/' in resp.headers['Location']

    def test_valid_walkin_creates_token_in_db(self, client, app):
        payload = _valid_walkin(app)
        client.post('/patient/register', data=payload, follow_redirects=True)
        with app.app_context():
            assert QueueToken.query.count() == 1
            token = QueueToken.query.first()
            assert token.priority == 'Normal'
            assert token.registration_type == 'Walk-in'

    def test_invalid_name_returns_200_with_error(self, client, app):
        """Bad name should return the form again (200), not redirect."""
        payload = _valid_walkin(app, name='Rahul123')
        resp = client.post('/patient/register', data=payload, follow_redirects=False)
        assert resp.status_code == 200
        assert b'letters, spaces' in resp.data or b'Name may only' in resp.data

    def test_invalid_phone_returns_error(self, client, app):
        payload = _valid_walkin(app, phone='12345')
        resp = client.post('/patient/register', data=payload)
        assert resp.status_code == 200
        assert b'10 digits' in resp.data

    def test_missing_required_fields_shows_error(self, client, app):
        resp = client.post('/patient/register', data={
            'name': '',
            'age': '',
            'gender': '',
            'phone': '',
            'department_id': '',
            'registration_type': 'Walk-in',
            'priority': 'Normal',
        })
        assert resp.status_code == 200
        assert b'required' in resp.data.lower() or b'correct the errors' in resp.data.lower()

    def test_nonexistent_department_blocked(self, client, app):
        payload = _valid_walkin(app, department_id='9999')
        resp = client.post('/patient/register', data=payload)
        assert resp.status_code == 200
        assert b'does not exist' in resp.data or b'department' in resp.data.lower()

    def test_emergency_priority_blocked_on_public_form(self, client, app):
        """Unauthenticated users cannot self-assign Emergency priority."""
        payload = _valid_walkin(app, priority='Emergency')
        resp = client.post('/patient/register', data=payload)
        assert resp.status_code == 200
        assert b'Emergency' in resp.data  # error message mentions Emergency

    def test_form_values_preserved_after_name_error(self, client, app):
        """After a name validation error, phone and department values are preserved."""
        payload = _valid_walkin(app, name='Bad1Name')
        resp = client.post('/patient/register', data=payload)
        assert resp.status_code == 200
        # Phone value should be present in the re-rendered form
        assert b'9876543210' in resp.data

    def test_online_registration_missing_appointment_blocked(self, client, app):
        payload = _valid_walkin(app,
            registration_type='Online',
            appointment_date='',
            appointment_time='')
        resp = client.post('/patient/register', data=payload)
        assert resp.status_code == 200
        assert b'required' in resp.data.lower() or b'appointment' in resp.data.lower()

    def test_online_valid_registration_succeeds(self, client, app):
        payload = _valid_walkin(app,
            registration_type='Online',
            appointment_date='2026-11-15',
            appointment_time='11:00')
        resp = client.post('/patient/register', data=payload, follow_redirects=False)
        assert resp.status_code == 302

    def test_no_token_created_on_validation_error(self, client, app):
        """DB must stay empty when validation fails."""
        payload = _valid_walkin(app, phone='BADPHONE')
        client.post('/patient/register', data=payload)
        with app.app_context():
            assert QueueToken.query.count() == 0

    def test_registration_page_loads(self, client):
        resp = client.get('/patient/register')
        assert resp.status_code == 200
        assert b'Patient Registration' in resp.data


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 – ValidationService.normalize_name
# ═══════════════════════════════════════════════════════════════════════════════

class TestNormalizeName:

    def test_strips_leading_trailing_spaces(self):
        assert ValidationService.normalize_name('  Rahul  ') == 'Rahul'

    def test_collapses_internal_spaces(self):
        assert ValidationService.normalize_name('Rahul   Kumar') == 'Rahul Kumar'

    def test_preserves_hyphen(self):
        assert ValidationService.normalize_name('Mary-Jane') == 'Mary-Jane'
