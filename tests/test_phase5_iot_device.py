"""
test_phase5_iot_device.py - Automated tests for Phase 5 IoT Device API and integration.

Covers:
1. Device API authentication (missing, invalid, valid X-Device-API-Key and Bearer header).
2. URL credential rejection (credentials in query params must NOT authenticate).
3. Department identification by numeric ID and department code (case-insensitive).
4. Missing department error handling (404).
5. Schema compliance and strict non-PII verification (no names, phones, clinical info).
6. Queue state retrieval (waiting count, current token, next token).
7. Empty queue handling (waiting count 0, next token null).
8. Doctor 'Call Next Patient' event generation (call_event_id increment, token transition).
9. Idempotent polling (repeated GET requests do not trigger new call events).
"""

import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from app.models import db, User, Department, Doctor, Patient, QueueToken, QueueCallEvent
from app.services.queue_service import QueueService
from app.services.doctor_service import DoctorService


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['DEVICE_API_KEY'] = 'test-iot-api-key-xyz-2026'

    with app.app_context():
        db.create_all()

        # Create Cardiology Department
        cardio = Department(name='Cardiology', code='CARD', description='Heart clinic')
        general = Department(name='General Medicine', code='GEN', description='General clinic')
        db.session.add_all([cardio, general])
        db.session.flush()

        # Create Doctor for Cardiology
        dr_user = User(
            username='dr_cardio',
            password_hash=generate_password_hash('doctorpass'),
            role='doctor',
            full_name='Dr. Cardio Test'
        )
        db.session.add(dr_user)
        db.session.flush()

        doctor = Doctor(
            user_id=dr_user.id,
            department_id=cardio.id,
            room_number='C-101',
            is_available=True,
            avg_consultation_mins=15.0
        )
        db.session.add(doctor)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_device_api_requires_auth(client):
    """Device endpoint must reject requests without an API key."""
    res = client.get('/api/v1/device/queue/CARD')
    assert res.status_code == 401
    data = res.get_json()
    assert data['error'] == 'Unauthorized device'


def test_device_api_rejects_invalid_key(client):
    """Device endpoint must reject invalid API keys."""
    res = client.get(
        '/api/v1/device/queue/CARD',
        headers={'X-Device-API-Key': 'completely-wrong-key'}
    )
    assert res.status_code == 401
    data = res.get_json()
    assert data['error'] == 'Unauthorized device'


def test_device_api_rejects_query_param_credentials(client):
    """Security rule: credentials in query strings must NOT authenticate."""
    res = client.get('/api/v1/device/queue/CARD?api_key=test-iot-api-key-xyz-2026')
    assert res.status_code == 401


def test_device_api_valid_headers(client):
    """Device endpoint accepts X-Device-API-Key and Bearer Authorization headers."""
    # Via X-Device-API-Key
    res1 = client.get(
        '/api/v1/device/queue/CARD',
        headers={'X-Device-API-Key': 'test-iot-api-key-xyz-2026'}
    )
    assert res1.status_code == 200
    assert res1.get_json()['status'] == 'online'

    # Via Authorization: Bearer
    res2 = client.get(
        '/api/v1/device/queue/CARD',
        headers={'Authorization': 'Bearer test-iot-api-key-xyz-2026'}
    )
    assert res2.status_code == 200
    assert res2.get_json()['department_code'] == 'CARD'


def test_device_api_department_lookup(client):
    """Endpoint resolves department by code (case-insensitive) and numeric ID."""
    headers = {'X-Device-API-Key': 'test-iot-api-key-xyz-2026'}

    # By uppercase code
    res_code = client.get('/api/v1/device/queue/CARD', headers=headers)
    assert res_code.status_code == 200
    assert res_code.get_json()['department_code'] == 'CARD'

    # By lowercase code
    res_code_lower = client.get('/api/v1/device/queue/card', headers=headers)
    assert res_code_lower.status_code == 200
    assert res_code_lower.get_json()['department_code'] == 'CARD'

    # By numeric ID
    dept_id = res_code.get_json()['department_id']
    res_id = client.get(f'/api/v1/device/queue/{dept_id}', headers=headers)
    assert res_id.status_code == 200
    assert res_id.get_json()['department_id'] == dept_id

    # Non-existent department
    res_404 = client.get('/api/v1/device/queue/UNKNOWN_DEPT', headers=headers)
    assert res_404.status_code == 404
    assert res_404.get_json()['error'] == 'Department not found'


