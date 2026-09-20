"""Banner-only regressions using disposable QA records and uploaded files."""
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

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

    def test_replace_banner_removes_old_unreferenced_file(self):
        event = self.data.create_event()
        old = Path(self.data.app.config["UPLOAD_FOLDER"]) / event["image_filename"]
        self.assertTrue(old.is_file())
        response = self.data.clients["admin"].post(f"/admin/events/{event['id']}/edit", data={**self.data.event_form(), "image": (image_bytes("WEBP"), "../../replacement.webp", "image/webp")})
        self.assertEqual(response.status_code, 302)
        current = self.event(event["id"])
        self.assertNotEqual(current["image_filename"], event["image_filename"])
        self.assertNotIn("/", current["image_filename"])
        self.assertTrue((old.parent / current["image_filename"]).is_file())
        self.assertFalse(old.exists())

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
        self.assertFalse((Path(self.data.app.config["UPLOAD_FOLDER"]) / event["image_filename"]).exists())
        self.assertIn(b"images/default-event.svg", self.data.clients["user"].get(f"/events/{event['id']}").data)

    def test_shared_banner_retained_until_last_reference_removed(self):
        first = self.data.create_event()
        second = self.data.create_event()
        own_image = second["image_filename"]
        self.data.query("UPDATE events SET image_filename = %s WHERE id = %s", (first["image_filename"], second["id"]), write=True)
        with self.data.app.app_context():
            remove_event_image(own_image)
        path = Path(self.data.app.config["UPLOAD_FOLDER"]) / first["image_filename"]
        self.assertEqual(self.remove(first).status_code, 302)
        self.assertTrue(path.is_file())
        self.assertEqual(self.remove(self.event(second["id"])).status_code, 302)
        self.assertFalse(path.exists())

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

    def test_file_delete_failure_does_not_undo_removal(self):
        event = self.data.create_event()
        path = Path(self.data.app.config["UPLOAD_FOLDER"]) / event["image_filename"]
        try:
            with patch("utils.event_helpers.Path.unlink", side_effect=PermissionError):
                self.assertEqual(self.remove(event).status_code, 302)
            self.assertIsNone(self.event(event["id"])["image_filename"])
        finally:
            with self.data.app.app_context():
                remove_event_image(event["image_filename"])
