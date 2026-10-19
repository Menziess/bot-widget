"""Terugvallers voor de lettertypen van het ontwerp, zodat Qt niet hoeft te zoeken."""

from PySide6.QtGui import QFont, QFontDatabase

from botwidget.theme import SAND_MONO, SAND_SANS


def install_font_fallbacks():
    """Een ontbrekend ontwerplettertype wordt het systeemlettertype."""
    installed = set(QFontDatabase.families())
    if SAND_SANS not in installed:
        QFont.insertSubstitution(SAND_SANS, QFontDatabase.systemFont(QFontDatabase.GeneralFont).family())
    if SAND_MONO not in installed:
        QFont.insertSubstitution(SAND_MONO, QFontDatabase.systemFont(QFontDatabase.FixedFont).family())
