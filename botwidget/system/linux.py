"""Linux: X11 via XWayland, /proc, canberra or pipewire for sound.

The face stays below normal windows, like a desktop widget.
"""

import ctypes
import glob
import os
import shutil
import subprocess
import sys
import tempfile

from botwidget.system import posix

SOUND_FILE = "/usr/share/sounds/freedesktop/stereo/complete.oga"

# Qt's xcb plugin leans on X11 libraries that the PySide6 wheel does not ship.
# Debian and Ubuntu have them as separate packages; we put them in the Qt lib
# folder ourselves, so a pip or uv install works without root.
XCB_PACKAGES = ("libxcb-cursor0", "libxkbcommon-x11-0", "libxcb-icccm4", "libxcb-image0",
                "libxcb-keysyms1", "libxcb-render-util0", "libxcb-xkb1")
XCB_LIBRARIES = ("libxcb-cursor.so.0", "libxkbcommon-x11.so.0", "libxcb-icccm.so.4",
                 "libxcb-image.so.0", "libxcb-keysyms.so.1", "libxcb-render-util.so.0",
                 "libxcb-xkb.so.1")


def _platform_plugin(name: str) -> str | None:
    """Qt's plugin file, or None when PySide6 is not there."""
    try:
        import PySide6
    except ImportError:
        return None
    root = os.path.dirname(os.path.abspath(PySide6.__file__))
    path = os.path.join(root, "Qt", "plugins", "platforms", name)
    return path if os.path.exists(path) else None


def _libs_not_found(ldd_output: str) -> list:
    """The library names that ldd reports as 'not found'."""
    return [line.split("=>")[0].strip() for line in ldd_output.splitlines() if "not found" in line]


def x11_libraries_missing(plugin: str) -> list:
    """X11 libraries this Qt plugin cannot find; empty when all of them are there."""
    done = subprocess.run(["ldd", plugin], capture_output=True, text=True)
    return _libs_not_found(done.stdout)


def _fetch_x11_libraries(qt_lib: str) -> bool:
    """Fetch the packages without root and unpack their .so files into the Qt lib folder."""
    if not (shutil.which("apt-get") and shutil.which("dpkg")):
        return False
    with tempfile.TemporaryDirectory() as work:
        got = subprocess.run(["apt-get", "download", *XCB_PACKAGES],
                             cwd=work, capture_output=True, text=True)
        if got.returncode != 0:
            return False
        out = os.path.join(work, "out")
        for deb in glob.glob(os.path.join(work, "*.deb")):
            if subprocess.run(["dpkg", "-x", deb, out], capture_output=True).returncode != 0:
                return False
        for lib in glob.glob(os.path.join(out, "usr", "lib", "*", "lib*.so*")):
            shutil.copy(lib, qt_lib)
    return True


def ensure_x11_libraries() -> None:
    """Put missing X11 libraries in the Qt lib folder; otherwise explain the apt line."""
    plugin = _platform_plugin("libqxcb.so")
    if plugin is None:
        return
    # Only the libraries we ship; Qt's own libs resolve while starting.
    missing = [lib for lib in x11_libraries_missing(plugin) if lib in XCB_LIBRARIES]
    if not missing:
        return
    qt_lib = os.path.normpath(os.path.join(os.path.dirname(plugin), os.pardir, os.pardir, "lib"))
    print("Bot Widget fetches X11 libraries it needs (one time)…", file=sys.stderr)
    if _fetch_x11_libraries(qt_lib) and not x11_libraries_missing(plugin):
        return
    print("Bot Widget is missing X11 libraries: " + ", ".join(missing), file=sys.stderr)
    print("On Debian or Ubuntu: sudo apt install " + " ".join(XCB_PACKAGES), file=sys.stderr)


HOTKEY_LABEL = ""
# Mutter honours the X11 desktop property on the XWayland window the widget uses: "Always on Visible Workspace".
CAN_PICK_DESKTOPS = True
# Not Qt.Tool: mutter lifts a utility window to the layer of its group (above other apps); skip-taskbar
# written before each map keeps the face out of the taskbar instead.
FACE_IS_TOOL = False
# Taking the keyboard without a click makes GNOME say "Bot Widget is ready" instead of focusing.
FOCUS_ON_HOVER = False


def set_desktops(win_id: int, everywhere: bool, travels: bool = False) -> None:
    """Put a face on every desktop, or back on the one you are on. A bubble travels: it opens on the desktop you are
    looking at and is never stuck to all of them."""
    if travels:
        return
    lib = _xlib()
    if lib is not None:
        lib.set_desktop(win_id, everywhere)


CAN_BLUR = False


def set_backdrop(win_id: int, x: float, y: float, w: float, h: float, mask_png: bytes) -> bool:
    """No blur behind a window here."""
    return False


