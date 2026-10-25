"""
auth_routes.py – Login, Logout, and HTTP error pages.

All credential validation happens on the server (backend).
Passwords are always checked via werkzeug's check_password_hash,
never compared as plain text.
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ── Login ────────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Basic server-side input validation
        if not username or not password:
            flash('Username and password are required.', 'warning')
            return render_template('auth/login.html')

        user = User.query.filter_by(username=username).first()

        # Deliberate: give the same error for wrong user or wrong password
        # to avoid username enumeration attacks.
        if user is None or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        login_user(user)
        flash(f'Welcome back, {user.full_name}!', 'success')

        # Honour the 'next' parameter but only for safe same-origin paths
        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        return _redirect_by_role(user)

    return render_template('auth/login.html')


# ── Logout ───────────────────────────────────────────────────────────────────

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


# ── Role-based post-login redirect ───────────────────────────────────────────

def _redirect_by_role(user):
    if user.role == 'doctor':
        return redirect(url_for('doctor.dashboard'))
    if user.role == 'admin':
        return redirect(url_for('admin.queue_dashboard'))
    if user.role == 'receptionist':
        return redirect(url_for('admin.queue_dashboard'))
    return redirect(url_for('main.index'))


# ── HTTP error pages ─────────────────────────────────────────────────────────

@auth_bp.app_errorhandler(401)
def unauthorized(e):
    flash('Please log in to access that page.', 'warning')
    return redirect(url_for('auth.login', next=request.path))


@auth_bp.app_errorhandler(403)
def forbidden(e):
    return render_template('auth/403.html'), 403


@auth_bp.app_errorhandler(404)
def not_found(e):
    return render_template('auth/404.html'), 404
