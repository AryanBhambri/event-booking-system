"""Regression checks for confirmed Phase 7 defects and complete route coverage."""
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, timedelta
from html.parser import HTMLParser
from io import BytesIO, StringIO
from threading import Barrier
import unittest
from unittest.mock import patch, MagicMock

from mysql.connector import Error

from app import create_app
from config import Config
from routes.auth import safe_next_url
from tests.helpers import image_bytes
from tests.qa_support import QAData
from tests.cloudinary_support import MockCloudinary
from utils.event_helpers import validate_event_form, save_event_image
from werkzeug.datastructures import FileStorage


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.images, self.ids = [], [], set()
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "a" and "href" in attributes:
            self.links.append(attributes["href"])
        if tag == "img":
            self.images.append(attributes.get("src", ""))


class SecurityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.enterContext(MockCloudinary(self.app))

    def test_csrf_rejects_missing_and_invalid_tokens(self):
        client = self.app.test_client()
        for token in (None, "invalid"):
            data = {} if token is None else {"csrf_token": token}
            for path in ("/auth/register", "/auth/login", "/auth/logout", "/admin/events/create", "/admin/events/1/delete", "/bookings/events/1/book"):
                with self.subTest(path=path, token=token):
                    self.assertEqual(client.post(path, data=data).status_code, 400)

    def test_redirects_reject_external_and_malformed_targets(self):
        for target in ("https://evil.test", "//evil.test", "/\\evil.test", "///evil.test", "//[", "/\nevil.test"):
            with self.subTest(target=target):
                self.assertIsNone(safe_next_url(target))
        self.assertEqual(safe_next_url("/events/?category=Music"), "/events/?category=Music")

    def test_numeric_validation_respects_database_limits(self):
        form = QAData().event_form()
        for value in ("NaN", "sNaN", "Infinity", "-Infinity", "100000000.00", "0.001", "-1"):
            with self.subTest(price=value):
                self.assertTrue(validate_event_form({**form, "ticket_price": value})[1])
        self.assertTrue(validate_event_form({**form, "total_seats": "4294967296"})[1])

    def test_upload_rejects_forged_and_oversized_images(self):
        with self.app.app_context():
            for data, name, mime in ((b"not an image", "image.png", "image/png"), (b"<svg></svg>", "image.svg", "image/svg+xml"), (b"x" * (5 * 1024 * 1024 + 1), "large.png", "image/png")):
                filename, error = save_event_image(FileStorage(BytesIO(data), filename=name, content_type=mime))
                self.assertIsNone(filename)
                self.assertTrue(error)
            filename, error = save_event_image(FileStorage(image_bytes(), filename="image.webp", content_type="image/webp"))
            self.assertIsNone(filename)
            self.assertTrue(error)

    def test_oversized_request_has_useful_error(self):
        response = self.app.test_client().post("/auth/login", data={"payload": "x" * (7 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)
        self.assertIn(b"Upload too large", response.data)

    def test_database_outage_has_useful_error(self):
        with patch("routes.events.get_db_connection", side_effect=Error("private diagnostic", errno=2003)):
            response = self.app.test_client().get("/events/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private diagnostic", response.data)

    def test_placeholder_secret_is_rejected(self):
        class UnsafeConfig(Config):
            SECRET_KEY = "replace-with-a-long-random-secret"
        with self.assertRaises(RuntimeError):
            create_app(UnsafeConfig)

    def test_all_templates_compile(self):
        for name in self.app.jinja_env.list_templates():
            with self.subTest(template=name):
                self.app.jinja_env.get_template(name)


class WorkflowRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = QAData()
        cls.addClassCleanup(cls.data.cleanup)
        cls.data.setup()

    def test_all_admin_routes_are_protected(self):
        clients = [self.data.app.test_client(), self.data.clients["user"]]
        for rule in self.data.app.url_map.iter_rules():
            if not rule.endpoint.startswith("admin."):
                continue
            path = str(rule).replace("<int:event_id>", "4294967295")
            method = "GET" if "GET" in rule.methods else "POST"
            for client in clients:
                with self.subTest(path=path, method=method):
                    response = client.open(path, method=method)
                    self.assertEqual(response.status_code, 302)
                    self.assertIn(response.location.split("?")[0], ("/auth/login", "/dashboard/"))

    def test_navigation_links_images_and_role_visibility(self):
        event = self.data.create_event()
        user = self.data.clients["user"]
        confirmation = user.post(f"/bookings/events/{event['id']}/book", data={"quantity": "1"}).location
        for role in ("anonymous", "user", "admin"):
            client = self.data.app.test_client() if role == "anonymous" else self.data.clients[role]
            checked_links, checked_images = set(), set()
            paths = ["/", "/about", "/events/", f"/events/{event['id']}"]
            paths += ["/auth/login", "/auth/register"] if role == "anonymous" else ["/dashboard/", "/bookings/", f"/bookings/events/{event['id']}/book"]
            if role == "user":
                paths += [confirmation]
            if role == "admin":
                paths += ["/admin/", "/admin/events", "/admin/events/create", f"/admin/events/{event['id']}/edit", "/admin/reports/bookings", "/admin/reports/events", "/admin/reports/users"]
            for path in paths:
                with self.subTest(role=role, path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    markup = Markup(response.get_data(as_text=True))
                    for link in markup.links:
                        if link.startswith("#"):
                            self.assertIn(link[1:], markup.ids)
                        elif link.startswith("/") and link not in checked_links:
                            with client.get(link, follow_redirects=True) as linked:
                                self.assertLess(linked.status_code, 400, link)
                            checked_links.add(link)
                    for image in markup.images:
                        if image.startswith("https://"):
                            if image == event["image_filename"]:
                                self.assertIn(image, {asset["secure_url"] for asset in self.data.cloudinary.assets.values()})
                            continue
                        if image not in checked_images:
                            with client.get(image) as loaded:
                                self.assertEqual(loaded.status_code, 200, image)
                            checked_images.add(image)
                    self.assertNotIn(b"password_hash", response.data)
                    nav = response.get_data(as_text=True).split("</nav>")[0]
                    self.assertEqual('href="/admin/"' in nav, role == "admin")
                    self.assertEqual('href="/bookings/"' in nav, role != "anonymous")
                    self.assertEqual('href="/auth/login"' in nav, role == "anonymous")

    def test_booking_total_and_price_snapshot(self):
        event = self.data.create_event()
        client = self.data.clients["user"]
        response = client.post(f"/bookings/events/{event['id']}/book", data={"quantity": "2", "total_amount": "0.01"})
        self.assertEqual(response.status_code, 302)
        self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data=self.data.event_form(ticket_price="200.00"))
        confirmation = client.get(response.location)
        self.assertIn(b"125.50", confirmation.data)
        self.assertIn(b"251.00", confirmation.data)
        row = self.data.query("SELECT available_seats FROM events WHERE id = %s", (event["id"],))[0]
        self.assertEqual(row["available_seats"], 6)
        self.assertEqual(self.data.clients["other"].get(response.location).status_code, 404)
        self.assertEqual(client.get("/bookings/not-a-booking").status_code, 404)

    def test_edit_preserves_seats_booked_since_form_read(self):
        event = self.data.create_event()
        from routes.admin import get_event_or_404
        def stale_read(event_id):
            old = get_event_or_404(event_id)
            self.data.clients["user"].post(f"/bookings/events/{event_id}/book", data={"quantity": "2"})
            return old
        with patch("routes.admin.get_event_or_404", side_effect=stale_read):
            response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data=self.data.event_form(total_seats="10"))
        self.assertEqual(response.status_code, 302)
        row = self.data.query("SELECT total_seats, available_seats FROM events WHERE id = %s", (event["id"],))[0]
        self.assertEqual(row, {"total_seats": 10, "available_seats": 8})

    def test_concurrent_bookings_cannot_oversell(self):
        event = self.data.create_event(total_seats="1")
        barrier = Barrier(2)
        def book(role):
            client = self.data.clients[role]
            barrier.wait(timeout=10)
            return client.post(f"/bookings/events/{event['id']}/book", data={"quantity": "1"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(book, ("user", "other"))), [302, 302])
        self.assertEqual(self.data.query("SELECT available_seats FROM events WHERE id = %s", (event["id"],))[0]["available_seats"], 0)
        self.assertEqual(self.data.query("SELECT COUNT(*) AS count FROM bookings WHERE event_id = %s", (event["id"],))[0]["count"], 1)

    def test_past_and_sold_out_events(self):
        event = self.data.create_event()
        client = self.data.clients["user"]
        self.data.query("UPDATE events SET event_date = %s WHERE id = %s", (date.today() - timedelta(days=1), event["id"]), write=True)
        response = client.post(f"/bookings/events/{event['id']}/book", data={"quantity": "1"}, follow_redirects=True)
        self.assertIn(b"Booking is closed", response.data)
        self.assertEqual(self.data.query("SELECT COUNT(*) AS count FROM bookings WHERE event_id = %s", (event["id"],))[0]["count"], 0)
        self.assertNotIn(str(event["id"]).encode() + b'">', client.get("/events/?upcoming=1").data)
        self.assertIn(f'/events/{event["id"]}'.encode(), client.get("/events/?upcoming=0").data)
        self.assertIn(b"No events found", client.get("/events/?search=" + self.data.token + "-none").data)
        self.assertEqual(client.get("/events/4294967295").status_code, 404)

    def test_csv_formula_protection_and_report_filters(self):
        event = self.data.create_event(title="=1+1", venue="@SUM(1)", city="+1")
        self.data.query("UPDATE users SET name = %s WHERE id = %s", ("=1+1", self.data.ids["user"]), write=True)
        self.data.clients["user"].post(f"/bookings/events/{event['id']}/book", data={"quantity": "1"})
        admin = self.data.clients["admin"]
        for kind in ("bookings", "events", "users"):
            response = admin.get(f"/admin/reports/{kind}/export")
            self.assertEqual(response.status_code, 200)
            rows = list(csv.reader(StringIO(response.get_data(as_text=True))))
            self.assertTrue(any("'=1+1" in row for row in rows))
            self.assertNotIn(b"password_hash", response.data)
        response = admin.get(f"/admin/reports/bookings/export?event_id={event['id']}&status=confirmed")
        self.assertEqual(len(list(csv.reader(StringIO(response.get_data(as_text=True))))), 2)
        self.assertIn(b"No report data", admin.get("/admin/reports/bookings?date=1900-01-01").data)

    def test_delete_with_bookings_is_blocked(self):
        event = self.data.create_event()
        self.data.clients["user"].post(f"/bookings/events/{event['id']}/book", data={"quantity": "1"})
        response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/delete", follow_redirects=True)
        self.assertIn(b"has bookings and cannot be deleted", response.data)
        self.assertTrue(self.data.query("SELECT id FROM events WHERE id = %s", (event["id"],)))

    def test_empty_states_without_deleting_existing_data(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = {key: 0 for key in ("total_users", "total_events", "total_bookings", "total_tickets", "total_revenue", "active_users", "upcoming_bookings", "past_bookings")}
        connection = MagicMock()
        connection.cursor.return_value = cursor
        cases = [("routes.events", "/events/", "user", b"No events found"), ("routes.bookings", "/bookings/", "user", b"No bookings yet"), ("routes.dashboard", "/dashboard/", "user", b"No upcoming bookings"), ("routes.admin", "/admin/", "admin", b"No bookings"), ("routes.admin", "/admin/events", "admin", b"No events yet"), ("routes.admin", "/admin/reports/events", "admin", b"No events to report"), ("routes.admin", "/admin/reports/users", "admin", b"No registered users")]
        for module, path, role, message in cases:
            with self.subTest(path=path), patch(module + ".get_db_connection", return_value=connection):
                response = self.data.clients[role].get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.data)
