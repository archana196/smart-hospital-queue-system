from datetime import datetime, timezone
from app.models import db

class QueueCallEvent(db.Model):
    """
    QueueCallEvent records every patient call action triggered by a doctor.
    Each event receives a strictly sequential, unique call event ID.
    Used by IoT edge devices (ESP8266 + OLED + Buzzer) and live display boards
    to identify new call transitions without false-triggering or missing calls.
    """
    __tablename__ = 'queue_call_events'

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=True)
    token_id = db.Column(db.Integer, db.ForeignKey('queue_tokens.id'), nullable=False)
    token_number = db.Column(db.String(30), nullable=False)
    called_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    department = db.relationship('Department', backref=db.backref('call_events', lazy='dynamic'))
    doctor = db.relationship('Doctor', backref=db.backref('call_events', lazy='dynamic'))
    token = db.relationship('QueueToken', backref=db.backref('call_events', lazy='dynamic'))

    def __repr__(self):
        return f'<QueueCallEvent #{self.id} Dept:{self.department_id} Token:{self.token_number}>'
