from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from app.models.user import User
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.token import QueueToken

__all__ = ['db', 'User', 'Department', 'Doctor', 'Patient', 'QueueToken']
