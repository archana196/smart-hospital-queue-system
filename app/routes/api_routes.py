import functools
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from app.models import db, Department, QueueToken, QueueCallEvent
from app.services.queue_service import QueueService, ELIGIBLE_STATUSES
from app.services.ml_service import MLService

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')


def device_auth_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-Device-API-Key')
        if not api_key:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                api_key = auth_header[7:].strip()

        configured_key = current_app.config.get('DEVICE_API_KEY')
        if not configured_key or not api_key or api_key != configured_key:
            return jsonify({'error': 'Unauthorized device'}), 401
        return f(*args, **kwargs)
    return decorated_function


@api_bp.route('/queue/<int:department_id>', methods=['GET'])
def get_queue(department_id):
    dept = db.session.get(Department, department_id)
    if not dept:
        return jsonify({'error': 'Department not found'}), 404

    queue = QueueService.get_department_queue(department_id)
    token_list = []
    for idx, token in enumerate(queue):
        pred_wait = MLService.predict_waiting_time(token, department_queue=queue)
        token_list.append({
            'position': idx + 1,
            'token_number': token.token_number,
            'priority': token.priority,
            'priority_score': token.priority_score,
            'registration_type': token.registration_type,
            'status': token.status,
            'created_at': token.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'waiting_duration_mins': int(QueueService.get_waiting_duration_mins(token)),
            'estimated_wait_mins': pred_wait
        })

    return jsonify({
        'department': dept.name,
        'department_code': dept.code,
        'queue_length': len(token_list),
        'tokens': token_list
    })


@api_bp.route('/token/<token_number>', methods=['GET'])
def get_token_details(token_number):
    """
    Public token status endpoint.
    PRIVACY: Returns only non-PII token information.
    Full patient name, appointment date/time, and contact details are NOT exposed.
    """
    token = QueueToken.query.filter_by(token_number=token_number).first()
    if not token:
        return jsonify({'error': 'Token not found'}), 404

    pred_wait = MLService.predict_waiting_time(token) if token.status in ['Waiting', 'Checked-In'] else None

    return jsonify({
        'token_number': token.token_number,
        # NOTE: patient_name, appointment_date, appointment_time intentionally omitted (PII / privacy)
        'department': token.department.name,
        'priority': token.priority,
        'status': token.status,
        'registration_type': token.registration_type,
        'created_at': token.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'waiting_duration_mins': int(QueueService.get_waiting_duration_mins(token)),
        'estimated_wait_mins': pred_wait
    })


@api_bp.route('/device/queue/<department_identifier>', methods=['GET'])
@device_auth_required
def get_device_queue_status(department_identifier):
    """
    Dedicated, authenticated IoT edge device endpoint (ESP8266 + OLED + Buzzer).
    READ-ONLY: Does not mutate queue or advance call events.
    PRIVACY: Strictly zero PII returned (no patient names, phones, or clinical data).
    """
    dept = None
    if department_identifier.isdigit():
        dept = db.session.get(Department, int(department_identifier))
    else:
        dept = Department.query.filter_by(code=department_identifier.upper()).first()

    if not dept:
        return jsonify({'error': 'Department not found'}), 404

    # Calculate waiting count and next eligible token using authoritative QueueService
    waiting_queue = QueueService.get_department_queue(dept.id)
    waiting_count = len(waiting_queue)
    next_token = waiting_queue[0].token_number if waiting_queue else None

    # Get active called / in-consultation token, if any
    active_token = QueueToken.query.filter(
        QueueToken.department_id == dept.id,
        QueueToken.status.in_(['Called', 'In-Consultation'])
    ).order_by(QueueToken.called_at.desc(), QueueToken.id.desc()).first()

    # Get latest sequential call event
    latest_event = QueueCallEvent.query.filter_by(
        department_id=dept.id
    ).order_by(QueueCallEvent.id.desc()).first()

    call_event_id = latest_event.id if latest_event else 0
    last_called_token = latest_event.token_number if latest_event else None

    return jsonify({
        'status': 'online',
        'department_id': dept.id,
        'department_code': dept.code,
        'department_name': dept.name,
        'waiting_count': waiting_count,
        'current_token': active_token.token_number if active_token else None,
        'current_status': active_token.status if active_token else 'Idle',
        'last_called_token': last_called_token,
        'next_token': next_token,
        'call_event_id': call_event_id,
        'server_time': datetime.now(timezone.utc).isoformat()
    })
