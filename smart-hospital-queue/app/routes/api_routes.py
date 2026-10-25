from flask import Blueprint, jsonify
from app.models import db, Department, QueueToken
from app.services.queue_service import QueueService
from app.services.ml_service import MLService

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

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
    token = QueueToken.query.filter_by(token_number=token_number).first()
    if not token:
        return jsonify({'error': 'Token not found'}), 404

    pred_wait = MLService.predict_waiting_time(token) if token.status in ['Waiting', 'Checked-In'] else None

    return jsonify({
        'token_number': token.token_number,
        'patient_name': token.patient.name,
        'department': token.department.name,
        'priority': token.priority,
        'status': token.status,
        'registration_type': token.registration_type,
        'appointment_date': token.appointment_date.strftime('%Y-%m-%d') if token.appointment_date else None,
        'appointment_time': token.appointment_time.strftime('%H:%M') if token.appointment_time else None,
        'created_at': token.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'waiting_duration_mins': int(QueueService.get_waiting_duration_mins(token)),
        'estimated_wait_mins': pred_wait
    })
