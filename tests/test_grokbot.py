"""Grok Bot through a fake gbot: the order of the flags, the answers and the stopping.

No network and no Qt: the fake gbot is a small script in a temporary folder that
does what a behaviour file says and writes down what it was asked.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botwidget import config, grokbot, openbot

FAKE = '''#!/usr/bin/env python3
"""A fake gbot: it does what behaviour.json says and writes down what it was asked."""
import json
import os
import sys
import time

folder = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(folder, "argv.jsonl"), "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")

step = {}
path = os.path.join(folder, "behaviour.json")
if os.path.exists(path):
    with open(path) as handle:
        step = json.load(handle)
if isinstance(step, dict) and "steps" in step:
    steps = step["steps"]
    counter = os.path.join(folder, "count")
    count = 0
    if os.path.exists(counter):
        with open(counter) as handle:
            count = int(handle.read().strip() or 0)
    with open(counter, "w") as handle:
        handle.write(str(count + 1))
    step = steps[min(count, len(steps) - 1)]

time.sleep(float(os.environ.get("GBOT_FAKE_SLEEP", step.get("sleep", 0))))
sys.stdout.write(os.environ.get("GBOT_FAKE_STDOUT", step.get("stdout", "")))
sys.stderr.write(os.environ.get("GBOT_FAKE_STDERR", step.get("stderr", "")))
sys.exit(int(os.environ.get("GBOT_FAKE_RC", step.get("rc", 0))))
'''


def entry(text: str, entry_id: str = "t1") -> dict:
    """A message of the bot, as it shows up in the thread."""
    return {"kind": "send-message", "id": entry_id, "timestampMs": 5,
            "message": {"type": "text", "content": text}}


def thread(entries: list, **extra) -> str:
    """The answer of gbot on a thread."""
    doc = {"target": {"id": "t1", "name": "General"},
           "transcript": {"entries": entries, "nextBeforeSeq": 1}}
    doc.update(extra)
    return json.dumps(doc)


class FakeGbot(unittest.TestCase):
    """Should talk to gbot the way the CLI wants it, and stop when gbot says so."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.gbot = os.path.join(self.folder, "gbot")
        with open(self.gbot, "w") as handle:
            handle.write(FAKE)
        os.chmod(self.gbot, 0o755)
        old = openbot.GBOT
        self.addCleanup(setattr, openbot, "GBOT", old)
        openbot.GBOT = self.gbot
        self.time = [1000.0]

    def behaviour(self, **kwargs):
        with open(os.path.join(self.folder, "behaviour.json"), "w") as handle:
            json.dump(kwargs, handle)

    def steps(self, *steps):
        with open(os.path.join(self.folder, "behaviour.json"), "w") as handle:
            json.dump({"steps": list(steps)}, handle)

    def argv(self) -> list:
        """What the fake gbot was asked, one list per call."""
        path = os.path.join(self.folder, "argv.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def link(self) -> grokbot.GrokLink:
        return grokbot.GrokLink("General", now=lambda: self.time[0])


class GbotFlags(FakeGbot):
    """Should put the flags after the subcommand, the way gbot wants them."""

    def test_the_bots_are_asked_for_with_the_flag_last(self):
        self.behaviour(stdout=json.dumps({"bots": []}))
        openbot.grok_bot_status()
        self.assertEqual(self.argv()[0], ["bots", "list", "--json"])

    def test_the_thread_and_the_message_use_the_documented_order(self):
        self.steps({"stdout": thread([entry("Hoi")])}, {"stdout": thread([])},
                   {"stdout": json.dumps({"delivery": "delivered"})})
        link = self.link()
        link.poll()
        link.poll()
        link.send("-text")
        first, second, third = self.argv()
        self.assertEqual(first, ["thread", "General", "--limit", "40", "--json"])
        self.assertEqual(second, ["thread", "General", "--limit", "40", "--after", "t1", "--json"])
        self.assertEqual(third, ["send", "General", "--json", "--", "-text"])


class Answers(FakeGbot):
    """Should show what the bot showed the user, and nothing else."""

    def test_a_message_of_the_bot_comes_in(self):
        self.behaviour(stdout=thread([entry("Hoi")]))
        link = self.link()
        link.poll()
        self.assertEqual(link.chat()["messages"], [{"role": "bot", "text": "Hoi"}])

    def test_traffic_between_the_bot_and_the_agent_stays_out(self):
        entries = [entry("Hoi"),
                   {"kind": "message", "role": "assistant", "id": "t2",
                    "toAgent": {"id": "a", "name": "Bot", "kind": "agent"},
                    "message": {"type": "text", "content": "intern"}},
                   {"kind": "something-else", "id": "t3"}]
        self.behaviour(stdout=thread(entries))
        link = self.link()
        link.poll()
        self.assertEqual([m["text"] for m in link.chat()["messages"]], ["Hoi"])

    def test_garbage_never_breaks_the_parser(self):
        rubbish = [None, "text", {}, {"kind": "send-message"}, {"kind": "send-message", "message": "x"},
                   {"kind": "send-message", "message": {"type": "text", "content": "  "}}]
        self.assertEqual(grokbot.parse_entries(rubbish), [])

    def test_the_same_answer_never_comes_twice(self):
        self.steps({"stdout": thread([entry("Hoi")])}, {"stdout": thread([entry("Hoi")])})
        link = self.link()
        link.poll()
        link.poll()
        self.assertEqual(len(link.chat()["messages"]), 1)

    def test_a_poll_without_new_entries_adds_nothing(self):
        self.steps({"stdout": thread([entry("Hoi")])}, {"stdout": thread([], entryCount=0)})
        link = self.link()
        link.poll()
        link.poll()
        self.assertEqual(len(link.chat()["messages"]), 1)

    def test_a_gap_replaces_the_answers_instead_of_repeating_them(self):
        self.steps({"stdout": thread([entry("Hoi")])},
                   {"stdout": thread([entry("Hoi")], gapReset=True)})
        link = self.link()
        link.poll()
        link.poll()
        self.assertEqual([m["text"] for m in link.chat()["messages"]], ["Hoi"])

    def test_the_line_of_the_user_survives_a_gap(self):
        self.steps({"stdout": thread([entry("Hoi")])}, {"stdout": thread([entry("Hoi")], gapReset=True)})
        self.behaviour(rc=0, stdout=json.dumps({"delivery": "delivered"}))
        link = self.link()
        link.poll()
        link.send("Hoi")
        self.steps({"stdout": thread([entry("Hoi")], gapReset=True)})
        link.poll()
        self.assertEqual([(m["role"], m["text"]) for m in link.chat()["messages"]],
                         [("bot", "Hoi"), ("user", "Hoi")])


class Stopped(FakeGbot):
    """Should stop when there is no route, and not try again on its own."""

    def test_no_live_route_stops_the_link(self):
        self.behaviour(rc=75, stderr="the Grok Bot app is not running")
        link = self.link()
        link.poll()
        self.assertTrue(link.stopped)
        self.assertIn("no live route", link.status)
        self.assertIn("not running", link.status)

    def test_a_stopped_link_does_not_ask_again(self):
        self.behaviour(rc=75, stderr="no route")
        link = self.link()
        link.poll()
        self.time[0] += 600
        self.assertFalse(link.due(), "no loop while it is stopped")
        link.resume()
        self.assertTrue(link.due(), "the next message of the user tries again")

    def test_a_gbot_that_is_not_there_stops_the_link(self):
        self.behaviour(rc=127, stderr="gbot: command not found")
        link = self.link()
        link.poll()
        self.assertTrue(link.stopped)
        self.assertIn("not installed", link.status)

    def test_a_missing_gbot_stops_the_link(self):
        openbot.GBOT = os.path.join(self.folder, "nothing")
        link = self.link()
        link.poll()
        self.assertTrue(link.stopped)
        self.assertIn("not installed", link.status)

    def test_a_gbot_that_gives_no_answer_does_not_stop_the_link(self):
        self.behaviour(sleep=1.0)
        link = self.link()
        link.TIMEOUT_S = 0.2
        link.poll()
        self.assertFalse(link.stopped)
        self.assertIn("did not answer", link.status)


class Timing(FakeGbot):
    """Should look quicker while it waits for an answer, and give up after ten minutes."""

    def test_the_look_comes_quicker_while_it_waits(self):
        self.behaviour(stdout=json.dumps({"delivery": "delivered"}))
        link = self.link()
        self.assertTrue(link.due(), "never looked yet")
        link.poll()
        self.assertFalse(link.due())
        link.send("Hoi")
        self.assertTrue(link.waiting)
        self.assertIn("Waiting for General", link.chat()["activity"])
        self.time[0] += grokbot.GrokLink.FAST_S - 1
        self.assertFalse(link.due())
        self.time[0] += 1
        self.assertTrue(link.due(), "every three seconds while it waits")

    def test_the_waiting_ends_by_itself_after_ten_minutes(self):
        self.behaviour(stdout=json.dumps({"delivery": "delivered"}))
        link = self.link()
        link.send("Hoi")
        self.time[0] += grokbot.GrokLink.WAIT_MAX_S
        self.assertFalse(link.waiting)
        self.assertIn("check every minute", link.status)

    def test_an_answer_ends_the_waiting(self):
        self.steps({"stdout": json.dumps({"delivery": "delivered"})}, {"stdout": thread([entry("Hoi")])})
        link = self.link()
        link.send("Hoi")
        self.assertTrue(link.waiting)
        link.poll()
        self.assertFalse(link.waiting)


class Sending(FakeGbot):
    """Should send a message once, and say why when it does not go out."""

    def test_a_message_that_goes_out_is_kept_as_a_line_of_the_user(self):
        self.behaviour(stdout=json.dumps({"delivery": "delivered"}))
        link = self.link()
        ok, error = link.send("Hoi")
        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertEqual(link.chat()["messages"], [{"role": "user", "text": "Hoi"}])

    def test_a_refused_message_is_not_kept_as_a_line_of_the_user(self):
        self.behaviour(rc=1, stdout=json.dumps({"delivery": "rejected", "error": "x", "exitCode": 1}))
        link = self.link()
        ok, error = link.send("Hoi")
        self.assertFalse(ok)
        self.assertEqual(error, "x")
        self.assertEqual(link.chat()["messages"], [])

    def test_an_error_given_as_an_object_still_reads_as_words(self):
        self.behaviour(rc=1, stdout=json.dumps({"error": {"code": "render-failed", "message": "gateway down"}}))
        ok, error = self.link().send("Hoi")
        self.assertFalse(ok)
        self.assertEqual(error, "gateway down")

    def test_the_conversation_keeps_only_the_latest_lines(self):
        self.behaviour(stdout=json.dumps({"delivery": "delivered"}))
        link = self.link()
        link.KEEP = 3
        for n in range(5):
            link.send(f"line {n}")
        self.assertEqual([m["text"] for m in link.messages], ["line 2", "line 3", "line 4"])

    def test_a_message_is_never_sent_twice(self):
        self.behaviour(rc=1, stdout=json.dumps({"error": "no route"}))
        link = self.link()
        link.send("Hoi")
        self.assertEqual(len(self.argv()), 1, "one call, no retry")


class Target(unittest.TestCase):
    """Should talk to the bot of widget.json, and to General without one."""

    def test_the_default_is_general(self):
        from unittest import mock
        with mock.patch.object(grokbot, "widget_config", return_value={}):
            self.assertEqual(grokbot.target(), "General")

    def test_widget_json_names_the_bot(self):
        from unittest import mock
        with mock.patch.object(grokbot, "widget_config", return_value={"grokbot_target": "Team"}):
            self.assertEqual(grokbot.target(), "Team")

    def test_the_target_is_kept_in_widget_json(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        old = config.CONFIG_PATH
        self.addCleanup(setattr, config, "CONFIG_PATH", old)
        config.CONFIG_PATH = os.path.join(folder, "widget.json")
        config.save_widget_config(grokbot_target="Team")
        self.assertEqual(config.widget_config()["grokbot_target"], "Team")

    def test_the_face_of_a_grok_bot_has_its_own_id(self):
        self.assertEqual(grokbot.face_id("General"), "grok:General")
        self.assertTrue(grokbot.is_grok("grok:General"))
        self.assertFalse(grokbot.is_grok("agent-1"))
