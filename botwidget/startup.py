"""Starting at login; the OS layer knows how, here is what gets started."""

import os
import sys

from botwidget.config import save_widget_config, widget_config
from botwidget.system.current import launch_at_login, set_launch_at_login

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def from_checkout() -> bool:
    """Is this running from a git checkout (development) rather than an installation?"""
    return os.path.isdir(os.path.join(PACKAGE_ROOT, ".git"))


def launch_command() -> list:
    """The packaged app starts itself; otherwise Python starts the package."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    command = [sys.executable, "-m", "botwidget"]
    # From a checkout the dev mode starts: it restarts as soon as the code changes.
    return command + ["--dev"] if from_checkout() else command


def is_enabled() -> bool:
    return launch_at_login()


def set_enabled(on: bool) -> None:
    set_launch_at_login(launch_command(), on)


def apply_default() -> bool:
    """Turn on starting at login the first time; True if this was the first time.

    After that the user's choice stays, even if they turn it off.
    """
    if widget_config().get("login_default_applied") is True:
        return False
    save_widget_config(login_default_applied=True)
    if not is_enabled():
        set_enabled(True)
    return True
