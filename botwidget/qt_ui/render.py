"""SVG and blur to QPixmap; sharp on every screen (devicePixelRatio)."""

import re

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene


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
    """Gaussian blur on a copy; radius in logical px."""
    ratio = pixmap.devicePixelRatio()
    flat = QPixmap(pixmap)
    flat.setDevicePixelRatio(1.0)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius * ratio)
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item = QGraphicsPixmapItem(flat)
    item.setGraphicsEffect(effect)
    scene = QGraphicsScene()
    scene.addItem(item)
    out = QImage(flat.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    scene.render(painter, QRectF(out.rect()), QRectF(out.rect()))
    painter.end()
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
