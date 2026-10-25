import pytest
from datetime import datetime, timedelta
from app import create_app
from app.models import db, Department, QueueToken
from app.services.queue_service import QueueService

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        dept = Department(name='Cardiology', code='CARD', description='Cardiology Dept')
        db.session.add(dept)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()

def test_sequential_token_numbering(app):
    with app.app_context():
        dept = Department.query.filter_by(code='CARD').first()
        t1 = QueueService.register_patient_and_issue_token(
            name='Patient One [SAMPLE DATA]', age=40, gender='Male', phone='9000000001',
            department_id=dept.id, priority='Normal'
        )
        t2 = QueueService.register_patient_and_issue_token(
            name='Patient Two [SAMPLE DATA]', age=50, gender='Female', phone='9000000002',
            department_id=dept.id, priority='Normal'
        )
        
        assert t1.token_number.endswith('-001')
        assert t2.token_number.endswith('-002')

def test_queue_engine_priority_ordering(app):
    with app.app_context():
        dept = Department.query.filter_by(code='CARD').first()
        
        # 1. Register Normal priority patient first
        t_normal = QueueService.register_patient_and_issue_token(
            name='Normal Patient [SAMPLE DATA]', age=30, gender='Male', phone='9000000010',
            department_id=dept.id, priority='Normal'
        )
        
        # 2. Register Emergency priority patient later
        t_emergency = QueueService.register_patient_and_issue_token(
            name='Emergency Patient [SAMPLE DATA]', age=65, gender='Female', phone='9000000011',
            department_id=dept.id, priority='Emergency'
        )
        
        # Get queue from Queue Engine
        queue = QueueService.get_department_queue(dept.id)
        
        assert len(queue) == 2
        # Emergency token MUST be first in queue
        assert queue[0].id == t_emergency.id
        assert queue[1].id == t_normal.id

def test_queue_aging_mechanism(app):
    with app.app_context():
        dept = Department.query.filter_by(code='CARD').first()
        
        t_normal = QueueService.register_patient_and_issue_token(
            name='Long Waiting Patient [SAMPLE DATA]', age=45, gender='Male', phone='9000000020',
            department_id=dept.id, priority='Normal'
        )
        
        # Simulate waiting 30 minutes in the past (+20 aging score bonus)
        t_normal.created_at = datetime.utcnow() - timedelta(minutes=30)
        db.session.commit()
        
        effective_score = QueueService.calculate_effective_priority_score(t_normal)
        # Normal base score 100 + (30 // 15)*10 = 120
        assert effective_score == 120
