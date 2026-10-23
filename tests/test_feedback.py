"""The /feedback link is a prefilled GitHub issue, with no token."""

import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botwidget.menu_pages import feedback_issue_url
from botwidget.startup import install_kind


class FeedbackTests(unittest.TestCase):
    def test_the_link_prefills_version_os_and_install(self):
        url = feedback_issue_url("1.2.3", "Linux", "packaged")
        self.assertTrue(url.startswith("https://github.com/Menziess/bot-widget/issues/new?"))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["title"], ["Feedback"])
        self.assertIn("Widget version: 1.2.3", query["body"][0])
        self.assertIn("OS: Linux", query["body"][0])
        self.assertIn("Install: packaged", query["body"][0])
        self.assertNotIn("token", url.lower())

    def test_a_checkout_is_not_called_uv(self):
        self.assertIn(install_kind(), ("packaged", "checkout", "uv"))


if __name__ == "__main__":
    unittest.main()
