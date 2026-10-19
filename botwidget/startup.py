"""Mee starten bij het aanmelden; de OS-laag weet hoe, hier staat wat er gestart wordt."""

import sys

from botwidget.system.current import launch_at_login, set_launch_at_login


def launch_command() -> list:
    """De gebundelde app start zichzelf; anders start Python het pakket."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "botwidget"]


def is_enabled() -> bool:
    return launch_at_login()


def set_enabled(on: bool) -> None:
    set_launch_at_login(launch_command(), on)