def clear_backdrop(win_id: int) -> None:
    pass


def on_active_space(win_id: int) -> bool:
    return True


def is_shown_here(win_id: int) -> bool:
    return True


def move_to_active_space(win_id: int) -> None:
    pass


def activate_app() -> None:
    pass


def hide_from_dock() -> None:
    pass


def register_hotkey(callback) -> bool:
    """No global key combination here yet."""
    return False


def prepare_gui_environment() -> None:
    # X11 (XWayland) rather than Wayland: on Wayland a normal window may not decide its own position
    # and stacking order, so the widget would sink behind other windows and could not be dragged.
    # Via XWayland moving and dragging do work.
    if os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        ensure_x11_libraries()


def process_cmdline(pid: int) -> bytes:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read()
    except OSError:
        return posix.process_cmdline(pid)


def play_notification() -> None:
    posix.spawn_first((["canberra-gtk-play", "-i", "complete"],
                       ["pw-play", SOUND_FILE]))


def data_home() -> str:
    """Where apps put their own folder; OpenBot and this widget share it."""
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def send_behind_windows(win_id: int) -> None:
    """Put one face under ordinary windows.

    Qt.Tool is a utility window. Mutter keeps that layer above Finder, so
    StaysOnBottomHint never lands there. Offscreen tests must not touch the
    real display.
    """
    if not win_id or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    lib = _xlib()
    if lib is None:
        return
    lib.behind(int(win_id))


def before_show(win_id: int, layer: str = "") -> None:
    """Mark a window that is about to be mapped as one without a taskbar entry.

    Every show maps the window anew. GNOME denies it focus and, unless the window skips the taskbar at
    that moment, shows "Bot Widget is ready". send_behind_windows only adds the skip after the map, too
    late; a state set on the unmapped window is what the window manager reads. Qt leaves the property
    alone only when it already holds the layer Qt wants ("above" or "below"), so that goes in too.
    """
    if not win_id or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    lib = _xlib()
    if lib is None:
        return
    lib.skip_taskbar_unmapped(int(win_id), layer)


def pointer_window() -> int | None:
    """The top-level X window under the pointer, 0 when it is over no X window at all, None when unknown.

    XWayland keeps the last pointer position when the pointer moves onto a Wayland window, but it does move
    its sprite to the root, so the child under the pointer becomes 0. Enter/leave events can get lost on the
    way; this asks the X server directly.
    """
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    lib = _xlib()
    if lib is None:
        return None
    return lib.pointer_child()


