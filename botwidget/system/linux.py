"""Linux: X11 via XWayland, /proc, canberra of pipewire voor geluid.

Het gezicht blijft onder gewone vensters, zoals een bureaubladwidget.
"""

import os
import sys

from botwidget.system import posix

SOUND_FILE = "/usr/share/sounds/freedesktop/stereo/complete.oga"


def prepare_gui_environment() -> None:
    # X11 (XWayland) en niet Wayland: op Wayland mag een gewoon venster zijn
    # positie en stapelorde niet zelf bepalen, dus dan zakt de widget achter
    # andere vensters en kan hij niet slepen. Via XWayland werken move en
    # slepen wel.
    if os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


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
    """Waar apps hun eigen map neerzetten; OpenBot en deze widget delen hem."""
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def send_behind_windows(win_id: int) -> None:
    # De vensterbeheerder honoreert Qt's StaysOnBottomHint.
    pass


def _autostart_file() -> str:
    return os.path.join(data_home(), "autostart", "botwidget.desktop")


def launch_at_login() -> bool:
    return os.path.exists(_autostart_file())


def set_launch_at_login(command: list, on: bool) -> None:
    """Een .desktop-bestand in de autostart-map van de gebruiker."""
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

# Wacht tot de widget weg is, draai het install.sh uit het archief en start opnieuw.
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
    """Alleen de gebundelde app die via install.sh is neergezet."""
    return getattr(sys, "frozen", False) and stable_app_command() is not None


def install_update(archive: str) -> bool:
    posix.spawn_script(_UPDATE_SCRIPT, archive, str(os.getpid()))
    return True


def stable_app_command() -> list | None:
    path = os.path.expanduser("~/.local/share/botwidget/app/Bot Widget")
    return [path] if os.path.exists(path) else None
