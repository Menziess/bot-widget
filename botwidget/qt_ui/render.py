"""SVG and blur to QPixmap; sharp on every screen (devicePixelRatio)."""

import re

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def _ratio() -> float:
    return max((screen.devicePixelRatio() for screen in QGuiApplication.screens()), default=1.0)


# QtSvg does not know #rrggbbaa; the SVGs use that for transparent ink.
ALPHA_HEX = re.compile(r'(fill|stroke)="#([0-9a-fA-F]{6})([0-9a-fA-F]{2})"')


def _split_alpha(match) -> str:
    kind, rgb, alpha = match.groups()
    return f'{kind}="#{rgb}" {kind}-opacity="{int(alpha, 16) / 255:.3f}"'


def svg_pixmap(svg: str) -> QPixmap:
    svg = ALPHA_HEX.sub(_split_alpha, svg)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    size = renderer.defaultSize()
    ratio = _ratio()
    image = QImage(round(size.width() * ratio), round(size.height() * ratio),
                   QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter, QRectF(image.rect()))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def blurred(pixmap: QPixmap, radius: float) -> QPixmap:
    """Soften a copy by scaling it down and back up.

    A scene blur paints its empty margin black, and a pixel loop is too slow while the bubble grows.
    """
    ratio = pixmap.devicePixelRatio() or 1.0
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    shrink = max(2, round(radius * ratio / 3))
    small_w, small_h = max(1, image.width() // shrink), max(1, image.height() // shrink)
    small = image.scaled(small_w, small_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = small.scaled(image.width(), image.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    result = QPixmap.fromImage(out)
    result.setDevicePixelRatio(ratio)
    return result


def stacked(*pixmaps: QPixmap) -> QPixmap:
    """Pixmaps of equal size on top of each other, the first at the bottom."""
    base = QPixmap(pixmaps[0])
    painter = QPainter(base)
    for pixmap in pixmaps[1:]:
        painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return base


def cut_out(pixmap: QPixmap, shape: QPixmap) -> QPixmap:
    """A copy of the pixmap without the part under the shape: a shadow must not show through glass."""
    result = QPixmap(pixmap)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    painter.drawPixmap(0, 0, shape)
    painter.end()
    return result
