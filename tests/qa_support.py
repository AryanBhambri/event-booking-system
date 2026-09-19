"""Disposable QA records in the existing database; no schema changes."""
from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import create_app
from database.db import get_db_connection
from tests.helpers import CSRFClient, image_bytes


class QAData:
    def __init__(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, DEBUG=False)
        self.app.test_client_class = CSRFClient
        self.token = uuid4().hex
        self.password = "QaWorkflow9!"
        self.emails = {role: f"qa7-{role}-{self.token}@example.test" for role in ("admin", "user", "other")}
        self.ids = {}
        self.events = []
        self.clients = {}

    def query(self, sql, params=(), *, write=False):
        with self.app.app_context():
            connection = get_db_connection()
            try:
                cursor = connection.cursor(dictionary=True)
                try:
                    cursor.execute(sql, params)
                    result = cursor.lastrowid if write else cursor.fetchall()
                    if write:
                        connection.commit()
                    return result
                finally:
                    cursor.close()
            finally:
                connection.close()

    def setup(self):
        for role, email in self.emails.items():
            self.ids[role] = self.query(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (f"QA {role}", email, generate_password_hash(self.password), "admin" if role == "admin" else "user"), write=True,
            )
            client = self.app.test_client()
            response = client.post("/auth/login", data={"email": email, "password": self.password})
            assert response.status_code == 302
            self.clients[role] = client

    def event_form(self, **overrides):
        values = {"title": f"QA event {self.token}", "description": "Temporary QA event for complete workflow validation.", "category": "QA workshop", "event_date": (date.today() + timedelta(days=14)).isoformat(), "event_time": "18:30", "venue": "QA Hall", "city": "QA City", "ticket_price": "125.50", "total_seats": "8"}
        values.update(overrides)
        return values

    def create_event(self, **overrides):
        form = self.event_form(**overrides)
        response = self.clients["admin"].post("/admin/events/create", data={**form, "image": (image_bytes(), "banner.png", "image/png")})
        assert response.status_code == 302, response.status_code
        event = self.query("SELECT * FROM events WHERE created_by = %s ORDER BY id DESC LIMIT 1", (self.ids["admin"],))[0]
        self.events.append(event["id"])
        return event

    def cleanup(self):
        if "admin" in self.ids:
            images = self.query("SELECT image_filename FROM events WHERE created_by = %s", (self.ids["admin"],))
            self.query("DELETE bookings FROM bookings JOIN events ON bookings.event_id = events.id WHERE events.created_by = %s", (self.ids["admin"],), write=True)
            self.query("DELETE FROM events WHERE created_by = %s", (self.ids["admin"],), write=True)
            with self.app.app_context():
                from utils.event_helpers import remove_event_image
                for row in images:
                    remove_event_image(row["image_filename"])
        for user_id in self.ids.values():
            self.query("DELETE FROM users WHERE id = %s", (user_id,), write=True)


@contextmanager
def qa_data():
    data = QAData()
    try:
        data.setup()
        yield data
    finally:
        data.cleanup()
