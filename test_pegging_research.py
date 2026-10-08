"""Collect scratch research regressions in the ordinary CI unittest discovery."""

import importlib
import unittest


def load_tests(loader, _tests, _pattern):
    """Load namespace-directory tests without installing scratch as a package."""
    suite = unittest.TestSuite()
    for name in (
        "scratch.test_pegging_opening_book",
        "scratch.test_pegging_book_checks",
        "scratch.test_exact_pegging_book",
    ):
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    return suite
