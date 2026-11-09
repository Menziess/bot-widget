"""Switching between the stable widget (installed) and the local one (from a checkout).

Each version can start the other. The login item follows whichever one is running,
so only one of the two starts at login.
"""

import os
import subprocess

from botwidget import startup
from botwidget.config import save_widget_config, widget_config
from botwidget.system.current import stable_app_command

# A local widget exits with this to let the stable one take over; the dev mode then stops too,
# instead of restarting it right away.
HANDOVER_EXIT = 75
BUNDLE_ENV = ("QT_PLUGIN_PATH", "SSL_CERT_FILE")


def running() -> str:
    return "local" if startup.from_checkout() else "stable"


def remember_local():
    """A local widget remembers how it starts, so the stable one can start it."""
    if startup.from_checkout():
        save_widget_config(local_command=startup.launch_command())


def other_command() -> list | None:
    """The command of the version we switch to, or None if there is none."""
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
    """Start the other version; True if this one should quit now."""
    command = other_command()
    if command is None:
        return False
    login = startup.is_enabled()
    if login:
        startup.set_enabled(False)  # the other version registers itself
    try:
        # The packaged app points Qt and SSL at its own bundle; a local widget with another Qt cannot start on that.
        env = {k: v for k, v in os.environ.items() if k not in BUNDLE_ENV and not k.startswith("_PYI")}
        subprocess.Popen(command + (["--keep-login"] if login else []), start_new_session=True, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        if login:
            startup.set_enabled(True)
        return False
    return True