def test_device_api_empty_queue(client):
    """When no patients are waiting, waiting_count is 0 and next_token is null."""
    headers = {'X-Device-API-Key': 'test-iot-api-key-xyz-2026'}
    res = client.get('/api/v1/device/queue/CARD', headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data['waiting_count'] == 0
    assert data['current_token'] is None
    assert data['next_token'] is None
    assert data['call_event_id'] == 0


def test_device_api_schema_and_zero_pii(app, client):
    """Verify that response schema contains all required fields and strictly ZERO PII."""
    with app.app_context():
        cardio = Department.query.filter_by(code='CARD').first()
        QueueService.register_patient_and_issue_token(
            name='Secret Patient Doe',
            age=45,
            gender='Female',
            phone='9876543210',
            department_id=cardio.id,
            registration_type='Walk-in',
            priority='High'
        )

    headers = {'X-Device-API-Key': 'test-iot-api-key-xyz-2026'}
    res = client.get('/api/v1/device/queue/CARD', headers=headers)
    assert res.status_code == 200
    data = res.get_json()

    # Required fields
    required_keys = [
        'status', 'department_id', 'department_code', 'department_name',
        'waiting_count', 'current_token', 'current_status', 'last_called_token',
        'next_token', 'call_event_id', 'server_time'
    ]
    for key in required_keys:
        assert key in data, f"Missing required field: {key}"

    # Strict Zero-PII assertions
    raw_text = res.get_data(as_text=True)
    assert 'Secret Patient' not in raw_text
    assert '9876543210' not in raw_text
    assert 'password' not in raw_text.lower()
    assert 'phone' not in data
    assert 'patient_name' not in data
    assert 'age' not in data
    assert 'gender' not in data


def test_call_next_patient_generates_event_and_updates_device_api(app, client):
    """
    Test full Phase 5 workflow:
    1. Register waiting patients.
    2. Check device API before call (waiting=2, next=Token1, current=None, event_id=0).
    3. Doctor calls next patient via DoctorService.
    4. Verify call_event created with sequential ID.
    5. Check device API after call (waiting=1, next=Token2, current=Token1, event_id=1).
    6. Repeated polling preserves state without generating new events.
    """
    with app.app_context():
        cardio = Department.query.filter_by(code='CARD').first()
        cardio_id = cardio.id

        # Register two patients
        t1 = QueueService.register_patient_and_issue_token(
            name='Patient One', age=30, gender='M', phone='9000000001',
            department_id=cardio_id, priority='Normal'
        )
        t2 = QueueService.register_patient_and_issue_token(
            name='Patient Two', age=35, gender='F', phone='9000000002',
            department_id=cardio_id, priority='High'
        )

        t1_num = t1.token_number
        t2_num = t2.token_number

    headers = {'X-Device-API-Key': 'test-iot-api-key-xyz-2026'}

    # Step 1: Device API before call
    # Note: t2 has High priority, so t2 is next!
    res_before = client.get('/api/v1/device/queue/CARD', headers=headers)
    assert res_before.status_code == 200
    data_before = res_before.get_json()
    assert data_before['waiting_count'] == 2
    assert data_before['next_token'] == t2_num
    assert data_before['current_token'] is None
    assert data_before['call_event_id'] == 0

    # Step 2: Doctor calls next patient
    with app.app_context():
        dr = Doctor.query.first()
        called_token, err = DoctorService.call_next_patient(dr)
        assert err is None
        assert called_token is not None
        assert called_token.token_number == t2_num
        assert called_token.status == 'Called'

        # Verify persistent QueueCallEvent record
        events = QueueCallEvent.query.filter_by(department_id=cardio_id).all()
        assert len(events) == 1
        assert events[0].token_number == t2_num
        assert events[0].id == 1

    # Step 3: Device API after call
    res_after = client.get('/api/v1/device/queue/CARD', headers=headers)
    assert res_after.status_code == 200
    data_after = res_after.get_json()
    assert data_after['waiting_count'] == 1
    assert data_after['current_token'] == t2_num
    assert data_after['current_status'] == 'Called'
    assert data_after['next_token'] == t1_num
    assert data_after['call_event_id'] == 1

    # Step 4: Repeated polling is idempotent
    for _ in range(5):
        poll_res = client.get('/api/v1/device/queue/CARD', headers=headers)
        poll_data = poll_res.get_json()
        assert poll_data['call_event_id'] == 1
        assert poll_data['current_token'] == t2_num
        assert poll_data['waiting_count'] == 1

    # Verify no extra call events were created in DB
    with app.app_context():
        total_events = QueueCallEvent.query.count()
        assert total_events == 1
