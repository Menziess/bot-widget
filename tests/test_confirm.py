"""Confirm primitive: toolkit-free logic tests, then an offscreen Qt smoke test.

Unit tests go against a pure-Python module (no PySide6 import).
The smoke test creates a FaceWindow with a temp config and clicks buttons.
"""

import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config


class PayloadHashTests(unittest.TestCase):
    """payload_hash returns the SHA-256 hex of the UTF-8 payload."""

    def test_returns_hex_digest(self):
        from botwidget.confirm import payload_hash
        result = payload_hash("hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        self.assertEqual(result, expected)

    def test_different_payloads_have_different_hashes(self):
        from botwidget.confirm import payload_hash
        self.assertNotEqual(payload_hash("a"), payload_hash("b"))

    def test_same_payload_is_same_hash(self):
        from botwidget.confirm import payload_hash
        self.assertEqual(payload_hash("same"), payload_hash("same"))


class ConfirmBoardTests(unittest.TestCase):
    """ConfirmBoard.put / get / decide behaviour. No Qt required."""

    def setUp(self):
        from botwidget import confirm
        self.board = confirm.ConfirmBoard()

    def test_yes_with_matching_hash_is_accepted_once(self):
        board = self.board
        req = board.put("bot1", "action", "echo hello", now=100)
        decision = board.decide("bot1", "yes", payload="echo hello", request_id=req.id, now=101)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "accepted")
        # Second yes for the same hash is refused.
        decision2 = board.decide("bot1", "yes", payload="echo hello", request_id=req.id, now=102)
        self.assertFalse(decision2.accepted)
        self.assertEqual(decision2.reason, "no_request")

    def test_yes_after_payload_changed_is_mismatch(self):
        board = self.board
        req = board.put("bot1", "action", "echo hello", now=100)
        decision = board.decide("bot1", "yes", payload="echo world", request_id=req.id, now=101)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "mismatch")

    def test_no_does_not_accept(self):
        board = self.board
        req = board.put("bot1", "action", "echo hello", now=100)
        decision = board.decide("bot1", "no", now=101)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "declined")

    def test_expired_request_is_refused(self):
        board = self.board
        req = board.put("bot1", "action", "echo hello", ttl=600, now=100)
        # After expiry (100 + 600 = 700).
        decision = board.decide("bot1", "yes", payload="echo hello", request_id=req.id, now=701)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "expired")

    def test_second_put_replaces_the_first(self):
        board = self.board
        req1 = board.put("bot1", "action", "first", now=100)
        req2 = board.put("bot1", "action", "second", now=110)
        # The first is replaced; yes for it is refused.
        decision = board.decide("bot1", "yes", payload="first", request_id=req1.id, now=120)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "no_request")
        # The second is the active one.
        decision2 = board.decide("bot1", "yes", payload="second", request_id=req2.id, now=120)
        self.assertTrue(decision2.accepted)
        self.assertEqual(decision2.reason, "accepted")

    def test_feedback_and_vault_always_is_ignored(self):
        board = self.board
        # feedback with always=True: always is silently ignored.
        req_fb = board.put("bot1", "feedback", "send issue", now=100, always=True)
        decision_fb = board.decide("bot1", "yes", payload="send issue", request_id=req_fb.id, now=101)
        self.assertTrue(decision_fb.accepted)
        self.assertEqual(decision_fb.always_allowed, False)
        # vault with always=True: same.
        req_vt = board.put("bot1", "vault", "get token", now=100, always=True)
        decision_vt = board.decide("bot1", "yes", payload="get token", request_id=req_vt.id, now=101)
        self.assertTrue(decision_vt.accepted)
        self.assertEqual(decision_vt.always_allowed, False)

    def test_action_and_routine_can_be_always_allowed(self):
        board = self.board
        req = board.put("bot1", "action", "echo hi", now=100, always=True)
        self.assertTrue(req.always_allowed)
        decision = board.decide("bot1", "yes", payload="echo hi", request_id=req.id, now=101)
        self.assertTrue(decision.accepted)
        self.assertTrue(decision.always_allowed)
        # A second yes for the same payload hash should be refused (still one use).
        decision2 = board.decide("bot1", "yes", payload="echo hi", request_id=req.id, now=102)
        self.assertFalse(decision2.accepted)
        self.assertEqual(decision2.reason, "no_request")

    def test_a_new_put_with_the_same_payload_can_be_accepted_again(self):
        """Once is per request, not a lifetime ban on that text."""
        board = self.board
        first = board.put("bot1", "feedback", "the same wording", now=100)
        self.assertTrue(board.decide("bot1", "yes", payload="the same wording",
                                     request_id=first.id, now=101).accepted)
        second = board.put("bot1", "feedback", "the same wording", now=200)
        again = board.decide("bot1", "yes", payload="the same wording",
                             request_id=second.id, now=201)
        self.assertTrue(again.accepted)
        self.assertEqual(again.reason, "accepted")

    def test_typed_yes_without_a_confirm_returns_no_request(self):
        board = self.board
        decision = board.decide("bot1", "yes", now=101)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "no_request")


