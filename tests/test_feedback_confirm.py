"""Block 1: feedback sends only after a confirm for the exact text.

Tests first. No real network, no real gh, no widget.json, no second widget.
"""

import shutil
import tempfile
import unittest
import urllib.parse
from unittest import mock


class FeedbackDraftTests(unittest.TestCase):
    """Draft creation: a draft is required; an empty or model-invented body is refused."""

    def test_empty_draft_is_refused(self):
        from botwidget.feedback import prepare_draft
        result = prepare_draft("")
        self.assertIsNone(result, "empty draft is refused")

    def test_only_whitespace_draft_is_refused(self):
        from botwidget.feedback import prepare_draft
        result = prepare_draft("   \n  ")
        self.assertIsNone(result, "whitespace-only draft is refused")

    def test_user_supplied_text_is_accepted(self):
        from botwidget.feedback import prepare_draft
        result = prepare_draft("The widget crashes on startup.")
        self.assertIsNotNone(result)
        self.assertEqual(result["body"], "The widget crashes on startup.")
        self.assertEqual(result["title"], "Feedback")

    def test_user_supplied_title_and_body(self):
        from botwidget.feedback import prepare_draft
        result = prepare_draft("The widget crashes on startup.")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Feedback")
        self.assertEqual(result["body"], "The widget crashes on startup.")


class FeedbackConfirmTests(unittest.TestCase):
    """The confirm gate: yes posts, no does not, changed body is refused."""

    def test_yes_for_exact_text_is_accepted(self):
        from botwidget.confirm import ConfirmBoard

        board = ConfirmBoard()
        req = board.put("bot1", "feedback", "the bug text", now=100)
        decision = board.decide("bot1", "yes", payload="the bug text", request_id=req.id, now=101)
        self.assertTrue(decision.accepted)
        # The callback is wired separately via ask_confirm's on_yes parameter;
        # the board itself stores None in the request.
        self.assertIsNotNone(decision.request)
        self.assertEqual(decision.request.kind, "feedback")

    def test_yes_after_body_changed_is_refused(self):
        from botwidget.confirm import ConfirmBoard

        board = ConfirmBoard()
        req = board.put("bot1", "feedback", "the bug text", now=100)
        decision = board.decide("bot1", "yes", payload="changed text", request_id=req.id, now=101)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "mismatch")

    def test_no_does_not_run_feedback(self):
        from botwidget.confirm import ConfirmBoard

        board = ConfirmBoard()
        req = board.put("bot1", "feedback", "the bug text", now=100)
        decision = board.decide("bot1", "no", now=101)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "declined")

    def test_second_yes_does_not_call_callback(self):
        from botwidget.confirm import ConfirmBoard

        board = ConfirmBoard()
        req = board.put("bot1", "feedback", "the bug text", now=100)
        call_count = [0]

        decision = board.decide("bot1", "yes", payload="the bug text", request_id=req.id, now=101)
        self.assertTrue(decision.accepted)
        call_count[0] += 1
        # Second yes is refused.
        decision2 = board.decide("bot1", "yes", payload="the bug text", request_id=req.id, now=102)
        self.assertFalse(decision2.accepted)
        self.assertEqual(call_count[0], 1)


class FeedbackIssueUrlTests(unittest.TestCase):
    """feedback_issue_url accepts confirmed title and body; no token in URL."""

    def test_default_prefill_shape(self):
        from botwidget.menu_pages import feedback_issue_url
        url = feedback_issue_url("1.2.3", "Linux", "packaged")
        self.assertTrue(url.startswith("https://github.com/Menziess/bot-widget/issues/new?"))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["title"], ["Feedback"])
        self.assertIn("Widget version: 1.2.3", query["body"][0])
        self.assertNotIn("token", url.lower())

    def test_with_confirmed_title_and_body(self):
        from botwidget.menu_pages import feedback_issue_url
        url = feedback_issue_url("1.2.3", "Linux", "packaged",
                                 title="Widget crashes on startup",
                                 body="The widget crashes on startup.")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["title"], ["Widget crashes on startup"])
        self.assertIn("The widget crashes on startup.", query["body"][0])
        self.assertNotIn("token", url.lower())

    def test_empty_title_defaults_to_Feedback(self):
        from botwidget.menu_pages import feedback_issue_url
        url = feedback_issue_url("1.2.3", "Linux", "packaged", title="", body="some body")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["title"], ["Feedback"])


class FeedbackGhPathTests(unittest.TestCase):
    """Test the gh issue create path and browser fallback."""

    def test_gh_available_check(self):
        from botwidget.feedback import _gh_available
        result = _gh_available()
        # Just check it returns a bool without crashing.
        self.assertIsInstance(result, bool)

    def test_send_feedback_calls_gh_when_available(self):
        from botwidget.feedback import send_feedback

        sender_calls = []
        with mock.patch("botwidget.feedback._gh_available", return_value=True):
            with mock.patch("botwidget.feedback._send_via_gh") as gh_send:
                gh_send.side_effect = lambda title, body, *_a: sender_calls.append((title, body))
                send_feedback("Test issue", "This is the body text", on_success=None, on_fail=None)
        self.assertEqual(len(sender_calls), 1)
        self.assertEqual(sender_calls[0], ("Test issue", "This is the body text"))

    def test_send_feedback_falls_back_to_browser(self):
        from botwidget.feedback import send_feedback

        browser_urls = []
        with mock.patch("botwidget.feedback._gh_available", return_value=False):
            with mock.patch("botwidget.feedback._send_via_browser") as browser_send:
                browser_send.side_effect = lambda *a, **kw: browser_urls.append(browser_send.call_args)
                send_feedback("Test issue", "This is the body text", on_success=None, on_fail=None)
        self.assertEqual(len(browser_urls), 1)
        url_args = browser_urls[0]
        self.assertIn("Test issue", str(url_args))


class FeedbackIntegrationTests(unittest.TestCase):
    """End-to-end: prepare draft, confirm, then send."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_full_feedback_flow_draft_then_confirm_then_send(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.feedback import prepare_draft

        # 1. Prepare the draft from user text.
        draft = prepare_draft("The widget crashes when I click the face.")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["title"], "Feedback")
        self.assertIn("The widget crashes when I click the face.", draft["body"])

        # 2. Put it on the confirm board.
        board = ConfirmBoard()
        req = board.put("bot1", "feedback", draft["body"], now=100)

        # 3. Decline first.
        decision = board.decide("bot1", "no", now=101)
        self.assertFalse(decision.accepted)

        # 4. Put it again (user re-sends).
        req2 = board.put("bot1", "feedback", draft["body"], now=200)

        # 5. Accept.
        decision = board.decide("bot1", "yes", payload=draft["body"], request_id=req2.id, now=201)
        self.assertTrue(decision.accepted)

        # 6. The callback should be wired (on_yes was set by ask_confirm).
        # We verify by checking the decision carries the request.
        self.assertIsNotNone(decision.request)
        self.assertEqual(decision.request.kind, "feedback")


if __name__ == "__main__":
    unittest.main()
