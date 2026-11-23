"""A key goes only where it is safe to send it, and never follows a redirect or shows in an error."""

import io
import os
import stat
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

from harness.agent.models import ChatCompletions, ModelError, http_error
from harness.agent.netsafe import key_file_problem, key_may_travel, open_url, private_host, redact


class Where(unittest.TestCase):
    def test_https_goes_anywhere_and_plain_http_only_to_your_own_machines(self):
        for url in ("https://api.x.ai/v1", "http://127.0.0.1:8080/v1", "http://localhost/v1", "http://[::1]:1/v1",
                    "http://192.168.1.20:8000/v1", "http://10.0.0.5/v1", "http://gpu-box:8000/v1",
                    "http://nas.local/v1", "http://169.254.1.1/v1"):
            self.assertTrue(key_may_travel(url), url)
        for url in ("http://api.example.com/v1", "http://8.8.8.8/v1", "ftp://x/v1", "https://user:pw@api.x.ai/v1",
                    "http://user@localhost/v1", ""):
            self.assertFalse(key_may_travel(url), url)
        self.assertFalse(private_host("evil.com") or private_host(""))

    def test_the_client_refuses_to_attach_a_key_for_a_public_http_address(self):
        with self.assertRaises(ModelError) as caught:
            ChatCompletions("http://api.example.com/v1", "m", api_key="sk-secret-123")._headers()
        self.assertIn("https://", str(caught.exception))
        self.assertNotIn("sk-secret-123", str(caught.exception))
        self.assertEqual(ChatCompletions("http://api.example.com/v1", "m")._headers(), {}, "no key, nothing to guard")


class Redirects(unittest.TestCase):
    def test_a_redirect_is_not_followed_so_the_key_never_reaches_another_address(self):
        seen = []

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

        target = HTTPServer(("127.0.0.1", 0), Target)

        class Origin(Target):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/stolen")
                self.end_headers()

        origin = HTTPServer(("127.0.0.1", 0), Origin)
        for server in (target, origin):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
        import urllib.request
        request = urllib.request.Request(f"http://127.0.0.1:{origin.server_address[1]}/v1/models",
                                         headers={"Authorization": "Bearer sk-secret-123"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            open_url(request, 5)
        self.assertEqual(caught.exception.code, 302)
        self.assertEqual(seen, [], "the second server never saw the key")


class Leaks(unittest.TestCase):
    def test_a_key_the_server_quotes_in_its_error_is_hidden(self):
        body = '{"error":"Incorrect API key provided: sk-secret-123456"}'
        error = urllib.error.HTTPError("http://x", 401, "no", {}, io.BytesIO(body.encode()))
        text = str(http_error(error, "sk-secret-123456"))
        self.assertNotIn("sk-secret-123456", text)
        self.assertIn("[key]", text)
        self.assertEqual(redact("abc", ""), "abc")
        self.assertEqual(redact("abc", "abc"), "abc", "a secret too short to be one is left alone")


class Files(unittest.TestCase):
    def test_a_key_file_other_users_can_read_is_named_and_a_private_one_is_not(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "key")
        with open(path, "w") as fh:
            fh.write("sk-secret-123456")
        os.chmod(path, 0o644)
        self.addCleanup(lambda: (os.chmod(path, 0o600), os.remove(path), os.rmdir(folder)))
        self.assertIn("chmod 600", key_file_problem(path))
        os.chmod(path, 0o600)
        self.assertEqual(key_file_problem(path), "")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(key_file_problem(os.path.join(folder, "missing")), "")
