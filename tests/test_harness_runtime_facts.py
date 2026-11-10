"""Pinned system prompt must state the real model and whether it runs locally, never guess."""

import json
import unittest
from unittest import mock

from harness.agent import context
from harness.agent.models import ChatCompletions


class _Stub:
    def __init__(self, base_url="", model="", reported_model="", model_owned_by=""):
        self.base_url = base_url
        self.model = model
        self.reported_model = reported_model
        self.model_owned_by = model_owned_by


class RuntimeFacts(unittest.TestCase):

    def test_local_loopback_is_local_and_does_not_name_openrouter(self):
        text = context.runtime_facts(_Stub(
            base_url="http://127.0.0.1:8080/v1", model="local",
            reported_model="Qwen2.5-7B-Instruct", model_owned_by="llama.cpp"))
        self.assertIn("Qwen2.5-7B-Instruct", text)
        self.assertIn("llama.cpp", text)
        self.assertIn("running locally on this machine (127.0.0.1)", text)
        self.assertNotIn("OpenRouter", text)
        self.assertIn("never guess", text.lower())

    def test_localhost_and_ipv6_loopback_count_as_local(self):
        for url in ("http://localhost:8080/v1", "http://[::1]:8080/v1"):
            text = context.runtime_facts(_Stub(base_url=url, model="local"))
            self.assertIn("running locally on this machine", text, url)
            self.assertNotIn("OpenRouter", text)

    def test_remote_openrouter_host_is_named_only_because_the_host_says_so(self):
        text = context.runtime_facts(_Stub(
            base_url="https://openrouter.ai/api/v1", model="anthropic/claude-sonnet-4"))
        self.assertIn("anthropic/claude-sonnet-4", text)
        self.assertIn("OpenRouter", text)
        self.assertIn("running remotely (openrouter.ai)", text)
        self.assertNotIn("running locally", text)

    def test_unknown_remote_host_does_not_invent_openrouter(self):
        text = context.runtime_facts(_Stub(
            base_url="https://api.example.com/v1", model="my-model"))
        self.assertIn("my-model", text)
        self.assertIn("running remotely (api.example.com)", text)
        self.assertIn("OpenAI-compatible", text)
        self.assertNotIn("OpenRouter", text)

    def test_no_model_adds_no_facts_and_does_not_guess(self):
        self.assertEqual(context.runtime_facts(None), "")
        self.assertEqual(context.runtime_facts(), "")

    def test_build_pins_facts_in_the_system_prompt(self):
        store = mock.Mock()
        store.summary = ""
        store.get.return_value = ""
        store.messages.return_value = []
        messages = context.build(store, "Ada", model=_Stub(
            base_url="http://127.0.0.1:1234/v1", model="local", reported_model="local"))
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        self.assertIn("Model: local", system)
        self.assertIn("running locally on this machine (127.0.0.1)", system)
        self.assertNotIn("OpenRouter", system)

    def test_build_without_a_model_does_not_claim_a_cloud_provider(self):
        store = mock.Mock()
        store.summary = ""
        store.get.return_value = ""
        store.messages.return_value = []
        messages = context.build(store, "Ada")
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        self.assertNotIn("OpenRouter", system)
        self.assertNotIn("Runtime facts", system)

    def test_models_payload_records_the_listed_name_not_a_guess(self):
        model = ChatCompletions("http://127.0.0.1:9/v1", "local")
        model._apply_models_payload({
            "data": [{"id": "local", "owned_by": "llama.cpp", "object": "model"}],
        })
        self.assertEqual(model.reported_model, "local")
        self.assertEqual(model.model_owned_by, "llama.cpp")
        # A mismatched list with several ids must not pick a random one.
        other = ChatCompletions("http://127.0.0.1:9/v1", "local")
        other._apply_models_payload({"data": [
            {"id": "alpha", "owned_by": "lab"},
            {"id": "beta", "owned_by": "lab"},
        ]})
        self.assertEqual(other.reported_model, "")
        self.assertEqual(other.model_owned_by, "")
        # A single listed model is what the server is actually running.
        one = ChatCompletions("http://127.0.0.1:9/v1", "local")
        one._apply_models_payload({"data": [{"id": "Qwen2.5-7B-Instruct", "owned_by": "llama.cpp"}]})
        self.assertEqual(one.reported_model, "Qwen2.5-7B-Instruct")