class BlocksTests(unittest.TestCase):
    """blocks(request) returns bubble blocks with the payload and actions."""

    def test_blocks_contains_code_block_with_payload(self):
        from botwidget.confirm import ConfirmBoard
        board = ConfirmBoard()
        req = board.put("bot1", "action", "echo hello", now=100)
        blocks = board.blocks(req)
        block_lines = [b.get("lines", []) for b in blocks if b.get("kind") == "code"]
        found = False
        for lines in block_lines:
            if "echo hello" in " ".join(lines):
                found = True
                break
        self.assertTrue(found, "payload not in any code block")

    def test_blocks_has_yes_and_no_actions(self):
        from botwidget.confirm import ConfirmBoard
        board = ConfirmBoard()
        req = board.put("bot1", "action", "echo hello", now=100)
        blocks = board.blocks(req)
        action_block_found = None
        for b in blocks:
            if b.get("kind") == "control" and "actions" in b:
                action_block_found = b
                break
        self.assertIsNotNone(action_block_found, "no actions_block in output")
        labels = [a["label"] for a in action_block_found["actions"]]
        self.assertIn("Yes", labels)
        self.assertIn("No", labels)
        # Commands should be of the form confirm/<id>/yes and confirm/<id>/no
        cmds = {a["command"] for a in action_block_found["actions"]}
        self.assertTrue(any("confirm/" + req.id + "/yes" in c for c in cmds))
        self.assertTrue(any("confirm/" + req.id + "/no" in c for c in cmds))

    def test_feedback_and_vault_no_always_allow(self):
        from botwidget.confirm import ConfirmBoard
        board = ConfirmBoard()
        for kind in ("feedback", "vault"):
            req = board.put("bot1", kind, f"payload for {kind}", now=100)
            blocks = board.blocks(req)
            action_block_found = None
            for b in blocks:
                if b.get("kind") == "control" and "actions" in b:
                    action_block_found = b
                    break
            self.assertIsNotNone(action_block_found, f"no actions for {kind}")
            labels = [a["label"] for a in action_block_found["actions"]]
            self.assertNotIn("Always allow", labels)

    def test_action_and_routine_no_always_allow_in_this_block(self):
        from botwidget.confirm import ConfirmBoard
        board = ConfirmBoard()
        for kind in ("action", "routine"):
            req = board.put("bot1", kind, f"payload for {kind}", now=100)
            blocks = board.blocks(req)
            action_block_found = None
            for b in blocks:
                if b.get("kind") == "control" and "actions" in b:
                    action_block_found = b
                    break
            self.assertIsNotNone(action_block_found, f"no actions for {kind}")
            labels = [a["label"] for a in action_block_found["actions"]]
            self.assertNotIn("Always allow", labels)


class RecordTests(unittest.TestCase):
    """A decision writes one line through harness.approvals.record."""

    def test_decision_writes_to_approval_log(self):
        from botwidget import confirm
        with tempfile.TemporaryDirectory() as folder:
            log_path = os.path.join(folder, "approvals.jsonl")
            board = confirm.ConfirmBoard()
            req = board.put("bot1", "action", "echo hello", now=100)
            board.record_path = log_path
            decision = board.decide("bot1", "yes", payload="echo hello", request_id=req.id, now=101)
            self.assertTrue(decision.accepted)
            # record() creates the directory; read the log.
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                lines = fh.readlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["decision"], "accepted")
            self.assertEqual(entry["request"], req.payload)
            # no secret or token should be in the log entry
            self.assertNotIn("secret", entry["request"].lower())
            self.assertNotIn("token", entry["request"].lower())

    def test_decision_uses_the_harness_approval_log_by_default(self):
        from botwidget import confirm
        from harness import approvals
        with tempfile.TemporaryDirectory() as folder:
            log_path = os.path.join(folder, "approvals.jsonl")
            old = approvals.PATH
            approvals.PATH = log_path
            try:
                board = confirm.ConfirmBoard()
                req = board.put("bot1", "action", "echo hello", now=100)
                self.assertTrue(board.decide("bot1", "yes", payload="echo hello",
                                             request_id=req.id, now=101).accepted)
                with open(log_path) as fh:
                    entry = json.loads(fh.read())
                self.assertEqual(entry["decision"], "accepted")
                self.assertEqual(entry["source"], "confirm")
                self.assertEqual(entry["request"], "echo hello")
            finally:
                approvals.PATH = old


