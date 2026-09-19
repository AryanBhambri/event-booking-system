"""Expose the six original integration scripts to unittest discovery."""
import importlib
import unittest


class ExistingIntegrationTests(unittest.TestCase):
    """Each case executes every assertion in one original script."""


def module_test(name):
    def run(self):
        importlib.import_module(f"tests.test_{name}").main()
    return run


for name in ("about", "auth", "events", "bookings", "dashboards", "reports"):
    setattr(ExistingIntegrationTests, f"test_{name}", module_test(name))
