"""The fixture browser returns the title of a local page."""

import os
import tempfile
import unittest

from harness.browser_local import read_page


class FixturePage(unittest.TestCase):
    """Should read a title from a file and not from the network."""

    def test_a_fixture_page_returns_its_title(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        path = os.path.join(folder, "page.html")
        with open(path, "w") as fh:
            fh.write("<html><head><title>Offline title</title></head></html>")
        page = read_page(path)
        self.assertEqual(page["title"], "Offline title")
        self.assertEqual(page["transport"], "fixture")
