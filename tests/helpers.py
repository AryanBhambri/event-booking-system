"""Test clients submit real CSRF tokens, just like browser forms."""
from io import BytesIO
import re

from flask.testing import FlaskClient
from PIL import Image


class CSRFClient(FlaskClient):
    def open(self, *args, **kwargs):
        if kwargs.get("method", "GET").upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            data = kwargs.get("data", {})
            if isinstance(data, dict) and "csrf_token" not in data:
                response = super().open("/about")
                token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
                if token is None:
                    response = super().open("/auth/login")
                    token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
                if token is None:
                    raise AssertionError("No CSRF token found in rendered form")
                kwargs["data"] = {**data, "csrf_token": token[1].decode()}
        return super().open(*args, **kwargs)


def image_bytes(image_format="PNG"):
    stream = BytesIO()
    Image.new("RGB", (32, 24), "orange").save(stream, format=image_format)
    stream.seek(0)
    return stream
