"""Computer control asks first, then calls one backend."""

import json
import os
import shutil
import tempfile
import unittest

from botwidget.system import control
from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
from harness.agent.tools import ToolError, Tools


class _Conn:
    def __init__(self, allow):
        self.allow = allow
        self.permission_requests = []

    async def session_update(self, session_id, update):
        pass

    async def request_permission(self, **kwargs):
        self.permission_requests.append(kwargs)

        class Outcome:
            outcome = "selected" if self.allow else "cancelled"
            option_id = "allow" if self.allow else "decline"

        class Response:
            outcome = Outcome()

        return Response()


class FakeBackend(unittest.TestCase):
    def test_a_fake_records_each_action(self):
        """Should record click, scroll, type, key, drag and a window move."""
        backend = control.Fake()
        moved = []
        desk = control.Desktop(backend, mover=lambda x, y: moved.append((x, y)))
        for action, arguments in (
            ("click", {"x": 1, "y": 2, "button": "left"}),
            ("scroll", {"dx": 0, "dy": -1}),
            ("type_text", {"text": "hi"}),
            ("key", {"combo": "ctrl+a"}),
            ("drag", {"x": 1, "y": 2, "to_x": 3, "to_y": 4}),
            ("move_window", {"x": 9, "y": 8}),
        ):
            self.assertEqual(control.perform(desk, action, arguments, approved=True), "ok")
        self.assertEqual(backend.calls, [
            ("click", 1, 2, "left"),
            ("scroll", 0, -1),
            ("type_text", "hi"),
            ("key", "ctrl+a"),
            ("drag", 1, 2, 3, 4),
        ])
        self.assertEqual(moved, [(9, 8)])

    def test_an_edge_move_uses_the_screen(self):
        """Should place the window on the named screen edge."""
        moved = []
        desk = control.Desktop(control.Fake(), mover=lambda x, y: moved.append((x, y)),
                               screen=(100, 80), size=(10, 10))
        control.perform(desk, "move_window", {"edge": "right"}, approved=True)
        self.assertEqual(moved, [(90, 35)])


