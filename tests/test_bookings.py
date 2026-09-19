"""Integration checks for Phase 4 ticket booking.

Run with: py -m tests.test_bookings
The script creates and removes its own temporary users, event, and bookings.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import create_app
from tests.helpers import CSRFClient
from database.db import get_db_connection


TOKEN = uuid4().hex[:12]
ADMIN_EMAIL = f"phase4-admin-{TOKEN}@example.test"
OWNER_EMAIL = f"phase4-owner-{TOKEN}@example.test"
OTHER_EMAIL = f"phase4-other-{TOKEN}@example.test"
PASSWORD = "Phase4Test9"
TITLE = f"Phase Four Event {TOKEN}"


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
            cursor.execute("DELETE FROM users WHERE email IN (%s, %s, %s)", (ADMIN_EMAIL, OWNER_EMAIL, OTHER_EMAIL))
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
            cursor.execute("INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')", ("Phase Four Admin", ADMIN_EMAIL, generate_password_hash(PASSWORD)))
            admin_id = cursor.lastrowid
            cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)", ("Booking Owner", OWNER_EMAIL, generate_password_hash(PASSWORD)))
            cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)", ("Other User", OTHER_EMAIL, generate_password_hash(PASSWORD)))
            cursor.execute(
                """INSERT INTO events (title, description, category, event_date, event_time, venue, city, ticket_price, total_seats, available_seats, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (TITLE, "A temporary event used to test ticket booking transactions.", "Music", date.today() + timedelta(days=10), "18:30:00", "Test Arena", "Mumbai", Decimal("100.00"), 5, 5, admin_id),
            )
            event_id = cursor.lastrowid
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    client = app.test_client()
    other_client = app.test_client()
    try:
        anonymous = client.get(f"/bookings/events/{event_id}/book")
        assert anonymous.status_code == 302 and "/auth/login?next=" in anonymous.location

        login = client.post(f"/auth/login?next=/bookings/events/{event_id}/book", data={"email": OWNER_EMAIL, "password": PASSWORD})
        assert login.status_code == 302 and login.location.endswith(f"/bookings/events/{event_id}/book")
        assert client.get(f"/bookings/events/{event_id}/book").status_code == 200

        assert client.post(f"/bookings/events/{event_id}/book", data={"quantity": "0"}).status_code == 400
        assert client.post(f"/bookings/events/{event_id}/book", data={"quantity": "-1"}).status_code == 400
        assert client.post(f"/bookings/events/{event_id}/book", data={"quantity": "6"}).status_code == 400

        booked = client.post(f"/bookings/events/{event_id}/book", data={"quantity": "2"})
        assert booked.status_code == 302
        booking_code = booked.location.rsplit("/", 1)[-1]
        assert client.get(booked.location).status_code == 200
        assert client.get("/bookings/").status_code == 200

        with app.app_context():
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT ticket_quantity, total_amount FROM bookings WHERE booking_code = %s", (booking_code,))
            booking = cursor.fetchone()
            cursor.execute("SELECT available_seats FROM events WHERE id = %s", (event_id,))
            availability = cursor.fetchone()["available_seats"]
            cursor.close()
            connection.close()
        assert booking["ticket_quantity"] == 2 and booking["total_amount"] == Decimal("200.00")
        assert availability == 3

        other_login = other_client.post("/auth/login", data={"email": OTHER_EMAIL, "password": PASSWORD})
        assert other_login.status_code == 302
        assert other_client.get(f"/bookings/{booking_code}").status_code == 404
        assert other_client.get("/admin/events").status_code == 302

        sold_out = client.post(f"/bookings/events/{event_id}/book", data={"quantity": "3"})
        assert sold_out.status_code == 302
        assert client.post(f"/bookings/events/{event_id}/book", data={"quantity": "1"}).status_code == 302
        with app.app_context():
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT available_seats FROM events WHERE id = %s", (event_id,))
            assert cursor.fetchone()[0] == 0
            cursor.close()
            connection.close()
        print("Ticket booking integration tests passed.")
    finally:
        clean_up(app)


if __name__ == "__main__":
    main()
