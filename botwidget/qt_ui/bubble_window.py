"""De bubbel: een los venster boven het gezicht.

Twee vormen: de denkwolk (kind "think") en de praatwolk (kind "say" en "hint").
Een praatwolk kan een invoerveld en een rij links krijgen.
"""

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QScrollArea, QWidget

from botwidget.avatar import AVATAR_SIZE
from botwidget.bubble import (
    bubble_body_svg,
    bubble_shadow_svg,
    bubble_text_svg,
    bubble_width,
    cloud_body_svg,
    cloud_shadow_svg,
    content_height,
)
from botwidget.bubble_layout import bubble_panels
from botwidget.markdown import block_text, md_blocks
from botwidget.qt_ui import screens
from botwidget.qt_ui.measure import measure
from botwidget.qt_ui.render import blurred, stacked, svg_pixmap
from botwidget.theme import (
    BUBBLE_LINGER,
    DOTS_MS,
    PAD_BODY,
    PAD_SVG,
    SAND_ACCENT,
    SAND_INK,
    SHADOW_BLUR,
    TAIL_ROOM,
)

STYLE = f"""
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{ background: transparent; border-radius: 3px; min-height: 24px; }}
QScrollArea:hover QScrollBar::handle:vertical {{ background: rgba(28, 28, 28, 115); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; border: none; height: 0; }}
QLineEdit {{
    background: #ffffff; color: {SAND_INK}; border: 1px solid rgba(28, 28, 28, 31);
    border-radius: 8px; padding: 4px 8px;
}}
QLineEdit:focus {{ border-color: rgba(22, 128, 243, 140); }}
QLabel#links {{ color: {SAND_ACCENT}; }}
"""
ENTRY_H = 34
ENTRY_GAP = 8
LINKS_H = 26
MIN_INTERACTIVE_W = 240


class BubbleEntry(QLineEdit):
    dismissed = Signal()

    def keyPressEvent(self, event):
        """Escape sluit de bubbel zonder iets te versturen."""
        if event.key() == Qt.Key_Escape:
            self.clear()
            self.dismissed.emit()
            return
        super().keyPressEvent(event)


