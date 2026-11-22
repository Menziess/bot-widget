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

    def test_a_fake_devtools_port_file_is_the_socket(self):
        import tempfile
        from unittest import mock

        from harness import browser_local

        class Socket:
            urls = []

            def __init__(self, url):
                Socket.urls.append(url)

            def call(self, method, params=None, session_id=None):
                return {"targetInfos": []}

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "DevToolsActivePort")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("9333\n/devtools/browser/fixture\n")
            browser_local._shared.clear()
            with mock.patch.object(browser_local, "WebSocketCdp", Socket), \
                    mock.patch.object(browser_local, "devtools_version", return_value=None), \
                    mock.patch.object(browser_local.subprocess, "run", return_value=mock.Mock(stdout="")):
                browser_local.attach(port_file=path).list_tabs()
            browser_local._shared.clear()
        self.assertEqual(Socket.urls, ["ws://127.0.0.1:9333/devtools/browser/fixture"])

    def test_the_port_file_is_the_browser_socket_when_json_version_is_closed(self):
        url = websocket_from_port_file("9222\n/devtools/browser/abc\n")
        self.assertEqual(url, "ws://127.0.0.1:9222/devtools/browser/abc")

    def test_one_connection_serves_every_call_and_a_dead_one_is_replaced(self):
        from unittest import mock

        from harness import browser_local

        class Socket:
            made = []

            def __init__(self, url):
                self.dead = False
                Socket.made.append(self)

            def call(self, method, params=None, session_id=None):
                if self.dead:
                    raise ConnectionError("socket closed")
                return {"ok": method}

        browser_local._shared.clear()
        with mock.patch.object(browser_local, "WebSocketCdp", Socket):
            call = browser_local._shared_call("ws://x")
            call("a"), browser_local._shared_call("ws://x")("b")
            self.assertEqual(len(Socket.made), 1, "Chrome asks the user for every new connection")
            Socket.made[0].dead = True
            self.assertEqual(call("c"), {"ok": "c"})
        self.assertEqual(len(Socket.made), 2)
        browser_local._shared.clear()

    def test_chrome_is_found_from_the_system_when_its_own_folder_is_off_limits(self):
        from unittest import mock

        from harness import browser_local

        class Socket:
            def __init__(self, url):
                if "1111" in url:
                    raise ConnectionError("HTTP/1.1 403 Forbidden")
                self.url = url

            def call(self, method, params=None, session_id=None):
                return {"targetInfos": [{"targetId": "t", "type": "page", "title": self.url, "url": "u"}]}

        listing = mock.Mock(stdout="p1\nn127.0.0.1:1111\nn*:5000\nn127.0.0.1:2222\n")
        browser_local._shared.clear()
        with mock.patch.object(browser_local.subprocess, "run", return_value=listing), \
                mock.patch.object(browser_local, "devtools_version", return_value=None), \
                mock.patch.object(browser_local, "WebSocketCdp", Socket), \
                mock.patch("builtins.open", side_effect=PermissionError("Operation not permitted")):
            tabs = browser_local.attach().list_tabs()
        browser_local._shared.clear()
        self.assertEqual(tabs[0]["title"], "ws://127.0.0.1:2222/devtools/browser")
