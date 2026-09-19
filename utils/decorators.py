"""Authentication and authorization decorators for protected routes."""
from functools import wraps

from flask import flash, redirect, request, session, url_for


def login_required(view):
    """Require an authenticated user before displaying a view."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    """Require an authenticated administrator before displaying a view."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access the admin area.", "warning")
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            flash("You do not have permission to access that page.", "danger")
            return redirect(url_for("dashboard.index"))
        return view(*args, **kwargs)

    return wrapped_view
