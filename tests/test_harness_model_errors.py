"""What the model's refusal looks like to the user."""

import io
import unittest
import urllib.error

from harness.agent.models import http_error


def refusal(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x/v1/chat/completions", code, "no", {}, io.BytesIO(body.encode()))


class HttpError(unittest.TestCase):
    def test_a_template_refusal_names_the_cause_and_the_way_out(self):
        text = str(http_error(refusal(400, '{"error":{"message":"Unable to generate parser for this template: '
                                           'Conversation roles must alternate user/assistant"}}')))
        self.assertTrue(text.startswith("HTTP 400:"))
        self.assertIn("Conversation roles must alternate", text)
        self.assertIn("supports tools", text)

    def test_any_other_refusal_is_the_code_and_what_the_server_said_cut_short(self):
        text = str(http_error(refusal(401, "x" * 1000)))
        self.assertEqual(text, "HTTP 401: " + "x" * 300)
        self.assertNotIn("template", str(http_error(refusal(400, "bad json"))))
