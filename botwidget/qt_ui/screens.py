"""Schermen als (x, y, breedte, hoogte) in logische px, zonder menubalk of dock."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication


def _rect(screen) -> tuple:
    g = screen.availableGeometry()
    return g.x(), g.y(), g.width(), g.height()


def rects() -> list:
    return [_rect(screen) for screen in QGuiApplication.screens()]


def rect_at(x: float, y: float) -> tuple:
    """Het scherm onder (x, y), anders het hoofdscherm."""
    screen = QGuiApplication.screenAt(QPoint(int(x), int(y))) or QGuiApplication.primaryScreen()
    return _rect(screen)
