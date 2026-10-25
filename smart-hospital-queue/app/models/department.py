from app.models import db

class Department(db.Model):
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False) # e.g. CARD, GEN, EMG
    description = db.Column(db.Text, nullable=True)
    
    doctors = db.relationship('Doctor', backref='department', lazy=True)
    tokens = db.relationship('QueueToken', backref='department', lazy=True)
    
    def __repr__(self):
        return f'<Department {self.code} - {self.name}>'
