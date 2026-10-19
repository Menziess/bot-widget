"""Tekstmeting met Qt, in dezelfde lettertypen als de SVG's."""

from functools import lru_cache

from PySide6.QtGui import QFont, QFontMetricsF

from botwidget.theme import BUBBLE_CODE_FONT, SAND_MONO, SAND_SANS


@lru_cache(maxsize=None)
def _metrics(style: str, size: int) -> QFontMetricsF:
    if style == "code":
        font = QFont(SAND_MONO)
        size = BUBBLE_CODE_FONT
    elif style == "mono":
        font = QFont(SAND_MONO)
    else:
        font = QFont(SAND_SANS)
        font.setBold(style == "b")
        font.setItalic(style == "i")
    font.setPixelSize(size)
    return QFontMetricsF(font)


def measure(text: str, style: str, size: int) -> float:
    """Breedte van text in px voor de stijl uit bubble_layout.md_layout."""
    return _metrics(style, size).horizontalAdvance(text)
