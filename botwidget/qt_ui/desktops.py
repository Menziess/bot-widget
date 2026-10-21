"""Which desktops a window lives on; only a real window of the system has that to set."""

from PySide6.QtGui import QGuiApplication

from botwidget.config import all_desktops
from botwidget.system.current import set_desktops


def apply(window) -> None:
    if QGuiApplication.platformName() in ("cocoa", "windows", "xcb", "wayland"):
        set_desktops(int(window.winId()), all_desktops())
