from flask import Flask
from flask_login import LoginManager
from config import config_by_name
from app.models import db

login_manager = LoginManager()
login_manager.login_view = 'auth.login'           # redirect unauthenticated users here
login_manager.login_message = 'Please log in to access that page.'
login_manager.login_message_category = 'warning'


def create_app(config_name='development'):
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # ── Initialise extensions ──────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)

    # ── User loader callback required by Flask-Login ───────────────────────
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── Template helpers & filters ─────────────────────────────────────────
    import time
    from app.services.queue_service import QueueService
    from app.services.ml_service import MLService

    @app.context_processor
    def inject_helpers():
        return {
            'now_ts': time.time(),
            'get_waiting_duration_mins': QueueService.get_waiting_duration_mins,
            'predict_waiting_time': MLService.predict_waiting_time,
        }

    @app.template_filter('waiting_mins')
    def waiting_mins_filter(token):
        return int(QueueService.get_waiting_duration_mins(token))

    @app.template_filter('predicted_wait')
    def predicted_wait_filter(token):
        return MLService.predict_waiting_time(token)

    @app.template_filter('predicted_wait_label')
    def predicted_wait_label_filter(token):
        pred = MLService.predict_waiting_time(token)
        if pred is None:
            return "Unavailable"
        return f"~{int(round(pred))} mins"

    # ── Register Blueprints ────────────────────────────────────────────────
    from app.routes.main_routes import main_bp
    from app.routes.patient_routes import patient_bp
    from app.routes.api_routes import api_bp
    from app.routes.auth_routes import auth_bp
    from app.routes.doctor_routes import doctor_bp
    from app.routes.admin_routes import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(admin_bp)

    # ── Create tables & safe schema migration ──────────────────────────────
    with app.app_context():
        db.create_all()
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            if 'queue_tokens' in inspector.get_table_names():
                columns = [c['name'] for c in inspector.get_columns('queue_tokens')]
                if 'consultation_started_at' not in columns:
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE queue_tokens ADD COLUMN consultation_started_at DATETIME'))
                        conn.commit()
        except Exception:
            pass

    return app
