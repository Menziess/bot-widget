"""Frosted glass behind the bubbles, where the system can blur what is behind a window."""

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QGuiApplication

from botwidget.config import widget_config
from botwidget.qt_ui.native import native_id
from botwidget.system.current import CAN_BLUR, clear_backdrop, set_backdrop
from botwidget.theme import GLASS_ALPHA, GLASS_ALPHA_FLAT


def available() -> bool:
    return CAN_BLUR and QGuiApplication.platformName() == "cocoa"


def wanted() -> bool:
    """The setting: on unless it was turned off."""
    return widget_config().get("glass") is not False


def enabled() -> bool:
    return available() and wanted()


def alpha() -> float:
    """How much of the glass is paint: less over a blurred background than over one that shows as it is."""
    return GLASS_ALPHA if enabled() else GLASS_ALPHA_FLAT


def png(pixmap) -> bytes:
    """The shape as a picture, at one pixel per point: the blur has no use for more. Uncompressed: it is made often,
    and read once."""
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    if ratio > 1:
        image = image.scaled(round(image.width() / ratio), round(image.height() / ratio), Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG", 100)
    return bytes(buffer.data())


def update(window, card: QRect, area: QRect, mask: bytes) -> None:
    """Blur behind the shape of the card, which sits in the window at card - area."""
    if enabled():
        set_backdrop(native_id(window), card.x() - area.x(), card.y() - area.y(), card.width(), card.height(), mask)


def clear(window) -> None:
    if available():
        clear_backdrop(native_id(window))
