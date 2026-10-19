"""Wisselen tussen de stabiele widget (geïnstalleerd) en de lokale (uit een checkout).

Elke versie kan de andere starten. Het inlogonderdeel volgt degene die draait, zodat
er bij het aanmelden maar één van de twee opstart.
"""

import subprocess

from botwidget import startup
from botwidget.config import save_widget_config, widget_config
from botwidget.system.current import stable_app_command

# Een lokale widget sluit hiermee af om de stabiele te laten overnemen; de ontwikkelmodus
# stopt dan ook, in plaats van hem meteen opnieuw te starten.
HANDOVER_EXIT = 75


def running() -> str:
    return "local" if startup.from_checkout() else "stable"


def remember_local():
    """Een lokale widget onthoudt hoe hij start, zodat de stabiele hem kan starten."""
    if startup.from_checkout():
        save_widget_config(local_command=startup.launch_command())


def other_command() -> list | None:
    """Het commando van de versie waar we naartoe wisselen, of None als die er niet is."""
    if running() == "local":
        return stable_app_command()
    command = widget_config().get("local_command")
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        return command
    return None


def switch_label() -> str | None:
    if other_command() is None:
        return None
    return "Switch to stable version" if running() == "local" else "Switch to local version"


def switch() -> bool:
    """Start de andere versie; True als deze nu moet afsluiten."""
    command = other_command()
    if command is None:
        return False
    login = startup.is_enabled()
    if login:
        startup.set_enabled(False)  # de andere versie meldt zichzelf aan
    try:
        subprocess.Popen(command + (["--keep-login"] if login else []), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        if login:
            startup.set_enabled(True)
        return False
    return True
