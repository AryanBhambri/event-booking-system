"""Banner regressions using disposable QA records and mocked Cloudinary."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch
from mysql.connector import Error

from tests.helpers import image_bytes
from tests.qa_support import QAData
from utils.event_helpers import remove_event_image


class BannerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = QAData()
        cls.addClassCleanup(cls.data.cleanup)
        cls.data.setup()

    def event(self, event_id):
        return self.data.query("SELECT * FROM events WHERE id = %s", (event_id,))[0]

    def asset_exists(self, url):
        return url in {asset["secure_url"] for asset in self.data.cloudinary.assets.values()}

    def remove(self, event):
        return self.data.clients["admin"].post(
            f"/admin/events/{event['id']}/banner/remove",
            data={"confirm_remove": "1", "image_filename": event["image_filename"]},
        )

    def test_create_without_banner_uses_placeholder(self):
        response = self.data.clients["admin"].post("/admin/events/create", data=self.data.event_form())
        self.assertEqual(response.status_code, 302)
        event = self.data.query("SELECT * FROM events WHERE created_by = %s ORDER BY id DESC LIMIT 1", (self.data.ids["admin"],))[0]
        self.assertIsNone(event["image_filename"])
        page = self.data.clients["user"].get(f"/events/{event['id']}")
        self.assertIn(b"images/default-event.svg", page.data)

    def test_replace_banner_removes_old_unreferenced_asset(self):
        event = self.data.create_event()
        self.assertTrue(self.asset_exists(event["image_filename"]))
        response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (image_bytes("WEBP"), "../../replacement.webp", "image/webp")})
        self.assertEqual(response.status_code, 302)
        current = self.event(event["id"])
        self.assertNotEqual(current["image_filename"], event["image_filename"])
        self.assertTrue(current["image_filename"].startswith("https://res.cloudinary.com/evently-tests/"))
        self.assertTrue(self.asset_exists(current["image_filename"]))
        self.assertFalse(self.asset_exists(event["image_filename"]))

    def test_remove_requires_confirmation_and_preserves_event_and_bookings(self):
        event = self.data.create_event()
        self.data.clients["user"].post(f"/bookings/events/{event['id']}/book", data={"quantity": "1"})
        before = self.event(event["id"])
        bookings = self.data.query("SELECT * FROM bookings WHERE event_id = %s", (event["id"],))
        path = f"/admin/events/{event['id']}/banner/remove"
        self.assertEqual(self.data.clients["admin"].get(path).status_code, 200)
        self.assertEqual(self.data.clients["admin"].post(path, data={}).status_code, 400)
        self.assertEqual(self.event(event["id"])["image_filename"], event["image_filename"])
        self.assertEqual(self.remove(event).status_code, 302)
        after = self.event(event["id"])
        self.assertIsNone(after["image_filename"])
        for key in before.keys() - {"image_filename", "updated_at"}:
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(bookings, self.data.query("SELECT * FROM bookings WHERE event_id = %s", (event["id"],)))
        self.assertFalse(self.asset_exists(event["image_filename"]))
        self.assertIn(b"images/default-event.svg", self.data.clients["user"].get(f"/events/{event['id']}").data)

    def test_shared_banner_retained_until_last_reference_removed(self):
        first = self.data.create_event()
        second = self.data.create_event()
        own_image = second["image_filename"]
        self.data.query("UPDATE events SET image_filename = %s WHERE id = %s", (first["image_filename"], second["id"]), write=True)
        with self.data.app.app_context():
            remove_event_image(own_image)
        self.assertEqual(self.remove(first).status_code, 302)
        self.assertTrue(self.asset_exists(first["image_filename"]))
        self.assertEqual(self.remove(self.event(second["id"])).status_code, 302)
        self.assertFalse(self.asset_exists(first["image_filename"]))

    def test_stale_removal_cannot_remove_replacement(self):
        event = self.data.create_event()
        self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (image_bytes(), "new.png", "image/png")})
        current = self.event(event["id"])
        response = self.remove(event)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.event(event["id"])["image_filename"], current["image_filename"])

    def test_invalid_replacement_keeps_existing_banner(self):
        event = self.data.create_event()
        response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (BytesIO(b"not an image"), "fake.png", "image/png")})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"valid, undamaged image", response.data)
        self.assertEqual(self.event(event["id"])["image_filename"], event["image_filename"])

    def test_cloudinary_delete_failure_does_not_undo_removal(self):
        event = self.data.create_event()
        try:
            with patch("cloudinary.uploader.destroy", side_effect=OSError("offline")):
                self.assertEqual(self.remove(event).status_code, 302)
            self.assertIsNone(self.event(event["id"])["image_filename"])
        finally:
            with self.data.app.app_context():
                remove_event_image(event["image_filename"])

    def test_failed_upload_preserves_event(self):
        event = self.data.create_event()
        with patch("cloudinary.uploader.upload", side_effect=OSError("private diagnostic")):
            response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (image_bytes(), "new.png", "image/png")})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"could not be uploaded", response.data)
        self.assertNotIn(b"private diagnostic", response.data)
        self.assertEqual(self.event(event["id"]), event)
        self.assertTrue(self.asset_exists(event["image_filename"]))

    def test_overlong_url_preserves_event_and_cleans_new_asset(self):
        event = self.data.create_event()
        assets_before = dict(self.data.cloudinary.assets)
        def upload(stream, **options):
            result = self.data.cloudinary.upload_image(stream, **options)
            result["secure_url"] += "x" * 256
            return result
        with patch("cloudinary.uploader.upload", side_effect=upload):
            response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (image_bytes(), "new.png", "image/png")})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"255-character", response.data)
        self.assertEqual(self.event(event["id"]), event)
        self.assertEqual(self.data.cloudinary.assets, assets_before)

    def test_database_failure_cleans_new_upload_for_create_and_edit(self):
        event = self.data.create_event()
        assets_before = dict(self.data.cloudinary.assets)
        from routes.admin import get_db_connection
        for path in ("/admin/events/create", f"/admin/events/{event['id']}/edit"):
            with self.subTest(path=path):
                # Editing first reads the event; fail only the subsequent write connection.
                if path.endswith("/edit"):
                    with self.data.app.app_context():
                        read_connection = get_db_connection()
                    effects = [read_connection, Error("simulated database outage")]
                else:
                    effects = Error("simulated database outage")
                with patch("routes.admin.get_db_connection", side_effect=effects):
                    response = self.data.clients["admin"].post(path, data={**self.data.event_form(), "image": (image_bytes(), "new.png", "image/png")})
                self.assertEqual(response.status_code, 500)
                self.assertEqual(self.event(event["id"]), event)
                self.assertEqual(self.data.cloudinary.assets, assets_before)

    def test_legacy_file_survives_removal_and_replacement(self):
        with TemporaryDirectory() as directory, patch.dict(self.data.app.config, {"UPLOAD_FOLDER": directory}):
            legacy = Path(directory) / "legacy.png"
            legacy.write_bytes(image_bytes().getvalue())
            for action in ("remove", "replace"):
                event = self.data.create_event()
                with self.data.app.app_context():
                    remove_event_image(event["image_filename"])
                self.data.query("UPDATE events SET image_filename = %s WHERE id = %s", ("legacy.png", event["id"]), write=True)
                event = self.event(event["id"])
                page = self.data.clients["user"].get(f"/events/{event['id']}")
                self.assertIn(b'/static/uploads/legacy.png', page.data)
                if action == "remove":
                    response = self.remove(event)
                else:
                    response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (image_bytes(), "new.png", "image/png")})
                self.assertEqual(response.status_code, 302)
                self.assertTrue(legacy.is_file())

    def test_commit_failure_rolls_back_event_and_cleans_new_asset(self):
        from routes.admin import get_db_connection
        event = self.data.create_event()
        assets_before = dict(self.data.cloudinary.assets)
        for path in ("/admin/events/create", f"/admin/events/{event['id']}/edit"):
            with self.subTest(path=path):
                before = self.data.query("SELECT * FROM events WHERE created_by = %s ORDER BY id", (self.data.ids["admin"],))
                with self.data.app.app_context():
                    write_connection = get_db_connection()
                    connections = [get_db_connection()] if path.endswith("/edit") else []
                failing = MagicMock(wraps=write_connection)
                failing.commit.side_effect = Error("simulated commit failure")
                connections.append(failing)
                try:
                    with patch("routes.admin.get_db_connection", side_effect=connections):
                        response = self.data.clients["admin"].post(path, data={**self.data.event_form(), "image": (image_bytes(), "new.png", "image/png")})
                    self.assertEqual(response.status_code, 500)
                    failing.rollback.assert_called_once()
                    self.assertEqual(self.data.query("SELECT * FROM events WHERE created_by = %s ORDER BY id", (self.data.ids["admin"],)), before)
                    self.assertEqual(self.data.cloudinary.assets, assets_before)
                finally:
                    if write_connection.is_connected():
                        write_connection.rollback()
                        write_connection.close()

    def test_remove_arbitrary_external_url_never_calls_destroy(self):
        event = self.data.create_event()
        with self.data.app.app_context():
            remove_event_image(event["image_filename"])
        self.data.query("UPDATE events SET image_filename = %s WHERE id = %s", ("https://other.example/banner.png", event["id"]), write=True)
        with patch("cloudinary.uploader.destroy") as destroy:
            self.assertEqual(self.remove(self.event(event["id"])).status_code, 302)
            destroy.assert_not_called()
        self.assertIsNone(self.event(event["id"])["image_filename"])
