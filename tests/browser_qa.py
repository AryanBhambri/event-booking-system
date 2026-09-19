"""Real Chromium workflows and responsive checks. Run separately from unittest discovery."""
from pathlib import Path
import json
import os
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler

from tests.helpers import image_bytes
from tests.qa_support import QAData


class QuietHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


class BrowserQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = QAData()
        cls.addClassCleanup(cls.data.cleanup)
        cls.data.setup()
        cls.event = cls.data.create_event(title="QA Summer's Workshop " + cls.data.token)
        cls.confirmation = cls.data.clients["user"].post(f"/bookings/events/{cls.event['id']}/book", data={"quantity": "1"}).location
        cls.server = make_server("127.0.0.1", 0, cls.data.app, threaded=True, request_handler=QuietHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(channel=os.getenv("QA_BROWSER_CHANNEL", "msedge"), headless=True)
        cls.addClassCleanup(cls.browser.close)
        cls.artifacts = Path(".qa-artifacts")
        cls.artifacts.mkdir(exist_ok=True)

    def login(self, page, role):
        page.goto(self.base + "/auth/login")
        page.get_by_label("Email address").fill(self.data.emails[role])
        page.get_by_label("Password", exact=True).fill(self.data.password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/admin/" if role == "admin" else "**/dashboard/")

    def test_browser_user_and_admin_workflows(self):
        context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(self.base)
        page.get_by_role("link", name="How it works", exact=True).click()
        self.assertTrue(page.url.endswith("#how-it-works"))
        page.get_by_role("link", name="Explore events").click()
        self.assertTrue(page.url.endswith("/events/"))
        page.get_by_role("link", name="Create account", exact=True).click()
        email = f"qa7-browser-{self.data.token}@example.test"
        page.get_by_label("Full name").fill("QA Browser User")
        page.get_by_label("Email address").fill(email)
        page.get_by_label("Password", exact=True).fill(self.data.password)
        page.get_by_label("Confirm password").fill(self.data.password)
        page.get_by_role("button", name="Create account", exact=True).click()
        page.wait_for_url("**/auth/login")
        self.data.ids["browser"] = self.data.query("SELECT id FROM users WHERE email = %s", (email,))[0]["id"]
        page.get_by_label("Email address").fill(email)
        page.get_by_label("Password", exact=True).fill(self.data.password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/dashboard/")
        page.goto(self.base + "/events/")
        page.get_by_label("Search", exact=True).fill(self.data.token)
        page.get_by_label("Category", exact=True).select_option("QA workshop")
        page.get_by_label("Location", exact=True).select_option("QA City")
        page.get_by_label("Upcoming only").uncheck()
        page.get_by_role("button", name="Apply filters").click()
        self.assertFalse(page.get_by_label("Upcoming only").is_checked())
        page.get_by_role("link", name="View event", exact=True).click()
        page.get_by_role("link", name="Book now", exact=True).click()
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="Increase tickets").click()
        self.assertEqual(page.locator("#total-price").inner_text(), "₹251.00", json.dumps({"errors": errors, "quantity": page.locator('#quantity').input_value(), "scripts": page.locator('script[src]').evaluate_all('elements => elements.map(element => element.src)')}))
        page.get_by_role("button", name="Confirm booking", exact=True).click()
        page.wait_for_url("**/bookings/BK*")
        page.wait_for_load_state("networkidle")
        self.assertIn("251.00", page.locator(".confirmation-total").inner_text())
        page.evaluate("window.print = () => { window.printInvoked = true; }")
        page.get_by_role("button", name="Print confirmation").click()
        self.assertTrue(page.evaluate("window.printInvoked"))
        page.emulate_media(media="print")
        self.assertFalse(page.locator(".site-nav").is_visible())
        self.assertFalse(page.locator(".no-print").is_visible())
        page.pdf(path=str(self.artifacts / "confirmation.pdf"), format="A4")
        page.emulate_media(media="screen")
        page.get_by_role("link", name="View my bookings").click()
        page.get_by_role("link", name="Dashboard", exact=True).click()
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/auth/login")
        self.login(page, "admin")
        self.assertEqual(page.locator("canvas").count(), 3)
        page.wait_for_function("window.Chart && Chart.getChart('bookingsChart')")
        page.get_by_role("link", name="Manage events").click()
        page.get_by_role("link", name="Create event").first.click()
        form = self.data.event_form(title="QA Delete O'Brien " + self.data.token)
        for name, value in form.items():
            page.locator(f'.form-panel [name="{name}"]').fill(value)
        page.locator('[name="image"]').set_input_files({"name": "banner.png", "mimeType": "image/png", "buffer": image_bytes().getvalue()})
        page.get_by_role("button", name="Create event", exact=True).click()
        page.wait_for_url("**/admin/events")
        row = page.locator("tr", has_text=form["title"])
        row.get_by_role("link", name="Edit", exact=True).click()
        page.get_by_label("Venue *", exact=True).fill("Updated QA Hall")
        page.get_by_role("button", name="Save changes").click()
        page.wait_for_url("**/admin/events")
        page.wait_for_load_state("networkidle")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("tr", has_text=form["title"]).get_by_role("button", name="Delete", exact=True).click()
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.locator("tr", has_text=form["title"]).count(), 0)
        for kind in ("bookings", "events", "users"):
            page.goto(self.base + f"/admin/reports/{kind}")
            with page.expect_download() as download:
                page.get_by_role("link", name="Download CSV").click()
            self.assertTrue(download.value.suggested_filename.endswith(".csv"))
            self.assertIsNone(download.value.failure())
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/auth/login")
        self.assertEqual(errors, [])
        (self.artifacts / "workflow-results.json").write_text(json.dumps({"user_workflow": "passed", "admin_workflow": "passed", "javascript_errors": errors, "print_pdf": "confirmation.pdf"}, indent=2), encoding="utf-8")

    def test_responsive_pages_at_three_viewports(self):
        checks = []
        for width, height in ((1440, 1000), (768, 1024), (390, 844)):
            for role in ("anonymous", "user", "admin"):
                context = self.browser.new_context(viewport={"width": width, "height": height})
                try:
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    if role != "anonymous":
                        self.login(page, role)
                    paths = ["/", "/about", "/events/", f"/events/{self.event['id']}", "/auth/login", "/auth/register"] if role == "anonymous" else (["/dashboard/", "/bookings/", self.confirmation, f"/bookings/events/{self.event['id']}/book"] if role == "user" else ["/admin/", "/admin/events", "/admin/reports/bookings", "/admin/reports/events", "/admin/reports/users", "/admin/events/create"])
                    for path in paths:
                        with self.subTest(width=width, role=role, path=path):
                            response = page.goto(self.base + path, wait_until="networkidle")
                            self.assertEqual(response.status, 200)
                            self.assertTrue(page.evaluate("getComputedStyle(document.querySelector('.container')).paddingLeft !== '0px'"), "Bootstrap CSS did not load")
                            overflow = page.evaluate("Array.from(document.querySelectorAll('body *')).filter(element => { const box = element.getBoundingClientRect(); return box.width && (box.right > innerWidth + 1 || box.left < -1) && !element.closest('.table-responsive'); }).map(element => ({tag: element.tagName, class: element.className, width: element.getBoundingClientRect().width}))")
                            page.screenshot(path=str(self.artifacts / f"inspect-{width}-{role}-{path.strip('/').replace('/', '-') or 'home'}.png"), full_page=True)
                            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"), "Page overflows horizontally: " + json.dumps(overflow))
                            self.assertEqual(page.locator("img").evaluate_all("images => images.filter(image => !image.complete || image.naturalWidth === 0).map(image => image.src)"), [])
                            for table in page.locator(".admin-table-wrap").all():
                                self.assertIn(table.evaluate("element => getComputedStyle(element).overflowX"), ("auto", "scroll"))
                            if width < 992:
                                page.get_by_role("button", name="Toggle navigation").click()
                                page.wait_for_function("document.querySelector('#mainNav').classList.contains('show') && !document.querySelector('#mainNav').classList.contains('collapsing')")
                                self.assertTrue(page.get_by_role("link", name="Home", exact=True).is_visible())
                                page.get_by_role("button", name="Toggle navigation").click()
                                page.wait_for_function("!document.querySelector('#mainNav').classList.contains('show') && !document.querySelector('#mainNav').classList.contains('collapsing')")
                            filename = f"{width}-{role}-{path.strip('/').replace('/', '-') or 'home'}.png"
                            page.screenshot(path=str(self.artifacts / filename), full_page=True)
                            checks.append({"width": width, "role": role, "path": path, "status": "passed"})
                    self.assertEqual(errors, [])
                finally:
                    context.close()
        (self.artifacts / "responsive-results.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
