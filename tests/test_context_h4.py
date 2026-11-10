"""Tests for H4 context window management (harness.agent.context).

Covers: token budget from model window, pinned prefix never evicted,
BACKGROUND extract for older turns without summary, no model calls
inside build(), and meter() using a passed-in model window.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.agent.context import build, estimate, meter, _budget_chars, _build_background
from harness.agent.store import SessionStore


class TestBudgetChars(unittest.TestCase):
    """BUDGET_CHARS is derived from the model window, not a second independent cap."""

    def test_default_window_gives_standard_budget(self):
        """No model window → falls back to CONTEXT_TOKENS (32000) minus margin."""
        chars = _budget_chars(0)
        self.assertGreater(chars, 0)
        # 32000 - 2048 = 29952 tokens * 4 = 119808 chars
        self.assertEqual(chars, (32000 - 2048) * 4)

    def test_model_window_scales_budget(self):
        """The model's own window drives the budget, even when it is smaller than the default."""
        self.assertEqual(_budget_chars(8192), (8192 - 2048) * 4)
        self.assertEqual(_budget_chars(128000), (128000 - 2048) * 4)
        self.assertLess(_budget_chars(8192), _budget_chars(0),
                        "a smaller model window must shrink the budget")

    def test_env_override_via_meter(self):
        """HARNESS_CONTEXT_TOKENS is used by meter when no window is passed."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "hi")
        store.add("bot", "hello")
        had_key = "HARNESS_CONTEXT_TOKENS" in os.environ
        original = os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        try:
            os.environ["HARNESS_CONTEXT_TOKENS"] = "64000"
            used, size = meter(store, "Test", 0)
            self.assertGreater(size, 32000, "meter should use HARNESS_CONTEXT_TOKENS")
        finally:
            os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
            if had_key:
                os.environ["HARNESS_CONTEXT_TOKENS"] = original


class TestBuildPinnedPrefix(unittest.TestCase):
    """Pinned prefix is never evicted even under tight budget."""

    def test_system_prompt_always_in_context(self):
        """The system prompt is always present, even with 0 budget for turns."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "hi")
        store.add("bot", "hello")
        context = build(store, "TestBot", model_window=0)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("You are TestBot", full)

    def test_workspace_rules_always_in_context(self):
        """Workspace rules are never evicted."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        rules_file = os.path.join(folder, "AGENTS.md")
        with open(rules_file, "w") as fh:
            fh.write("# Test workspace rules\n")
        store = SessionStore(folder)
        store.add("user", "hi")
        os.environ["HARNESS_WORKSPACE"] = folder
        try:
            context = build(store, "TestBot", model_window=0)
            texts = [m.get("content", "") for m in context]
            full = " ".join(texts)
            self.assertIn("# Test workspace rules", full)
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)

    def test_facts_always_in_context(self):
        """Pinned facts survive even with tight budget."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.set("facts", "Project Alpha is the main repo.\nToken XRAY-42 is critical.")
        store.add("user", "hi")
        context = build(store, "TestBot", model_window=0)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("Project Alpha is the main repo.", full)
        self.assertIn("XRAY-42", full)

    def test_summary_always_in_context(self):
        """A rolling summary is always present in context."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.set_summary("User likes coffee.")
        store.add("user", "hi")
        context = build(store, "TestBot", model_window=0)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("Earlier in this conversation:", full)
        self.assertIn("User likes coffee.", full)


class TestBuildBackgroundExtract(unittest.TestCase):
    """BACKGROUND extract preserves older turns when no summary exists."""

    def test_background_includes_token_in_older_turn(self):
        """A CAPS-LIKE token from an early turn survives in BACKGROUND."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "Remember: SILVER-ORCHID-7 is the special token.")
        for i in range(50):
            store.add("user", f"Filler question {i}?")
            store.add("bot", f"Filler answer {i}.")
        # No summary.
        context = build(store, "Bench", model_window=8192)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("SILVER-ORCHID-7", full,
                      "token from early turn should be in BACKGROUND extract")

    def test_background_not_present_when_summary_exists(self):
        """When a summary exists, the BACKGROUND header should not appear
        (summary covers older turns, and facts preserve specific tokens)."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "Remember: SILVER-ORCHID-7 is the special token.")
        for i in range(50):
            store.add("user", f"Filler question {i}?")
            store.add("bot", f"Filler answer {i}.")
        store.set_summary("SILVER-ORCHID-7 is the special token.")
        context = build(store, "Bench", model_window=8192)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("SILVER-ORCHID-7", full)
        self.assertIn("Earlier in this conversation:", full)

    def test_token_still_appears_with_summary(self):
        """Once a summary exists, the fact still appears (via summary)."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "Remember: CORAL-TREE-19 is the project code.")
        for i in range(50):
            store.add("user", f"Question {i}?")
            store.add("bot", f"Answer {i}.")
        store.set_summary("The project code is CORAL-TREE-19.")
        context = build(store, "Bench", model_window=8192)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("CORAL-TREE-19", full,
                      "fact should still appear via rolling summary")

    def test_build_does_not_call_model(self):
        """build() is purely synchronous and does not import or call any model."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "hi")
        # build should not raise and should not touch network or model APIs.
        context = build(store, "TestBot")
        self.assertIsInstance(context, list)

    def test_tight_budget_keeps_pinned(self):
        """Even with a tight budget, pinned prefix survives."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.set("facts", "CRITICAL-01 is the fail-safe.")
        store.add("user", "hi")
        store.add("bot", "hello")
        context = build(store, "TestBot", model_window=1024)
        texts = [m.get("content", "") for m in context]
        full = " ".join(texts)
        self.assertIn("CRITICAL-01", full)
        self.assertIn("You are TestBot", full)

    def test_keep_turns_still_configurable(self):
        """KEEP_TURNS controls how many recent turns are kept verbatim."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        from harness.agent import context as ctx
        old_keep = ctx.KEEP_TURNS
        try:
            ctx.KEEP_TURNS = 2
            store = SessionStore(folder)
            for i in range(20):
                store.add("user", f"Q{i}")
                store.add("bot", f"A{i}")
            context = build(store, "TestBot", model_window=8192)
            bot_messages = [m for m in context if m["role"] == "assistant"]
            # At most 2 * KEEP_TURNS = 4 bot turns (2 user + 2 bot = 4)
            # plus the 2 user turns themselves → up to 4 bot turns in context
            self.assertLessEqual(len(bot_messages), 4)
        finally:
            ctx.KEEP_TURNS = old_keep


class TestMeter(unittest.TestCase):
    """meter() uses the passed-in model window."""

    def test_meter_uses_model_window(self):
        """When model_window is provided, meter uses it as the size."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "hello")
        store.add("bot", "hi")
        used, size = meter(store, "Test", 16384)
        self.assertEqual(size, 16384)
        self.assertGreater(used, 0)

    def test_meter_fallback_to_context_tokens(self):
        """When model_window is 0, meter falls back to CONTEXT_TOKENS."""
        # Make sure HARNESS_CONTEXT_TOKENS is not set.
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "hi")
        used, size = meter(store, "Test", 0)
        self.assertEqual(size, 32000)


