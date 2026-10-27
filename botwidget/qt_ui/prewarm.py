"""Do the first-time work of the bubble before the first one opens: the first text measured, the first picture drawn
and the first glass made each cost far more than the ones after them, which showed as a stall on the first hover."""

import string

from botwidget.bubble import bubble_body_svg, bubble_shadow_svg
from botwidget.qt_ui import glass
from botwidget.qt_ui.measure import measure
from botwidget.qt_ui.render import blurred, cut_out, svg_pixmap
from botwidget.theme import BUBBLE_CODE_FONT, BUBBLE_FONT, SHADOW_BLUR

GLYPHS = string.printable.strip() + "àáâäçèéêëìíîïñòóôöùúûüÿœ€…–—’“”"


def prewarm() -> None:
    for style, size in (("", BUBBLE_FONT), ("b", BUBBLE_FONT), ("i", BUBBLE_FONT), ("mono", BUBBLE_FONT),
                        ("code", BUBBLE_CODE_FONT)):
        measure(GLYPHS, style, size)
    shape = svg_pixmap(bubble_body_svg(240, 120, mask=True))
    cut_out(blurred(svg_pixmap(bubble_shadow_svg(240, 120)), SHADOW_BLUR * 3), shape)
    svg_pixmap(bubble_body_svg(240, 120))
    glass.png(shape)
