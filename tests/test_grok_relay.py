"""Grok Bot status relay: parse ntfy messages and show them on Grok faces.

Offscreen Qt only. A fake subscriber stands in for ntfy. No display and no network.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config, grok_relay


def _write_config(data: dict):
    """widget.json for this test (CONFIG_PATH must already point at a temp file)."""
    os.makedirs(os.path.dirname(config.CONFIG_PATH), exist_ok=True)
    with open(config.CONFIG_PATH, "w") as fh:
        json.dump(data, fh)
    config._config_read[:] = [None, {}]


STATUS_TITLES = {
    "start": "Working",
    "done": "Done",
    "stuck": "Stuck",
    "needs_you": "Needs you",
}


class ParseRelayMessages(unittest.TestCase):
    """Should parse a status line and a roster, and reject a bad or partial one."""

    def test_should_parse_a_status_line(self):
        got = grok_relay.parse(
            '{"bot":"Ada","state":"stuck","summary":"loop","ts":1700000000}')
        self.assertEqual(got, {
            "kind": "status", "bot": "Ada", "state": "stuck",
            "summary": "loop", "ts": 1700000000,
        })

    def test_should_parse_an_iso_timestamp_and_a_blank_summary(self):
        got = grok_relay.parse(
            {"bot": " Ada ", "state": " Done ", "ts": "2026-11-06T12:00:00Z"})
        self.assertEqual(got["bot"], "Ada")
        self.assertEqual(got["state"], "done")
        self.assertEqual(got["summary"], "")
        self.assertEqual(got["ts"], "2026-11-06T12:00:00Z")

    def test_should_unwrap_an_ntfy_message_event(self):
        inner = json.dumps({"bot": "Ada", "state": "start", "summary": "on", "ts": 2})
        got = grok_relay.parse({"id": "abc", "event": "message", "topic": "crew", "message": inner})
        self.assertEqual(got["kind"], "status")
        self.assertEqual(got["state"], "start")
        self.assertEqual(got["summary"], "on")

    def test_should_ignore_an_ntfy_keepalive(self):
        self.assertIsNone(grok_relay.parse('{"event":"keepalive","id":"x"}'))

    def test_should_parse_a_roster_and_keep_optional_fields(self):
        got = grok_relay.parse({"bots": [
            {"name": "Ada", "team": "app", "color": "black", "face": "blob",
             "chat_url": "https://example/ada"},
            {"name": " Bea "},
            {"team": "dropped"},
            "nope",
            {"name": "   "},
        ]})
        self.assertEqual(got, {"kind": "roster", "bots": [
            {"name": "Ada", "team": "app", "color": "black", "face": "blob",
             "chat_url": "https://example/ada"},
            {"name": "Bea", "team": "", "color": "", "face": "", "chat_url": ""},
        ]})

    def test_should_reject_bad_or_incomplete_messages(self):
        for raw in (
            "", "not json", "[]", "null", "{}",
            '{"bot": "Ada"}', '{"state": "done"}',
            '{"bot": "Ada", "state": "sleeping"}',
            '{"bots": "no"}', {"bot": "", "state": "done"},
            {"summary": 5}, None, 3,
        ):
            self.assertIsNone(grok_relay.parse(raw), raw)

    def test_should_treat_a_non_string_summary_as_empty(self):
        got = grok_relay.parse({"bot": "Ada", "state": "start", "summary": 5, "ts": 1})
        self.assertEqual(got["summary"], "")
        self.assertEqual(got["ts"], 1)
        self.assertIsNone(grok_relay.parse({"bot": "Ada", "state": "start", "ts": True})["ts"])
        self.assertIsNone(grok_relay.parse({"bot": "Ada", "state": "start", "ts": {"n": 1}})["ts"])


class RelayChannel(unittest.TestCase):
    """Should subscribe only when widget.json names a channel, and only through the injected listener."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config._config_read[:] = [None, {}]

    def test_should_read_a_blank_channel_as_off(self):
        self.assertEqual(grok_relay.channel(), "")
        self.assertEqual(grok_relay.stream_url(""), "")
        _write_config({"grok_relay": "   "})
        self.assertEqual(grok_relay.channel(), "")
        self.assertEqual(grok_relay.stream_url(grok_relay.channel()), "")

    def test_should_build_a_json_stream_url_from_a_topic_or_a_url(self):
        self.assertEqual(grok_relay.stream_url("crew-topic"), "https://ntfy.sh/crew-topic/json")
        self.assertEqual(
            grok_relay.stream_url("https://ntfy.sh/crew-topic"),
            "https://ntfy.sh/crew-topic/json")
        self.assertEqual(
            grok_relay.stream_url("https://ntfy.sh/crew-topic/json"),
            "https://ntfy.sh/crew-topic/json")
        self.assertEqual(
            grok_relay.stream_url("https://ntfy.sh/crew-topic/"),
            "https://ntfy.sh/crew-topic/json")
        self.assertEqual(
            grok_relay.stream_url("http://127.0.0.1:8080/desk"),
            "http://127.0.0.1:8080/desk/json")

    def test_should_keep_the_channel_key_when_settings_are_saved(self):
        config.save_widget_config(grok_relay="crew-topic")
        self.assertEqual(config.widget_config().get("grok_relay"), "crew-topic")

    def test_should_not_listen_when_the_channel_is_missing_or_blank(self):
        calls = []

        def listen(url, on_text, stop):
            calls.append(url)

        grok_relay.Relay(on_message=lambda _message: None, listen=listen).start()
        _write_config({"grok_relay": "  "})
        relay = grok_relay.Relay(on_message=lambda _message: None, listen=listen)
        relay.start()
        self.assertEqual(calls, [])
        self.assertIsNone(relay._thread)

    def test_should_listen_once_and_hand_parsed_messages_over(self):
        _write_config({"grok_relay": " crew-topic "})
        got = []

        def listen(url, on_text, stop):
            got.append(url)
            on_text("nope")
            on_text('{"bot":"Ada","state":"done","summary":"ok","ts":1}')

        relay = grok_relay.Relay(on_message=got.append, listen=listen)
        relay.start()
        relay.start()
        relay._thread.join(2)
        self.assertFalse(relay._thread.is_alive())
        self.assertEqual(got[0], "https://ntfy.sh/crew-topic/json")
        self.assertEqual(got[1], {
            "kind": "status", "bot": "Ada", "state": "done", "summary": "ok", "ts": 1,
        })

    def test_should_replace_a_blank_topic_and_read_the_stream_until_it_drops(self):
        """Should mint a topic when the given one is blank, and keep reading after a dropped line."""
        from threading import Event
        with mock.patch.object(grok_relay, "new_topic", return_value="bw-fresh"):
            made = grok_relay.link_channel(topic="  ")
        self.assertEqual(made["topic"], "bw-fresh")
        seen = []

        class Response:
            def __init__(self):
                self.n = 0

            def readline(self):
                self.n += 1
                if self.n == 1:
                    return b'{"a":1}\n'
                if self.n == 2:
                    return b"   \n"
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        calls = {"n": 0}
        stop = Event()

        def urlopen(url, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                return Response()
            stop.set()
            raise OSError("down")

        with mock.patch.object(grok_relay.urllib.request, "urlopen", urlopen), \
                mock.patch.object(grok_relay, "_RETRY_S", 0.01):
            grok_relay.listen("http://example/json", seen.append, stop)
        self.assertEqual(seen, ['{"a":1}'])
        self.assertGreaterEqual(calls["n"], 2)


class RelayFaces(unittest.TestCase):
    """Should give each roster bot a Grok face and keep its live status on that face."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui.faces import Faces
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.Faces = Faces
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as fh:
            json.dump({"enabled": ["home"], "pos": {"home": [400, 400]}}, fh)
        self.state_path = path
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        bots = [{"id": "home", "name": "Home", "threadId": "t-home", "hue": None,
                 "seed": "home", "status": "ready"}]
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.STATE_PATH", path))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.list_bots", return_value=bots))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.gbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.hermesbot.is_hermes_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.check_updates", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.threading.Thread", return_value=mock.Mock()))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.latest_chat", return_value={"messages": [], "activity": ""}))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.openbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.gbot_installed", return_value=False))
        self.stack = stack

    def _boot(self):
        self.faces = self.Faces()
        self.app.processEvents()
        self._quiet()
        self.addCleanup(self._close)

    def _close(self):
        faces = getattr(self, "faces", None)
        if faces is None:
            return
        self.faces = None
        relay = getattr(faces, "relay", None)
        stop = getattr(relay, "_stop", None)
        if stop is not None:
            stop.set()
        thread = getattr(relay, "_thread", None)
        if thread is not None:
            thread.join(2)
        faces._semicircle_timer.stop()
        faces._semicircle_hide_timer.stop()
        app = type(self).app
        app.removeEventFilter(faces)
        for face in list(faces.faces.values()) + list(faces._arc_guests.values()):
            face._poll_timer.stop()
            face._anim_timer.stop()
            face.close_face()
        faces._catcher.close()
        app.processEvents()

    def _quiet(self):
        for face in list(self.faces.faces.values()) + list(self.faces._arc_guests.values()):
            face._poll_timer.stop()
            face._anim_timer.stop()

    def test_should_not_subscribe_without_a_channel(self):
        calls = []

        def listen(url, on_text, stop):
            calls.append(url)

        with mock.patch("botwidget.grok_relay.listen", listen):
            self._boot()
            time.sleep(0.05)
        self.assertEqual(calls, [])
        relay = self.faces.relay
        self.assertIsNone(relay._thread)

    def test_should_not_subscribe_when_the_channel_is_blank(self):
        _write_config({"grok_relay": "   "})
        calls = []
        with mock.patch("botwidget.grok_relay.listen", lambda *args, **kwargs: calls.append(args)):
            self._boot()
            time.sleep(0.05)
        self.assertEqual(calls, [])
        self.assertIsNone(self.faces.relay._thread)

    def test_should_subscribe_from_the_faces_when_a_topic_is_configured(self):
        _write_config({"grok_relay": "crew-topic"})
        calls = []

        def listen(url, on_text, stop):
            calls.append(url)

        with mock.patch("botwidget.grok_relay.listen", listen):
            self._boot()
            self.faces.relay._thread.join(2)
        self.assertEqual(calls, ["https://ntfy.sh/crew-topic/json"])

    def test_should_create_a_grok_face_per_roster_bot_with_its_avatar(self):
        from PySide6.QtCore import Qt
        self._boot()
        self.faces.apply_relay(json.dumps({"bots": [
            {"name": "Ada", "team": "app", "color": "black", "face": "blob",
             "chat_url": "https://example/ada"},
            {"name": "Bea", "color": "red", "face": "hex"},
            {"name": "Cara"},
        ]}))
        self._quiet()
        ada = self.faces.faces["grok:Ada"]
        bea = self.faces.faces["grok:Bea"]
        cara = self.faces.faces["grok:Cara"]
        self.assertEqual(ada.bot_name, "Ada")
        self.assertEqual(bea.bot_name, "Bea")
        self.assertEqual(cara.bot_name, "Cara")
        self.assertEqual(ada._avatar, {"shape": "blob", "color": "black"})
        self.assertEqual(bea._avatar, {"shape": "hex", "color": "red"})
        self.assertIsNone(cara._avatar)
        self.assertEqual(getattr(ada, "live_status", ""), "")
        self.assertTrue(ada.windowFlags() & Qt.Tool)
        self.assertTrue(ada.windowFlags() & Qt.FramelessWindowHint)
        with open(self.state_path) as fh:
            saved = json.load(fh)
        self.assertEqual(saved.get("enabled"), ["home"])

    def test_should_update_the_same_face_when_the_roster_changes(self):
        self._boot()
        self.faces.apply_relay({"bots": [{"name": "Ada", "face": "blob", "color": "black"}]})
        self.faces.apply_relay({"bot": "Ada", "state": "stuck", "summary": "loop", "ts": 1})
        first = self.faces.faces["grok:Ada"]
        self.faces.apply_relay({"bots": [{"name": "Ada", "face": "hex", "color": "red"}]})
        self._quiet()
        self.assertIs(self.faces.faces["grok:Ada"], first)
        self.assertEqual(first._avatar, {"shape": "hex", "color": "red"})
        self.assertEqual(first.live_status, "stuck")
        self.assertEqual([key for key in self.faces.faces if key.startswith("grok:")], ["grok:Ada"])

    def test_should_set_live_status_for_each_state_on_the_matching_face(self):
        self._boot()
        self.faces.apply_relay({"bots": [
            {"name": "Ada", "face": "blob", "color": "black"},
            {"name": "Bea", "face": "hex", "color": "red"},
        ]})
        self._quiet()
        ada = self.faces.faces["grok:Ada"]
        bea = self.faces.faces["grok:Bea"]
        for state, label in STATUS_TITLES.items():
            self.faces.apply_relay({
                "bot": "ADA", "state": state, "summary": state + " note", "ts": 9,
            })
            self.assertEqual(ada.live_status, state)
            self.assertEqual(ada.live_summary, state + " note")
            self.assertEqual(ada.windowTitle(), f"Ada · {label}")
            self.assertEqual(ada.toolTip(), state + " note")
            self.assertEqual(getattr(bea, "live_status", ""), "")
            self.assertEqual(bea.windowTitle(), "Bea")

    def test_should_ignore_a_status_for_a_bot_that_has_no_face(self):
        self._boot()
        before = set(self.faces.faces)
        self.faces.apply_relay({"bot": "Zoe", "state": "start", "summary": "x", "ts": 1})
        self.faces.apply_relay("not json")
        self.faces.apply_relay(None)
        self.assertEqual(set(self.faces.faces), before)


class LinkGrokBotsTest(unittest.TestCase):
    """Backlog #5: Link button + chief prompt (no network)."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config._config_read[:] = [None, {}]

    def test_new_topic_unique_nonempty(self) -> None:
        a, b = grok_relay.new_topic(), grok_relay.new_topic()
        self.assertTrue(a.startswith("bw-"))
        self.assertNotEqual(a, b)

    def test_chief_prompt_includes_topic_and_states(self) -> None:
        text = grok_relay.chief_prompt("bw-demo")
        self.assertIn("bw-demo", text)
        self.assertIn("ntfy.sh/bw-demo", text)
        for state in ("start", "done", "stuck", "needs_you"):
            self.assertIn(state, text)
        self.assertIn("roster", text.lower())

    def test_link_channel_writes_config(self) -> None:
        out = grok_relay.link_channel(topic="bw-fixed-topic")
        self.assertEqual(out["topic"], "bw-fixed-topic")
        self.assertIn("bw-fixed-topic", out["prompt"])
        self.assertEqual(config.widget_config().get("grok_relay"), "bw-fixed-topic")
        self.assertEqual(grok_relay.channel(), "bw-fixed-topic")

    def test_connections_page_shows_link_button_when_unlinked(self) -> None:
        from botwidget import menu_pages
        state = {
            "openbot": False, "automation_ready": False, "gbot": False, "grok": "",
            "wanted": (), "grok_relay": "",
        }
        blocks = menu_pages.connections(state)
        commands = [b.get("command") for b in blocks if isinstance(b, dict) and b.get("command")]
        self.assertIn("action/link-grok", commands)
        self.assertNotIn("action/copy-grok-prompt", commands)

    def test_connections_page_shows_copy_when_linked(self) -> None:
        from botwidget import menu_pages
        state = {
            "openbot": False, "automation_ready": False, "gbot": True, "grok": "ok",
            "wanted": (), "grok_relay": "bw-linked",
        }
        blocks = menu_pages.connections(state)
        blob = json.dumps(blocks)
        self.assertIn("bw-linked", blob)
        commands = [b.get("command") for b in blocks if isinstance(b, dict) and b.get("command")]
        self.assertIn("action/copy-grok-prompt", commands)
        self.assertNotIn("action/link-grok", commands)

    def test_menu_command_link_grok(self) -> None:
        from botwidget.qt_ui.faces import Faces
        clip = []

        class _Clip:
            def setText(self, text):
                clip.append(text)

        class _App:
            @staticmethod
            def clipboard():
                return _Clip()

        faces = mock.Mock()
        faces.relay = mock.Mock()
        with mock.patch("botwidget.qt_ui.faces.QApplication", _App):
            page = Faces.menu_command(faces, "action/link-grok", "connections")
        self.assertEqual(page, "connections")
        faces.relay.start.assert_called_once()
        self.assertEqual(len(clip), 1)
        self.assertIn("ntfy", clip[0])
        self.assertTrue(grok_relay.channel().startswith("bw-"))
