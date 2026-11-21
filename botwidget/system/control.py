"""Mouse, keyboard and moving this widget. Each action is approved before it runs.

Linux uses xdotool on X11 and ydotool on Wayland when that program is on PATH.
A missing program is named in CONSENT and nothing is installed from here.
Windows and macOS are named and not implemented. A window this process owns
can still be moved and typed into without those programs.
"""

import os
import shutil
import subprocess
import sys

# The in-widget dialog is not built. install_after_agree is the only install entry.
CONSENT = {
    "built": False,
    "title": "Computer control",
    "packages": ("xdotool", "ydotool"),
    "choices": ("Agree", "Not now"),
    "install": "install_after_agree",
}

_BUTTONS = {"left": "1", "middle": "2", "right": "3"}


class ControlUnavailable(Exception):
    """This desktop cannot do the action. The text is what the bot is told."""


class Fake:
    """Records calls. Tests use this in place of the desktop."""

    def __init__(self):
        self.calls = []

    def click(self, x, y, button="left"):
        self.calls.append(("click", int(x), int(y), button or "left"))

    def scroll(self, dx, dy):
        self.calls.append(("scroll", int(dx), int(dy)))

    def type_text(self, text):
        self.calls.append(("type_text", str(text)))

    def key(self, combo):
        self.calls.append(("key", str(combo)))

    def drag(self, x, y, to_x, to_y):
        self.calls.append(("drag", int(x), int(y), int(to_x), int(to_y)))


class Stub:
    """Windows or macOS until that backend exists."""

    def __init__(self, title):
        self.title = title

    def _refuse(self, *_args, **_kwargs):
        raise ControlUnavailable(f"{self.title} computer control is not implemented")

    click = scroll = type_text = key = drag = _refuse


class Linux:
    """One external program, argv only, no shell. Absent means do nothing."""

    def __init__(self, session, which=None, run=None):
        self.session = session or "unknown"
        self.which = which or shutil.which
        self.run = run or _run

    def click(self, x, y, button="left"):
        code = _BUTTONS.get(button or "left")
        if code is None:
            raise ControlUnavailable(f"unknown button {button}")
        tool = self._tool()
        if self.session == "x11":
            self._spawn([tool, "mousemove", str(int(x)), str(int(y)), "click", code])
            return
        self._spawn([tool, "mousemove", "--absolute", "-x", str(int(x)), "-y", str(int(y))])
        self._spawn([tool, "click", code])

    def scroll(self, dx, dy):
        # shortcut: xdotool scroll buttons; ydotool uses the same click codes when present.
        button = "4" if int(dy) > 0 else "5" if int(dy) < 0 else "6" if int(dx) > 0 else "7" if int(dx) < 0 else ""
        if not button:
            return
        steps = abs(int(dy) or int(dx))
        tool = self._tool()
        argv = [tool, "click", "--repeat", str(steps), button] if self.session == "x11" else [tool, "click", button]
        self._spawn(argv)

    def type_text(self, text):
        tool = self._tool(typing=True)
        if os.path.basename(tool) == "wtype":
            self._spawn([tool, str(text)])
            return
        self._spawn([tool, "type", "--", str(text)])

    def key(self, combo):
        tool = self._tool(typing=True)
        if os.path.basename(tool) == "wtype":
            self._spawn([tool, "-k", str(combo)])
            return
        self._spawn([tool, "key", str(combo)])

    def drag(self, x, y, to_x, to_y):
        tool = self._tool()
        if self.session == "x11":
            self._spawn([tool, "mousemove", str(int(x)), str(int(y)), "mousedown", "1",
                         "mousemove", str(int(to_x)), str(int(to_y)), "mouseup", "1"])
            return
        self._spawn([tool, "mousemove", "--absolute", "-x", str(int(x)), "-y", str(int(y))])
        self._spawn([tool, "mousedown", "1"])
        self._spawn([tool, "mousemove", "--absolute", "-x", str(int(to_x)), "-y", str(int(to_y))])
        self._spawn([tool, "mouseup", "1"])

    def _tool(self, typing=False):
        if self.session == "x11":
            path = self.which("xdotool")
            if path:
                return path
            raise ControlUnavailable("X11 needs xdotool. " + _consent_line())
        if self.session == "wayland":
            path = self.which("ydotool") or (self.which("wtype") if typing else None)
            if path:
                return path
            raise ControlUnavailable("Wayland needs ydotool. " + _consent_line())
        raise ControlUnavailable("no desktop session to control. " + _consent_line())

    def _spawn(self, argv):
        done = self.run(argv)
        if getattr(done, "returncode", 0) != 0:
            raise ControlUnavailable(getattr(done, "stderr", "") or "input tool failed")


