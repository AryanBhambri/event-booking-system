"""Registration, login, and logout routes."""
import re
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db_connection

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def safe_next_url(next_url):
    """Allow redirects only to local paths after a successful login."""
    if not next_url:
        return None
    if next_url.startswith("//") or "\\" in next_url or any(ord(character) < 32 for character in next_url):
        return None
    try:
        parsed_url = urlparse(next_url)
    except ValueError:
        return None
    if parsed_url.scheme or parsed_url.netloc or not next_url.startswith("/"):
        return None
    return next_url


def validate_registration(name, email, password, confirm_password):
    """Return user-friendly validation messages for a registration form."""
    errors = []
    if not 2 <= len(name) <= 100:
        errors.append("Full name must contain between 2 and 100 characters.")
    if len(email) > 150 or not EMAIL_PATTERN.match(email):
        errors.append("Enter a valid email address.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    elif not (re.search(r"[A-Z]", password) and re.search(r"[a-z]", password) and re.search(r"\d", password)):
        errors.append("Password must include an uppercase letter, lowercase letter, and number.")
    if password != confirm_password:
        errors.append("Password and confirm password must match.")
    return errors


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Create a normal user account in the existing users table."""
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = validate_registration(name, email, password, confirm_password)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("register.html"), 400

        connection = cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("An account with that email already exists. Please sign in.", "danger")
                return render_template("register.html"), 409
            cursor.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                (name, email, generate_password_hash(password)),
            )
            connection.commit()
            flash("Your account was created. Please sign in.", "success")
            return redirect(url_for("auth.login"))
        except Error as error:
            if connection:
                connection.rollback()
            if error.errno == 1062:
                flash("An account with that email already exists. Please sign in.", "danger")
                return render_template("register.html"), 409
            flash("We could not create your account. Please try again.", "danger")
            return render_template("register.html"), 500
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Verify a user password and establish a signed Flask session."""
    if session.get("user_id"):
        return redirect(safe_next_url(request.args.get("next")) or url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Enter both your email address and password.", "danger")
            return render_template("login.html"), 400
        connection = cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id, name, password_hash, role FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
        except Error:
            flash("We could not sign you in right now. Please try again.", "danger")
            return render_template("login.html"), 500
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return render_template("login.html"), 401
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["role"] = user["role"]
        flash(f"Welcome back, {user['name']}!", "success")
        next_url = safe_next_url(request.args.get("next"))
        if next_url:
            return redirect(next_url)
        return redirect(url_for("admin.index" if user["role"] == "admin" else "dashboard.index"))
    return render_template("login.html")


@auth_bp.post("/logout")
def logout():
    """End the signed-in session."""
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
