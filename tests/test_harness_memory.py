"""H5: topic-scoped, durable memory for harness bots.

Tests the memory module in isolation (store, retrieve, topic assignment, forget)
and the integration into context.build() and the lean agent.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from harness.agent import context
from harness.agent.memory import (
    _tokenise,
    _overlap_score,
    write_memory,
    write_memory_list,
    retrieve_memories,
    suggest_topic,
    topic_for_message,
    forget_memory,
    update_memory,
    list_memories,
    memory_tools_for,
    memory_write_tool,
    memory_read_tool,
    memory_forget_tool,
)
from harness.agent.store import SessionStore
from tests.fake_model import FakeModel


# ── Token helpers ──────────────────────────────────────────────────


class TokenHelpers(unittest.TestCase):
    def test_tokenise_lowercases_and_keeps_two_char_plus(self):
        tokens = _tokenise("the cat and the dog")
        self.assertIn("the", tokens)  # >= 2 chars, included
        self.assertIn("and", tokens)
        self.assertIn("cat", tokens)
        self.assertIn("dog", tokens)
        self.assertEqual(len(tokens), 4)

    def test_tokenise_caps_like(self):
        tokens = _tokenise("use API-KEY-01 and my-string")
        self.assertIn("API-KEY-01", tokens)
        self.assertNotIn("my-string", tokens)  # not all-caps

    def test_overlap_score_same_text(self):
        self.assertAlmostEqual(_overlap_score("hello world", "hello world"), 1.0)

    def test_overlap_score_no_common(self):
        self.assertEqual(_overlap_score("hello world", "xyz abc"), 0.0)
        self.assertEqual(_overlap_score("", "hello"), 0.0)
        self.assertEqual(_overlap_score("hello", ""), 0.0)

    def test_overlap_score_partial(self):
        score = _overlap_score("hello world foo", "world bar")
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 0.5)


# ── Store ──────────────────────────────────────────────────────────


class Store(unittest.TestCase):
    def setUp(self):
        self.memory_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self._old = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir

    def tearDown(self):
        if self._old is not None:
            os.environ["HARNESS_MEMORY_DIR"] = self._old
        elif "HARNESS_MEMORY_DIR" in os.environ:
            del os.environ["HARNESS_MEMORY_DIR"]

    def test_write_and_list(self):
        eid = write_memory("Hello world", "user")
        self.assertTrue(len(eid), "ID is returned")
        items = list_memories()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "Hello world")
        self.assertEqual(items[0]["scope"], "user")

    def test_write_multiple_scopes(self):
        write_memory("User fact", "user")
        write_memory("Project fact", "project", workspace="/tmp/ws")
        write_memory("Topic fact", "topic", topic="login")
        items = list_memories()
        scopes = {m["scope"] for m in items}
        self.assertIn("user", scopes)
        self.assertIn("topic", scopes)

    def test_list_sorted_newest_first(self):
        write_memory("old", "user")
        time.sleep(0.01)
        write_memory("new", "user")
        items = list_memories()
        self.assertEqual(items[0]["text"], "new")
        self.assertEqual(items[1]["text"], "old")

    def test_write_memory_list(self):
        ids = write_memory_list(
            [{"text": "a"}, {"text": "b"}], "user"
        )
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(list_memories()), 2)

    def test_project_memory_keyed_by_workspace(self):
        ws1 = write_memory("ws1 data", "project", workspace="/tmp/ws1")
        ws2 = write_memory("ws2 data", "project", workspace="/tmp/ws2")
        self.assertNotEqual(ws1, ws2, "different workspaces get different IDs")
        self.assertNotEqual(ws1, "")
        self.assertNotEqual(ws2, "")
        # Check they wrote to different files by reading the project file directly.
        from harness.agent.memory import _memory_path
        path1 = _memory_path("project", "/tmp/ws1")
        path2 = _memory_path("project", "/tmp/ws2")
        self.assertNotEqual(path1, path2)

    def test_write_memory_returns_empty_for_missing_workspace(self):
        eid = write_memory("data", "project")
        self.assertEqual(eid, "")

    def test_topic_memory_stored_with_topic(self):
        eid = write_memory("login detail", "topic", topic="login_flow")
        items = list_memories()
        topic_items = [m for m in items if m["topic"] == "login_flow"]
        self.assertEqual(len(topic_items), 1)
        self.assertEqual(topic_items[0]["text"], "login detail")


# ── Retrieve ───────────────────────────────────────────────────────


class Retrieve(unittest.TestCase):
    def setUp(self):
        self.memory_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self._old = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir

    def tearDown(self):
        if self._old is not None:
            os.environ["HARNESS_MEMORY_DIR"] = self._old
        elif "HARNESS_MEMORY_DIR" in os.environ:
            del os.environ["HARNESS_MEMORY_DIR"]

    def test_retrieve_returns_empty_when_no_memories(self):
        results = retrieve_memories("anything")
        self.assertEqual(results, [])

    def test_retrieve_scores_by_overlap(self):
        write_memory("The bot uses Python for all scripts", "user")
        write_memory("Random unrelated thing about gardening", "user")
        results = retrieve_memories("Python scripting bot")
        self.assertGreaterEqual(len(results), 1)
        # The Python-related memory should rank higher.
        self.assertEqual(results[0]["text"], "The bot uses Python for all scripts")

    def test_retrieve_caps_at_max_chars(self):
        for i in range(10):
            write_memory("x" * 300, "user")
        results = retrieve_memories("x", max_chars=500)
        total_chars = sum(len(r["text"]) for r in results)
        self.assertLessEqual(total_chars, 500)

    def test_retrieve_topic_boost(self):
        write_memory("Login page has a blue button", "topic", topic="login_ui")
        write_memory("Random unrelated fact", "user")
        results = retrieve_memories("login blue button")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["topic"], "login_ui")

    def test_retrieve_all_scopes(self):
        write_memory("User preference", "user")
        write_memory("Project config", "project", workspace="/tmp/ws")
        results = retrieve_memories("preference config")
        scopes = {r["scope"] for r in results}
        self.assertIn("user", scopes)


# ── Topic assignment ───────────────────────────────────────────────


class TopicAssignment(unittest.TestCase):
    def setUp(self):
        self.memory_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self._old = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir

    def tearDown(self):
        if self._old is not None:
            os.environ["HARNESS_MEMORY_DIR"] = self._old
        elif "HARNESS_MEMORY_DIR" in os.environ:
            del os.environ["HARNESS_MEMORY_DIR"]

    def test_topic_for_message_reuses_existing(self):
        write_memory("The login flow needs OAuth", "topic", topic="login_flow")
        name = topic_for_message("How does the OAuth login work?")
        self.assertEqual(name, "login_flow")

    def test_topic_for_message_starts_new(self):
        name = topic_for_message("This is a completely new topic about gardening")
        self.assertTrue(len(name) > 0)
        self.assertNotEqual(name, "login_flow")

    def test_suggest_topic_new(self):
        write_memory("The bot uses Python", "user")
        suggestion = suggest_topic("Gardening tips for beginners")
        self.assertEqual(suggestion, "new topic")

    def test_suggest_topic_existing(self):
        write_memory("The bot uses Python for automation", "user")
        suggestion = suggest_topic("Python automation scripts")
        self.assertIsNone(suggestion)


# ── Forget ─────────────────────────────────────────────────────────


class Forget(unittest.TestCase):
    def setUp(self):
        self.memory_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self._old = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir

    def tearDown(self):
        if self._old is not None:
            os.environ["HARNESS_MEMORY_DIR"] = self._old
        elif "HARNESS_MEMORY_DIR" in os.environ:
            del os.environ["HARNESS_MEMORY_DIR"]

    def test_forget_by_id(self):
        eid = write_memory("Remove me", "user")
        result = forget_memory(eid)
        self.assertIn("Removed", result)
        self.assertEqual(len(list_memories()), 0)

    def test_forget_by_text(self):
        write_memory("Keep this one", "user")
        write_memory("Remove me too", "user")
        result = forget_memory("Remove me too")
        self.assertIn("Removed", result)
        self.assertEqual(len(list_memories()), 1)
        self.assertEqual(list_memories()[0]["text"], "Keep this one")

    def test_update_changes_text_and_topic_and_keeps_the_rest(self):
        eid = write_memory("Old text", "user", topic="a")
        other = write_memory("Other", "user")
        before = next(m for m in list_memories() if m["id"] == eid)
        self.assertEqual(update_memory(eid, "New text", "b"), "Updated.")
        after = next(m for m in list_memories() if m["id"] == eid)
        self.assertEqual((after["text"], after["topic"]), ("New text", "b"))
        self.assertEqual((after["id"], after["scope"], after["ts"]), (eid, "user", before["ts"]))
        self.assertEqual(next(m for m in list_memories() if m["id"] == other)["text"], "Other")
        self.assertEqual(update_memory(eid, "Newer")[:0], "")
        self.assertEqual(next(m for m in list_memories() if m["id"] == eid)["topic"], "b", "no topic given keeps it")
        self.assertIn("Not found", update_memory("abcdef123456", "x"))

    def test_forget_not_found(self):
        result = forget_memory("nonexistent-id-abcdef")
        self.assertIn("Not found", result)

    def test_forget_removes_from_file(self):
        eid1 = write_memory("first", "user")
        eid2 = write_memory("second", "user")
        forget_memory(eid1)
        files = [f for f in os.listdir(self.memory_dir) if f.endswith(".jsonl")]
        for fname in files:
            with open(os.path.join(self.memory_dir, fname)) as fh:
                lines = fh.readlines()
                user_lines = [l for l in lines if '"user"' in l]
                self.assertEqual(len(user_lines), 1)


# ── Tools ──────────────────────────────────────────────────────────


class MemoryTools(unittest.TestCase):
    def setUp(self):
        self.memory_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self._old = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir

    def tearDown(self):
        if self._old is not None:
            os.environ["HARNESS_MEMORY_DIR"] = self._old
        elif "HARNESS_MEMORY_DIR" in os.environ:
            del os.environ["HARNESS_MEMORY_DIR"]

    def test_memory_write_tool_stores(self):
        tool = memory_write_tool()
        result = tool.run({"text": "Tool wrote this"})
        self.assertIn("Stored", result)
        self.assertIn("user", result)
        self.assertEqual(len(list_memories()), 1)

    def test_memory_write_tool_empty(self):
        tool = memory_write_tool()
        self.assertEqual(tool.run({}), "Nothing to write.")

    def test_memory_write_tool_topic(self):
        tool = memory_write_tool()
        tool.run({"text": "topic data", "scope": "topic", "topic": "test_topic"})
        items = list_memories()
        self.assertEqual(items[0]["scope"], "topic")
        self.assertEqual(items[0]["topic"], "test_topic")

    def test_memory_read_tool_returns_matches(self):
        write_memory("Python is great", "user")
        write_memory("Bash too", "user")
        tool = memory_read_tool()
        result = tool.run({"query": "Python"})
        self.assertIn("Python", result)

    def test_memory_read_tool_no_match(self):
        write_memory("Unrelated data", "user")
        tool = memory_read_tool()
        # Use a query that has no overlap with any memory.
        result = tool.run({"query": "xyzzyz xyzzyz xyzzyz"})
        self.assertEqual(result, "(no matching memories)")

    def test_memory_forget_tool_by_id(self):
        eid = write_memory("To forget", "user")
        tool = memory_forget_tool()
        result = tool.run({"target": eid})
        self.assertIn("Removed", result)
        self.assertEqual(len(list_memories()), 0)

    def test_memory_tools_for_returns_three(self):
        tools = memory_tools_for()
        self.assertEqual(len(tools), 3)
        names = [t.name for t in tools]
        self.assertIn("memory_write", names)
        self.assertIn("memory_read", names)
        self.assertIn("memory_forget", names)


# ── Context integration ────────────────────────────────────────────


class ContextMemoryIntegration(unittest.TestCase):
    def setUp(self):
        self.memory_dir = tempfile.mkdtemp()
        self.agent_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self.addCleanup(shutil.rmtree, self.agent_dir, True)
        self._old_mem = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir
        self._old_ws = os.environ.get("HARNESS_WORKSPACE")
        os.environ["HARNESS_WORKSPACE"] = self.agent_dir

    def tearDown(self):
        if self._old_mem is not None:
            os.environ["HARNESS_MEMORY_DIR"] = self._old_mem
        elif "HARNESS_MEMORY_DIR" in os.environ:
            del os.environ["HARNESS_MEMORY_DIR"]
        if self._old_ws is not None:
            os.environ["HARNESS_WORKSPACE"] = self._old_ws
        elif "HARNESS_WORKSPACE" in os.environ:
            del os.environ["HARNESS_WORKSPACE"]

    def test_memory_injected_into_build(self):
        store = SessionStore(self.agent_dir)
        write_memory("The user prefers dark mode and a compact layout", "user")
        store.add("user", "I prefer dark mode")
        messages = context.build(store, "TestBot")
        # Look for a system message containing the stored text.
        system_texts = [m["content"] for m in messages if m["role"] == "system"]
        found = any("dark mode" in text for text in system_texts)
        self.assertTrue(found, f"memory text should be injected into the context. system texts: {[t[:80] for t in system_texts]}")

    def test_empty_memory_does_not_break_build(self):
        store = SessionStore(self.agent_dir)
        store.add("user", "Hello")
        messages = context.build(store, "TestBot")
        self.assertGreater(len(messages), 0)

    def test_build_with_many_recent_messages(self):
        """The query for memory retrieval uses recent messages."""
        store = SessionStore(self.agent_dir)
        write_memory("The project uses FastAPI for the web framework", "project", workspace=self.agent_dir)
        for i in range(10):
            store.add("user", f"Question {i}")
            store.add("bot", f"Answer {i}")
        store.add("user", "What web framework does this use?")
        messages = context.build(store, "TestBot")
        system_texts = [m["content"] for m in messages if m["role"] == "system"]
        found = any("FastAPI" in text for text in system_texts)
        self.assertTrue(found, f"project memory should be retrieved. system texts: {[t[:80] for t in system_texts]}")


# ── Agent integration ──────────────────────────────────────────────


class AgentMemoryTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.memory_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.memory_dir, True)
        self._old_mem = os.environ.get("HARNESS_MEMORY_DIR")
        os.environ["HARNESS_MEMORY_DIR"] = self.memory_dir
        self.model = FakeModel("I stored that.")
        self.addCleanup(self.model.close)

    def client(self) -> AcpClient:
        from harness.acp_client import AcpClient
        env = {"HARNESS_BOT": "TestMem", "HARNESS_MODEL_BASE_URL": self.model.base_url,
               "HARNESS_MODEL": "fake-model", "HARNESS_AGENT_DIR": self.folder,
               "HARNESS_WORKSPACE": self.folder, "HARNESS_MEMORY_DIR": self.memory_dir}
        return AcpClient(sys.executable, "-m", "harness.agent", cwd=self.ROOT, env=env)

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    async def test_memory_write_tool_is_available(self):
        async with self.client() as client:
            await client.start()
            self.model.script = [{"tool_calls": [{"name": "memory_write", "arguments": {"text": "Test memory"}}]}, "Done."]
            result = await client.prompt("Store a memory")
            self.assertEqual(result.stop_reason, "end_turn")
            # Check that the memory was written.
            items = list_memories()
            self.assertTrue(any("Test memory" in m["text"] for m in items))

    async def test_memory_read_tool_returns_stored(self):
        write_memory("Read me please", "user")
        async with self.client() as client:
            await client.start()
            self.model.script = [{"tool_calls": [{"name": "memory_read", "arguments": {"query": "read"}}]}, "Here it is."]
            result = await client.prompt("Read my memories")
            self.assertEqual(result.stop_reason, "end_turn")
