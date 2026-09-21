"""Integration checks for Phase 3 event management.

Run with: py -m tests.test_events
Temporary database rows and uploaded files are removed after the test.
"""
from datetime import date, timedelta
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import create_app
from tests.helpers import CSRFClient, image_bytes
from database.db import get_db_connection
from utils.event_helpers import remove_event_image
from tests.cloudinary_support import MockCloudinary


TOKEN = uuid4().hex[:12]
EMAIL = f"phase3-admin-{TOKEN}@example.test"
TITLE = f"Phase Three Event {TOKEN}"
EVENT_DATE = (date.today() + timedelta(days=7)).isoformat()


def clean_up(app):
    """Remove only the rows and image files created by this test."""
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT image_filename FROM events WHERE title = %s", (TITLE,))
            filenames = [row["image_filename"] for row in cursor.fetchall()]
            cursor.execute("DELETE FROM events WHERE title = %s", (TITLE,))
            cursor.execute("DELETE FROM users WHERE email = %s", (EMAIL,))
            connection.commit()
            for filename in filenames:
                remove_event_image(filename)
        finally:
            cursor.close()
            connection.close()


def event_data(total_seats="30", venue="City Hall"):
    return {"title": TITLE, "description": "A temporary event used to validate Phase 3 event management.", "category": "Workshop", "event_date": EVENT_DATE, "event_time": "18:30", "venue": venue, "city": "Pune", "ticket_price": "299.00", "total_seats": total_seats}


def main():
    app = create_app()
    with MockCloudinary(app) as storage:
        run_checks(app, storage)


def run_checks(app, storage):
    app.config.update(TESTING=True)
    app.test_client_class = CSRFClient
    clean_up(app)
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')", ("Phase Three Admin", EMAIL, generate_password_hash("Phase3Admin9")))
        admin_id = cursor.lastrowid
        connection.commit()
        cursor.close()
        connection.close()

    client = app.test_client()
    try:
        assert client.get("/admin/events").status_code == 302
        with client.session_transaction() as session:
            session["user_id"] = admin_id
            session["user_name"] = "Phase Three Admin"
            session["role"] = "user"
        assert client.get("/admin/events").status_code == 302
        with client.session_transaction() as session:
            session["role"] = "admin"

        invalid = client.post("/admin/events/create", data={"title": "", "description": "short"})
        assert invalid.status_code == 400
        payload = event_data()
        payload["image"] = (image_bytes(), "unsafe banner.png", "image/png")
        created = client.post("/admin/events/create", data=payload, content_type="multipart/form-data")
        assert created.status_code == 302

        with app.app_context():
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM events WHERE title = %s", (TITLE,))
            event = cursor.fetchone()
            cursor.close()
            connection.close()
        assert event["available_seats"] == 30 and event["total_seats"] == 30
        assert event["image_filename"] in {asset["secure_url"] for asset in storage.assets.values()}

        assert client.get("/admin/events").status_code == 200
        assert client.get("/events/").status_code == 200
        assert client.get(f"/events/?search={TOKEN}").status_code == 200
        assert client.get("/events/?category=Workshop&city=Pune&upcoming=1").status_code == 200
        assert client.get(f"/events/{event['id']}").status_code == 200

        updated = event_data(total_seats="45", venue="Updated City Hall")
        updated["image"] = (image_bytes("WEBP"), "replacement.webp", "image/webp")
        edited = client.post(f"/admin/events/{event['id']}/edit", data=updated, content_type="multipart/form-data")
        assert edited.status_code == 302
        with app.app_context():
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM events WHERE id = %s", (event["id"],))
            updated_event = cursor.fetchone()
            cursor.close()
            connection.close()
        assert updated_event["total_seats"] == 45 and updated_event["available_seats"] == 45
        assert updated_event["venue"] == "Updated City Hall" and updated_event["image_filename"] != event["image_filename"]

        deleted = client.post(f"/admin/events/{event['id']}/delete")
        assert deleted.status_code == 302
        assert client.get(f"/events/{event['id']}").status_code == 404
        print("Event management integration tests passed.")
    finally:
        clean_up(app)


if __name__ == "__main__":
    main()