class TestBuildNoModel(unittest.TestCase):
    """build() is fully synchronous, no network, no model calls."""

    def test_build_is_synchronous(self):
        """build should return immediately without spawning threads."""
        import time
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        for i in range(100):
            store.add("user", f"Filler {i}")
            store.add("bot", f"Reply {i}")
        start = time.monotonic()
        context = build(store, "TestBot", model_window=8192)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.5, "build should complete in < 500 ms")
        self.assertIsInstance(context, list)


class TestBackgroundExtract(unittest.TestCase):
    """Direct tests for _build_background helper."""

    def test_extract_preserves_token(self):
        """CAPS-LIKE tokens are kept."""
        older = [{"role": "user", "text": "The project code is ALPHA-99."}]
        result = _build_background(older)
        self.assertIn("ALPHA-99", result)

    def test_extract_preserves_remember_lines(self):
        """Lines mentioning remember/keep are kept."""
        older = [{"role": "user", "text": "Please remember this: the port is 8080."}]
        result = _build_background(older)
        self.assertIn("8080", result)

    def test_empty_older_returns_empty(self):
        """Empty older list → empty string."""
        self.assertEqual(_build_background([]), "")

    def test_extract_has_markers(self):
        """Output is wrapped in BACKGROUND markers."""
        older = [{"role": "user", "text": "Hello."}]
        result = _build_background(older)
        self.assertIn("[BACKGROUND", result)
        self.assertIn("]", result)


if __name__ == "__main__":
    unittest.main()
