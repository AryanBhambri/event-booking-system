"""Application entry point for the Event Booking System."""
import click
from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect, CSRFError
from mysql.connector import Error

from config import Config
from routes.auth import auth_bp
from routes.events import events_bp
from routes.bookings import bookings_bp
from routes.dashboard import dashboard_bp
from routes.admin import admin_bp


def create_app(config_class=Config):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    if not app.secret_key or len(app.secret_key) < 32 or app.secret_key in {
        "change-this-development-secret", "replace-with-a-long-random-secret"
    }:
        raise RuntimeError("Set SECRET_KEY to a unique random value of at least 32 characters.")
    CSRFProtect(app)

    # Blueprints keep each feature area in a small, easy-to-find module.
    app.register_blueprint(auth_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)

    @app.cli.command("check-db")
    def check_database_connection():
        """Confirm that Flask can connect to the configured MySQL database."""
        from database.db import get_db_connection

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT DATABASE()")
            database_name = cursor.fetchone()[0]
            click.echo(f"Database connection successful: {database_name}")
        except Error as error:
            raise click.ClickException(f"Database connection failed: {error}") from error
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None and connection.is_connected():
                connection.close()

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/about")
    def about():
        """Describe Evently and its event-discovery experience."""
        return render_template("about.html")

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template("500.html"), 500

    @app.errorhandler(CSRFError)
    def invalid_form(error):
        return render_template("request-error.html", title="Please reload the form", message="Your form session expired or could not be verified. Go back, reload the page, and try again."), 400

    @app.errorhandler(413)
    def upload_too_large(error):
        return render_template("request-error.html", title="Upload too large", message="Choose an image no larger than 5 MB and submit the form again."), 413

    @app.errorhandler(Error)
    def database_unavailable(error):
        app.logger.error("Database request failed (error %s).", error.errno)
        return render_template("request-error.html", title="Temporarily unavailable", message="We could not load your data. Please try again shortly."), 503

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if response.mimetype in {"text/html", "text/csv"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
