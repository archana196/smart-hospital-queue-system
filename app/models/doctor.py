from app.models import db

class Doctor(db.Model):
    __tablename__ = 'doctors'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    room_number = db.Column(db.String(20), nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    avg_consultation_mins = db.Column(db.Float, default=10.0)
    
    tokens = db.relationship('QueueToken', backref='assigned_doctor', lazy=True)
    
    def __repr__(self):
        return f'<Doctor ID {self.id} Room {self.room_number}>'
