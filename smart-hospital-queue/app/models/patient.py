from datetime import datetime
from app.models import db

class Patient(db.Model):
    __tablename__ = 'patients'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_code = db.Column(db.String(30), unique=True, nullable=False) # e.g. PAT-20261008-0001
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10), nullable=False) # Male, Female, Other
    phone = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Nullable for walk-ins without account
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tokens = db.relationship('QueueToken', backref='patient', lazy=True)
    
    def __repr__(self):
        return f'<Patient {self.patient_code} - {self.name}>'
