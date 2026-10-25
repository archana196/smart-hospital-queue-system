from flask import Blueprint, render_template
from app.models import Department, QueueToken

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    departments = Department.query.all()
    # Simple count of waiting patients per department
    dept_stats = []
    for dept in departments:
        waiting_count = QueueToken.query.filter_by(department_id=dept.id, status='Waiting').count()
        in_consult_count = QueueToken.query.filter_by(department_id=dept.id, status='In-Consultation').count()
        dept_stats.append({
            'id': dept.id,
            'name': dept.name,
            'code': dept.code,
            'waiting': waiting_count,
            'in_consultation': in_consult_count
        })
    return render_template('index.html', dept_stats=dept_stats)