class OwnedWindow:
    """Events for a window this process opened. Never a global pointer."""

    def __init__(self, widget):
        self.widget = widget

    def click(self, x, y, button="left"):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        buttons = {"left": Qt.LeftButton, "middle": Qt.MiddleButton, "right": Qt.RightButton}
        QTest.mouseClick(self.widget, buttons.get(button or "left", Qt.LeftButton))

    def scroll(self, dx, dy):
        return None

    def type_text(self, text):
        from PySide6.QtTest import QTest
        QTest.keyClicks(self.widget, str(text))

    def key(self, combo):
        return None

    def drag(self, x, y, to_x, to_y):
        return None


def session_type(environ=None) -> str:
    """x11, wayland, or unknown. The session variable wins over the display name."""
    environ = os.environ if environ is None else environ
    kind = (environ.get("XDG_SESSION_TYPE") or "").lower()
    if kind in ("x11", "wayland"):
        return kind
    if environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def make_backend(platform=None, session=None, which=None, run=None):
    """The backend for this operating system. Stubs refuse instead of guessing."""
    platform = platform or sys.platform
    if platform == "win32":
        return Stub("Windows")
    if platform == "darwin":
        return Stub("macOS")
    return Linux(session if session is not None else session_type(), which, run)


def edge_point(edge, screen, size) -> tuple:
    """Top-left of a window sitting on one edge of the screen."""
    width, height = screen
    win_w, win_h = size
    edge = (edge or "").lower()
    if edge not in ("left", "right", "top", "bottom"):
        raise ControlUnavailable(f"unknown edge {edge}")
    x = 0 if edge == "left" else (width - win_w if edge == "right" else (width - win_w) // 2)
    y = 0 if edge == "top" else (height - win_h if edge == "bottom" else (height - win_h) // 2)
    return int(x), int(y)


class Desktop:
    """One backend plus the widget window, when one is bound."""

    def __init__(self, backend, mover=None, screen=(1920, 1080), size=(64, 64)):
        self.backend = backend
        self.mover = mover
        self.screen = screen
        self.size = size

    def dispatch(self, action, arguments) -> str:
        arguments = arguments or {}
        if action == "move_window":
            edge = str(arguments.get("edge") or "")
            if edge:
                x, y = edge_point(edge, self.screen, self.size)
            else:
                x, y = int(arguments.get("x") or 0), int(arguments.get("y") or 0)
            if self.mover is None:
                raise ControlUnavailable("no widget window is bound")
            self.mover(x, y)
            return "ok"
        if action == "click":
            self.backend.click(int(arguments.get("x") or 0), int(arguments.get("y") or 0),
                               str(arguments.get("button") or "left"))
        elif action == "scroll":
            self.backend.scroll(int(arguments.get("dx") or 0), int(arguments.get("dy") or 0))
        elif action == "type_text":
            self.backend.type_text(str(arguments.get("text") or ""))
        elif action == "key":
            self.backend.key(str(arguments.get("combo") or ""))
        elif action == "drag":
            self.backend.drag(int(arguments.get("x") or 0), int(arguments.get("y") or 0),
                              int(arguments.get("to_x") or 0), int(arguments.get("to_y") or 0))
        else:
            raise ControlUnavailable(f"unknown action {action}")
        return "ok"


def perform(desktop, action, arguments, approved) -> str:
    """Run one action after approval. A denial does not touch the backend."""
    if not approved:
        return "declined"
    return desktop.dispatch(action, arguments)


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=10)


def _consent_line() -> str:
    return f"Agree in the widget to install {', '.join(CONSENT['packages'])}. Nothing is installed yet."


desktop = Desktop(make_backend())


def bind_backend(backend) -> None:
    desktop.backend = backend


def bind_mover(mover, screen=None, size=None) -> None:
    """The widget window that computer_move moves. The last face to open wins."""
    desktop.mover = mover
    if screen is not None:
        desktop.screen = screen
    if size is not None:
        desktop.size = size


def throwaway(text="demo-key", x=40, y=30) -> dict:
    """Open a window, move it, type, close it. The tick reads the position and the text."""
    from PySide6.QtWidgets import QApplication, QLineEdit

    from botwidget.demo_check import control_outcome

    app = QApplication.instance() or QApplication([])
    box = QLineEdit()
    box.setWindowTitle("botwidget-control-demo")
    box.resize(200, 40)
    box.move(0, 0)
    box.show()
    app.processEvents()
    try:
        owned = OwnedWindow(box)
        desk = Desktop(owned, mover=lambda px, py: box.move(int(px), int(py)))
        perform(desk, "type_text", {"text": "nope"}, approved=False)
        perform(desk, "move_window", {"x": x, "y": y}, approved=True)
        perform(desk, "type_text", {"text": text}, approved=True)
        app.processEvents()
        moved = box.x() == int(x) and box.y() == int(y) and box.text() != "nope"
        return control_outcome(moved, box.text(), text)
    finally:
        box.close()
        app.processEvents()
