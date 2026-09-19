"""Integration checks for Phase 5 dashboards and analytics.

Run with: py -m tests.test_dashboards
Temporary rows are removed after the test completes.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import create_app
from tests.helpers import CSRFClient
from database.db import get_db_connection


TOKEN = uuid4().hex[:12]
ADMIN_EMAIL = f"phase5-admin-{TOKEN}@example.test"
USER_EMAIL = f"phase5-user-{TOKEN}@example.test"
OTHER_EMAIL = f"phase5-other-{TOKEN}@example.test"
UPCOMING_TITLE = f"Phase Five Upcoming {TOKEN}"
PAST_TITLE = f"Phase Five Past {TOKEN}"


def clean_up(app):
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT id FROM events WHERE title IN (%s, %s)", (UPCOMING_TITLE, PAST_TITLE))
            event_ids = [row[0] for row in cursor.fetchall()]
            if event_ids:
                placeholders = ", ".join(["%s"] * len(event_ids))
                cursor.execute(f"DELETE FROM bookings WHERE event_id IN ({placeholders})", tuple(event_ids))
                cursor.execute(f"DELETE FROM events WHERE id IN ({placeholders})", tuple(event_ids))
            cursor.execute("DELETE FROM users WHERE email IN (%s, %s, %s)", (ADMIN_EMAIL, USER_EMAIL, OTHER_EMAIL))
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
            cursor.execute("INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')", ("Phase Five Admin", ADMIN_EMAIL, generate_password_hash("Phase5Test9")))
            admin_id = cursor.lastrowid
            cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)", ("Dashboard User", USER_EMAIL, generate_password_hash("Phase5Test9")))
            user_id = cursor.lastrowid
            cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)", ("Other Dashboard User", OTHER_EMAIL, generate_password_hash("Phase5Test9")))
            other_id = cursor.lastrowid
            cursor.execute("""INSERT INTO events (title, description, category, event_date, event_time, venue, city, ticket_price, total_seats, available_seats, created_by)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (UPCOMING_TITLE, "Upcoming dashboard test event description.", "Music", date.today() + timedelta(days=5), "19:00:00", "Future Hall", "Delhi", Decimal("250.00"), 20, 17, admin_id))
            upcoming_id = cursor.lastrowid
            cursor.execute("""INSERT INTO events (title, description, category, event_date, event_time, venue, city, ticket_price, total_seats, available_seats, created_by)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (PAST_TITLE, "Past dashboard test event description.", "Workshop", date.today() - timedelta(days=5), "10:00:00", "History Hall", "Delhi", Decimal("100.00"), 10, 8, admin_id))
            past_id = cursor.lastrowid
            cursor.execute("INSERT INTO bookings (booking_code, user_id, event_id, ticket_quantity, total_amount) VALUES (%s, %s, %s, %s, %s)", (f"D{TOKEN[:10].upper()}1", user_id, upcoming_id, 3, Decimal("750.00")))
            cursor.execute("INSERT INTO bookings (booking_code, user_id, event_id, ticket_quantity, total_amount) VALUES (%s, %s, %s, %s, %s)", (f"D{TOKEN[:10].upper()}2", user_id, past_id, 2, Decimal("200.00")))
            cursor.execute("INSERT INTO bookings (booking_code, user_id, event_id, ticket_quantity, total_amount) VALUES (%s, %s, %s, %s, %s)", (f"D{TOKEN[:10].upper()}3", other_id, upcoming_id, 1, Decimal("250.00")))
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    user_client = app.test_client()
    admin_client = app.test_client()
    try:
        assert user_client.get("/dashboard/").status_code == 302
        with user_client.session_transaction() as session:
            session.update(user_id=user_id, user_name="Dashboard User", role="user")
        dashboard = user_client.get("/dashboard/")
        assert dashboard.status_code == 200
        assert UPCOMING_TITLE.encode() in dashboard.data and PAST_TITLE.encode() in dashboard.data
        assert b"Other Dashboard User" not in dashboard.data
        assert user_client.get("/admin/").status_code == 302

        with admin_client.session_transaction() as session:
            session.update(user_id=admin_id, user_name="Phase Five Admin", role="admin")
        admin_dashboard = admin_client.get("/admin/")
        assert admin_dashboard.status_code == 200
        assert b"Total users" in admin_dashboard.data
        assert UPCOMING_TITLE.encode() in admin_dashboard.data
        assert b"bookingsChart" in admin_dashboard.data and b"ticketsChart" in admin_dashboard.data and b"revenueChart" in admin_dashboard.data
        assert b"Dashboard User" in admin_dashboard.data
        print("Dashboard analytics integration tests passed.")
    finally:
        clean_up(app)


if __name__ == "__main__":
    main()
