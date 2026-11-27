"""Tests for H8: adaptive window scaling of KEEP_TURNS, RESULT_KEEP and CONTEXT_TOKENS.

Three constants that used to be fixed (12 / 6 / 32000) now scale with the context
window the model reports.  Unknown window falls back to today's numbers.

Tests are written first: they fail against the current code, pass after the change.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.agent.context import (
    BUDGET_CHARS,
    CONTEXT_TOKENS,
    RESULT_STUB,
    _token_window,
    build,
)
from harness.agent.context import (
    KEEP_TURNS as ORIG_KEEP_TURNS,
)
from harness.agent.store import SessionStore

# ── Helper ────────────────────────────────────────────────────────────────

def _count_assistant_turns(context: list[dict]) -> int:
    """How many assistant (bot) turns appear in a built context."""
    return sum(1 for m in context if m["role"] == "assistant")


def _count_user_turns(context: list[dict]) -> int:
    return sum(1 for m in context if m["role"] == "user")


def _seed_store(store: SessionStore, n: int) -> None:
    """Add n user/bot pairs without summary."""
    for i in range(n):
        store.add("user", f"User message number {i}, filler text to make the context larger.")
        store.add("bot", f"Bot response number {i}, also filler to grow the prompt text volume.")


# ── Test: fallback for unknown window ────────────────────────────────────

class TestFallbackUnknownWindow(unittest.TestCase):
    """When the model reports no context window, values fall back to today's numbers."""

    def test_keep_turns_fallback(self):
        """model_window=0 → KEEP_TURNS stays 12."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        _seed_store(store, 100)
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        context = build(store, "Bench", model_window=0)
        # With window=0 the fallback is 32000, KEEP_TURNS=12 → keeps 12*2=24 recent turns.
        self.assertGreaterEqual(_count_assistant_turns(context), 10)

    def test_result_keep_fallback(self):
        """model_window=0 → RESULT_KEEP stays 6 (tool results from recent turns)."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        store.add("user", "hi")
        store.add("bot", "hello")
        for i in range(10):
            store.add_tool_result(f"tool_{i}", f"Result {i}" * 20, f"/tmp/tool_{i}.txt")
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        context = build(store, "Bench", model_window=0)
        full = " ".join(m.get("content", "") for m in context)
        # With fallback window we should see tool results from up to RESULT_KEEP=6 recent results
        self.assertIn("[tool_9]", full)

    def test_budget_fallback(self):
        """No model window → BUDGET_CHARS is derived from CONTEXT_TOKENS (32000)."""
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        self.assertEqual(BUDGET_CHARS, (32000 - 2048) * 4)


# ── Test: small window gives smaller limits ──────────────────────────────

class TestSmallWindow(unittest.TestCase):
    """A small context window scales down KEEP_TURNS and RESULT_KEEP."""

    def test_small_window_fewer_turns(self):
        """8192 window → fewer recent turns than the default 32000 window."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        _seed_store(store, 100)
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        small = build(store, "Bench", model_window=8192)
        large = build(store, "Bench", model_window=128000)
        small_count = _count_assistant_turns(small) + _count_user_turns(small)
        large_count = _count_assistant_turns(large) + _count_user_turns(large)
        self.assertGreater(large_count, small_count,
                           "a larger window must keep more turns than a small one")

    def test_small_window_still_has_turns(self):
        """Even 8192 window should keep at least a few turns (monotonic, not zero)."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        _seed_store(store, 30)
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        context = build(store, "Bench", model_window=8192)
        self.assertGreater(_count_assistant_turns(context), 0,
                           "8192 window must keep at least one assistant turn")


# ── Test: large window gives more room ───────────────────────────────────

class TestLargeWindow(unittest.TestCase):
    """A large context window keeps more recent turns than a small one."""

    def test_large_window_keeps_more(self):
        """128000 window → more turns than 32000 default."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        _seed_store(store, 200)
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        medium = build(store, "Bench", model_window=32000)
        large = build(store, "Bench", model_window=128000)
        medium_count = _count_assistant_turns(medium) + _count_user_turns(medium)
        large_count = _count_assistant_turns(large) + _count_user_turns(large)
        self.assertGreater(large_count, medium_count,
                           "128k window must keep more turns than 32k")


# ── Test: monotonic scaling ──────────────────────────────────────────────

class TestMonotonicScaling(unittest.TestCase):
    """Larger window → more turns, always non-decreasing."""

    def test_monotonic_three_windows(self):
        """Three window sizes: 4k < 32k < 128k, turn counts must be non-decreasing."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        _seed_store(store, 300)
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        counts = []
        for w in (4096, 32000, 128000):
            ctx = build(store, "Bench", model_window=w)
            counts.append(_count_assistant_turns(ctx) + _count_user_turns(ctx))
        self.assertTrue(
            counts[0] <= counts[1] <= counts[2],
            f"turn counts must be monotonic across [4k, 32k, 128k]: {counts}",
        )

    def test_monotonic_token_window(self):
        """_token_window returns model value when > 0, fallback when 0."""
        os.environ.pop("HARNESS_CONTEXT_TOKENS", None)
        self.assertEqual(_token_window(8192), 8192)
        self.assertEqual(_token_window(0), CONTEXT_TOKENS)


# ── Test: environment override still works ───────────────────────────────

class TestEnvOverride(unittest.TestCase):
    """HARNESS_CONTEXT_TOKENS still overrides the fallback."""

    def test_env_sets_fallback_window(self):
        """HARNESS_CONTEXT_TOKENS=64000 → budget and meter use 64000."""
        os.environ["HARNESS_CONTEXT_TOKENS"] = "64000"
        try:
            folder = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, folder, True)
            store = SessionStore(folder)
            _seed_store(store, 200)
            # No model window → env takes over
            medium = build(store, "Bench", model_window=0)
            # 32000 window as comparison
            default = build(store, "Bench", model_window=32000)
            medium_count = _count_assistant_turns(medium) + _count_user_turns(medium)
            default_count = _count_assistant_turns(default) + _count_user_turns(default)
            # 64k env > 32k default → more turns
            self.assertGreaterEqual(medium_count, default_count)
        finally:
            os.environ.pop("HARNESS_CONTEXT_TOKENS", None)


# ── Test: constants unchanged at module level ────────────────────────────

class TestModuleConstants(unittest.TestCase):
    """The module-level constants themselves stay at their original defaults."""

    def test_keep_turns_default(self):
        self.assertEqual(ORIG_KEEP_TURNS, 12)

    def test_result_keep_default(self):
        from harness.agent.context import RESULT_KEEP
        self.assertEqual(RESULT_KEEP, 6)

    def test_context_tokens_default(self):
        self.assertEqual(CONTEXT_TOKENS, 32000)

    def test_stub_unchanged(self):
        self.assertEqual(RESULT_STUB, 160)


if __name__ == "__main__":
    unittest.main()
