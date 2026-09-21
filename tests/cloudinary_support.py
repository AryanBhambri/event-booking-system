"""In-memory Cloudinary mock shared by integration and browser tests."""
from contextlib import ExitStack
from unittest.mock import patch

from PIL import Image


class MockCloudinary:
    def __init__(self, app):
        self.app = app
        self.assets = {}
        self.stack = ExitStack()

    def __enter__(self):
        self.stack.enter_context(patch.dict(self.app.config, {
            "CLOUDINARY_CLOUD_NAME": "evently-tests",
            "CLOUDINARY_API_KEY": "test-key",
            "CLOUDINARY_API_SECRET": "test-secret",
        }))
        # Fail closed if a future test bypasses the mocked SDK entry points.
        self.stack.enter_context(patch("cloudinary.uploader.call_api", side_effect=AssertionError("Real Cloudinary requests are forbidden in tests")))
        self.upload = self.stack.enter_context(patch("cloudinary.uploader.upload", side_effect=self.upload_image))
        self.destroy = self.stack.enter_context(patch("cloudinary.uploader.destroy", side_effect=self.destroy_image))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def upload_image(self, stream, **options):
        with Image.open(stream) as image:
            extension = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}[image.format]
        public_id = options["public_id"]
        result = {
            "public_id": public_id,
            "secure_url": f"https://res.cloudinary.com/{options['cloud_name']}/image/upload/v1/{public_id}.{extension}",
        }
        self.assets[public_id] = result
        return result

    def destroy_image(self, public_id, **options):
        return {"result": "ok" if self.assets.pop(public_id, None) else "not found"}


def mock_browser_images(context):
    """Browser QA never requests the mock account's images from the real CDN."""
    context.route("https://res.cloudinary.com/evently-tests/**", lambda route: route.fulfill(
        status=200, content_type="image/svg+xml",
        body='<svg xmlns="http://www.w3.org/2000/svg" width="32" height="24"><rect width="32" height="24" fill="orange"/></svg>',
    ))
