"""Startpunt van de widget."""

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from botwidget.instance import ensure_single_instance
from botwidget.qt_ui.faces import Faces
from botwidget.qt_ui.fonts import install_font_fallbacks
from botwidget.system.current import prepare_gui_environment


def main():
    prepare_gui_environment()
    app = QApplication(sys.argv)
    # De gezichten zijn Tool-vensters; sluiten van het chatvenster mag de app niet stoppen.
    app.setQuitOnLastWindowClosed(False)
    install_font_fallbacks()
    ensure_single_instance()
    faces = Faces()
    first = next(iter(faces.faces.values()), None)
    if first and os.environ.get("BOT_WIDGET_OPEN_CHAT"):
        QTimer.singleShot(800, first.pin)
    sys.exit(app.exec())
