"""Grok Bot through a fake gbot: the order of the flags, the answers and the stopping.

No network and no Qt: the fake gbot is a small script in a temporary folder that
does what a behaviour file says and writes down what it was asked.
"""

import json
import os
import shutil
import sys
import tempfile
import time
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
with open(os.path.join(folder, "env.jsonl"), "a") as handle:
    handle.write(json.dumps(os.environ.get("GBOT_NO_WAKE")) + "\\n")

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

if step.get("grandchild"):
    # Like the wrapper starting node: a child that would outlive us if nobody stopped the group.
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open(os.path.join(folder, "grandchild.pid"), "w") as handle:
        handle.write(str(child.pid))
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


# What gbot 0.12.4 printed for a real send to General (measured on the PC), with placeholder ids:
# delivery stays "unknown" even when the message went out; result.accepted says it did.
SENT = json.dumps({"correlationId": "corr-0000", "delivery": "unknown", "envelopeId": "env-0000", "exitCode": 0,
                   "hop": 0, "id": "bot-0000", "kind": "bot", "maxHops": 4, "name": "General",
                   "result": {"accepted": True}})


@unittest.skipIf(sys.platform == "win32", "the fake gbot is a script with a #! line")
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

    def envs(self) -> list:
        """GBOT_NO_WAKE as each call of the fake gbot saw it."""
        path = os.path.join(self.folder, "env.jsonl")
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
                   {"stdout": SENT})
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

    def test_a_second_identical_answer_without_an_id_still_shows(self):
        no_id = {"kind": "send-message", "message": {"type": "text", "content": "Ok"}}
        self.steps({"stdout": thread([entry("Hoi")])}, {"stdout": thread([no_id, no_id])})
        link = self.link()
        link.poll()
        link.poll()
        self.assertEqual([m["text"] for m in link.chat()["messages"]], ["Hoi", "Ok", "Ok"])

    def test_the_same_id_at_another_time_is_another_answer(self):
        later = dict(entry("Hoi"), timestampMs=9)
        self.steps({"stdout": thread([entry("Hoi")])}, {"stdout": thread([entry("Hoi"), later])})
        link = self.link()
        link.poll()
        link.poll()
        self.assertEqual([m["text"] for m in link.chat()["messages"]], ["Hoi", "Hoi"])

    def test_the_first_look_shows_only_the_latest_answers(self):
        many = [entry(f"answer {n}", f"t{n}") for n in range(12)]
        self.behaviour(stdout=thread(many))
        link = self.link()
        link.poll()
        texts = [m["text"] for m in link.chat()["messages"]]
        self.assertEqual(texts, [f"answer {n}" for n in range(7, 12)])
        self.assertEqual(link.cursor, "t11", "the next look starts after the newest entry")

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
        self.behaviour(rc=0, stdout=SENT)
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
        self.assertIn("connection stopped", link.note())
        self.assertIn("send a message to try again", link.note())
        self.assertIn("not running", link.note())

    def test_a_send_without_a_route_still_names_it(self):
        self.behaviour(rc=75, stderr="no route")
        link = self.link()
        ok, error = link.send("Hoi")
        self.assertFalse(ok)
        self.assertIn("no live route", error)

    def test_a_stopped_link_does_not_ask_again(self):
        self.behaviour(rc=75, stderr="no route")
        link = self.link()
        link.poll()
        self.time[0] += 600
        self.assertFalse(link.due(), "no loop while it is stopped")
        self.assertFalse(link.active(), "no timer while it is stopped")
        link.request_fetch()
        self.assertFalse(link.due(), "opening the bubble does not retry a stopped link")
        link.resume()
        link.request_fetch()
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


class Orphans(FakeGbot):
    """Should stop gbot and what it started (node) when it gives no answer in time."""

    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc to see the grandchild")
    def test_a_timeout_stops_the_whole_group(self):
        self.behaviour(sleep=30, grandchild=True)
        link = self.link()
        link.TIMEOUT_S = 1.0
        link.poll()
        with open(os.path.join(self.folder, "grandchild.pid")) as handle:
            pid = int(handle.read())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            with open(f"/proc/{pid}/stat") as stat:
                if stat.read().split(")")[-1].split()[0] == "Z":
                    break  # a zombie is dead, it only waits for init to reap it
            time.sleep(0.1)
        else:
            self.fail("the grandchild outlived the timeout")


