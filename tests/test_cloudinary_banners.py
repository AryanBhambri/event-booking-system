"""Storage and rendering tests: no database or real Cloudinary calls."""
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

from flask import render_template
from PIL import Image
from werkzeug.datastructures import FileStorage

from app import create_app
from tests.cloudinary_support import MockCloudinary
from tests.helpers import image_bytes
from utils.event_helpers import event_image_url, owned_event_image_id, remove_event_image, remove_unreferenced_event_image, save_event_image


class CloudinaryBannerTests(TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.storage = self.enterContext(MockCloudinary(self.app))
        self.enterContext(self.app.test_request_context())

    def upload(self, extension="png", image_format="PNG"):
        return save_event_image(FileStorage(image_bytes(image_format), filename="../../user supplied." + extension, content_type="image/" + extension))

    def test_upload_validated_stream_with_controlled_id(self):
        for extension, image_format in (("png", "PNG"), ("jpg", "JPEG"), ("jpeg", "JPEG"), ("gif", "GIF"), ("webp", "WEBP")):
            with self.subTest(extension=extension):
                url, error = self.upload(extension, image_format)
                self.assertIsNone(error)
                self.assertLessEqual(len(url), 255)
                options = self.storage.upload.call_args.kwargs
                self.assertRegex(options["public_id"], r"^evently/event-banners/[0-9a-f]{32}$")
                self.assertEqual(options["asset_folder"], "evently/event-banners")
                self.assertFalse(options["overwrite"])
                self.assertFalse(options["use_filename"])
                self.assertEqual(url, self.storage.assets[options["public_id"]]["secure_url"])
                self.assertEqual(owned_event_image_id(url), options["public_id"])

    def test_shared_url_helper(self):
        for value, expected in ((None, "/static/images/default-event.svg"), ("", "/static/images/default-event.svg"), ("legacy.png", "/static/uploads/legacy.png"), ("https://external.example/banner.png", "https://external.example/banner.png")):
            self.assertEqual(event_image_url(value), expected)

    def test_all_eight_templates_render_external_legacy_and_default(self):
        templates = ("events.html", "event-details.html", "admin/events.html", "admin/event-form.html", "admin/remove-banner.html", "booking.html", "booking-confirmation.html", "dashboard.html")
        event = dict(id=1, title="Test banner", description="A test event", category="Music", event_date=date.today(), event_time=time(18), event_time_display="06:00 PM", event_time_input="18:00", venue="Hall", city="Pune", ticket_price=Decimal("10.00"), total_seats=10, available_seats=10, has_started=False, event_status="Upcoming")
        for value in ("https://external.example/banner.png", "legacy.png", None):
            event["image_filename"] = value
            booking = {**event, "user_name": "Test", "user_email": "test@example.test", "booking_code": "ABC123", "ticket_quantity": 1, "total_amount": Decimal("10.00"), "booked_at": datetime.now(), "status": "confirmed"}
            for template in templates:
                with self.subTest(template=template, image=value):
                    html = render_template(
                        template, event=event, events=[event], booking=booking,
                        upcoming_bookings=[booking], categories=[], cities=[],
                        filters={"upcoming": True}, form_title="Edit event",
                        summary={"total_bookings": 1, "upcoming_bookings": 1, "past_bookings": 0, "total_tickets": 1},
                        recent_bookings=[], booking_history=[],
                    )
                    if template == "admin/remove-banner.html" and value is None:
                        self.assertIn("already uses the default banner", html)
                    else:
                        self.assertIn('src="' + event_image_url(value) + '"', html)

    def test_rejects_invalid_content_before_cloudinary(self):
        cases = ((b"fake", "banner.png", "image/png"), (image_bytes().getvalue(), "banner.jpg", "image/jpeg"), (image_bytes().getvalue(), "banner.png", "text/plain"), (b"<svg/>", "banner.svg", "image/svg+xml"), (b"x" * (5 * 1024 * 1024 + 1), "banner.png", "image/png"))
        for content, filename, mime in cases:
            with self.subTest(filename=filename, mime=mime):
                url, error = save_event_image(FileStorage(BytesIO(content), filename=filename, content_type=mime))
                self.assertIsNone(url)
                self.assertTrue(error)
        self.storage.upload.assert_not_called()

    def test_decompression_bomb_rejected_before_cloudinary(self):
        with patch.object(Image, "MAX_IMAGE_PIXELS", 500):
            self.assertIsNone(self.upload()[0])
        self.storage.upload.assert_not_called()

    def test_missing_configuration_does_not_fall_back_to_disk(self):
        with patch.dict(self.app.config, {"CLOUDINARY_API_SECRET": ""}):
            url, error = self.upload()
        self.assertIsNone(url)
        self.assertIn("not configured", error)
        self.storage.upload.assert_not_called()

    def test_255_accepted_256_rejected_without_truncation(self):
        def upload(stream, **options):
            result = self.storage.upload_image(stream, **options)
            url = result["secure_url"]
            result["secure_url"] = url.replace("/v1/", "/v" + "1" * (1 + target - len(url)) + "/")
            return result
        for target in (255, 256):
            with self.subTest(length=target), patch("cloudinary.uploader.upload", side_effect=upload):
                url, error = self.upload()
                if target == 255:
                    self.assertEqual(len(url), 255)
                    self.assertIsNone(error)
                    self.assertEqual(url, next(iter(self.storage.assets.values()))["secure_url"])
                else:
                    self.assertIsNone(url)
                    self.assertIn("255-character", error)
                    self.assertEqual(len(self.storage.assets), 1)

    def test_untrusted_urls_are_never_deleted(self):
        url, _ = self.upload()
        for candidate in (None, "legacy.png", "https://evil.example/banner.png", url.replace("https:", "http:"), url.replace("evently-tests", "another-account"), url.replace("event-banners", "other-folder"), url.replace("res.cloudinary.com/", "res.cloudinary.com.evil.example/"), url.replace("res.cloudinary.com/", "res.cloudinary.com@evil.example/"), url + "?x=1", url + "#fragment", url + "\n", url.replace("/image/upload/", "/video/upload/"), url.replace("/v1/", "/w_100/v1/"), url.replace("/evently/", "/%65vently/"), url.replace("/v1/", "/v1/../"), url.replace(".png", "/../victim.png")):
            with self.subTest(url=candidate):
                remove_event_image(candidate)
        self.storage.destroy.assert_not_called()
        remove_event_image(url)
        self.storage.destroy.assert_called_once()
        self.assertTrue(self.storage.destroy.call_args.kwargs["invalidate"])

    def test_invalid_upload_url_cleans_only_generated_id(self):
        def upload(stream, **options):
            result = self.storage.upload_image(stream, **options)
            result["secure_url"] = "https://other.example/unrelated.png"
            return result
        with patch("cloudinary.uploader.upload", side_effect=upload):
            url, error = self.upload()
        self.assertIsNone(url)
        self.assertIn("valid secure", error)
        self.assertEqual(self.storage.assets, {})
        self.assertRegex(self.storage.destroy.call_args.args[0], r"^evently/event-banners/[0-9a-f]{32}$")

    def test_existing_asset_collision_is_never_deleted(self):
        with patch("cloudinary.uploader.upload", return_value={"existing": True}):
            self.assertIsNone(self.upload()[0])
        self.storage.destroy.assert_not_called()

    def test_reference_check_failure_retains_asset(self):
        from mysql.connector import Error
        url, _ = self.upload()
        with patch("database.db.get_db_connection", side_effect=Error("offline")):
            remove_unreferenced_event_image(url)
        self.storage.destroy.assert_not_called()