class _Xlib:
    def __init__(self):
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                        ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_void_p, ctypes.c_int]
        x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                   ctypes.c_long, ctypes.c_void_p]
        x11.XLowerWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        ulong, sint = ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)
        x11.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ulong, ulong, sint, sint, sint, sint,
                                      ctypes.POINTER(ctypes.c_uint)]
        x11.XGetWindowProperty.restype = ctypes.c_int
        x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                           ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ulong, sint, ulong, ulong,
                                           ctypes.POINTER(ctypes.c_void_p)]
        x11.XFree.argtypes = [ctypes.c_void_p]
        self._x11 = x11
        self._display = x11.XOpenDisplay(None)
        self._root = x11.XDefaultRootWindow(self._display) if self._display else 0
        self._atoms = {}

    def skip_taskbar_unmapped(self, win_id: int, layer: str) -> None:
        if not self._display:
            return
        names = ["_NET_WM_STATE_SKIP_PAGER", "_NET_WM_STATE_SKIP_TASKBAR"]
        if layer:
            names.append("_NET_WM_STATE_" + layer.upper())
        atoms = (ctypes.c_ulong * len(names))(*[self._atom(name) for name in names])
        # format 32 is an array of long on this libX11; mode 0 replaces, which is right for a window not yet mapped.
        self._x11.XChangeProperty(self._display, win_id, self._atom("_NET_WM_STATE"), 4, 32, 0, atoms, len(names))
        self._x11.XFlush(self._display)

    def pointer_child(self) -> int | None:
        if not self._display:
            return None
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        a, b, c, d = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        mask = ctypes.c_uint()
        same_screen = self._x11.XQueryPointer(self._display, self._root, ctypes.byref(root), ctypes.byref(child),
                                              ctypes.byref(a), ctypes.byref(b), ctypes.byref(c), ctypes.byref(d),
                                              ctypes.byref(mask))
        return child.value if same_screen else 0

    def set_desktop(self, win_id: int, everywhere: bool) -> None:
        """0xFFFFFFFF is the X11 value for a window on all desktops; anything else is one desktop, by number."""
        if not self._display:
            return
        desktop = 0xFFFFFFFF if everywhere else (self._cardinal(self._root, "_NET_CURRENT_DESKTOP") or 0)
        event = _ClientMessage()
        event.type = 33
        event.display = self._display
        event.window = win_id
        event.message_type = self._atom("_NET_WM_DESKTOP")
        event.format = 32
        event.data[0] = desktop
        mask = (1 << 20) | (1 << 19)  # StructureNotify and SubstructureNotify, as the window manager wants
        self._x11.XSendEvent(self._display, self._root, False, mask, ctypes.byref(event))
        self._x11.XFlush(self._display)

    def _cardinal(self, win_id: int, name: str) -> int | None:
        """One number out of a window property, such as the desktop that is showing now."""
        if not self._display:
            return None
        kind, size = ctypes.c_ulong(), ctypes.c_int()
        count, rest = ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.c_void_p()
        if self._x11.XGetWindowProperty(self._display, win_id, self._atom(name), 0, 1, False, 0,
                                        ctypes.byref(kind), ctypes.byref(size), ctypes.byref(count),
                                        ctypes.byref(rest), ctypes.byref(data)) != 0 or not data.value:
            return None
        value = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0]
        self._x11.XFree(data)
        return int(value)

    def _atom(self, name: str) -> int:
        cached = self._atoms.get(name)
        if cached is None:
            cached = self._x11.XInternAtom(self._display, name.encode(), False)
            self._atoms[name] = cached
        return cached

    def behind(self, win_id: int) -> None:
        if not self._display:
            return
        normal = ctypes.c_ulong(self._atom("_NET_WM_WINDOW_TYPE_NORMAL"))
        # format 32 is an array of long on this libX11.
        self._x11.XChangeProperty(self._display, win_id, self._atom("_NET_WM_WINDOW_TYPE"),
                                  4, 32, 0, ctypes.byref(normal), 1)
        self._state(win_id, 0, "_NET_WM_STATE_ABOVE")
        self._state(win_id, 1, "_NET_WM_STATE_BELOW", "_NET_WM_STATE_SKIP_TASKBAR")
        self._x11.XLowerWindow(self._display, win_id)
        self._x11.XFlush(self._display)

    def _state(self, win_id: int, action: int, first: str, second: str = "") -> None:
        event = _ClientMessage()
        event.type = 33
        event.display = self._display
        event.window = win_id
        event.message_type = self._atom("_NET_WM_STATE")
        event.format = 32
        event.data[0] = action
        event.data[1] = self._atom(first)
        event.data[2] = self._atom(second) if second else 0
        mask = (1 << 20) | (1 << 19)
        self._x11.XSendEvent(self._display, self._root, False, mask, ctypes.byref(event))


class _ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


_xlib_once = None


def _xlib():
    global _xlib_once
    if _xlib_once is None:
        try:
            _xlib_once = _Xlib()
        except OSError:
            _xlib_once = False
    return _xlib_once or None


def _autostart_file() -> str:
    return os.path.join(data_home(), "autostart", "botwidget.desktop")


def launch_at_login() -> bool:
    return os.path.exists(_autostart_file())


def set_launch_at_login(command: list, on: bool) -> None:
    """A .desktop file in the user's autostart folder."""
    path = _autostart_file()
    if not on:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    quoted = " ".join('"' + part.replace('"', '\\"') + '"' if " " in part else part for part in command)
    with open(path, "w") as fh:
        icon = os.path.expanduser("~/.local/share/botwidget/icon.png")
        icon_line = f"Icon={icon}\n" if os.path.exists(icon) else ""
        fh.write("[Desktop Entry]\nType=Application\nName=Bot Widget\n"
                 "Comment=Animated bot face for OpenBot and Grok Bot\n"
                 f"{icon_line}Exec={quoted}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")


UPDATE_ASSET = "BotWidget-Linux.tar.gz"

# Wait until the widget is gone, run install.sh from the archive and start again.
_UPDATE_SCRIPT = """#!/bin/sh
archive="$1"; pid="$2"
work="$(mktemp -d)"
tar xzf "$archive" -C "$work" || { rm -rf "$work"; exit 1; }
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
sh "$work/botwidget/install.sh" >/dev/null 2>&1
rm -rf "$work"
nohup "$HOME/.local/share/botwidget/app/Bot Widget" >/dev/null 2>&1 &
"""


def can_install_update() -> bool:
    """Only the packaged app that was put in place by install.sh."""
    return getattr(sys, "frozen", False) and stable_app_command() is not None


def install_update(archive: str) -> bool:
    posix.spawn_script(_UPDATE_SCRIPT, archive, str(os.getpid()))
    return True


def stable_app_command() -> list | None:
    path = os.path.expanduser("~/.local/share/botwidget/app/Bot Widget")
    return [path] if os.path.exists(path) else None
