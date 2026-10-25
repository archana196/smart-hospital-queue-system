from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Roles: admin, doctor, receptionist, patient
    role = db.Column(db.String(20), nullable=False, default='patient')
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    doctor_profile = db.relationship('Doctor', backref='user', uselist=False, lazy=True)

    def set_password(self, password):
        """Hash and store password — never store plain text."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a candidate password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    # ------ Role helper properties ------
    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_doctor(self):
        return self.role == 'doctor'

    @property
    def is_receptionist(self):
        return self.role == 'receptionist'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
