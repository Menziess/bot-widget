"""Screens as (x, y, width, height) in logical px, without menu bar or dock."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication


def _rect(screen) -> tuple:
    g = screen.availableGeometry()
    return g.x(), g.y(), g.width(), g.height()


def rects() -> list:
    return [_rect(screen) for screen in QGuiApplication.screens()]


def rect_at(x: float, y: float) -> tuple:
    """The screen under (x, y), otherwise the primary screen."""
    screen = QGuiApplication.screenAt(QPoint(int(x), int(y))) or QGuiApplication.primaryScreen()
    return _rect(screen)