class Approval(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.backend = control.Fake()
        self.previous = control.desktop.backend
        control.bind_backend(self.backend)
        self.addCleanup(control.bind_backend, self.previous)
        self.tools = Tools()
        self.agent = LeanAgent("Test", object(), folder=self.folder, tools=self.tools)
        self.store = SessionStore(self.folder)
        self.addCleanup(self.store.close)

    def test_every_computer_tool_asks(self):
        """Should mark pointer, keyboard and window moves as writes."""
        names = (
            "computer_click", "computer_scroll", "computer_type", "computer_key",
            "computer_drag", "computer_window",
        )
        for name in names:
            tool = self.tools.find(name)
            self.assertIsNotNone(tool, name)
            self.assertTrue(tool.writes, name)

    def test_a_denial_does_not_call_the_backend(self):
        """Should leave the backend untouched when perform is not approved."""
        desk = control.Desktop(self.backend, mover=lambda x, y: self.backend.calls.append(("move", x, y)))
        for action in ("click", "scroll", "type_text", "key", "drag", "move_window"):
            self.assertEqual(control.perform(desk, action, {"x": 1, "y": 2, "text": "a", "combo": "a",
                                                            "to_x": 3, "to_y": 4, "dx": 1, "dy": 1},
                                             approved=False), "declined")
        self.assertEqual(self.backend.calls, [])

    async def _call(self, name, arguments, allow):
        self.agent.conn = _Conn(allow)
        call = {"id": "c1", "function": {"name": name, "arguments": json.dumps(arguments)}}
        return await self.agent._use_tool("s", self.store, call)

    async def test_the_bubble_decline_does_not_call_the_backend(self):
        """Should decline in the existing approval bubble and skip the backend."""
        result = await self._call("computer_click", {"x": 3, "y": 4, "button": "left"}, allow=False)
        self.assertIn("declined", result)
        self.assertEqual(self.backend.calls, [])
        options = self.agent.conn.permission_requests[0]["options"]
        self.assertEqual([option.option_id for option in options], ["allow", "decline"])

    async def test_the_bubble_accept_calls_the_backend(self):
        """Should call the backend after Accept."""
        result = await self._call("computer_click", {"x": 3, "y": 4, "button": "right"}, allow=True)
        self.assertIn("ok", result)
        self.assertEqual(self.backend.calls, [("click", 3, 4, "right")])

    async def test_an_accepted_move_puts_the_window_of_that_app_there(self):
        """Should move the window of another app only after Accept."""
        result = await self._call("computer_window", {"app": "Chrome", "state": "move", "x": 15, "y": 25, "width": 800, "height": 600},
                                  allow=True)
        self.assertIn("ok", result)
        self.assertEqual(self.backend.calls, [("move_window", "Chrome", 15, 25, 800, 600)])
        self.backend.calls.clear()
        await self._call("computer_window", {"app": "Chrome", "state": "move", "x": 1, "y": 1}, allow=False)
        self.assertEqual(self.backend.calls, [])

    async def test_an_accepted_window_state_reaches_the_backend_and_a_decline_does_not(self):
        result = await self._call("computer_window", {"app": "Chrome", "state": "minimize"}, allow=True)
        self.assertIn("ok", result)
        self.assertEqual(self.backend.calls, [("window_state", "Chrome", "minimize")])
        self.backend.calls.clear()
        await self._call("computer_window", {"app": "Chrome", "state": "maximize"}, allow=False)
        self.assertEqual(self.backend.calls, [])


class Platforms(unittest.TestCase):
    def test_windows_is_not_implemented(self):
        """Should refuse Windows with a clear not-implemented result."""
        backend = control.make_backend("win32")
        for name in ("click", "scroll", "type_text", "key", "drag"):
            with self.assertRaises(control.ControlUnavailable) as caught:
                getattr(backend, name)(0, 0) if name == "scroll" else (
                    backend.click(0, 0, "left") if name == "click"
                    else backend.type_text("a") if name == "type_text"
                    else backend.key("a") if name == "key"
                    else backend.drag(0, 0, 1, 1))
            self.assertIn("not implemented", str(caught.exception).lower())
            self.assertIn("Windows", str(caught.exception))

    def test_a_backend_without_window_moves_says_so(self):
        desk = control.Desktop(control.make_backend("win32"))
        with self.assertRaises(control.ControlUnavailable) as caught:
            control.perform(desk, "move_app_window", {"app": "x", "x": 1, "y": 1}, approved=True)
        self.assertIn("not available", str(caught.exception))

    def test_a_backend_without_window_states_says_so(self):
        desk = control.Desktop(control.make_backend("win32"))
        with self.assertRaises(control.ControlUnavailable) as caught:
            control.perform(desk, "window_state", {"app": "x", "state": "minimize"}, approved=True)
        self.assertIn("not available", str(caught.exception))

    def test_this_session_is_wayland_or_x11(self):
        """Should read XDG_SESSION_TYPE, then Wayland, then X11."""
        self.assertEqual(control.session_type({"XDG_SESSION_TYPE": "wayland"}), "wayland")
        self.assertEqual(control.session_type({"WAYLAND_DISPLAY": "wayland-0"}), "wayland")
        self.assertEqual(control.session_type({"DISPLAY": ":0"}), "x11")

    def test_a_missing_linux_tool_does_not_run(self):
        """Should name the package and spawn nothing when the tool is absent."""
        spawned = []
        backend = control.Linux("wayland", which=lambda _name: None, run=lambda argv: spawned.append(argv))
        with self.assertRaises(control.ControlUnavailable) as caught:
            backend.click(1, 2, "left")
        self.assertIn("ydotool", str(caught.exception))
        self.assertEqual(spawned, [])
        self.assertIn("ydotool", control.CONSENT["packages"])
        self.assertFalse(control.CONSENT["built"])

    def test_x11_calls_xdotool_without_a_shell(self):
        """Should pass xdotool an argument list."""
        spawned = []

        class Done:
            returncode = 0
            stderr = ""

        backend = control.Linux("x11", which=lambda name: "/usr/bin/xdotool" if name == "xdotool" else None,
                                run=lambda argv: spawned.append(argv) or Done())
        backend.click(4, 5, "left")
        backend.type_text("ab")
        self.assertEqual(spawned[0][:3], ["/usr/bin/xdotool", "mousemove", "4"])
        self.assertEqual(spawned[1][:2], ["/usr/bin/xdotool", "type"])
        self.assertNotIn("shell", spawned[0])

    def test_a_tool_turns_an_unavailable_backend_into_text(self):
        """Should return the not-implemented reason as a tool error."""
        control.bind_backend(control.make_backend("win32"))
        self.addCleanup(control.bind_backend, self.backend if hasattr(self, "backend") else control.make_backend())
        tool = Tools().find("computer_type")
        with self.assertRaises(ToolError) as caught:
            tool.run({"text": "hi"})
        self.assertIn("not implemented", str(caught.exception).lower())


class DemoControl(unittest.TestCase):
    def test_the_tick_needs_the_position_and_the_text(self):
        """Should tick only when the window sits where asked and holds the text."""
        from botwidget.demo_check import Board, control_outcome
        board = Board()
        board.consider("computer", control_outcome(True, "demo-key", "demo-key"))
        self.assertTrue(board.ticked("computer"))
        board.consider("computer", control_outcome(True, "other", "demo-key"))
        self.assertFalse(board.ticked("computer"))
        board.consider("computer", control_outcome(False, "demo-key", "demo-key"))
        self.assertFalse(board.ticked("computer"))

    def test_the_throwaway_window_lands_the_text(self):
        """Should move a window this test owns and type into it."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        evidence = control.throwaway(text="demo-key", x=40, y=30)
        self.assertTrue(evidence["ok"], evidence)
        self.assertEqual(evidence["detail"], "landed")
