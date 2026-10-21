"""Linux: X11 via XWayland, /proc, canberra or pipewire for sound.

The face stays below normal windows, like a desktop widget.
"""

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


def hide_from_dock() -> None:
    pass


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
    # The window manager honours Qt's StaysOnBottomHint.
    pass


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
