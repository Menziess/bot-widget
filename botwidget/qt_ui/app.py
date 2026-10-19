"""Startpunt van de widget."""

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from botwidget import __version__, channel, startup, updates
from botwidget.config import auto_update
from botwidget.instance import ensure_single_instance
from botwidget.qt_ui.faces import Faces
from botwidget.qt_ui.fonts import install_font_fallbacks
from botwidget.system.current import prepare_gui_environment


def _login_item(args: list):
    """botwidget --login-item on|off|status: het inlogonderdeel beheren zonder de widget te starten."""
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
    # Een update die eerder is klaargezet gaat nu in: de widget sluit af en start opnieuw.
    updates.clean_staging()
    if auto_update() and updates.install_staged():
        sys.exit(0)
    prepare_gui_environment()
    app = QApplication(sys.argv)
    # De gezichten zijn Tool-vensters; sluiten van het chatvenster mag de app niet stoppen.
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