class BubbleWindow(QWidget):
    clicked = Signal()

    def __init__(self, face):
        super().__init__()
        self.face = face
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # Tool-vensters verbergen zich op macOS zodra de app niet actief is; de bubbel moet blijven.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setStyleSheet(STYLE)

        self.kind = ""
        self.full_text = ""
        self.blocks = []
        self.changed = 0.0
        self._input = False
        self._links = []
        self._geom = None
        self._tip = None
        self._vx = self._vy = 0.0
        self._physics_on = False
        self._dots_on = False
        self._dots_phase = 0.0
        self._dots_lines = []

        self._chrome = QLabel(self)
        self._text = QLabel()
        self._text.setAttribute(Qt.WA_TranslucentBackground)
        self._scroll = QScrollArea(self)
        self._scroll.setWidget(self._text)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._link_row = QLabel(self)
        self._link_row.setObjectName("links")
        self._link_row.setOpenExternalLinks(True)
        self._link_row.setTextFormat(Qt.RichText)
        self._entry = BubbleEntry(self)
        self._entry.setPlaceholderText("Send a message…")
        self._entry.returnPressed.connect(self._send)
        self._entry.dismissed.connect(face.unpin)

        self._physics = QTimer(self)
        self._physics.setInterval(16)
        self._physics.timeout.connect(self._tick)
        self._dots = QTimer(self)
        self._dots.setInterval(DOTS_MS)
        self._dots.timeout.connect(self._tick_dots)

    # ── Invoer ─────────────────────────────────────────────────────

    def _send(self):
        text = self._entry.text().strip()
        if text:
            self._entry.clear()
            self.face.on_user_message(text)

    def focus_entry(self):
        if self._input:
            self.activateWindow()
            self._entry.setFocus()

    def shows(self, kind: str, text: str, input: bool) -> bool:
        """Staat precies dit al in de bubbel? Dan hoeft er niets opnieuw getekend te worden."""
        return self.kind == kind and self.full_text == text and self._input == input and self.isVisible()

    def typing(self) -> bool:
        return self._input and self._entry.hasFocus()

    def enterEvent(self, event):
        """Muis boven de bubbel: hij blijft staan."""
        self.changed = time.monotonic()

    def mousePressEvent(self, event):
        """Klik op de bubbel: vastzetten en typen."""
        self.clicked.emit()

    # ── Inhoud ─────────────────────────────────────────────────────

    def _parts(self):
        """Panelen, breedte van het tekstvlak en hoogte van de inhoud."""
        blocks = self.blocks or md_blocks("…")
        panels = bubble_panels(measure, blocks) or bubble_panels(measure, md_blocks("…"))
        self._dots_lines = [line for panel in panels for line in panel["lines"]
                            if line["kind"] == "dots"]
        box_w = bubble_width(panels)
        if self._input or self._links:
            box_w = max(box_w, MIN_INTERACTIVE_W)
        return panels, box_w, content_height(panels)

    def _extras(self) -> int:
        """Hoogte onder de tekst voor de linkrij en het invoerveld."""
        return (LINKS_H if self._links else 0) + (ENTRY_H + ENTRY_GAP if self._input else 0)

    def _body_h(self, inner: int) -> int:
        """Hoogte van het witte vlak; nooit hoger dan het plafond."""
        natural = inner + 2 * PAD_BODY + self._extras()
        cap = self._ceiling() - PAD_SVG - TAIL_ROOM
        return max(2 * PAD_BODY + 12 + self._extras(), min(natural, cap))

    def _ceiling(self) -> int:
        """Ongeveer 40% van het scherm; de bubbel blijft tegen de kop."""
        fx, fy = self.face.spot()
        _x, _y, _w, h = screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)
        return max(200, int(h * 0.4))

    def _paint_chrome(self):
        if self._geom is None:
            self._geom = self._parts()
        _panels, box_w, inner = self._geom
        tip_x, tip_up = self._tip or (None, False)
        args = (box_w + 2 * PAD_BODY, self._body_h(inner), tip_x, tip_up)
        cloud = self.kind == "think"
        shadow_svg = cloud_shadow_svg(*args) if cloud else bubble_shadow_svg(*args)
        body_svg = cloud_body_svg(*args) if cloud else bubble_body_svg(*args)
        pix = stacked(blurred(svg_pixmap(shadow_svg), SHADOW_BLUR * 3), svg_pixmap(body_svg))
        self._chrome.setPixmap(pix)
        return pix

    def _layout_children(self, pix):
        """Chrome, tekstvlak, linkrij en invoerveld op hun plek."""
        _panels, box_w, inner = self._geom
        size = pix.deviceIndependentSize().toSize()
        self._chrome.setGeometry(0, 0, size.width(), size.height())
        self.resize(size)
        x, y = PAD_SVG + PAD_BODY, PAD_SVG + PAD_BODY
        view_h = max(1, self._body_h(inner) - 2 * PAD_BODY - self._extras())
        self._scroll.setGeometry(x, y, box_w, view_h)
        below = y + view_h
        if self._links:
            self._link_row.setGeometry(x, below + 4, box_w, LINKS_H - 4)
            below += LINKS_H
        if self._input:
            self._entry.setGeometry(x, below + ENTRY_GAP, box_w, ENTRY_H)
        self._link_row.setVisible(bool(self._links))
        self._entry.setVisible(self._input)

    def _set_text(self):
        panels, box_w, _inner = self._geom
        pix = svg_pixmap(bubble_text_svg(panels, box_w))
        self._text.setPixmap(pix)
        self._text.resize(pix.deviceIndependentSize().toSize())

    def show_blocks(self, blocks: list, kind: str, input: bool = False, links: list | None = None):
        """Zet blokken in de bubbel; nieuwste onderaan."""
        self._links = links or []
        self._input = input
        self._link_row.setText(" &nbsp;·&nbsp; ".join(
            f'<a href="{url}" style="color:{SAND_ACCENT}">{label} ↗</a>' for label, url in self._links))
        self.blocks = blocks
        self.full_text = block_text(blocks)
        self.changed = time.monotonic()
        restyle = kind != self.kind
        self.kind = kind
        self._geom = self._parts()
        pix = self._paint_chrome()
        self._layout_children(pix)
        self._set_text()
        self._scroll_to_bottom()
        if restyle or not self.isVisible():
            self.place(kind)

    def _scroll_to_bottom(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _tick_dots(self):
        """De denkpuntjes laten pulseren zolang de bot denkt."""
        if not self._dots_lines:
            self._dots_on = False
            self._dots.stop()
            return
        self._dots_phase = (self._dots_phase + 0.22) % 1.0
        for line in self._dots_lines:
            line["phase"] = self._dots_phase
        if self._geom:
            self._set_text()
            self._scroll_to_bottom()
        self.changed = time.monotonic()

    # ── Plaats en beweging ─────────────────────────────────────────

    def _goal(self):
        """De bubbel hangt boven het hoofd; het staartje volgt de kop."""
        fx, fy = self.face.spot()
        bw = self.width() or 80
        bh = self.height() or 48
        gx, gy, gw, gh = screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)
        tx = fx + (AVATAR_SIZE - bw) / 2
        ty = fy - bh + 6 + self.face.head_top
        up = False
        if ty < gy + 4:  # geen ruimte boven de kop: bubbel eronder, staart omhoog
            ty = fy + self.face.head_bottom - 8
            up = True
        tx = max(gx + 4, min(tx, gx + gw - bw - 4))
        ty = max(gy + 4, min(ty, gy + gh - bh - 4))
        return tx, ty, (round(fx + AVATAR_SIZE / 2 - tx), up)

    def _tick(self):
        """Veer: de bubbel loopt achter het icoon aan."""
        if not self.kind:
            self._physics_on = False
            self._physics.stop()
            return
        if (self.changed and time.monotonic() - self.changed > BUBBLE_LINGER
                and not self.face.pinned and not self.typing()
                and not self.face.pointer_near(self)):
            # Niets nieuws en de muis is niet in de buurt: de bubbel gaat weg.
            self.place("")
            return
        tx, ty, tip = self._goal()
        if tip != self._tip:
            self._tip = tip
            self._layout_children(self._paint_chrome())
            tx, ty, _tip = self._goal()
        x, y = self.x(), self.y()
        self._vx = (self._vx + (tx - x) * 0.16) * 0.7
        self._vy = (self._vy + (ty - y) * 0.16) * 0.7
        nx, ny = x + self._vx, y + self._vy
        if abs(tx - nx) < 0.6 and abs(self._vx) < 0.35 and abs(ty - ny) < 0.6 and abs(self._vy) < 0.35:
            nx, ny, self._vx, self._vy = tx, ty, 0.0, 0.0
        self.move(int(nx), int(ny))

    def place(self, kind: str):
        """Toon of verberg de bubbel. Het gezicht blijft staan."""
        self.kind = kind
        if kind == "":
            self._physics.stop()
            self._physics_on = False
            self.hide()
            return
        self.changed = time.monotonic()
        if not self._dots_on and self._dots_lines:
            self._dots_on = True
            self._dots.start()
        pix = self._paint_chrome()
        tx, ty, tip = self._goal()
        if tip != self._tip:
            self._tip = tip
            pix = self._paint_chrome()
            tx, ty, _tip = self._goal()
        self._layout_children(pix)
        if not self.isVisible():
            self._vx = self._vy = 0.0
            self.move(int(tx), int(ty))
            self.show()
        if not self._physics_on:
            self._physics_on = True
            self._physics.start()
