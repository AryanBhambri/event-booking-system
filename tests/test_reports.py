"""Integration checks for Phase 6 reports, exports, and confirmation UI.

Run with: py -m tests.test_reports
Temporary database rows are removed at the end of the test.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import create_app
from tests.helpers import CSRFClient
from database.db import get_db_connection


TOKEN = uuid4().hex[:10]
ADMIN_EMAIL = f"phase6-admin-{TOKEN}@example.test"
USER_EMAIL = f"phase6-user-{TOKEN}@example.test"
TITLE = f"Phase Six Event {TOKEN}"
BOOKING_CODE = f"P6{TOKEN.upper()}"


def clean_up(app):
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT id FROM events WHERE title = %s", (TITLE,))
            event = cursor.fetchone()
            if event:
                cursor.execute("DELETE FROM bookings WHERE event_id = %s", (event[0],))
                cursor.execute("DELETE FROM events WHERE id = %s", (event[0],))
            cursor.execute("DELETE FROM users WHERE email IN (%s, %s)", (ADMIN_EMAIL, USER_EMAIL))
            connection.commit()
        finally:
            cursor.close()
            connection.close()


def main():
    app = create_app()
    app.config.update(TESTING=True)
    app.test_client_class = CSRFClient
    clean_up(app)
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')", ("Phase Six Admin", ADMIN_EMAIL, generate_password_hash("Phase6Test9")))
            admin_id = cursor.lastrowid
            cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)", ("Phase Six User", USER_EMAIL, generate_password_hash("Phase6Test9")))
            user_id = cursor.lastrowid
            cursor.execute("""INSERT INTO events (title, description, category, event_date, event_time, venue, city, ticket_price, total_seats, available_seats, created_by)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (TITLE, "Phase Six reporting test event description.", "Festival", date.today() + timedelta(days=8), "18:00:00", "Report Hall", "Pune", Decimal("400.00"), 10, 8, admin_id))
            event_id = cursor.lastrowid
            cursor.execute("INSERT INTO bookings (booking_code, user_id, event_id, ticket_quantity, total_amount) VALUES (%s, %s, %s, %s, %s)", (BOOKING_CODE, user_id, event_id, 2, Decimal("800.00")))
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    user_client = app.test_client()
    admin_client = app.test_client()
    try:
        home = user_client.get("/")
        assert home.status_code == 200 and b"/events/" in home.data and b"how-it-works" in home.data
        assert user_client.get("/admin/reports/bookings").status_code == 302
        with user_client.session_transaction() as session:
            session.update(user_id=user_id, user_name="Phase Six User", role="user")
        confirmation = user_client.get(f"/bookings/{BOOKING_CODE}")
        assert confirmation.status_code == 200 and USER_EMAIL.encode() in confirmation.data and b"Print confirmation" in confirmation.data
        assert user_client.get("/admin/reports/events").status_code == 302

        with admin_client.session_transaction() as session:
            session.update(user_id=admin_id, user_name="Phase Six Admin", role="admin")
        booking_report = admin_client.get(f"/admin/reports/bookings?event_id={event_id}&status=confirmed")
        assert booking_report.status_code == 200 and BOOKING_CODE.encode() in booking_report.data
        assert b"No report data" in admin_client.get("/admin/reports/bookings?date=2000-01-01").data
        assert admin_client.get("/admin/reports/events").status_code == 200
        users = admin_client.get("/admin/reports/users")
        assert users.status_code == 200 and b"password_hash" not in users.data

        csv_export = admin_client.get(f"/admin/reports/bookings/export?event_id={event_id}")
        assert csv_export.status_code == 200 and csv_export.mimetype == "text/csv"
        assert BOOKING_CODE.encode() in csv_export.data and b"password_hash" not in csv_export.data
        assert admin_client.get("/admin/reports/events/export").status_code == 200
        assert admin_client.get("/admin/reports/users/export").status_code == 200
        print("Reports and confirmations integration tests passed.")
    finally:
        clean_up(app)


if __name__ == "__main__":
    main()
