"""Phase 4: the Anthropic adapter and its cache marks, against a fake Messages API."""

import json
import os
import shutil
import sys
import tempfile
import unittest

from harness.acp_client import AcpClient

from harness.agent.models import AnthropicMessages, from_environment
from tests.fake_anthropic import FakeAnthropic

TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                           "parameters": {"type": "object",
                                                          "properties": {"path": {"type": "string"}}}}}]


class CacheMarks(unittest.TestCase):
    def setUp(self):
        self.server = FakeAnthropic()
        self.addCleanup(self.server.close)
        self.model = AnthropicMessages("claude-test", "sk-test", self.server.base_url)

    def test_the_stable_prefix_carries_a_cache_mark_and_the_newest_turn_does_too(self):
        messages = [{"role": "system", "content": "You are Test."},
                    {"role": "user", "content": "Hallo"}]
        list(self.model.stream(messages, tools=TOOLS))
        body = self.server.requests[-1]
        self.assertEqual(body["system"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["messages"][-1]["content"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["tools"][0]["name"], "read_file", "tools go out in Anthropic's shape")
        self.assertEqual(body["tools"][0]["input_schema"]["type"], "object")

    def test_a_twenty_turn_replay_is_mostly_cached_after_the_first_turn(self):
        """The done-criterion for phase 4: the prefix is stable, so later turns read from cache."""
        messages = [{"role": "system", "content": "You are Test. Answer briefly."}]
        shares = []
        for turn in range(20):
            messages.append({"role": "user", "content": f"vraag {turn} " + "x" * 200})
            events = list(self.model.stream(messages))
            reply = "".join(value for kind, value in events if kind == "text")
            usage = next(dict(value) for kind, value in events if kind == "usage")
            messages.append({"role": "assistant", "content": reply.strip()})
            shares.append(usage["prompt_tokens_details"]["cached_tokens"] / usage["prompt_tokens"])
        self.assertEqual(shares[0], 0.0, "nothing is cached on the first turn")
        # From the third turn the history outweighs the new question and most of it is a cache read.
        self.assertTrue(all(share > 0.5 for share in shares[2:]),
                        f"the history is mostly cached: {shares}")
        self.assertGreater(shares[-1], 0.9, "by turn twenty only the new question is fresh")

    def test_a_tool_use_block_becomes_a_tool_call_event(self):
        self.server.replies = [{"text": "Even lezen. ",
                                "tool": {"name": "read_file", "input": {"path": "/tmp/x"}}}, {"text": "Klaar."}]
        events = list(self.model.stream([{"role": "user", "content": "Lees het"}]))
        calls = next(value for kind, value in events if kind == "tool_calls")
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "/tmp/x"})
        self.assertEqual("".join(value for kind, value in events if kind == "text"), "Even lezen. ")

    def test_a_tool_result_goes_back_as_a_tool_result_block(self):
        messages = [{"role": "user", "content": "Lees het"},
                    {"role": "assistant", "content": "",
                     "tool_calls": [{"id": "call-1", "type": "function",
                                     "function": {"name": "read_file", "arguments": "{\"path\": \"/tmp/x\"}"}}]},
                    {"role": "tool", "tool_call_id": "call-1", "content": "blauw"}]
        list(self.model.stream(messages))
        sent = self.server.requests[-1]["messages"]
        result = sent[-1]["content"][-1]
        self.assertEqual((result["type"], result["tool_use_id"], result["content"]),
                         ("tool_result", "call-1", "blauw"))
        self.assertIn("cache_control", result, "the newest block is the cache breakpoint")

    def test_the_environment_picks_the_anthropic_adapter(self):
        model = from_environment({"HARNESS_MODEL_PROVIDER": "anthropic", "HARNESS_MODEL_API_KEY": "sk-test",
                                  "HARNESS_MODEL_BASE_URL": self.server.base_url, "HARNESS_MODEL": "claude-test"})
        self.assertIsInstance(model, AnthropicMessages)
        self.assertEqual(model.model, "claude-test")


class AgentTurn(unittest.IsolatedAsyncioTestCase):
    """The whole agent, not only the adapter: a turn through the Anthropic shape lands in usage.jsonl."""

    async def test_two_turns_log_the_cache_read_the_provider_reported(self):
        server = FakeAnthropic()
        self.addCleanup(server.close)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        client = AcpClient(sys.executable, "-m", "harness.agent", cwd=os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))),
            env={"HARNESS_BOT": "T", "HARNESS_MODEL_PROVIDER": "anthropic", "HARNESS_MODEL": "claude-test",
                 "HARNESS_MODEL_API_KEY": "sk-test", "HARNESS_MODEL_BASE_URL": server.base_url,
                 "HARNESS_AGENT_DIR": folder})
        async with client:
            await client.start()
            await client.prompt("Hallo")
            turn = await client.prompt("En nog eens, met wat meer woorden erbij")
        self.assertEqual(turn.stop_reason, "end_turn")
        usage = [json.loads(line) for line in open(os.path.join(folder, "usage.jsonl"))]
        self.assertEqual(len(usage), 2)
        self.assertGreater(usage[-1]["cached_tokens"], 0, "the second turn reads the cached prefix")
        self.assertGreater(usage[-1]["input_tokens"], usage[-1]["cached_tokens"])


if __name__ == "__main__":
    unittest.main()
