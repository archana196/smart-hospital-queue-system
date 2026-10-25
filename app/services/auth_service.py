"""
auth_service.py – Role-Based Access Control helpers.

Provides route decorators that enforce backend permissions.
The client-side UI may hide buttons, but access is always enforced here,
on the server, regardless of what the browser sends.
"""

from functools import wraps
from flask import abort
from flask_login import current_user


def roles_required(*roles):
    """
    Decorator that requires the current user to have one of the specified roles.
    Usage:
        @roles_required('admin', 'receptionist')
        def my_view(): ...

    Returns HTTP 403 Forbidden if the role is not permitted.
    (Flask-Login's @login_required handles the unauthenticated 401 case separately.)
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
