"""browser_tabs should number tabs and show a tab count line at the end."""

import unittest
from unittest import mock


class TestBrowserTabsNumbering(unittest.TestCase):
    """Should number tabs and append the total count."""

    def test_numbered_tabs_and_footer(self):
        # Mock the attach() call to return fake tab data
        fake_tabs = [
            {"title": "Tab One", "url": "https://example.com/one"},
            {"title": "Tab Two", "url": "https://example.com/two"},
        ]
        mock_attach = mock.Mock(return_value=mock.Mock(list_tabs=mock.Mock(return_value=fake_tabs)))

        with mock.patch("harness.browser_local.attach", mock_attach):
            # Import the actual browser_tabs function
            from harness.agent.tools import browser_tabs
            result = browser_tabs()

        lines = result.split("\n")
        # Each tab: number+title line + indented URL line; then footer
        # 2 tabs => 4 tab lines + 1 footer = 5 lines
        self.assertEqual(len(lines), 5)
        self.assertIn("1. Tab One", lines[0])
        self.assertIn("example.com/one", lines[1])
        self.assertIn("2. Tab Two", lines[2])
        self.assertIn("example.com/two", lines[3])
        self.assertEqual(lines[4], "2 tabs")

    def test_single_tab(self):
        fake_tabs = [{"title": "Only One", "url": "https://only.test"}]
        mock_attach = mock.Mock(return_value=mock.Mock(list_tabs=mock.Mock(return_value=fake_tabs)))

        with mock.patch("harness.browser_local.attach", mock_attach):
            from harness.agent.tools import browser_tabs
            result = browser_tabs()

        lines = result.split("\n")
        # 1 tab => 2 tab lines + 1 footer = 3 lines
        self.assertEqual(len(lines), 3)
        self.assertIn("1. Only One", lines[0])
        self.assertIn("only.test", lines[1])
        self.assertEqual(lines[2], "1 tab")

    def test_no_tabs(self):
        mock_attach = mock.Mock(return_value=mock.Mock(list_tabs=mock.Mock(return_value=[])))

        with mock.patch("harness.browser_local.attach", mock_attach):
            from harness.agent.tools import browser_tabs
            result = browser_tabs()

        self.assertEqual(result, "No open tabs.")

    def test_connection_error(self):
        mock_attach = mock.Mock(side_effect=ConnectionError("Chrome not listening"))

        with mock.patch("harness.browser_local.attach", mock_attach):
            from harness.agent.tools import browser_tabs
            with self.assertRaises(Exception) as ctx:
                browser_tabs()
            self.assertIn("Chrome is not listening", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
