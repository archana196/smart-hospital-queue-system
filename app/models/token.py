from datetime import datetime
from app.models import db

class QueueToken(db.Model):
    __tablename__ = 'queue_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    token_number = db.Column(db.String(30), unique=True, nullable=False) # e.g. GEN-20261008-001
    
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=True)
    
    # Registration Type & Appointment Date/Time
    registration_type = db.Column(db.String(20), nullable=False, default='Walk-in') # Online or Walk-in
    appointment_date = db.Column(db.Date, nullable=True) # Required if Online, NULL if Walk-in
    appointment_time = db.Column(db.Time, nullable=True) # Required if Online, NULL if Walk-in
    
    # Priority & Scheduling
    priority = db.Column(db.String(20), nullable=False, default='Normal') # Emergency, High, Medium, Normal
    priority_score = db.Column(db.Integer, nullable=False, default=100) # Dynamic priority with aging
    status = db.Column(db.String(20), nullable=False, default='Waiting') # Waiting, Checked-In, Called, In-Consultation, Completed, Cancelled
    
    # Secure Non-PII QR Code Verification Hash
    qr_code_hash = db.Column(db.String(100), unique=True, nullable=False) # Secure UUID token reference (NO PII)
    qr_scanned_at = db.Column(db.DateTime, nullable=True) # For duplicate scan protection
    
    # ML Estimation & Timestamps
    estimated_wait_mins = db.Column(db.Float, nullable=True) # Set strictly by ML Service (Read-Only)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # Actual registration timestamp
    called_at = db.Column(db.DateTime, nullable=True)
    consultation_started_at = db.Column(db.DateTime, nullable=True) # Actual timestamp when consultation starts
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<QueueToken {self.token_number} [{self.priority}] - Status: {self.status}>'
