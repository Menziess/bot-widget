"""The fixture browser returns the title of a local page.

The same module's DevTools calls are driven through a scripted socket, so a
missing Chrome still proves list, switch, navigation, read, screenshot, click
and in-page fetch.
"""

import os
import tempfile
import unittest

from harness.browser_local import Cdp, read_page, redact, websocket_from_port_file


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


class Scripted:
    """Records DevTools calls and returns the next queued result."""

    def __init__(self, replies):
        self.calls = []
        self.replies = list(replies)

    def __call__(self, method, params, session_id):
        self.calls.append((method, params, session_id))
        return self.replies.pop(0) if self.replies else {}


class DirectCdp(unittest.TestCase):
    """Should drive the shipped Cdp methods, including the rule that a window is never opened."""

    def test_list_and_switch_reuse_tabs(self):
        socket = Scripted([{"targetInfos": [
            {"targetId": "a", "type": "page", "title": "One", "url": "https://one.example"},
            {"targetId": "b", "type": "page", "title": "Two", "url": "https://two.example"},
            {"targetId": "w", "type": "worker", "title": "", "url": ""},
        ]}])
        browser = Cdp(socket)
        self.assertEqual([tab["id"] for tab in browser.list_tabs()], ["a", "b"])
        browser.switch_tab("b")
        self.assertEqual(socket.calls[1][0], "Target.activateTarget")
        self.assertNotIn("Target.createTarget", [call[0] for call in socket.calls])

    def test_a_new_tab_is_not_a_new_window(self):
        socket = Scripted([{"targetId": "fresh"}])
        tab = Cdp(socket).open_tab("https://example.test")
        method, params, _session = socket.calls[0]
        self.assertEqual(tab, "fresh")
        self.assertEqual(method, "Target.createTarget")
        self.assertEqual(params["newWindow"], False)
        self.assertEqual(params["url"], "https://example.test")

    def test_goto_waits_until_the_document_has_loaded(self):
        socket = Scripted([
            {"frameId": "f"},
            {"result": {"value": "interactive"}},
            {"result": {"value": "complete"}},
        ])
        Cdp(socket).goto_url("https://example.test/next")
        self.assertEqual(socket.calls[0][0], "Page.navigate")
        self.assertEqual(socket.calls[0][1]["url"], "https://example.test/next")
        states = [call[1]["expression"] for call in socket.calls if call[0] == "Runtime.evaluate"]
        self.assertEqual(states, ["document.readyState", "document.readyState"])

    def test_read_text_uses_inner_text(self):
        socket = Scripted([{"result": {"value": "Hello page"}}])
        self.assertEqual(Cdp(socket).read_text(), "Hello page")
        self.assertIn("document.body.innerText", socket.calls[0][1]["expression"])

    def test_screenshot_does_not_activate_the_tab(self):
        socket = Scripted([{"data": "abc"}])
        self.assertEqual(Cdp(socket).screenshot(), "abc")
        self.assertEqual([call[0] for call in socket.calls], ["Page.captureScreenshot"])

    def test_click_uses_element_click_on_the_visible_text(self):
        socket = Scripted([{"result": {"value": True}}])
        self.assertTrue(Cdp(socket).click_text("Save"))
        expression = socket.calls[0][1]["expression"]
        self.assertIn("element.click()", expression)
        self.assertIn("Save", expression)
        self.assertNotIn("Input.dispatchMouseEvent", expression)

    def test_page_fetch_keeps_the_session_and_hides_tokens(self):
        body = '{"access_token":"super-secret-token"} Authorization: Bearer super-secret-token'
        socket = Scripted([{"result": {"value": {"status": 200, "body": body}}}])
        fetched = Cdp(socket).page_fetch("https://example.test/me")
        expression = socket.calls[0][1]["expression"]
        self.assertIn("fetch(", expression)
        self.assertIn("credentials", expression)
        self.assertTrue(socket.calls[0][1]["awaitPromise"])
        self.assertEqual(fetched["status"], 200)
        self.assertNotIn("super-secret-token", fetched["body"])
        self.assertIn("[redacted]", fetched["body"])
        self.assertNotIn("super-secret-token", redact(body))

    def test_the_port_file_is_the_browser_socket_when_json_version_is_closed(self):
        url = websocket_from_port_file("9222\n/devtools/browser/abc\n")
        self.assertEqual(url, "ws://127.0.0.1:9222/devtools/browser/abc")
