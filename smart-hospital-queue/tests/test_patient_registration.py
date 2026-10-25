import pytest
from datetime import date, time
from app import create_app
from app.models import db, Department, Patient, QueueToken
from app.services.queue_service import QueueService

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        # Seed test department
        dept = Department(name='General Medicine', code='GEN', description='Test Dept')
        db.session.add(dept)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_walkin_patient_registration(app):
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Test Patient Walkin [SAMPLE DATA]',
            age=30,
            gender='Male',
            phone='9998887770',
            department_id=dept.id,
            registration_type='Walk-in',
            priority='Normal'
        )
        assert token is not None
        assert token.token_number.startswith('GEN-')
        assert token.registration_type == 'Walk-in'
        assert token.appointment_date is None
        assert token.appointment_time is None
        assert token.qr_code_hash.startswith('qr_sec_')
        # Ensure NO PII is in the QR token reference string
        assert 'Test Patient' not in token.qr_code_hash
        assert '9998887770' not in token.qr_code_hash

def test_online_patient_registration_success(app):
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        appt_d = date(2026, 10, 15)
        appt_t = time(14, 30)
        token = QueueService.register_patient_and_issue_token(
            name='Test Patient Online [SAMPLE DATA]',
            age=45,
            gender='Female',
            phone='9998887771',
            department_id=dept.id,
            registration_type='Online',
            appointment_date=appt_d,
            appointment_time=appt_t,
            priority='High'
        )
        assert token is not None
        assert token.registration_type == 'Online'
        assert token.appointment_date == appt_d
        assert token.appointment_time == appt_t
        assert token.priority == 'High'

def test_online_patient_registration_missing_fields_raises_error(app):
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        with pytest.raises(ValueError, match="Appointment Date and Time are required"):
            QueueService.register_patient_and_issue_token(
                name='Invalid Online Registration',
                age=25,
                gender='Other',
                phone='9998887772',
                department_id=dept.id,
                registration_type='Online',
                appointment_date=None,
                appointment_time=None
            )
