"""Block 5a: Vault tests — fake backend, set/get/delete, confirm gate.

No real keychain is ever touched. The fake backend stores values in a
thread-safe dict keyed by (service, username).
"""

import json
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config


class FakeBackendTests(unittest.TestCase):
    """The FakeKeyring stores values in a dict, not on the OS keychain."""

    def setUp(self):
        from botwidget.vault import _fake
        _fake.clear()

    def test_set_and_get(self):
        from botwidget.vault import _fake
        _fake.set_password("botwidget.vault", "my-key", "secret-value")
        self.assertEqual(_fake.get_password("botwidget.vault", "my-key"), "secret-value")

    def test_get_missing_returns_None(self):
        from botwidget.vault import _fake
        self.assertIsNone(_fake.get_password("botwidget.vault", "no-such-key"))

    def test_delete(self):
        from botwidget.vault import _fake
        _fake.set_password("botwidget.vault", "del-me", "data")
        _fake.delete_password("botwidget.vault", "del-me")
        self.assertIsNone(_fake.get_password("botwidget.vault", "del-me"))

    def test_different_usernames_are_separate(self):
        from botwidget.vault import _fake
        _fake.set_password("botwidget.vault", "user-a", "val-a")
        _fake.set_password("botwidget.vault", "user-b", "val-b")
        self.assertEqual(_fake.get_password("botwidget.vault", "user-a"), "val-a")
        self.assertEqual(_fake.get_password("botwidget.vault", "user-b"), "val-b")

    def test_different_services_are_separate(self):
        from botwidget.vault import _fake
        _fake.set_password("botwidget.vault", "key1", "s1")
        _fake.set_password("other.service", "key1", "s2")
        self.assertEqual(_fake.get_password("botwidget.vault", "key1"), "s1")
        self.assertEqual(_fake.get_password("other.service", "key1"), "s2")


