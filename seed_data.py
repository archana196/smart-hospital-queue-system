from datetime import datetime, date, time
from app import create_app
from app.models import db, User, Department, Doctor, Patient, QueueToken
from app.services.queue_service import QueueService
from werkzeug.security import generate_password_hash

def seed_database():
    app = create_app('development')
    with app.app_context():
        print("Initializing database tables...")
        db.drop_all()
        db.create_all()
        
        print("Seeding sample departments...")
        departments_data = [
            {'name': 'General Medicine', 'code': 'GEN', 'description': 'General health checks and primary care [SAMPLE DATA]'},
            {'name': 'Cardiology', 'code': 'CARD', 'description': 'Heart and cardiovascular care [SAMPLE DATA]'},
            {'name': 'Orthopedics', 'code': 'ORTH', 'description': 'Bone and joint specialists [SAMPLE DATA]'},
            {'name': 'Pediatrics', 'code': 'PED', 'description': 'Child healthcare and immunizations [SAMPLE DATA]'},
            {'name': 'Emergency Care', 'code': 'EMG', 'description': '24/7 Urgent and critical trauma care [SAMPLE DATA]'}
        ]
        
        created_depts = {}
        for d in departments_data:
            dept = Department(name=d['name'], code=d['code'], description=d['description'])
            db.session.add(dept)
            db.session.flush()
            created_depts[d['code']] = dept
            
        print("Seeding sample users and doctors...")
        # Doctor User 1
        u_dr1 = User(
            username='dr_sharma',
            password_hash=generate_password_hash('doctor123'),
            role='doctor',
            full_name='Dr. Ananya Sharma [SAMPLE DATA]',
            email='dr.sharma@smarthospital.sample',
            phone='9876543210'
        )
        db.session.add(u_dr1)
        db.session.flush()
        
        dr1 = Doctor(
            user_id=u_dr1.id,
            department_id=created_depts['GEN'].id,
            room_number='OPD-101',
            is_available=True,
            avg_consultation_mins=10.0
        )
        db.session.add(dr1)
        
        # Doctor User 2
        u_dr2 = User(
            username='dr_verma',
            password_hash=generate_password_hash('doctor123'),
            role='doctor',
            full_name='Dr. Vikram Verma [SAMPLE DATA]',
            email='dr.verma@smarthospital.sample',
            phone='9876543211'
        )
        db.session.add(u_dr2)
        db.session.flush()
        
        dr2 = Doctor(
            user_id=u_dr2.id,
            department_id=created_depts['CARD'].id,
            room_number='OPD-204',
            is_available=True,
            avg_consultation_mins=15.0
        )
        db.session.add(dr2)

        # Admin User
        admin_u = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            full_name='System Administrator [SAMPLE DATA]',
            email='admin@smarthospital.sample',
            phone='9000000000'
        )
        db.session.add(admin_u)

        # Receptionist User
        recept_u = User(
            username='receptionist',
            password_hash=generate_password_hash('recept123'),
            role='receptionist',
            full_name='Front Desk Staff [SAMPLE DATA]',
            email='receptionist@smarthospital.sample',
            phone='9000000001'
        )
        db.session.add(recept_u)

        db.session.commit()

        print("Seeding sample patient registrations and tokens...")
        sample_patients = [
            {
                'name': 'Aarav Kumar [SAMPLE DATA]',
                'age': 35,
                'gender': 'Male',
                'phone': '9111111111',
                'dept_code': 'GEN',
                'reg_type': 'Walk-in',
                'priority': 'Normal'
            },
            {
                'name': 'Priya Patel [SAMPLE DATA]',
                'age': 52,
                'gender': 'Female',
                'phone': '9222222222',
                'dept_code': 'GEN',
                'reg_type': 'Online',
                'appt_date': date(2026, 10, 9),
                'appt_time': time(10, 30),
                'priority': 'High'
            },
            {
                'name': 'Ramesh Gupta [SAMPLE DATA]',
                'age': 68,
                'gender': 'Male',
                'phone': '9333333333',
                'dept_code': 'CARD',
                'reg_type': 'Walk-in',
                'priority': 'Emergency'
            }
        ]

        for sp in sample_patients:
            dept = created_depts[sp['dept_code']]
            QueueService.register_patient_and_issue_token(
                name=sp['name'],
                age=sp['age'],
                gender=sp['gender'],
                phone=sp['phone'],
                department_id=dept.id,
                registration_type=sp['reg_type'],
                appointment_date=sp.get('appt_date'),
                appointment_time=sp.get('appt_time'),
                priority=sp['priority']
            )

        print("Database successfully seeded with sample data!")

if __name__ == '__main__':
    seed_database()