class Timing(FakeGbot):
    """Should look quicker while it waits for an answer, and give up after ten minutes."""

    def test_nothing_is_asked_while_there_is_nothing_to_wait_for(self):
        link = self.link()
        self.assertFalse(link.due(), "no look at start")
        self.assertFalse(link.active(), "no timer when idle")
        self.time[0] += 3600
        self.assertFalse(link.due(), "no idle polling, not even after an hour")

    def test_opening_the_bubble_looks_once(self):
        self.behaviour(stdout=thread([entry("Hoi")]))
        link = self.link()
        link.request_fetch()
        self.assertTrue(link.due())
        link.poll()
        self.assertFalse(link.due(), "one look, not a loop")
        self.assertFalse(link.active())
        self.time[0] += 1
        link.request_fetch()
        self.assertFalse(link.due(), "opening it again right away does not ask again")

    def test_it_looks_every_few_seconds_while_it_waits(self):
        self.steps({"stdout": SENT}, {"stdout": thread([])})
        link = self.link()
        link.send("Hoi")
        self.assertTrue(link.waiting)
        self.assertTrue(link.active())
        self.assertIn("Waiting for General", link.chat()["activity"])
        self.assertTrue(link.due(), "the first look comes right after the send")
        link.poll()
        self.time[0] += grokbot.GrokLink.FAST_S - 1
        self.assertFalse(link.due())
        self.time[0] += 1
        self.assertTrue(link.due(), "every FAST_S seconds while it waits")

    def test_the_waiting_ends_by_itself_and_so_does_the_timer(self):
        self.behaviour(stdout=SENT)
        link = self.link()
        link.send("Hoi")
        self.time[0] += grokbot.GrokLink.WAIT_MAX_S
        self.assertFalse(link.waiting)
        self.assertFalse(link.active(), "no timer after the wait window")
        self.assertFalse(link.due())
        self.time[0] += 3600
        self.assertFalse(link.due(), "it stays quiet after the window")
        self.assertIn("No answer from General yet", link.status)

    def test_an_answer_ends_the_waiting(self):
        self.steps({"stdout": SENT}, {"stdout": thread([entry("Hoi")])})
        link = self.link()
        link.send("Hoi")
        self.assertTrue(link.waiting)
        link.poll()
        self.assertFalse(link.waiting)


class Sending(FakeGbot):
    """Should send a message once, and say why when it does not go out."""

    def test_a_message_that_goes_out_is_kept_as_a_line_of_the_user(self):
        self.behaviour(stdout=SENT)
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
        self.behaviour(stdout=SENT)
        link = self.link()
        link.KEEP = 3
        for n in range(5):
            link.send(f"line {n}")
        self.assertEqual([m["text"] for m in link.messages], ["line 2", "line 3", "line 4"])

    def test_the_measured_answer_of_a_send_counts_as_sent(self):
        self.behaviour(stdout=SENT)
        self.assertEqual(self.link().send("Hoi"), (True, ""))

    def test_a_send_that_was_not_accepted_does_not_count(self):
        for answer in ({"delivery": "unknown", "exitCode": 0, "result": {"accepted": False}},
                       {"delivery": "unknown", "exitCode": 0}, {"delivery": "delivered"}):
            with self.subTest(answer=answer):
                self.behaviour(stdout=json.dumps(answer))
                link = self.link()
                ok, error = link.send("Hoi")
                self.assertFalse(ok)
                self.assertTrue(error)
                self.assertEqual(link.chat()["messages"], [])

    def test_a_send_that_timed_out_shows_with_a_question_mark(self):
        self.behaviour(sleep=2.0)
        link = self.link()
        link.TIMEOUT_S = 0.3
        ok, _error = link.send("Hoi")
        self.assertTrue(ok, "not refused: it may have gone out")
        self.assertEqual(link.chat()["messages"], [{"role": "user", "text": "Hoi (?)"}])
        self.assertTrue(link.waiting, "an answer may still come")
        self.assertIn("may or may not", link.note())

    def test_the_unsure_note_stays_through_a_look_and_goes_with_an_answer(self):
        self.steps({"sleep": 2.0}, {"stdout": thread([])}, {"stdout": thread([entry("Hoi")], cursor="t1")})
        link = self.link()
        link.TIMEOUT_S = 0.3
        link.send("Hoi")
        link.poll()
        self.assertIn("may or may not", link.note(), "a look without an answer keeps it in sight")
        link.poll()
        self.assertEqual(link.note(), "", "the answer shows the message arrived")

    def test_only_a_send_may_wake_the_app(self):
        self.steps({"stdout": SENT}, {"stdout": thread([])})
        link = self.link()
        link.send("Hoi")
        link.poll()
        self.assertEqual(self.envs(), [None, "1"], "send without GBOT_NO_WAKE, thread with GBOT_NO_WAKE=1")

    def test_a_read_never_wakes_the_app_even_when_the_caller_says_so(self):
        self.behaviour(stdout=thread([]))
        old = os.environ.get("GBOT_NO_WAKE")
        os.environ["GBOT_NO_WAKE"] = "0"
        self.addCleanup(lambda: os.environ.pop("GBOT_NO_WAKE") if old is None else os.environ.update(GBOT_NO_WAKE=old))
        self.link().poll()
        self.assertEqual(self.envs(), ["1"])

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


class GrokFaceBubble(unittest.TestCase):
    """Should show the notes of a Grok face in its bubble, also with nothing in the chat."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication

            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = self.face.FaceWindow(grokbot.face_id("General"), "General", spot=(300, 400))
        self.window._poll_timer.stop()
        self.addCleanup(self.window.close_face)

    def text(self, messages):
        from botwidget.markdown import block_text
        return block_text(self.window._chat_blocks(messages, greet=False))

    def test_a_stopped_read_says_so_in_the_bubble(self):
        self.window.grok._apply(grokbot.Result(75, None, "app not running"))
        self.assertIn("connection stopped", self.text([]))
        self.assertIn("send a message to try again", self.text([{"role": "bot", "text": "Hoi"}]))

    def test_an_unsure_send_says_so_in_the_bubble(self):
        self.window.grok.unsure = grokbot.UNSURE_NOTE
        self.assertIn("may or may not have gone out", self.text([{"role": "user", "text": "Hoi (?)"}]))
