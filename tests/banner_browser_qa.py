"""Focused banner preview, confirmation and responsive browser checks."""
from base64 import b64encode
from io import BytesIO
from pathlib import Path
from threading import Thread
import unittest

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.qa_support import QAData


class BannerBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = QAData()
        cls.addClassCleanup(cls.data.cleanup)
        cls.data.setup()
        cls.event = cls.data.create_event()
        cls.server = make_server("127.0.0.1", 0, cls.data.app, threaded=True)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(channel="msedge", headless=True)
        cls.addClassCleanup(cls.browser.close)

    def test_preview_replace_confirm_remove(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(self.base + "/auth/login")
        page.get_by_label("Email address").fill(self.data.emails["admin"])
        page.get_by_label("Password", exact=True).fill(self.data.password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        path = f"/admin/events/{self.event['id']}/edit"
        page.goto(self.base + path, wait_until="networkidle")
        page.locator("#image").set_input_files({"name": "fake.png", "mimeType": "image/png", "buffer": b"invalid image"})
        page.locator("#banner-error").wait_for(state="visible")
        page.get_by_role("button", name="Clear selected image").click()
        self.assertTrue(page.locator("#banner-error").is_hidden())
        image = BytesIO()
        Image.new("RGB", (600, 1200), "orange").save(image, format="PNG")
        page.locator("#image").set_input_files({"name": "portrait.png", "mimeType": "image/png", "buffer": image.getvalue()})
        page.wait_for_function("document.querySelector('#banner-preview').src.startsWith('blob:')")
        self.assertEqual(page.locator("#banner-preview").evaluate("image => getComputedStyle(image).objectFit"), "contain")
        page.get_by_role("button", name="Save changes").click()
        page.wait_for_url("**/admin/events")
        page.goto(self.base + path)
        page.get_by_role("link", name="Remove Banner", exact=True).click()
        page.get_by_role("link", name="Cancel", exact=True).click()
        self.assertTrue(page.get_by_role("link", name="Remove Banner", exact=True).is_visible())
        page.get_by_role("link", name="Remove Banner", exact=True).click()
        page.get_by_role("button", name="Confirm Remove Banner", exact=True).click()
        page.wait_for_url("**/edit")
        self.assertIn("default-event.svg", page.locator("#banner-preview").get_attribute("src"))
        response = page.goto(self.base + f"/events/{self.event['id']}")
        self.assertEqual(response.status, 200)
        self.assertIn("default-event.svg", page.locator(".event-detail-hero img").get_attribute("src"))
        self.assertEqual(errors, [])

    def test_complete_images_at_three_viewports(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        css = Path("static/css/style.css").read_text(encoding="utf-8")
        for width in (1440, 768, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            for w, h in ((1600, 900), (600, 1200), (8000, 1000)):
                with self.subTest(viewport=width, image=(w, h)):
                    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><rect width="100%" height="100%" fill="orange"/></svg>'
                    url = "data:image/svg+xml;base64," + b64encode(svg.encode()).decode()
                    page.set_content('<style>body{margin:0}' + css + '</style><section class="event-detail-hero"><img src="' + url + '"></section>')
                    data = page.locator(".event-detail-hero img").evaluate("image => ({fit:getComputedStyle(image).objectFit,position:getComputedStyle(image).objectPosition,width:image.width,height:image.height,overflow:document.documentElement.scrollWidth>innerWidth,loaded:image.complete && image.naturalWidth>0})")
                    self.assertEqual(data["fit"], "contain")
                    self.assertEqual(data["position"], "50% 50%")
                    self.assertAlmostEqual(data["width"] / data["height"], 16/9, places=2)
                    self.assertFalse(data["overflow"])
                    self.assertTrue(data["loaded"])
