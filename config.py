import os
import warnings

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

_SECRET_KEY = os.environ.get('SECRET_KEY')
if not _SECRET_KEY:
    warnings.warn(
        "SECRET_KEY environment variable is not set. "
        "Using the insecure development default. "
        "NEVER deploy to production without setting a strong SECRET_KEY env variable.",
        stacklevel=2
    )
    _SECRET_KEY = 'smart-hospital-queue-secret-key-2026'

_DEVICE_API_KEY = os.environ.get('DEVICE_API_KEY') or 'dev-esp8266-secret-key-2026'

class Config:
    SECRET_KEY = _SECRET_KEY
    DEVICE_API_KEY = _DEVICE_API_KEY
    
    # Database: SQLite locally, easily configurable for PostgreSQL in production
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(BASE_DIR, 'hospital.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Queue aging mechanism settings (Phase 3 foundation)
    AGING_INTERVAL_MINS = 15
    AGING_BONUS_POINTS = 10
    
    # Priority base scores
    PRIORITY_SCORES = {
        'Emergency': 1000,
        'High': 500,
        'Medium': 200,
        'Normal': 100
    }

class DevelopmentConfig(Config):
    DEBUG = True

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

class ProductionConfig(Config):
    DEBUG = False
    # In production, ensure SECRET_KEY and DATABASE_URL are set via env variables

config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
