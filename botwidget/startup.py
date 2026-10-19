"""Mee starten bij het aanmelden; de OS-laag weet hoe, hier staat wat er gestart wordt."""

import os
import sys

from botwidget.config import save_widget_config, widget_config
from botwidget.system.current import launch_at_login, set_launch_at_login

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def from_checkout() -> bool:
    """Draait dit uit een git-checkout (ontwikkeling) in plaats van uit een installatie?"""
    return os.path.isdir(os.path.join(PACKAGE_ROOT, ".git"))


def launch_command() -> list:
    """De gebundelde app start zichzelf; anders start Python het pakket."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    command = [sys.executable, "-m", "botwidget"]
    # Uit een checkout start de ontwikkelmodus: die herstart zodra de code verandert.
    return command + ["--dev"] if from_checkout() else command


def is_enabled() -> bool:
    return launch_at_login()


def set_enabled(on: bool) -> None:
    set_launch_at_login(launch_command(), on)


def apply_default() -> bool:
    """De eerste keer meestarten bij het aanmelden aanzetten; True als dit de eerste keer was.

    Daarna blijft de keuze van de gebruiker staan, ook als die hem uitzet.
    """
    if widget_config().get("login_default_applied") is True:
        return False
    save_widget_config(login_default_applied=True)
    if not is_enabled():
        set_enabled(True)
    return True