class VaultModuleTests(unittest.TestCase):
    """botwidget.vault.set_secret / get_secret / delete_secret with the fake backend active."""

    def setUp(self):
        # Activate the fake backend before importing vault module-level state.
        from botwidget import vault
        vault._activate_fake()

    # ── set_secret ──────────────────────────────────────────────

    def test_set_secret_stores_the_value(self):
        from botwidget.vault import set_secret
        set_secret("my-key", "my-value")
        from botwidget.vault import _fake
        self.assertEqual(_fake.get_password("botwidget.vault", "my-key"), "my-value")

    def test_set_secret_overwrites(self):
        from botwidget.vault import set_secret
        set_secret("my-key", "first")
        set_secret("my-key", "second")
        from botwidget.vault import _fake
        self.assertEqual(_fake.get_password("botwidget.vault", "my-key"), "second")

    # ── get_secret (confirm gate) ───────────────────────────────

    def test_get_secret_without_decision_returns_None(self):
        from botwidget.vault import get_secret, set_secret
        set_secret("my-key", "my-value")
        self.assertIsNone(get_secret("my-key"))

    def test_get_secret_with_accepted_decision_is_accepted(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import get_secret, set_secret
        set_secret("my-key", "my-value")
        board = ConfirmBoard()
        req = board.put("bot1", "vault", "read my-key", now=100)
        decision = board.decide("bot1", "yes", payload="read my-key", request_id=req.id, now=101)
        self.assertEqual(get_secret("my-key", decision=decision), "my-value")

    def test_get_secret_declined_returns_None(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import get_secret, set_secret
        set_secret("my-key", "my-value")
        board = ConfirmBoard()
        req = board.put("bot1", "vault", "read my-key", now=100)
        decision = board.decide("bot1", "no", now=101)
        self.assertIsNone(get_secret("my-key", decision=decision))

    def test_get_secret_expired_returns_None(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import get_secret, set_secret
        set_secret("my-key", "my-value")
        board = ConfirmBoard()
        req = board.put("bot1", "vault", "read my-key", now=100, ttl=600)
        decision = board.decide("bot1", "yes", request_id=req.id, now=701)
        self.assertIsNone(get_secret("my-key", decision=decision))

    def test_get_secret_a_cannot_read_b(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import get_secret, set_secret
        set_secret("key-a", "value-a")
        set_secret("key-b", "value-b")
        board = ConfirmBoard()
        req = board.put("bot1", "vault", "read key-a", now=100)
        decision = board.decide("bot1", "yes", payload="read key-a", request_id=req.id, now=101)
        self.assertEqual(get_secret("key-a", decision=decision), "value-a")
        # The decision was for key-a only; key-b is not accessible.
        self.assertIsNone(get_secret("key-b", decision=decision))

    # ── delete_secret (confirm gate) ────────────────────────────

    def test_delete_secret_without_decision_does_nothing(self):
        from botwidget.vault import _fake, delete_secret, set_secret
        set_secret("my-key", "my-value")
        delete_secret("my-key", decision=None)
        self.assertEqual(_fake.get_password("botwidget.vault", "my-key"), "my-value")

    def test_delete_secret_with_accepted_decision_removes(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import _fake, delete_secret, set_secret
        set_secret("my-key", "my-value")
        board = ConfirmBoard()
        req = board.put("bot1", "vault", "delete my-key", now=100)
        decision = board.decide("bot1", "yes", payload="delete my-key", request_id=req.id, now=101)
        delete_secret("my-key", decision=decision)
        self.assertIsNone(_fake.get_password("botwidget.vault", "my-key"))

    def test_delete_secret_declined_does_nothing(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import _fake, delete_secret, set_secret
        set_secret("my-key", "my-value")
        board = ConfirmBoard()
        req = board.put("bot1", "vault", "delete my-key", now=100)
        decision = board.decide("bot1", "no", now=101)
        delete_secret("my-key", decision=decision)
        self.assertEqual(_fake.get_password("botwidget.vault", "my-key"), "my-value")

    # ── list_secret_ids ─────────────────────────────────────────

    def test_list_secret_ids_returns_only_ids(self):
        from botwidget.vault import _ids_lock
        with _ids_lock:
            from botwidget.vault import _save_ids
            _save_ids(set())
        from botwidget.vault import list_secret_ids, set_secret
        set_secret("a", "v-a")
        set_secret("b", "v-b")
        set_secret("c", "v-c")
        ids = list_secret_ids()
        self.assertEqual(sorted(ids), ["a", "b", "c"])

    def test_list_secret_ids_does_not_leak_values(self):
        from botwidget.vault import _ids_lock
        with _ids_lock:
            from botwidget.vault import _save_ids
            _save_ids(set())
        from botwidget.vault import list_secret_ids, set_secret
        set_secret("secret-key", "top-secret-value")
        ids = list_secret_ids()
        self.assertIn("secret-key", ids)
        self.assertNotIn("top-secret-value", json.dumps(ids))

    # ── No secrets in logs ──────────────────────────────────────

    def test_get_secret_declined_is_logged_without_value(self):
        from botwidget.confirm import ConfirmBoard
        from botwidget.vault import get_secret, set_secret
        with tempfile.TemporaryDirectory() as folder:
            log_path = os.path.join(folder, "approvals.jsonl")
            from harness import approvals
            old = approvals.PATH
            approvals.PATH = log_path
            try:
                set_secret("my-key", "top-secret")
                board = ConfirmBoard(record_path=log_path)
                req = board.put("bot1", "vault", "read my-key", now=100)
                decision = board.decide("bot1", "no", now=101)
                get_secret("my-key", decision=decision)
                with open(log_path) as fh:
                    entry = json.loads(fh.readline())
                self.assertNotIn("top-secret", entry["request"])
            finally:
                approvals.PATH = old


class VaultSmoke(unittest.TestCase):
    """Offscreen Qt smoke: ask_confirm with kind=vault shows the confirm, buttons work."""

    def setUp(self):
        try:
            from PySide6.QtWidgets import QApplication

            from botwidget.qt_ui.face import FaceWindow
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}") from error
        from botwidget.qt_ui.face import FaceWindow
        self.app = QApplication.instance() or QApplication([])
        folder = tempfile.TemporaryDirectory()
        old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        os.makedirs(folder.name, exist_ok=True)
        with open(config.CONFIG_PATH, "w") as fh:
            json.dump({"unlinked_hint_shown": True}, fh)
        config._config_read[:] = [None, {}]
        self.window = FaceWindow("t", "Ada", spot=(300, 400))
        self.window._poll_timer.stop()
        self.window._anim_timer.stop()
        self.folder = folder
        self.old_config = old
        self.addCleanup(self._close)
        self.addCleanup(self._restore)

    def _close(self):
        self.window.acp = None
        self.window.close_face()

    def _restore(self):
        config.CONFIG_PATH = self.old_config
        config._config_read[:] = [None, {}]
        self.folder.cleanup()

    def test_ask_confirm_vault_shows_payload(self):
        from botwidget.confirm import ConfirmBoard
        from tests import action_labels
        self.window.confirm_board = ConfirmBoard()
        self.window._confirm_pending = None
        self.window.ask_confirm("vault", "Read secret test-key", on_yes=lambda: None)
        self.app.processEvents()
        self.assertIn("test-key", self.window.bubble.full_text)
        labels = action_labels(self.window.bubble._control_widgets)
        self.assertIn("Yes", labels)
        self.assertIn("No", labels)
        self.assertNotIn("Always allow", labels)


if __name__ == "__main__":
    unittest.main()


class VaultIdsPath(unittest.TestCase):
    def test_the_id_index_lives_in_the_app_folder_and_never_in_the_working_directory(self):
        from botwidget import vault
        from botwidget.config import APP_DIR
        self.assertTrue(os.path.isabs(vault._SECRET_IDS_PATH), vault._SECRET_IDS_PATH)
        if not os.environ.get("BOT_WIDGET_APP_DIR"):
            self.assertEqual(os.path.dirname(vault._SECRET_IDS_PATH), APP_DIR)
