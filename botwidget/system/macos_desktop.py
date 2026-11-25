"""Other apps' windows, the pointer and the keyboard on macOS, the way a user does it.

macOS lets a program do this once the user has allowed it under System Settings > Privacy & Security >
Accessibility (events and windows) and Automation (System Events). Scripts run in osascript, as JavaScript for
Automation: no package to install. A script is a constant and its arguments travel as JSON in argv, so a text from
the model is never part of the code.
"""

import json
import subprocess

PRELUDE = """
ObjC.import("ApplicationServices");
function allowed() {
  if (!$.AXIsProcessTrusted()) {
    $.AXIsProcessTrustedWithOptions($({AXTrustedCheckOptionPrompt: true}));
    throw new Error("NOT_TRUSTED");
  }
}
function mouse(type, x, y, button) {
  $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent(null, type, $.CGPointMake(x, y), button));
}
const events = {
  left: [$.kCGEventLeftMouseDown, $.kCGEventLeftMouseUp, $.kCGMouseButtonLeft, $.kCGEventLeftMouseDragged],
  right: [$.kCGEventRightMouseDown, $.kCGEventRightMouseUp, $.kCGMouseButtonRight, $.kCGEventRightMouseDragged],
  middle: [$.kCGEventOtherMouseDown, $.kCGEventOtherMouseUp, $.kCGMouseButtonCenter, $.kCGEventOtherMouseDragged],
};
"""

CLICK = """function run(argv) {
  const a = JSON.parse(argv[0]); allowed();
  const [down, up, button] = events[a.button];
  mouse($.kCGEventMouseMoved, a.x, a.y, button); delay(0.02);
  mouse(down, a.x, a.y, button); mouse(up, a.x, a.y, button);
}"""

SCROLL = """function run(argv) {
  const a = JSON.parse(argv[0]); allowed();
  $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateScrollWheelEvent2(null, $.kCGScrollEventUnitLine, 2, a.dy, a.dx, 0));
}"""

DRAG = """function run(argv) {
  const a = JSON.parse(argv[0]); allowed();
  const [down, up, button, dragged] = events.left, steps = 20;
  mouse($.kCGEventMouseMoved, a.x, a.y, button); delay(0.05);
  mouse(down, a.x, a.y, button); delay(0.05);
  for (let i = 1; i <= steps; i++) {
    mouse(dragged, a.x + (a.to_x - a.x) * i / steps, a.y + (a.to_y - a.y) * i / steps, button); delay(0.01);
  }
  mouse(up, a.to_x, a.to_y, button);
}"""

TYPE = """function run(argv) {
  const a = JSON.parse(argv[0]); allowed();
  Application("System Events").keystroke(a.text);
}"""

KEY = """function run(argv) {
  const a = JSON.parse(argv[0]); allowed();
  const events = Application("System Events");
  if (a.code === null) events.keystroke(a.key, {using: a.mods}); else events.keyCode(a.code, {using: a.mods});
}"""

MOVE = """function run(argv) {
  const a = JSON.parse(argv[0]); allowed();
  const window = Application("System Events").processes.byName(a.app).windows[a.index];
  window.position = [a.x, a.y];
  if (a.width) window.size = [a.width, a.height];
}"""

WINDOWS = """function run(argv) {
  const se = Application("System Events"), out = [];
  for (const process of se.processes.whose({backgroundOnly: false})()) {
    let windows = [];
    try {
      windows = process.windows().map(w => ({title: w.name() || "", x: w.position()[0], y: w.position()[1],
                                             width: w.size()[0], height: w.size()[1]}));
    } catch (e) {}
    out.push({app: process.name(), frontmost: process.frontmost(), windows});
  }
  return JSON.stringify(out);
}"""

MODIFIERS = {"ctrl": "control down", "control": "control down", "cmd": "command down", "command": "command down",
             "super": "command down", "alt": "option down", "option": "option down", "shift": "shift down"}
KEY_CODES = {"enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51, "delete": 51, "esc": 53,
             "escape": 53, "left": 123, "right": 124, "down": 125, "up": 126}
NOT_ALLOWED = ("NOT_TRUSTED", "-25211", "-1719", "assistive")
NOT_AUTHORISED = ("-1743", "Not authorized")


def _unavailable(text: str):
    """control builds its backend when it loads, so this module cannot import it first."""
    from botwidget.system.control import ControlUnavailable
    return ControlUnavailable(text)


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def explain(stderr: str) -> str:
    """What the user has to do, when macOS refused; otherwise what osascript said."""
    if any(word in stderr for word in NOT_ALLOWED):
        return ("macOS has not allowed this to control the computer. A prompt was shown: allow the app that runs the "
                "widget (Terminal, or Python) under System Settings > Privacy & Security > Accessibility, then ask again.")
    if any(word in stderr for word in NOT_AUTHORISED):
        return ("macOS asks whether this may control System Events: answer Allow, or set it under System Settings > "
                "Privacy & Security > Automation, then ask again.")
    if "Can't get process" in stderr or "Invalid index" in stderr:
        return "no running app with that name and window"
    return stderr.strip().splitlines()[-1] if stderr.strip() else "osascript failed"


def parse_combo(combo: str) -> dict:
    """`cmd+shift+a` as a key and its modifiers: a key code for a named key, else the character itself."""
    *mods, key = [part.strip().lower() for part in str(combo).split("+") if part.strip()] or [""]
    unknown = [mod for mod in mods if mod not in MODIFIERS]
    if unknown or not key or (key not in KEY_CODES and len(key) != 1):
        raise _unavailable(f"cannot press {combo}")
    return {"key": key, "code": KEY_CODES.get(key), "mods": [MODIFIERS[mod] for mod in mods]}


class Macos:
    """The same actions as the Linux backend, plus the windows of other apps."""

    def __init__(self, run=None):
        self.run = run or _run

    def _script(self, script: str, arguments: dict) -> str:
        done = self.run(["osascript", "-l", "JavaScript", "-e", PRELUDE + script, json.dumps(arguments)])
        if getattr(done, "returncode", 0) != 0:
            raise _unavailable(explain(getattr(done, "stderr", "") or ""))
        return (getattr(done, "stdout", "") or "").strip()

    def click(self, x, y, button="left"):
        if button not in ("left", "right", "middle"):
            raise _unavailable(f"unknown button {button}")
        self._script(CLICK, {"x": int(x), "y": int(y), "button": button})

    def scroll(self, dx, dy):
        self._script(SCROLL, {"dx": int(dx), "dy": int(dy)})

    def type_text(self, text):
        self._script(TYPE, {"text": str(text)})

    def key(self, combo):
        self._script(KEY, parse_combo(combo))

    def drag(self, x, y, to_x, to_y):
        self._script(DRAG, {"x": int(x), "y": int(y), "to_x": int(to_x), "to_y": int(to_y)})

    def move_window(self, app, x, y, width=0, height=0, index=0):
        """The window of another app, to a place and, when asked, a size."""
        self._script(MOVE, {"app": str(app), "x": int(x), "y": int(y), "width": int(width), "height": int(height),
                            "index": int(index)})

    def windows(self) -> list:
        """Every app with a window: name, whether it is in front, and each window's title, place and size."""
        return json.loads(self._script(WINDOWS, {}) or "[]")
