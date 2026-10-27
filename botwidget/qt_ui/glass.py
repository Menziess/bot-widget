"""Frosted glass behind the bubbles: a real blur where the system can blur what is behind a window, and a painted
frost where it cannot."""

import random

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap

from botwidget.config import widget_config
from botwidget.qt_ui.native import native_id
from botwidget.system.current import CAN_BLUR, clear_backdrop, set_backdrop
from botwidget.theme import (FROST_GRAIN, GLASS_ALPHA, GLASS_ALPHA_CLEAR, GLASS_ALPHA_FLAT,
                             GLASS_ALPHA_FLAT_CLEAR, GLASS_CLEAR_DEFAULT)

FROST_TILE = 64  # one tile of grain, in points
_tiles: dict = {}


def blurs() -> bool:
    """Can the system blur what is behind the window? Only macOS has the window effect for it: GNOME on Wayland has
    no blur request for an app, and the Windows blur-behind call has been ignored since Windows 8."""
    return CAN_BLUR and QGuiApplication.platformName() == "cocoa"


def available() -> bool:
    """Is there glass to show? Everywhere: where nothing behind the window can be blurred, it is painted with grain,
    so the setting for it belongs in the settings on every platform."""
    return True


def enabled() -> bool:
    return available()


def clear_percent() -> int:
    """How see-through the glass is, as set in the settings: 0 is solid white, 100 is mostly clear."""
    value = widget_config().get("glass_clear")
    return min(100, max(0, value)) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        else GLASS_CLEAR_DEFAULT


def alpha() -> float:
    """How much of the glass is paint. Over a blur as much as the setting leaves; where the glass is painted it starts
    almost solid, so the text can be read, and the setting still takes paint away."""
    percent = clear_percent()
    top = GLASS_ALPHA if blurs() else GLASS_ALPHA_FLAT
    clear = GLASS_ALPHA_CLEAR if blurs() else GLASS_ALPHA_FLAT_CLEAR
    if percent <= GLASS_CLEAR_DEFAULT:
        return round(1 - (1 - top) * percent / GLASS_CLEAR_DEFAULT, 3)
    return round(top - (top - clear) * (percent - GLASS_CLEAR_DEFAULT) / (100 - GLASS_CLEAR_DEFAULT), 3)


def _tile(ratio: float) -> QPixmap:
    """One tile of frost grain, made once per pixel density. The seed is fixed: a redraw must not make the grain
    crawl, and a tile is what keeps this off the per-frame path."""
    tile = _tiles.get(ratio)
    if tile is None:
        side = max(1, round(FROST_TILE * ratio))
        image = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        rng = random.Random(7)
        for y in range(side):
            for x in range(side):
                level = rng.randrange(256) - 128
                grain = round(abs(level) / 128 * 255 * FROST_GRAIN)
                # Light and dark specks both: only light ones look like dust on the screen.
                image.setPixelColor(x, y, QColor(255, 255, 255, grain) if level > 0 else QColor(28, 32, 40, grain))
        tile = QPixmap.fromImage(image)
        tile.setDevicePixelRatio(ratio)
        _tiles[ratio] = tile
    return tile


def frost(pixmap: QPixmap, shape: QPixmap) -> QPixmap:
    """The glass with fine grain in it, but only where the shape is: the frost that a system without blur cannot give
    us. Called where the chrome is painted, never per frame."""
    ratio = pixmap.devicePixelRatio() or 1.0
    area = QRect(QPoint(0, 0), pixmap.deviceIndependentSize().toSize())
    grain = QPixmap(pixmap.size())
    grain.setDevicePixelRatio(ratio)
    grain.fill(Qt.transparent)
    painter = QPainter(grain)
    painter.drawTiledPixmap(area, _tile(ratio))
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawPixmap(0, 0, shape)
    painter.end()
    out = QPixmap(pixmap)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, grain)
    painter.end()
    return out


def png(pixmap) -> bytes:
    """The shape as a picture, at the pixel density of the screen: a smaller one made the blur show as a second,
    smaller bubble. Uncompressed: it is made often, and read once."""
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.toImage().save(buffer, "PNG", 100)
    return bytes(buffer.data())


def update(window, card: QRect, area: QRect, mask: bytes) -> None:
    """Blur behind the shape of the card, which sits in the window at card - area."""
    if blurs():
        set_backdrop(native_id(window), card.x() - area.x(), card.y() - area.y(),
                     card.width(), card.height(), mask)


def clear(window) -> None:
    """Remove any backdrop/blur effect behind the window."""
    if blurs():
        clear_backdrop(native_id(window))