# ── Offscreen Qt smoke test ───────────────────────────────────────────

def _temp_config():
    folder = tempfile.TemporaryDirectory()
    old = config.CONFIG_PATH
    config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
    os.makedirs(folder.name, exist_ok=True)
    with open(config.CONFIG_PATH, "w") as fh:
        json.dump({"unlinked_hint_shown": True}, fh)
    config._config_read[:] = [None, {}]
    return folder, old


def _restore_config(folder, old):
    config.CONFIG_PATH = old
    config._config_read[:] = [None, {}]
    folder.cleanup()


class ConfirmSmoke(unittest.TestCase):
    """Offscreen Qt: ask_confirm shows the payload, buttons work, typed yes/no routes."""

    def setUp(self):
        try:
            from PySide6.QtWidgets import QApplication

            from botwidget.qt_ui.face import FaceWindow
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}") from error
        self.app = QApplication.instance() or QApplication([])
        self.folder, old = _temp_config()
        self.addCleanup(_restore_config, self.folder, old)
        self.window = FaceWindow("t", "Ada", spot=(300, 400))
        self.window._poll_timer.stop()
        self.window._anim_timer.stop()
        self.addCleanup(self._close)

    def _close(self):
        self.window.acp = None
        self.window.close_face()

    def test_ask_confirm_shows_payload_and_yes_no(self):
        from botwidget.confirm import ConfirmBoard
        from tests import action_labels
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("action", "echo hello")
        self.app.processEvents()
        self.assertIn("echo hello", self.window.bubble.full_text)
        labels = action_labels(self.window.bubble._control_widgets)
        self.assertIn("Yes", labels)
        self.assertIn("No", labels)
        self.assertNotIn("Always allow", labels)

    def test_ask_confirm_feedback_no_always_allow(self):
        from botwidget.confirm import ConfirmBoard
        from tests import action_labels
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("feedback", "send feedback text")
        self.app.processEvents()
        labels = action_labels(self.window.bubble._control_widgets)
        self.assertNotIn("Always allow", labels)

    def test_press_yes_calls_on_yes_once(self):
        from botwidget.confirm import ConfirmBoard
        from tests import action_labels, press
        calls = []
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("action", "echo hello", on_yes=lambda: calls.append(1))
        self.app.processEvents()
        labels = action_labels(self.window.bubble._control_widgets)
        self.assertIn("Yes", labels)
        press(self.window.bubble._control_widgets, "Yes")
        self.app.processEvents()
        self.assertEqual(calls, [1])
        # A second confirm with the same wording is a new request and may be accepted.
        self.window.ask_confirm("action", "echo hello", on_yes=lambda: calls.append(2))
        self.app.processEvents()
        press(self.window.bubble._control_widgets, "Yes")
        self.app.processEvents()
        self.assertEqual(calls, [1, 2])

    def test_press_no_does_not_call_on_yes(self):
        from botwidget.confirm import ConfirmBoard
        from tests import press
        calls = []
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("action", "echo hello", on_yes=lambda: calls.append(1))
        self.app.processEvents()
        press(self.window.bubble._control_widgets, "No")
        self.app.processEvents()
        self.assertEqual(calls, [])

    def test_typed_yes_accepts_and_does_not_go_to_bot(self):
        from botwidget.confirm import ConfirmBoard
        outbox_items = []
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("action", "echo hello")
        self.app.processEvents()
        # Patch _pump_outbox to capture what would be sent.
        with mock.patch.object(self.window, "_pump_outbox") as pump:
            self.window.on_user_message("yes")
        self.assertEqual(pump.call_count, 0, "typed yes should not go to the bot")
        # The confirm is already accepted and closed by on_user_message.
        self.assertIsNone(self.window._confirm_pending)

    def test_typed_yes_with_no_confirm_does_not_crash(self):
        """When no confirm is open, typed yes goes through the normal chat path."""
        self.window.confirm_board = None
        self.window._confirm_pending = None
        # Should not crash even with no confirm open.
        self.window.on_user_message("yes")
        self.window.on_user_message("Yes")

    def test_pending_confirm_lights_attention(self):
        from botwidget.confirm import ConfirmBoard
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.assertFalse(self.window._has_attention())
        self.window.ask_confirm("action", "echo hello")
        self.app.processEvents()
        self.assertTrue(self.window._has_attention())
        self.assertTrue(self.window.has_pending)

    def test_typed_no_does_not_call_on_yes(self):
        from botwidget.confirm import ConfirmBoard
        calls = []
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("action", "echo hello", on_yes=lambda: calls.append(1))
        self.app.processEvents()
        self.window.on_user_message("no")
        self.app.processEvents()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
