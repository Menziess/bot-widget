"""Frosted glass behind the bubbles, where the system can blur what is behind a window."""

from PySide6.QtCore import QBuffer, QIODevice, QRect
from PySide6.QtGui import QGuiApplication

from botwidget.config import widget_config
from botwidget.qt_ui.native import native_id
from botwidget.system.current import CAN_BLUR, clear_backdrop, set_backdrop
from botwidget.theme import GLASS_ALPHA_FLAT, GLASS_CLEAR_DEFAULT, GLASS_CLEAR_RANGE


def available() -> bool:
    return CAN_BLUR and QGuiApplication.platformName() == "cocoa"


def enabled() -> bool:
    return available()


def clear_percent() -> int:
    """How see-through the glass is, as set in the settings: 0 is solid white, 100 is mostly clear."""
    value = widget_config().get("glass_clear")
    return min(100, max(0, value)) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        else GLASS_CLEAR_DEFAULT


def alpha() -> float:
    """How much of the glass is paint: where it can blur, as much as the setting leaves; elsewhere it stays almost
    solid, so the text can be read."""
    return round(1 - GLASS_CLEAR_RANGE * clear_percent() / 100, 3) if enabled() else GLASS_ALPHA_FLAT


def png(pixmap) -> bytes:
    """The shape as a picture, at the pixel density of the screen: a smaller one made the blur show as a second,
    smaller bubble. Uncompressed: it is made often, and read once."""
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.toImage().save(buffer, "PNG", 100)
    return bytes(buffer.data())


def update(window, card: QRect, area: QRect, mask: bytes) -> None:
    """Blur behind the shape of the card, which sits in the window at card - area."""
    if enabled():
        set_backdrop(native_id(window), card.x() - area.x(), card.y() - area.y(), card.width(), card.height(), mask)


def clear(window) -> None:
    if available():
        clear_backdrop(native_id(window))
