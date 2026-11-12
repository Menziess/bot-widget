"""Phase 1: an ACP agent behind the calls the face already makes, driven by the fake agent."""

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

from botwidget import acplink
from botwidget.acplink import AcpLink

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = f"{sys.executable} {os.path.join(ROOT, 'tests', 'fake_acp_agent.py')}"


def wait_for(condition, timeout: float = 20.0):
    """Wait for something the agent pushes; the link answers from another thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


CONFIGURED = {"acp_bots": [
    {"name": "Local Bot", "command": "python -m harness.agent",
     "env": {"HARNESS_MODEL": "local", "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1",
             "PATH": "/nope", "api_key": "leak"}, "key_file": "~/.config/llm/key"},
    {"name": "no command"},
    "not an entry",
]}


class Configured(unittest.TestCase):
    """A face per bot in widget.json, with its own command, env and key file."""

    def test_a_configured_bot_becomes_a_face_with_its_command_and_its_harness_env(self):
        with mock.patch.object(acplink, "widget_config", return_value=CONFIGURED):
            bots = acplink.configured_bots()
            self.assertEqual([bot["id"] for bot in bots], ["acp:local-bot"])
            self.assertEqual(bots[0]["name"], "Local Bot")
            self.assertEqual(acplink.target_for("acp:local-bot"), "python -m harness.agent")
            options = acplink.options_for("acp:local-bot")
        self.assertEqual(options["face"], "acp:local-bot")
        self.assertEqual(options["env"], {"HARNESS_MODEL": "local",
                                          "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1"})
        self.assertEqual(options["key_file"], "~/.config/llm/key",
                         "only the path is in widget.json, never the key")

    def test_an_unconfigured_face_falls_back_to_the_settings(self):
        with mock.patch.object(acplink, "widget_config", return_value={"acp_target": "hermes-acp"}):
            self.assertEqual(acplink.target_for("acp:whatever"), "hermes-acp")
            self.assertEqual(acplink.options_for("acp:whatever"), {})

    def test_the_key_is_read_from_its_file_into_the_environment(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        key = os.path.join(folder, "key")
        with open(key, "w") as fh:
            fh.write("sk-from-file\n")
        link = AcpLink("python -m harness.agent", env={"HARNESS_MODEL": "local"}, key_file=key)
        self.addCleanup(link.close)
        self.addCleanup(shutil.rmtree, link.room(), True)
        self.assertEqual(link._environment(),
                         {"HARNESS_MODEL": "local", "HARNESS_MODEL_API_KEY": "sk-from-file"})

    def test_a_key_file_that_cannot_be_read_says_which_file(self):
        link = AcpLink("python -m harness.agent", key_file="/nonexistent/llm/key")
        self.addCleanup(link.close)
        self.addCleanup(shutil.rmtree, link.room(), True)
        with self.assertRaises(RuntimeError) as caught:
            link._environment()
        self.assertIn("/nonexistent/llm/key", str(caught.exception))

    def test_a_prefixed_id_is_kept_once_and_the_connection_supplies_the_key(self):
        """Should ignore a second bot with the same id, and read the key file from the connection."""
        config = {"connections": [{"id": "c", "base_url": "http://127.0.0.1:9/v1", "model": "qwen",
                                   "key_file": "/keys/one", "enabled": True}],
                  "acp_bots": [
                      {"id": "acp:same", "name": "One", "command": "python -m harness.agent", "connection": "c"},
                      {"id": "acp:same", "name": "Two", "command": "python -m harness.agent", "connection": "c"},
                  ]}
        with mock.patch.object(acplink, "widget_config", return_value=config):
            bots = acplink.configured_bots()
        self.assertEqual([bot["id"] for bot in bots], ["acp:same"])
        self.assertEqual(bots[0]["key_file"], "/keys/one")
        self.assertEqual(bots[0]["env"]["HARNESS_MODEL"], "qwen")


class AcpTurns(unittest.TestCase):
    def link(self, **kwargs) -> AcpLink:
        face = "acp:test-" + next(tempfile._get_candidate_names())
        kwargs.setdefault("face", face)
        link = AcpLink(FAKE, **kwargs)
        self.addCleanup(shutil.rmtree, link.room(), True)
        self.addCleanup(link.close)
        return link

    def test_a_message_shows_the_thought_as_activity_and_then_the_answer(self):
        link = self.link()
        ok, error = link.send("slow down")
        self.assertTrue(ok, error)
        self.assertTrue(link.active(), "the face keeps drawing while the turn runs")
        self.assertTrue(wait_for(lambda: link.chat()["activity"].startswith("step")))
        link.cancel()
        self.assertTrue(wait_for(lambda: not link.active()))
        chat = link.chat()
        self.assertEqual(chat["activity"], "")
        self.assertEqual([message["role"] for message in chat["messages"]], ["user", "bot"])
        self.assertIn("part 0", chat["messages"][-1]["text"])

    def test_a_restart_loads_the_saved_session(self):
        face = "acp:restart-" + next(tempfile._get_candidate_names())
        first = AcpLink(FAKE, face=face)
        self.addCleanup(shutil.rmtree, first.room(), True)
        first.send("hello")
        self.assertTrue(wait_for(lambda: not first.active()))
        first.close()
        second = AcpLink(FAKE, face=face)
        self.addCleanup(second.close)
        second.send("again")
        self.assertTrue(wait_for(lambda: not second.active()))
        self.assertTrue(wait_for(lambda: any("restored" in message["text"]
                                             for message in second.chat()["messages"])),
                        "the saved session is in the bubble before the next message")
        messages = second.chat()["messages"]
        self.assertEqual([message["role"] for message in messages], ["bot", "user", "bot"])
        self.assertIn("restored", messages[0]["text"])

    def test_a_turn_cut_off_by_a_restart_is_picked_up_again_without_a_message_from_you(self):
        face = "acp:resume-" + next(tempfile._get_candidate_names())
        first = AcpLink(FAKE, face=face)
        self.addCleanup(shutil.rmtree, first.room(), True)
        first.send("hello")
        self.assertTrue(wait_for(lambda: not first.active()))
        first.close(wait=5)  # until its agent is gone: a process still open when its loop ends is a warning on Windows
        second = AcpLink(FAKE, face=face, env={"FAKE_ACP_INTERRUPTED": "1"})
        self.addCleanup(second.close, 5)
        self.assertTrue(wait_for(lambda: any("[resume]" in message["text"] for message in second.chat()["messages"])),
                        "the agent answered the turn that was cut off")
        self.assertTrue(wait_for(lambda: not second.active()))
        self.assertNotIn("user", [message["role"] for message in second.chat()["messages"][1:]],
                         "picking up again is not a new message of yours")

    def test_a_model_error_is_shown_in_the_note_instead_of_a_bare_refusal(self):
        from harness.acp_client import Turn
        link = self.link()

        class Stub:
            async def prompt(self, text):
                return Turn(stop_reason="refusal", error="HTTP 401: invalid api key")

        async def fake_ensure():
            # Boot may call this stand-in before the real opener clears the flag.
            try:
                return Stub()
            finally:
                with link._lock:
                    link._booting = False

        link._ensure = fake_ensure
        link.send("hoi")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.note(), "HTTP 401: invalid api key")

    def test_a_cancel_with_nothing_running_never_reaches_the_agent(self):
        link = self.link()

        class Stub:
            cancels = 0

            async def cancel(self):
                Stub.cancels += 1

        link._client = Stub()
        link.cancel()
        self.assertEqual(Stub.cancels, 0)
        link._client = None

    def test_a_short_turn_still_leaves_the_answer_and_no_activity(self):
        link = self.link()
        link.send("hello")
        self.assertTrue(wait_for(lambda: not link.active()))
        chat = link.chat()
        self.assertEqual(chat["activity"], "")
        self.assertIn("Answer hello", chat["messages"][-1]["text"])

    def test_a_permission_request_waits_for_the_bubble_and_the_choice_reaches_the_agent(self):
        link = self.link()
        link.send("please ask")
        self.assertTrue(wait_for(lambda: link.attention()["approvals"]), "the bubble shows Accept and Decline")
        request = link.attention()["approvals"][0]
        self.assertIn("Write", request["reason"])
        link.decide(request["requestId"], True)
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.chat()["messages"][-1]["text"], "chose yes")

    def test_an_answer_is_logged_with_who_gave_it_and_the_face_is_woken(self):
        from harness import approvals
        link = self.link()
        woken = []
        link.on_change = lambda: woken.append(1)
        link.send("please ask")
        self.assertTrue(wait_for(lambda: link.attention()["approvals"]))
        self.assertGreaterEqual(len(woken), 2, "the message and the question each wake the face")
        self.assertTrue(link.decide(link.attention()["approvals"][0]["requestId"], False, "cli", "claude"))
        self.assertTrue(wait_for(lambda: not link.active()))
        last = approvals.recent(1)
        self.assertIn('"decision": "declined"', last)
        self.assertIn('"source": "cli"', last)
        self.assertIn('"by": "claude"', last)

    def test_declining_says_no_to_the_agent(self):
        link = self.link()
        link.send("please ask")
        self.assertTrue(wait_for(lambda: link.attention()["approvals"]))
        link.decide(link.attention()["approvals"][0]["requestId"], False)
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.chat()["messages"][-1]["text"], "chose no")

    def test_a_message_while_a_choice_waits_declines_it_and_stops_the_turn(self):
        link = self.link()
        link.send("please ask")
        self.assertTrue(wait_for(lambda: link.attention()["approvals"]))
        link.interrupt()
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.attention()["approvals"], [])
        self.assertTrue(link.send("next")[0], "the turn is over, so the next message goes out")

    def test_the_login_shell_path_is_used_and_a_failure_is_only_reported(self):
        done = mock.Mock(stdout="motd\n__PATH__/opt/homebrew/bin:/usr/bin", returncode=0)
        with mock.patch.object(acplink.subprocess, "run", return_value=done):
            acplink.login_path.cache_clear()
            self.assertEqual(acplink.login_path(), ("/opt/homebrew/bin:/usr/bin", ""))
        with mock.patch.object(acplink.subprocess, "run", side_effect=acplink.subprocess.TimeoutExpired("zsh", 5)):
            acplink.login_path.cache_clear()
            self.assertEqual(acplink.login_path(), ("", "timed out"))
        acplink.login_path.cache_clear()

    def test_a_running_turn_can_be_cancelled(self):
        link = self.link()
        link.send("slow down")
        self.assertTrue(wait_for(lambda: link.chat()["activity"].startswith("step")))
        link.cancel()
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.note(), "Cancelled.")

    def test_a_failed_turn_says_so_under_the_conversation(self):
        link = self.link()
        link.send("this will fail")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.chat()["failed"], "The model refused to answer.")

    def test_the_context_meter_and_the_compaction_notice_reach_the_note(self):
        from harness.acp_client import Update
        link = self.link()
        # At 80%: show percentage.
        link._updated(Update("usage", extra={"used": 80, "size": 100}))
        self.assertEqual(link.note(), "Context 80% full.")
        # Below 50%: silence (no chatter for nearly empty windows).
        link._updated(Update("usage", extra={"used": 20, "size": 100}))
        self.assertEqual(link.note(), "")
        # Very small fraction (<1%) is also silent.
        link._updated(Update("usage", extra={"used": 100, "size": 131072}))
        self.assertEqual(link.note(), "")
        # Compacted notice is always shown.
        link._updated(Update("usage", extra={"used": 20, "size": 100, "compacted": True}))
        self.assertEqual(link.note(), "Compacted older turns.")
        # Size 0 shows nothing.
        link._updated(Update("usage", extra={"used": 1, "size": 0}))
        self.assertEqual(link.note(), "")

    def test_an_agent_that_cannot_start_does_not_hang_the_face(self):
        link = AcpLink(f"{sys.executable} -c 'raise SystemExit(1)'")
        self.addCleanup(link.close)
        ok, _error = link.send("hello")
        self.assertTrue(ok, "the message was accepted; the failure comes as a note")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertIn("did not start", link.chat()["failed"])
        self.assertTrue(link.stopped)

    def test_a_second_send_waits_and_a_silent_turn_says_nothing_came_back(self):
        """Should refuse a send while one is running, and say so when a turn ends with no words."""
        import asyncio
        from harness.acp_client import Turn, Update
        link = self.link()
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertFalse(link.due())
        self.assertFalse(link.is_polling)
        link.poll()
        link.request_fetch()
        link._note = "old"
        link.resume()
        self.assertEqual(link.note(), "")
        link._sending = True
        ok, why = link.send("again")
        self.assertFalse(ok)
        self.assertIn("still answering", why)
        link._sending = False
        link._loading = True
        link._updated(Update("text", "eerste"))
        link._updated(Update("text", " tweede"))
        self.assertEqual(link._history[-1]["text"], "eerste tweede")
        link._loading = False
        link._updated(Update("tool", "   "))
        link._updated(Update("tool", "read file"))
        self.assertIn("read file", link.chat()["activity"])
        link._updated(Update("usage", extra={"used": 1, "size": 0}))
        self.assertEqual(link.note(), "")
        link._updated(Update("usage", extra={"used": 80, "size": 100}))
        link._updated(Update("usage", extra={"jobs_only": True, "jobs": 1, "followup": True}))
        self.assertEqual(link.note(), "Context 80% full. · 1 background job")
        self.assertTrue(link._followup)
        woken = []
        link.on_change = lambda: woken.append(1)
        link._updated(Update("text", "job done"))
        self.assertEqual(woken, [1], "a follow-up answer wakes the face")
        self.assertIn("job done", link.messages[-1]["text"])
        link.on_change = None
        link._updated(Update("user", "Background job j1 finished."))
        self.assertEqual(link.messages[-1]["role"], "user")
        self.assertIn("j1", link.messages[-1]["text"])
        link._updated(Update("usage", extra={"jobs_only": True, "jobs": 0, "followup": False}))
        self.assertEqual(link.note(), "Context 80% full.")
        self.assertFalse(link._followup)
        link.decide("no-such-request", False)
        link.cancel()

        class Stub:
            async def prompt(self, text):
                return Turn(stop_reason="end_turn")

        async def fake_ensure():
            try:
                return Stub()
            finally:
                with link._lock:
                    link._booting = False

        link._ensure = fake_ensure
        link.send("silent")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertIn("no answer", link.note())
        with mock.patch.object(acplink.os, "makedirs", side_effect=OSError("ro")):
            link._save_session("abc")
        with mock.patch.object(acplink, "PERMISSION_WAIT_S", 0.05):
            answered = asyncio.run_coroutine_threadsafe(link._ask("Write"), link._loop).result(2)
        self.assertFalse(answered)
        self.assertIn("No answer", link.note())

    def test_closing_a_client_that_fails_still_stops_the_loop(self):
        """Should ignore a client that errors while closing, and a loop that is already gone."""
        link = self.link()

        class Bad:
            async def __aexit__(self, *args):
                raise RuntimeError("bye")

        link._client = Bad()
        link.close()
        self.assertTrue(link._closed)

    def test_closing_does_not_wait_for_an_agent_that_is_slow_to_stop(self):
        """Should return at once: close runs on the Qt thread, where a wait freezes every animation."""
        link = self.link()
        self.assertTrue(wait_for(lambda: not link.active()))

        class Slow:
            async def __aexit__(self, *args):
                await asyncio.sleep(1.5)

        link._client = Slow()
        start = time.monotonic()
        link.close()
        self.assertLess(time.monotonic() - start, 0.5)
        self.assertTrue(wait_for(lambda: not link._thread.is_alive(), timeout=4), "the loop stops afterwards")

    def test_closing_again_after_the_loop_has_stopped_still_finishes(self):
        """Should give up when the background loop is already gone."""
        link = self.link()
        self.assertTrue(wait_for(lambda: not link.active()))
        link.close()
        link._closed = False
        link.close()
        self.assertTrue(link._closed)


class AcpFace(unittest.TestCase):
    """An `acp:` id gives a face an ACP link, and nothing else in the face changes."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_the_face_picks_the_acp_link_for_an_acp_id_and_none_otherwise(self):
        from unittest import mock
        from botwidget.qt_ui import face
        with mock.patch.object(face, "latest_chat", return_value={"messages": [], "activity": ""}), \
                mock.patch.object(face, "automation_ready", return_value=False):
            # Other tests share this face's folder; a saved session would show up at start now.
            shutil.rmtree(os.path.expanduser(
                "~/.local/share/botwidget/harness/" + acplink._slug(FAKE)), ignore_errors=True)
            window = face.FaceWindow("acp:" + FAKE, "T", spot=(300, 400))
            self.addCleanup(window.close_face)
            window._poll_timer.stop()
            self.assertIsNotNone(window.acp)
            self.assertIs(window.link, window.acp)
            self.assertIsNone(window.grok)
            self.assertIsNone(window.hermes)
            self.assertEqual(window._latest(), {"messages": [], "activity": "", "failed": "", "approvals": []})
