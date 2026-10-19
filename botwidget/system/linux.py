"""Linux: X11 via XWayland, /proc, canberra of pipewire voor geluid.

Het gezicht blijft onder gewone vensters, zoals een bureaubladwidget.
"""

import os

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
