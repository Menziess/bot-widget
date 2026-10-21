"""The bubble: a separate window above the face.

Two shapes: the thinking cloud (kind "think") and the speech bubble (kind "say"
and "hint"). A speech bubble can get an input field and a row of links.
"""

import time

from PySide6.QtCore import QEasingCurve, QSize, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QScrollArea, QTextBrowser, QWidget

from botwidget.avatar import AVATAR_SIZE
from botwidget.bubble import (
    bubble_body_svg,
    bubble_deco_svg,
    bubble_shadow_svg,
    bubble_width,
    cloud_body_svg,
    cloud_shadow_svg,
    content_height,
    panel_pad,
    panel_rects,
    reading_seconds,
)
from botwidget.bubble_layout import bubble_panels
from botwidget.markdown import block_text, md_blocks, plain_text
from botwidget.qt_ui import desktops, screens
from botwidget.qt_ui.measure import measure
from botwidget.qt_ui.render import blurred, stacked, svg_pixmap
from botwidget.qt_ui.text_doc import fill_document, selected_text
from botwidget.theme import (
    BUBBLE_MAX_SCREEN_SHARE,
    BUBBLE_MAX_W,
    BUBBLE_WAIT_MAX,
    BUBBLE_WIDER,
    DOTS_CYCLE_S,
    DOTS_GAP,
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
QTextBrowser, QTextBrowser > QWidget {{ background: transparent; border: none; padding: 0; }}
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
QPushButton#copy {{
    background: #ffffff; border: 1px solid rgba(28, 28, 28, 31); border-radius: 12px; padding: 0;
}}
QPushButton#copy:hover {{ background: #f2f2f2; }}
"""
ENTRY_H = 34
ENTRY_GAP = 8
LINKS_H = 26
MIN_INTERACTIVE_W = 240
SCROLLBAR_W = 6
COPY_SIZE, COPY_ICON_SIZE = 24, 14
COPIED_MS = 1200
GROW_MS = 240
OLDER_PAUSE_S = 0.3
# Where a bubble starts when it grows out of nothing: the text width and the white height.
SEED_W, SEED_H = 36, 22
_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16">{}'
         '</svg>')
_STROKE = 'fill="none" stroke="#1c1c1c" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
CHECK_ICON = _ICON.format(f'<path d="M3 8.6l3.2 3.2L13 4.6" {_STROKE}/>')


class BubbleEntry(QLineEdit):
    dismissed = Signal()

    def keyPressEvent(self, event):
        """Escape closes the bubble without sending anything."""
        if event.key() == Qt.Key_Escape:
            self.clear()
            self.dismissed.emit()
            return
        super().keyPressEvent(event)


class Growth:
    """A bubble changing size: it starts at this width and height and grows to the real ones."""

    def __init__(self, width: int, height: int, added: int = 0, opening: bool = False):
        self.width, self.height, self.added, self.opening = width, height, added, opening
        self.progress = 0.0


class OlderScroll(QScrollArea):
    """Scrolling up when already at the top asks for the message before."""

    older = Signal()

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        if event.angleDelta().y() > 0 and bar.value() <= bar.minimum():
            self.older.emit()
            event.accept()
            return
        super().wheelEvent(event)


class BubbleText(QTextBrowser):
    """The words in the bubble as real text: a click copies the message, a drag selects and copies."""

    clicked = Signal(float, bool)  # where in the text, and whether shift was held
    selected = Signal(str, float)  # the selected words, and where the pointer was let go
    SLOP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.message_at = lambda y: None
        self._press = None
        self._shift = False
        self._dragging = False
        self.setFrameShape(QTextBrowser.NoFrame)
        # Not openLinks: that would navigate this read-only view. The window opens the link itself.
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._open)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.setFocusPolicy(Qt.ClickFocus)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setMouseTracking(True)

    def _open(self, url: QUrl):
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def wheelEvent(self, event):
        """The text is never taller than its frame: the bubble scrolls, not the text."""
        event.ignore()

    def _cursor_for(self, pos):
        """A hand over a message (a click copies it), the text cursor while selecting."""
        if self._dragging:
            shape = Qt.IBeamCursor
        elif self.anchorAt(pos) or self.message_at(pos.y()) is not None:
            shape = Qt.PointingHandCursor
        else:
            shape = Qt.ArrowCursor
        self.viewport().setCursor(shape)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
            self._shift = bool(event.modifiers() & Qt.ShiftModifier)
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        if self._press is not None and event.buttons() & Qt.LeftButton and not self._dragging:
            if (pos - self._press).manhattanLength() > self.SLOP:
                self._dragging = True
        self._cursor_for(pos)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pos = event.position().toPoint()
        if event.button() == Qt.LeftButton and self._press is not None:
            if self._dragging:
                cursor = self.textCursor()
                text = selected_text(self.document(), cursor.selectionStart(), cursor.selectionEnd())
                if text.strip():
                    self.selected.emit(text, pos.y())
            elif not self.anchorAt(self._press):
                cursor = self.textCursor()
                cursor.clearSelection()
                self.setTextCursor(cursor)
                self.clicked.emit(pos.y(), self._shift)
        self._press, self._dragging = None, False
        self._cursor_for(pos)

class BubbleWindow(QWidget):
    older = Signal()

    def __init__(self, face):
        super().__init__()
        self.face = face
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # Tool windows hide themselves on macOS as soon as the app is not active; the bubble must
        # stay.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setStyleSheet(STYLE)

        self.kind = ""
        self.full_text = ""
        self.blocks = []
        self.changed = 0.0
        self._input = False
        self._links = []
        self._geom = None
        self._built = None
        self._chrome_key = self._chrome_pix = None
        self._was_near = False
        self._had_focus = False
        self._wait_since = 0.0
        self._growth = None
        self._older_until = 0.0
        self._tip = None
        self._vx = self._vy = 0.0
        self._physics_on = False
        self._dots_on = False
        self._dots_phase = 0.0
        self._dots_lines = []

        self._chrome = QLabel(self)
        self._text = QLabel()
        self._text.setAttribute(Qt.WA_TranslucentBackground)
        self._doc = BubbleText(self._text)
        self._doc.message_at = self._message_at
        self._doc.clicked.connect(self._on_click)
        self._doc.selected.connect(self._on_selected)
        self._scroll = OlderScroll(self)
        self._scroll.older.connect(self._wheel_older)
        self._scroll.setWidget(self._text)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._link_row = QLabel(self)
        self._link_row.setObjectName("links")
        self._link_row.setOpenExternalLinks(True)
        self._link_row.setTextFormat(Qt.RichText)
        self._copied_icon = None
        self._copied = QPushButton(self)
        self._copied.setObjectName("copy")
        self._copied.setFixedSize(COPY_SIZE, COPY_SIZE)
        self._copied.setIconSize(QSize(COPY_ICON_SIZE, COPY_ICON_SIZE))
        self._copied.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._copied.hide()
        self._hide_copied = QTimer(self)
        self._hide_copied.setSingleShot(True)
        self._hide_copied.timeout.connect(self._copied.hide)
        self._entry = BubbleEntry(self)
        self._entry.setPlaceholderText("Send a message…")
        self._entry.returnPressed.connect(self._send)
        self._entry.dismissed.connect(face.unpin)

        self._physics = QTimer(self)
        self._physics.setInterval(16)
        self._physics.timeout.connect(self._tick)
        self._slide = QVariantAnimation(self)
        self._slide.setDuration(GROW_MS)
        self._slide.setStartValue(0.0)
        self._slide.setEndValue(1.0)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.valueChanged.connect(self._growth_step)
        self._slide.finished.connect(self._growth_done)
        self._dots = QTimer(self)
        self._dots.setInterval(DOTS_MS)
        self._dots.timeout.connect(self._tick_dots)

    # ── Input ───────────────────────────────────────────────────

    def _send(self):
        text = self._entry.text().strip()
        if text:
            self._entry.clear()
            self.face.on_user_message(text)

    def _message_at(self, y: float) -> dict | None:
        """The message under this height in the text, if it is one a click can copy."""
        if self.kind != "say" or not self._geom:
            return None
        content_y = y + self._doc.y()
        for (top, height), panel in zip(panel_rects(self._geom[0]), self._geom[0]):
            if top <= content_y < top + height and panel.get("copy"):
                return panel
        return None

    def _on_click(self, y: float, shift: bool):
        """Click copies the message as plain text, shift+click as the markdown it was written in."""
        panel = self._message_at(y)
        if panel:
            self._copied_to_clipboard(panel["copy"] if shift else plain_text(panel["copy"]), y)

    def _on_selected(self, text: str, y: float):
        self._copied_to_clipboard(text, y)

    def _copied_to_clipboard(self, text: str, y: float):
        """Copy, and show a check in the corner of the message so you know it worked."""
        QApplication.clipboard().setText(text)
        self.changed = time.monotonic()
        if self._copied_icon is None:
            self._copied_icon = QIcon(svg_pixmap(CHECK_ICON))
        self._copied.setIcon(self._copied_icon)
        content_y, scrolled = y + self._doc.y(), self._scroll.verticalScrollBar().value()
        top = next((t for (t, h) in panel_rects(self._geom[0]) if t <= content_y < t + h), content_y)
        box_w = self._shown_w(self._geom[1])
        self._copied.move(self._scroll.x() + box_w - COPY_SIZE - 6, self._scroll.y() + max(top - scrolled, 0) + 6)
        self._copied.show()
        self._copied.raise_()
        self._hide_copied.start(COPIED_MS)

    def focus_entry(self):
        if self._input:
            self.activateWindow()
            self._entry.setFocus()

    def shows(self, kind: str, text: str, input: bool) -> bool:
        """Is exactly this already showing in the bubble? Then nothing needs to be redrawn."""
        return self.kind == kind and self.full_text == text and self._input == input and self.isVisible()

    def typing(self) -> bool:
        """Words typed that are not sent yet; an empty field in focus is no reason to stay."""
        return self._input and self._entry.hasFocus() and bool(self._entry.text())

    def holding(self) -> bool:
        """Typing, or words selected to copy: the bubble stays for as long as that lasts."""
        return self.typing() or (self._doc.hasFocus() and self._doc.textCursor().hasSelection())

    def enterEvent(self, event):
        """Mouse over the bubble: it stays."""
        self.changed = time.monotonic()

    # ── Content ─────────────────────────────────────────────────

    def _parts(self):
        """Panels, width of the text area and height of the content."""
        blocks = self.blocks or md_blocks("…")
        panels = self._panels(blocks) or bubble_panels(measure, md_blocks("…"))
        self._dots_lines = [line for panel in panels for line in panel["lines"]
                            if line["kind"] == "dots"]
        box_w = bubble_width(panels)
        if self._input or self._links:
            box_w = max(box_w, MIN_INTERACTIVE_W)
        return panels, box_w, content_height(panels)

    def _panels(self, blocks: list) -> list:
        """The text broken into lines; wider, step by step, while it would not fit the height."""
        panels = bubble_panels(measure, blocks)
        fx, fy = self.face.spot()
        screen_w = screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)[2]
        room = self._ceiling() - PAD_SVG - TAIL_ROOM - 2 * PAD_BODY - self._extras()
        for width in BUBBLE_WIDER:
            if content_height(panels) <= room or width > screen_w * BUBBLE_MAX_SCREEN_SHARE:
                break
            panels = bubble_panels(measure, blocks, width)
        return panels

    def _extras(self) -> int:
        """Height below the text for the link row and the input field."""
        return (LINKS_H if self._links else 0) + (ENTRY_H + ENTRY_GAP if self._input else 0)

    def _body_h(self, inner: int) -> int:
        """Height of the white area; never taller than the ceiling."""
        natural = inner + 2 * PAD_BODY + self._extras()
        cap = self._ceiling() - PAD_SVG - TAIL_ROOM
        body = max(2 * PAD_BODY + 12 + self._extras(), min(natural, cap))
        if self._growth is not None:
            body = round(self._growth.height + (body - self._growth.height) * self._growth.progress)
        return body

    def _shown_w(self, box_w: int) -> int:
        """The text area width right now: the real one, or on its way there."""
        if self._growth is None:
            return box_w
        return round(self._growth.width + (box_w - self._growth.width) * self._growth.progress)

    def _ceiling(self) -> int:
        """About 40% of the screen; the bubble stays against the head."""
        fx, fy = self.face.spot()
        _x, _y, _w, h = screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)
        return max(200, int(h * 0.4))

    def _paint_chrome(self):
        if self._geom is None:
            self._geom = self._parts()
        _panels, box_w, inner = self._geom
        tip_x, tip_up = self._tip or (None, False)
        args = (self._shown_w(box_w) + 2 * PAD_BODY, self._body_h(inner), tip_x, tip_up)
        if (self.kind, args) == self._chrome_key:
            return self._chrome_pix
        cloud = self.kind == "think"
        shadow_svg = cloud_shadow_svg(*args) if cloud else bubble_shadow_svg(*args)
        body_svg = cloud_body_svg(*args) if cloud else bubble_body_svg(*args)
        pix = stacked(blurred(svg_pixmap(shadow_svg), SHADOW_BLUR * 3), svg_pixmap(body_svg))
        self._chrome.setPixmap(pix)
        self._chrome_key, self._chrome_pix = (self.kind, args), pix
        return pix

    def _layout_children(self, pix):
        """Chrome, text area, link row and input field in their places."""
        _panels, full_w, inner = self._geom
        box_w = self._shown_w(full_w)
        size = pix.deviceIndependentSize().toSize()
        self._chrome.setGeometry(0, 0, size.width(), size.height())
        self.resize(size)
        x, y = PAD_SVG + PAD_BODY, PAD_SVG + PAD_BODY
        view_h = max(1, self._body_h(inner) - 2 * PAD_BODY - self._extras())
        self._scroll.setGeometry(x, y, box_w + SCROLLBAR_W, view_h)
        below = y + view_h
        if self._links:
            self._link_row.setGeometry(x, below + 4, box_w, LINKS_H - 4)
            below += LINKS_H
        if self._input:
            self._entry.setGeometry(x, below + ENTRY_GAP, box_w, ENTRY_H)
        self._link_row.setVisible(bool(self._links))
        # Not while the bubble is still tiny: a field alone looks odd.
        self._entry.setVisible(self._input and (self._growth is None or self._growth.progress >= 0.35))


    def _set_text(self):
        """The shapes behind the text; the words themselves are the text document."""
        panels, box_w, inner = self._geom
        pix = svg_pixmap(bubble_deco_svg(panels, box_w))
        self._text.setPixmap(pix)
        self._text.resize(pix.deviceIndependentSize().toSize())
        # One panel padding lower: the shapes keep the text of the first panel at that spot.
        top = panel_pad(panels[0])
        self._doc.setGeometry(0, top, box_w, max(1, inner - top))
        self._doc.setVisible(self.kind != "")

    def _set_doc(self):
        panels, box_w, _inner = self._geom
        fill_document(self._doc.document(), panels, box_w)

    def show_blocks(self, blocks: list, kind: str, input: bool = False, links: list | None = None,
                    older: bool = False):
        """Put blocks in the bubble; newest at the bottom. With older, a message was added above."""
        key = (kind, block_text(blocks), input, tuple(links or []), self._ceiling())
        visible = self.isVisible()
        if key == self._built and not self._dots_lines:
            # The same bubble as before, only hidden: showing it again needs no new layout or shadow.
            self.changed = time.monotonic()
            if not visible:
                self._growth = Growth(SEED_W, SEED_H, opening=True)
                self.setWindowOpacity(0.0)
                self.place(kind)
                self._slide.start()
            return
        start = (self._shown_w(self._geom[1]), self._body_h(self._geom[2])) if self._geom and visible else None
        old_inner = self._geom[2] if self._geom else 0
        self._slide.stop()
        self._growth = None
        self._built = key
        self._was_near = False
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
        if self._dots_lines and not self._dots_on:
            self._dots_on = True
            self._dots.start()
        start = start or (SEED_W, SEED_H)
        if start != (self._geom[1], self._body_h(self._geom[2])):
            added = max(0, self._geom[2] - old_inner) if older and visible else 0
            self._growth = Growth(*start, added=added, opening=not visible)
            if not visible:
                self.setWindowOpacity(0.0)
        pix = self._paint_chrome()
        self._layout_children(pix)
        self._set_text()
        self._set_doc()
        if restyle or not visible:
            self.place(kind)
        if self._growth is not None:
            self._growth.older = older and visible
            self._slide.start()
            return
        self._scroll_to_bottom()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _wheel_older(self):
        now = time.monotonic()
        if self._growth is None and now >= self._older_until and self.kind == "say":
            self._older_until = now + OLDER_PAUSE_S
            self.older.emit()

    def _growth_step(self, progress):
        """The bubble grows to its size: upward from the face, the older message sliding in from the top."""
        growth = self._growth
        if growth is None or not self.kind:
            return
        growth.progress = float(progress)
        self._layout_children(self._paint_chrome())
        tx, ty, _tip = self._goal()
        self._vx = self._vy = 0.0
        self.move(int(tx), int(ty))
        bar = self._scroll.verticalScrollBar()
        bar.setValue(min(bar.maximum(), round(growth.added * (1 - progress))) if getattr(growth, "older", False)
                     else bar.maximum())
        if growth.opening:
            self.setWindowOpacity(min(1.0, progress * 3))

    def _growth_done(self):
        if self._growth is None:
            return
        older = getattr(self._growth, "older", False)
        self._growth = None
        self.setWindowOpacity(1.0)
        if self.kind:
            self._layout_children(self._paint_chrome())
            bar = self._scroll.verticalScrollBar()
            bar.setValue(0 if older else bar.maximum())

    def _scroll_to_bottom(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _tick_dots(self):
        """Make the thinking dots pulse for as long as the bot is thinking."""
        if not self._dots_lines:
            self._dots_on = False
            self._dots.stop()
            return
        self._dots_phase = (self._dots_phase + DOTS_MS / 1000 / DOTS_CYCLE_S) % 1.0
        for line in self._dots_lines:
            line["phase"] = self._dots_phase
        if self._geom:
            self._set_text()
            self._scroll_to_bottom()

    # ── Position and movement ───────────────────────────────────

    def _goal(self):
        """The bubble hangs above the head; the tail follows the head."""
        fx, fy = self.face.spot()
        bw = self.width() or 80
        bh = self.height() or 48
        gx, gy, gw, gh = screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)
        tx = fx + (AVATAR_SIZE - bw) / 2
        ty = fy - bh + 6 + self.face.head_top
        up = False
        # The side follows the size it will have: a bubble that still fits above while small must not
        # swing below once it has grown.
        if fy - self._final_height() + 6 + self.face.head_top < gy + 4:  # no room above the head: below, tail up
            ty = fy + self.face.head_bottom - 8
            up = True
        tx = max(gx + 4, min(tx, gx + gw - bw - 4))
        ty = max(gy + 4, min(ty, gy + gh - bh - 4))
        return tx, ty, (round(fx + AVATAR_SIZE / 2 - tx), up)

    def _final_height(self) -> int:
        """The window height once it has grown to its size."""
        if self._growth is None or not self._geom:
            return self.height() or 48
        growth, self._growth = self._growth, None
        try:
            return self._body_h(self._geom[2]) + PAD_SVG + TAIL_ROOM
        finally:
            self._growth = growth

    def _tick(self):
        """Spring: the bubble trails behind the icon."""
        if not self.kind:
            self._physics_on = False
            self._physics.stop()
            return
        now = time.monotonic()
        self._wait_since = (self._wait_since or now) if self.face.awaiting() else 0.0
        awaiting = bool(self._wait_since) and now - self._wait_since < BUBBLE_WAIT_MAX
        if self._input and self._entry.hasFocus():
            self._had_focus = True
        elif (self._had_focus and self._input and not self._entry.text() and not awaiting
              and QApplication.activeWindow() not in (self, self.face)):
            # Clicked into another window with nothing typed: the bubble goes, pinned or not.
            # Clicking on its own words or on the face is not leaving.
            self.face.unpin()
            self.place("")
            return
        if self.face.pointer_near(self) or self.holding() or awaiting:
            self.changed = now
            self._was_near = self._was_near or not awaiting
        elif self._was_near and not self.face.pinned:
            # The pointer was here and left: gone at once.
            self.place("")
            return
        elif self.changed and now - self.changed > reading_seconds(self.full_text) and not self.face.pinned:
            # Nobody pointed at it and nothing new came: it goes away after a while.
            self.place("")
            return
        tx, ty, tip = self._goal()
        if tip != self._tip:
            self._tip = tip
            self._layout_children(self._paint_chrome())
            tx, ty, _tip = self._goal()
        if self._growth is not None:
            return
        x, y = self.x(), self.y()
        self._vx = (self._vx + (tx - x) * 0.16) * 0.7
        self._vy = (self._vy + (ty - y) * 0.16) * 0.7
        nx, ny = x + self._vx, y + self._vy
        if abs(tx - nx) < 0.6 and abs(self._vx) < 0.35 and abs(ty - ny) < 0.6 and abs(self._vy) < 0.35:
            nx, ny, self._vx, self._vy = tx, ty, 0.0, 0.0
        self.move(int(nx), int(ny))

    def place(self, kind: str):
        """Show or hide the bubble. The face stays."""
        self.kind = kind
        if kind == "":
            self._slide.stop()
            self._growth = None
            self.setWindowOpacity(1.0)
            self._was_near = False
            self._had_focus = False
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
            desktops.apply(self)
        if not self._physics_on:
            self._physics_on = True
            self._physics.start()
