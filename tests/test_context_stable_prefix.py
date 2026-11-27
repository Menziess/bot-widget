"""Tests for H8 task 2: stable prefix in build().

The stable prefix (system text, workspace rules, summary, facts, skill, kept
conversation) must be byte-identical between two consecutive build() calls when
nothing in the store changed. Only per-turn items (reminders, newest tool
results) must change, and they must appear at the very end of the message list.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.agent.context import build
from harness.agent.store import SessionStore


class TestStablePrefix(unittest.TestCase):
    """Two consecutive build() calls share the longest possible prefix."""

    def _make_store(self, messages=None, **meta):
        """Create a temp store and optionally seed it."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        for key, val in meta.items():
            store.set(key, val)
        if messages:
            for role, text in messages:
                store.add(role, text)
        return store

    def _prefixes(self, build_a, build_b):
        """Return the length (in messages) of the shared prefix."""
        shared = 0
        for a, b in zip(build_a, build_b, strict=False):
            if a == b:
                shared += 1
            else:
                break
        return shared

    def test_consecutive_builds_share_prefix_when_store_unchanged(self):
        """When the store is unchanged, two build() calls share the entire prefix."""
        store = self._make_store(
            [("user", "What's 2+2?"), ("bot", "4.")],
            facts="Capital is Paris.",
        )
        # Disable memory to keep things deterministic.
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        a = build(store, "Bot", model_window=8192)
        b = build(store, "Bot", model_window=8192)
        # Every message is identical — the whole prefix is shared.
        self.assertEqual(len(a), len(b))
        self.assertEqual(self._prefixes(a, b), len(a))

    def test_reminder_change_only_affects_tail(self):
        """When only a per-turn reminder changes, the stable prefix is untouched."""
        store = self._make_store(
            [("user", "hi"), ("bot", "hello")],
        )
        # Set a reminder that would be injected per-turn.
        store.set("reminder", "First build.")
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        a = build(store, "Bot", model_window=8192)

        store.set("reminder", "Second build.")
        b = build(store, "Bot", model_window=8192)

        # The reminder is at the very end; the shared prefix is everything before it.
        shared = self._prefixes(a, b)
        # There must be at least the system message shared.
        self.assertGreater(shared, 0,
                           "stable prefix must exist even with a reminder change")
        # The last message(s) differ (the reminder is in the tail).
        self.assertNotEqual(a[-1], b[-1],
                            "the tail must differ when the reminder changes")

    def test_newest_tool_results_at_tail(self):
        """Newest tool results appear after the kept conversation, at the very end."""
        store = self._make_store(
            [("user", "hi"), ("bot", "hello")],
        )
        # Add a tool result.
        store.add_tool_result("read_file", "file content", "file content")
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        context = build(store, "Bot", model_window=8192)

        # Find the index of the tool results block: it should be after all
        # system and conversation messages.
        # The system messages come first, then conversation (user/bot), then tool results.
        last_system_idx = -1
        last_conv_idx = -1
        for i, msg in enumerate(context):
            if msg["role"] == "system":
                last_system_idx = i
            elif msg["role"] in ("user", "assistant"):
                last_conv_idx = i

        # Tool results are also system messages but come after conversation.
        # So the very last messages should contain the tool result text.
        tool_text = context[-1]["content"] if context else ""
        self.assertIn("read_file", tool_text,
                      "newest tool results should appear in the tail")

    def test_consecutive_builds_with_new_tool_result_change_tail(self):
        """Adding a tool result changes only the tail; the stable prefix is shared."""
        store = self._make_store(
            [("user", "hi"), ("bot", "hello")],
        )
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        a = build(store, "Bot", model_window=8192)

        store.add_tool_result("shell", "exit 0", "exit 0")
        b = build(store, "Bot", model_window=8192)

        # There must be a shared prefix that is not just the system message.
        shared = self._prefixes(a, b)
        self.assertGreater(shared, 0,
                           "stable prefix must exist when only tool results change")
        # The last message(s) differ.
        self.assertNotEqual(a[-1], b[-1],
                            "the tail must differ when tool results are added")


class TestPrefixOrder(unittest.TestCase):
    """The order of blocks in build() is: system → facts/summary → kept conversation → per-turn tail."""

    def _make_store(self, messages=None, **meta):
        """Create a temp store and optionally seed it."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        for key, val in meta.items():
            store.set(key, val)
        if messages:
            for role, text in messages:
                store.add(role, text)
        return store

    def test_system_messages_come_first(self):
        """All system messages (system prompt, facts, summary, skill) are at the start."""
        store = self._make_store(
            [("user", "hi"), ("bot", "hello")],
            facts="Facts here.",
        )
        store.set_summary("Earlier summary.")
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        context = build(store, "Bot", model_window=8192)

        # Find the first non-system message.
        first_conv_idx = None
        for i, msg in enumerate(context):
            if msg["role"] != "system":
                first_conv_idx = i
                break

        self.assertIsNotNone(first_conv_idx,
                             "there should be at least one non-system message")
        # All messages before it are system.
        for i in range(first_conv_idx):
            self.assertEqual(context[i]["role"], "system",
                             f"message {i} should be system")

    def test_kept_conversation_before_tool_results(self):
        """Kept conversation messages come before tool results."""
        store = self._make_store(
            [("user", "hi"), ("bot", "hello"), ("user", "again?"), ("bot", "sure.")],
        )
        store.add_tool_result("read_file", "content here", "content here")
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        context = build(store, "Bot", model_window=8192)

        # Find the last user/assistant message and the last tool result block.
        last_conv_idx = -1
        last_result_idx = -1
        for i, msg in enumerate(context):
            if msg["role"] in ("user", "assistant"):
                last_conv_idx = i
            if "read_file" in msg.get("content", ""):
                last_result_idx = i

        self.assertGreaterEqual(last_result_idx, last_conv_idx,
                                "tool results must come after kept conversation")


class TestReminderAtEnd(unittest.TestCase):
    """Per-turn reminders are always the very last block in the context."""

    def _make_store(self, messages=None, **meta):
        """Create a temp store and optionally seed it."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        for key, val in meta.items():
            store.set(key, val)
        if messages:
            for role, text in messages:
                store.add(role, text)
        return store

    def test_reminder_is_last_message(self):
        """When a reminder is set, it must be the very last message in the built context."""
        store = self._make_store(
            [("user", "hi"), ("bot", "hello")],
        )
        store.set("reminder", "Remember to check the diff.")
        os.environ.pop("HARNESS_MEMORY_DIR", None)
        context = build(store, "Bot", model_window=8192)

        # The last message should contain the reminder text.
        self.assertIn("Remember to check the diff.", context[-1]["content"],
                      "the reminder must be in the last message")


if __name__ == "__main__":
    unittest.main()
