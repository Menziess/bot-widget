"""Entry point of the widget."""

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from botwidget import __version__, channel, startup, updates
from botwidget.config import auto_update
from botwidget.instance import ensure_single_instance
from botwidget.qt_ui.faces import Faces
from botwidget.qt_ui.fonts import install_font_fallbacks
from botwidget.system.current import hide_from_dock, prepare_gui_environment


def _login_item(args: list):
    """botwidget --login-item on|off|status: manage the login item without starting the widget."""
    action = args[0] if args else "status"
    if action in ("on", "off"):
        startup.set_enabled(action == "on")
    print("start at login:", "on" if startup.is_enabled() else "off")


def main():
    if "--version" in sys.argv[1:]:
        print(__version__)
        return
    if "--login-item" in sys.argv[1:]:
        _login_item(sys.argv[sys.argv.index("--login-item") + 1:])
        return
    if "--dev" in sys.argv[1:]:
        from botwidget.dev import run
        run()
        return
    # An update that was staged earlier takes effect now: the widget quits and starts again.
    updates.clean_staging()
    if auto_update() and updates.install_staged():
        sys.exit(0)
    prepare_gui_environment()
    app = QApplication(sys.argv)
    hide_from_dock()
    # The faces and bubbles are Tool windows; closing one must not stop the app.
    app.setQuitOnLastWindowClosed(False)
    install_font_fallbacks()
    ensure_single_instance()
    channel.remember_local()
    if "--keep-login" in sys.argv[1:]:
        startup.set_enabled(True)
    faces = Faces()
    faces.welcome(startup.apply_default())
    first = next(iter(faces.faces.values()), None)
    if first and os.environ.get("BOT_WIDGET_OPEN_CHAT"):
        QTimer.singleShot(800, first.pin)
    sys.exit(app.exec())
