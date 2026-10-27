"""The bubble: a separate window above the face.

Two shapes: the thinking cloud (kind "think") and the speech bubble (kind "say"
and "hint"). A speech bubble can get an input field and a row of links.
"""

import html
import os
import sys
import time

from PySide6.QtCore import (
    QAbstractAnimation,
    QBuffer,
    QByteArray,
    QEasingCurve,
    QIODevice,
    QPoint,
    QRect,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QImage, QPainter, QRegion, QTextOption
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QScrollArea, QTextBrowser, QWidget

from botwidget import attachments, menu_pages
from botwidget.avatar import AVATAR_SIZE, CIRCLE_R
from botwidget.bubble import (
    bubble_body_svg,
    bubble_deco_svg,
    bubble_height_cap,
    menu_height_cap,
    bubble_shadow_svg,
    bubble_width,
    cloud_body_svg,
    cloud_shadow_svg,
    content_height,
    line_height,
    panel_pad,
    panel_rects,
    reading_seconds,
)
from botwidget.config import always_on_top
from botwidget.bubble_layout import bubble_panels
from botwidget.markdown import block_text, md_blocks, plain_text
from botwidget.qt_ui import desktops, screens
from botwidget.qt_ui.native import drop_hidden, native_id, set_flags
from botwidget.system.current import before_show, pointer_window, send_behind_windows
from botwidget.qt_ui.controls import ActionButton, SlashList, Switch
from botwidget.qt_ui.measure import measure
from botwidget.qt_ui.render import blurred, stacked, svg_pixmap
from botwidget.qt_ui.text_doc import fill_document, selected_text
from botwidget.theme import (
    BUBBLE_FONT,
    BUBBLE_MAX_SCREEN_SHARE,
    BUBBLE_MAX_W,
    BUBBLE_WAIT_MAX,
    BUBBLE_WIDER,
    DOTS_CYCLE_S,
    DOTS_GAP,
    DOTS_MS,
    MORE_HIT_HALF_W,
    PAD_BODY,
    PAD_PANEL_X,
    PAD_SVG,
    SAND_ACCENT,
    SAND_BUBBLE,
    SAND_INK,
    SAND_ON_USER,
    SAND_PANEL_USER,
    SAND_RADIUS_PANEL,
    SAND_SANS,
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
QPlainTextEdit {{
    background: #ffffff; color: {SAND_INK}; border: 1px solid rgba(28, 28, 28, 31);
    border-radius: 8px; padding: 8px;
}}
QPlainTextEdit:focus {{ border-color: rgba(22, 128, 243, 140); }}
QLabel#links {{ color: {SAND_ACCENT}; }}
"""
ENTRY_H = 34
ENTRY_MAX_LINES = 5
ATTACH_H = 26
COMMANDS_GAP = 4
FOLLOW_SLACK = 6  # a thought counts as read to its end when it is scrolled this close to the bottom
ENTRY_PAD = 18  # the field's padding and border, above and below its lines
ENTRY_GAP = 8
LINKS_H = 26
MIN_INTERACTIVE_W = 240
SCROLLBAR_W = 6
NOTICE_MS = 1600
GROW_MS = 240
OPEN_SLIDE = 14  # a new bubble starts this many pixels toward its face
OPEN_TOWARD = {"above": (0, 1), "below": (0, -1), "right": (-1, 0), "left": (1, 0)}
OLDER_PAUSE_S = 0.3
# The arrow for the message before shows when you scroll up at the top, or the pointer is in the top MORE_ZONE_PX of
# the bubble; it stays while the pointer is within MORE_KEEP_PX of the top (the bubble grew by the arrow, so the
# zone moved with it), and goes MORE_LINGER_S after that. A click loads the message at once, scrolling on at the top
# for HOLD_LOAD_S does too; wheel events less than WHEEL_RUN_GAP_S apart are one run of scrolling.
MORE_ZONE_PX = 28
MORE_KEEP_PX = 70
MORE_LINGER_S = 0.8
HOLD_LOAD_S = 0.5
WHEEL_RUN_GAP_S = 0.25
TAIL_LENGTH = 7
THINK_GAP = 12  # the extra distance of a thinking cloud from the face, for the balls on their arc

# A button of a menu page: the pill sits in the middle of its line.
BUTTON_H = 28

def mark_before_show(widget) -> None:
    """Called right before a top-level window of ours is mapped; see system before_show."""
    flags = widget.windowFlags()
    layer = "above" if flags & Qt.WindowStaysOnTopHint else "below" if flags & Qt.WindowStaysOnBottomHint else ""
    before_show(native_id(widget), layer)


def pointer_on_no_window() -> bool:
    """XWayland: the pointer is over no X window at all, so it is on another app or the desktop.

    The enter/leave events of our windows can get lost when the pointer goes straight onto a Wayland window;
    the X server's own answer does not. Only 0 counts: another X window under the pointer is left to the
    leave event.
    """
    return pointer_window() == 0


def pointer_on(widget) -> bool | None:
    """X: is the pointer on this very window? None where the X server cannot tell.

    The answer of the X server is the top window under the pointer, so it holds when enter/leave events got
    lost (a bubble that shrank away from under the pointer after the back arrow, a jump onto another app),
    and a bubble hidden behind another window does not count as pointed at.
    """
    if QGuiApplication.platformName() != "xcb":
        return None
    child = pointer_window()
    if child is None:
        return None
    return child == native_id(widget)


def pasted_files(source) -> list:
    """Files and pictures on the clipboard, copied under the shared folder; none when it holds only text."""
    paths = [p for p in (
        [attachments.store_file(url.toLocalFile()) for url in source.urls()
         if url.isLocalFile() and os.path.isfile(url.toLocalFile())]
        if source.hasUrls() else []) if p is not None]
    if not paths and source.hasImage():
        image = source.imageData()
        if isinstance(image, QImage) and not image.isNull():
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer, "PNG")
            paths.append(attachments.store_bytes("image.png", bytes(data)))
    return paths


class BubbleEntry(QPlainTextEdit):
    """The input field: Enter sends, Shift+Enter starts a new line, files and pictures can be pasted,
    and the field grows with its lines."""

    returnPressed = Signal()
    dismissed = Signal()
    resized = Signal()
    attached = Signal(list)  # paths of pasted files and pictures
    moved = Signal(int)  # up or down in the list of slash commands
    completed = Signal()  # Tab: the command that is selected goes into the field
    chosen = Signal()  # Return: the command that is selected runs
    closed = Signal()  # Escape: only the list of commands goes away

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commands_open = False
        self.document().setDocumentMargin(0)
        self.setTabChangesFocus(True)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        # Spaces at the end of a line hang outside the width by default, and the cursor behind them then pulls the
        # text sideways and hides its left part. Counted in the width they wrap like any letter.
        option = self.document().defaultTextOption()
        option.setFlags(option.flags() | QTextOption.IncludeTrailingSpaces)
        self.document().setDefaultTextOption(option)
        self.horizontalScrollBar().valueChanged.connect(self._stay_left)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().documentLayout().documentSizeChanged.connect(self._document_resized)

    def mousePressEvent(self, event):
        # A click into the field asks for the keyboard, also where the window manager does not focus on click.
        self.window().activateWindow()
        super().mousePressEvent(event)

    def _document_resized(self, _size):
        # A scrollbar only once the lines no longer fit: before that it would flash up for the moment
        # a new line has wrapped and the field has not grown yet.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if self.line_count() > ENTRY_MAX_LINES
                                        else Qt.ScrollBarAlwaysOff)
        self.resized.emit()
        # The field grows a moment later: until then the cursor may sit below what is shown.
        QTimer.singleShot(0, self._show_cursor)

    def _stay_left(self, value: int):
        """The text wraps, so it never needs to scroll sideways."""
        if value:
            self.horizontalScrollBar().setValue(0)

    def line_count(self) -> int:
        """The lines on screen, wrapped ones too: a paragraph that wraps over six lines is six lines, not one block.
        Counted from the layout of each block; the height of the document is in lines or in pixels, depending on
        the system."""
        total, block = 0, self.document().begin()
        while block.isValid():
            total += max(1, block.lineCount())
            block = block.next()
        return max(1, total)

    def _show_cursor(self):
        if self.line_count() <= ENTRY_MAX_LINES:
            self.verticalScrollBar().setValue(0)
        else:
            self.ensureCursorVisible()

    def canInsertFromMimeData(self, source) -> bool:
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        paths = pasted_files(source)
        if paths:
            self.attached.emit(paths)
        elif source.hasText():
            super().insertFromMimeData(source)

    def focusNextPrevChild(self, forward: bool) -> bool:
        # Tab never gets to keyPressEvent in a field that lets it move the focus.
        if self.commands_open and forward:
            self.completed.emit()
            return True
        return super().focusNextPrevChild(forward)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str):
        self.setPlainText(text)

    def wanted_height(self) -> int:
        lines = min(ENTRY_MAX_LINES, self.line_count())
        return max(ENTRY_H, lines * self.fontMetrics().lineSpacing() + ENTRY_PAD + 2)

    def keyPressEvent(self, event):
        """Escape closes the bubble without sending anything and keeps what was typed; with the list of commands open it
        closes that."""
        if self.commands_open and not event.modifiers() & Qt.ShiftModifier:
            handled = {Qt.Key_Up: lambda: self.moved.emit(-1), Qt.Key_Down: lambda: self.moved.emit(1),
                       Qt.Key_Tab: self.completed.emit, Qt.Key_Escape: self.closed.emit}
            if event.key() in handled:
                handled[event.key()]()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.chosen.emit()
                return
        if event.key() == Qt.Key_Escape:
            self.dismissed.emit()
            return
        if (sys.platform == "darwin" and event.key() == Qt.Key_Backspace
                and event.modifiers() == Qt.ControlModifier):
            # Cmd+Backspace: the line up to the cursor, as in any other Mac text field; Qt does not do it itself.
            cursor = self.textCursor()
            if not cursor.hasSelection():
                cursor.movePosition(cursor.MoveOperation.StartOfLine, cursor.MoveMode.KeepAnchor)
                if not cursor.hasSelection():
                    cursor.movePosition(cursor.MoveOperation.PreviousCharacter, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)


class CopyNotice(QWidget):
    """"Copied" in the middle of a message: the words fade out behind it, then it fades away itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text, self.dark, self.level = "", False, 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(NOTICE_MS)
        for at, level in ((0.0, 0.0), (0.12, 1.0), (0.7, 1.0), (1.0, 0.0)):
            self._fade.setKeyValueAt(at, level)
        self._fade.valueChanged.connect(self._set_level)
        self._fade.finished.connect(self.hide)
        self.hide()

    def show_over(self, rect: QRect, text: str, dark: bool):
        self.text, self.dark = text, dark
        self.setGeometry(rect)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.start()

    def dismiss(self):
        self._fade.stop()
        self.hide()

    def _set_level(self, level):
        self.level = float(level)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        ground = QColor(SAND_PANEL_USER if self.dark else SAND_BUBBLE)
        ground.setAlphaF(0.94 * self.level)
        painter.setPen(Qt.NoPen)
        painter.setBrush(ground)
        painter.drawRoundedRect(self.rect(), SAND_RADIUS_PANEL, SAND_RADIUS_PANEL)
        ink = QColor(SAND_ON_USER if self.dark else SAND_INK)
        ink.setAlphaF(self.level)
        painter.setPen(ink)
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self.text)


class Growth:
    """A bubble changing size: it starts at this width and height and grows to the real ones."""

    def __init__(self, width: int, height: int, added: int = 0, opening: bool = False):
        self.width, self.height, self.added, self.opening = width, height, added, opening
        self.progress = 0.0


class OlderScroll(QScrollArea):
    """Scrolling up at the top says so (pulled, with whether it is only the momentum after a lifted finger); what
    the bubble does with that is up to the bubble."""

    pulled = Signal(bool)

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        if event.angleDelta().y() > 0 and bar.value() <= bar.minimum():
            self.pulled.emit(event.phase() == Qt.ScrollMomentum)
            event.accept()
            return
        super().wheelEvent(event)


class BubbleText(QTextBrowser):
    """The words in the bubble as real text: a click copies the message, a drag selects and copies."""

    clicked = Signal(float, float, bool)  # where in the text, and whether shift was held
    command = Signal(str)  # a menu row was clicked
    selected = Signal(str, float)  # the selected words, and where the pointer was let go
    SLOP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.message_at = lambda x, y: None
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
        elif url.scheme() == "bw":
            self.command.emit(url.path())

    def wheelEvent(self, event):
        """The text is never taller than its frame: the bubble scrolls, not the text."""
        event.ignore()

    def _cursor_for(self, pos):
        """A hand over a message (a click copies it), the text cursor while selecting."""
        if self._dragging:
            shape = Qt.IBeamCursor
        elif self.anchorAt(pos) or self.message_at(pos.x(), pos.y()) is not None:
            shape = Qt.PointingHandCursor
        else:
            shape = Qt.ArrowCursor
        self.viewport().setCursor(shape)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
            self._shift = bool(event.modifiers() & Qt.ShiftModifier)
            self._dragging = False
            if self._shift:
                # Shift is for copying markdown; the text control would take it as "extend the selection".
                cursor = self.textCursor()
                cursor.clearSelection()
                self.setTextCursor(cursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._shift and self._press is not None:
            self._cursor_for(pos)
            return
        super().mouseMoveEvent(event)
        if self._press is not None and event.buttons() & Qt.LeftButton and not self._dragging:
            if (pos - self._press).manhattanLength() > self.SLOP:
                self._dragging = True
        self._cursor_for(pos)

    def mouseReleaseEvent(self, event):
        if not self._shift:
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
                self.clicked.emit(pos.x(), pos.y(), self._shift)
        self._press, self._dragging = None, False
        self._cursor_for(pos)

class BubbleWindow(QWidget):
    travels = True  # it belongs to the desktop of its face, wherever that is now, see desktops.apply
    older = Signal()
    command = Signal(str)
    edit_queued = Signal(str)  # the id of a queued message that was clicked

    def __init__(self, face):
        super().__init__()
        self.face = face
        self._apply_flags()
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
        self._list_only = False
        self._links = []
        self._geom = None
        self._built = None
        self._chrome_key = self._chrome_pix = None
        self._was_near = False
        self._near_at = 0.0
        # Qt's enter/leave for this window. A leave newer than the last enter means the pointer is
        # gone, whatever underMouse() still says on XWayland.
        self._entered_at = None
        self._left_at = None
        self._had_focus = False
        self._wants_keys = False
        self._wait_since = 0.0
        self._growth = None
        self._older_until = 0.0
        self._has_older = False  # earlier messages wait above
        self._more_open = False  # their arrow is showing
        self._toggling = False
        self._pull_since = self._pull_last = 0.0  # a run of scrolling at the top: its start and its latest event
        self._more_engaged = 0.0
        self._more_progress = 0.0
        self._tip = None
        self._vx = self._vy = 0.0
        self._physics_on = False
        self._dots_on = False
        self._dots_phase = 0.0
        self._dots_lines = []

        # Everything that shows sits on the card; the window around it can be bigger (see _hold_after).
        self._card = QWidget(self)
        self._card_at = QPoint(0, 0)  # where the card is on the screen
        self._chrome = QLabel(self._card)
        self._text = QLabel()
        self._text.setAttribute(Qt.WA_TranslucentBackground)
        self._doc = BubbleText(self._text)
        self._doc.message_at = self._message_at
        self._doc.clicked.connect(self._on_click)
        self._doc.command.connect(self.command)
        self._doc.selected.connect(self._on_selected)
        self._scroll = OlderScroll(self._card)
        self._scroll.pulled.connect(self._on_pulled)
        self._scroll.setWidget(self._text)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._link_row = QLabel(self._card)
        self._link_row.setObjectName("links")
        self._link_row.setOpenExternalLinks(True)
        self._link_row.setTextFormat(Qt.RichText)
        self._notice = CopyNotice(self._scroll.viewport())
        self._notice_from_end = 0
        self._scroll.verticalScrollBar().valueChanged.connect(self._move_notice)
        self._entry = BubbleEntry(self._card)
        self._entry.setPlaceholderText("Send a message…")
        self._entry.returnPressed.connect(self._send)
        self._entry.resized.connect(self._entry_resized)
        self._entry.attached.connect(self._attach)
        self._slash = SlashList(self._card)
        self._slash.chosen.connect(self._run_command)
        self._entry.textChanged.connect(self._update_commands)
        self._entry.textChanged.connect(self._edited)
        self._entry.moved.connect(self._slash.move_selection)
        self._entry.completed.connect(lambda: self._entry.setText(self._slash.current()))
        self._entry.chosen.connect(lambda: self._run_command(self._slash.current()))
        self._entry.closed.connect(self._close_commands)
        self._commands_forced = False
        self._attachments = []
        self._attachment_row = QLabel(self._card)
        self._attachment_row.setTextFormat(Qt.RichText)
        self._attachment_row.setObjectName("attachments")
        self._attachment_row.linkActivated.connect(self._unattach)
        self._attachment_row.hide()
        self._control_widgets = []
        self._controls_key = None
        self._opened = 0.0
        self._spot = (0, 0, 0, 0)
        self._yielding = False
        self._scroll_target = 0
        self._follow = False
        self._entry.dismissed.connect(face.unpin)

        self._held = None  # QRect on the screen the window still covers after the card shrank under the pointer
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

    def _edited(self):
        self.changed = time.monotonic()

    def _send(self):
        self.changed = time.monotonic()
        text, files = self._entry.text().strip(), self._attachments
        if text or files:
            self._entry.clear()
            self._attachments = []
            self._show_attachments()
            self.face.on_user_message(text, files=files)

    def _update_commands(self):
        """A message that starts with a slash gets the commands that fit it, in a list above the field."""
        self._commands_forced = False
        text = self._entry.text().strip().lower()
        fitting = [row for row in menu_pages.COMMANDS if row[0].startswith(text)] \
            if text.startswith("/") and " " not in text else []
        self._show_commands(fitting)

    def open_command_list(self):
        """The list of commands, without touching what was typed. A slash already in the field filters the list."""
        text = self._entry.text()
        if text.startswith("/") and " " not in text:
            self._update_commands()
            return
        self._commands_forced = True
        self._show_commands(list(menu_pages.COMMANDS))

    def show_command_menu(self):
        """Right-click: the command list on its own, without the conversation."""
        old = self._area_under_pointer()
        self._show_command_menu()
        self._hold_after(old)

    # ── The card and the window around it ──────────────────────────
    #
    # The bubble is drawn on a card. Normally the window is exactly the card. When a change of content makes the
    # card smaller or moves it away from under the pointer (the back arrow, a page swap), the window keeps the area
    # it had: the rest of it is see-through but still this window, so the X server keeps naming it as the window
    # under the pointer and leaving it closes the bubble as ever. No second window, nothing to map late, no timer.

    def card(self) -> QRect:
        """Where the bubble is drawn on the screen."""
        return QRect(self._card_at, self._card.size())

    def _put(self, x, y):
        """The card to this spot; the window follows."""
        self._card_at = QPoint(int(x), int(y))
        self._fit_window()

    def _fit_window(self):
        card = self.card()
        area = card.united(self._held) if self._held is not None else card
        if self.geometry() != area:
            self.setGeometry(area)
        self._card.move(card.topLeft() - area.topLeft())
        self._shape(area, card)

    def _shape(self, area: QRect, card: QRect):
        """A held area takes no clicks meant for a face: those spots are cut out of the window."""
        region = QRegion()
        if self._held is not None:
            faces = getattr(getattr(self.face, "faces", None), "faces", None) or {}
            for face in {id(f): f for f in [self.face, *faces.values()]}.values():
                if not face.isVisible():
                    continue
                rect = face.frameGeometry().intersected(area)
                if not rect.isEmpty():
                    region = region.united(QRegion(rect).subtracted(QRegion(card)))
        if region.isEmpty():
            if not self.mask().isEmpty():
                self.clearMask()
            return
        mask = QRegion(area.translated(-area.topLeft())).subtracted(region.translated(-area.topLeft()))
        if mask != self.mask():
            self.setMask(mask)

    def holding_area(self) -> QRect | None:
        """The area the window still holds for a card that shrank, None when the window is just the card."""
        return QRect(self._held) if self._held is not None else None

    def _area_under_pointer(self) -> QRect | None:
        """The whole window, when the pointer is on it: what a smaller card keeps as hover area."""
        if not (self.isVisible() and self.kind and self.face.pointer_near(self)):
            return None
        return QRect(self.frameGeometry())

    def _hold_after(self, old: QRect | None):
        """A page change made the card smaller (the back arrow) or moved it (a tall page that no longer fits
        above the face goes beside it): the window keeps covering the area it had, until the pointer leaves the
        window or comes onto the card.

        The pointer was on the bubble, so it has been touched: leaving closes it at once, not after a while.
        """
        self._release_hold()
        if old is None or not self.isVisible() or not self.kind:
            return
        self._was_near = True
        width, height = self._final_size()
        tx, ty, _tip = self._goal()
        final = QRect(int(tx), int(ty), width, height)
        if final.contains(old) and self.card().contains(old):
            return  # it grows over where it was: the pointer stays on it
        self._held = QRect(old)
        self._fit_window()

    def _release_hold(self):
        """The window becomes the card again."""
        if self._held is None:
            return
        self._held = None
        self._fit_window()

    def _pointer_on_card(self) -> bool:
        """Only where the position can be trusted: on X while the pointer is on this window, or where the
        pointer is known everywhere. A stale position must not shrink the window away from under it."""
        if not (pointer_on(self) or self.face.pointer_known()):
            return False
        px, py = self.face._pointer()
        return self.card().contains(QPoint(int(px), int(py)))

    def _show_command_menu(self):
        self._list_only = True
        self._input = False
        self._links = []
        self.blocks = []
        self.full_text = ""
        self.kind = "say"
        # Armed once the pointer is on the face or the list: after the back arrow it may be elsewhere, and the
        # list must not vanish before it got there.
        self._was_near = False
        self._commands_forced = True
        # The dots of a thought before belong to text that is gone; ticking them on would draw nothing.
        self._dots_lines = []
        self._slash.show_rows(list(menu_pages.COMMANDS))
        # As wide as the commands and their notes need, so nothing is cut; never wider than a chat bubble.
        self._geom = ([], max(MIN_INTERACTIVE_W, min(self._slash.wanted_width(), BUBBLE_MAX_W + 60)), 0)
        self._built = ("commands",)
        self._growth = None
        self.setWindowOpacity(1.0)
        self.changed = time.monotonic()
        self._layout_children(self._paint_chrome())
        self.place("say")

    def _show_commands(self, rows: list):
        """The list sits in the bubble right above the field, which makes room for it."""
        before = len(self._slash.rows)
        self._entry.commands_open = bool(rows) and self._input
        self._slash.show_rows(rows if self._input else [])
        if len(self._slash.rows) != before:
            self._entry_resized()

    def _close_commands(self):
        """Escape: a slash command that was typed goes away with its list; a message that was already there stays."""
        if not self._commands_forced:
            self._entry.clear()
        self._show_commands([])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and not self._input:
            self.face.unpin()
            return
        super().keyPressEvent(event)

    def _commands_h(self) -> int:
        return self._slash.height_for(len(self._slash.rows)) + COMMANDS_GAP if self._slash.rows else 0

    def _run_command(self, command: str):
        self.changed = time.monotonic()
        # A slash being typed is the command. A message that was already there stays, also after a right-click.
        typed = self._entry.text().strip()
        if not self._commands_forced or (typed.startswith("/") and " " not in typed):
            self._entry.clear()
        if not self._list_only:
            # The list above the field goes. The right-click list is the whole bubble: it stays until the page
            # replaces it, else the bubble shrank to a sliver first and left the pointer outside (and closed).
            self._show_commands([])
        self._commands_forced = False
        self.face.on_user_message(command)

    def _attach(self, paths: list):
        self.changed = time.monotonic()
        self._attachments += paths
        self._show_attachments()

    def _unattach(self, link: str):
        index = int(link)
        if 0 <= index < len(self._attachments):
            del self._attachments[index]
            self._show_attachments()

    def _show_attachments(self):
        self._attachment_row.setText("   ".join(
            f'📎 {html.escape(path.name)} <a href="{i}" style="color:{SAND_ACCENT}">✕</a>'
            for i, path in enumerate(self._attachments)))
        self._attachment_row.setVisible(bool(self._attachments))
        self._entry_resized()

    def _message_at(self, x: float, y: float) -> dict | None:
        """The panel a click at this spot in the text does something with: a message to copy, or the arrow."""
        if self.kind not in ("say", "think") or not self._geom:
            return None
        content_y = y + self._doc.y()
        for (top, height), panel in zip(panel_rects(self._geom[0]), self._geom[0]):
            if not top <= content_y < top + height:
                continue
            if panel["role"] == "more":
                if abs(x - self._shown_w(self._geom[1]) / 2) <= MORE_HIT_HALF_W:
                    return panel
            elif panel.get("queued") or (panel.get("copy") and self.kind == "say"):
                return panel
        return None

    def _on_click(self, x: float, y: float, shift: bool):
        """Click on the arrow loads the message before; on a message it copies it, shift+click as markdown."""
        panel = self._message_at(x, y)
        if panel and panel["role"] == "more":
            self._arrow_clicked()
        elif panel and panel.get("queued"):
            self.edit_queued.emit(panel["queued"])
        elif panel and shift:
            self._copied_to_clipboard(panel["copy"], "Copied markdown", y)
        elif panel:
            self._copied_to_clipboard(plain_text(panel["copy"]), "Copied", y)

    def _on_selected(self, text: str, y: float):
        self._copied_to_clipboard(text, "Copied", y)

    def _copied_to_clipboard(self, text: str, notice: str, y: float):
        """Copy, and say so over the message: its words fade out behind the notice, which fades away too."""
        QApplication.clipboard().setText(text)
        self.changed = time.monotonic()
        content_y, scrolled = y + self._doc.y(), self._scroll.verticalScrollBar().value()
        rects = panel_rects(self._geom[0])
        for index, ((top, height), panel) in enumerate(zip(rects, self._geom[0])):
            if top <= content_y < top + height:
                # Counted from the end: an older message loaded above does not move it.
                self._notice_from_end = len(rects) - index
                self._notice.show_over(self._notice_rect(), notice, panel["role"] == "user")
                return

    def _notice_rect(self) -> QRect:
        """The part of the copied message that is in view: the notice is read in the middle of the bubble."""
        rects = panel_rects(self._geom[0])
        index = len(rects) - self._notice_from_end
        if not 0 <= index < len(rects):
            return QRect()
        top, height = rects[index]
        scrolled, view = self._scroll.verticalScrollBar().value(), self._scroll.viewport().height()
        shown_top, shown_bottom = max(0, top - scrolled), min(view, top - scrolled + height)
        return QRect(0, shown_top, self._shown_w(self._geom[1]), max(0, shown_bottom - shown_top))

    def _move_notice(self):
        """The notice stays on its message when the bubble scrolls."""
        if self._notice_from_end and self._notice.isVisible():
            self._notice.setGeometry(self._notice_rect())

    def focus_entry(self):
        """The cursor into the field, asked for by the user. A field that is not there yet (the bubble is still
        growing) gets it as soon as it shows: Qt drops focus given to a hidden widget."""
        if self._input:
            self.activateWindow()
            self._entry.setFocus()
            self._wants_keys = self.focusWidget() is not self._entry

    def shows(self, kind: str, text: str, input: bool) -> bool:
        """Is exactly this already showing in the bubble? Then nothing needs to be redrawn."""
        return self.kind == kind and self.full_text == text and self._input == input and self.isVisible()

    def holding(self) -> bool:
        """Words in the field that are not sent yet, or words selected to copy: the bubble stays for as long as
        one of those lasts, and leaves with the pointer once the field is empty again."""
        return (self._input and bool(self._entry.text())) or (
            self._doc.hasFocus() and self._doc.textCursor().hasSelection())

    def shown_by_pointer(self):
        """The pointer is on the face, so it has been near: leaving takes the bubble with it, also when it was
        not yet read to the end."""
        self._was_near = True
        self._near_at = time.monotonic()

    def enterEvent(self, event):
        """Mouse over the bubble: it stays."""
        self._entered_at = time.monotonic()
        self.changed = time.monotonic()

    def leaveEvent(self, event):
        """Mouse left the bubble: the pointer is away, even when underMouse() stays true.

        The grace that lets the pointer cross the gap lives in _tick, so _was_near is left alone here.
        """
        self._left_at = time.monotonic()

    def pointer_over(self) -> bool:
        """Whether the pointer is over the bubble, trusting a leave that came after the last enter."""
        on = pointer_on(self)
        if on is not None:
            return on
        if self._left_at is not None and (self._entered_at is None or self._left_at > self._entered_at):
            return False
        if pointer_on_no_window():
            return False
        return self.underMouse()

    # ── Content ─────────────────────────────────────────────────

    def _parts(self):
        """Panels, width of the text area and height of the content."""
        blocks = self.blocks or md_blocks("…")
        # The arrow for the message before only takes room while it shows.
        self._has_older = len(blocks) > 1 and blocks[0].get("role") == "more" and not blocks[0].get("back")
        if self._has_older and not self._more_open:
            blocks = blocks[2:]
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

    def _entry_h(self) -> int:
        return self._entry.wanted_height()

    def _entry_resized(self):
        """The field gained or lost a line: the bubble grows or shrinks with it, the tail keeps pointing."""
        if self._geom is not None and self._input and self._growth is None:
            self._layout_children(self._paint_chrome())

    def user_owned(self) -> bool:
        """The user is busy with this bubble: a bubble that opened by itself gives way to it."""
        return self.face.pinned or self.holding() or self.face.pointer_near(self)

    def rank(self) -> int:
        """How much the user is with this bubble: pointing at its face asks for it (it wins from everything, and the
        other bubbles then close), typing or a pin comes next, then the pointer near it, then a bubble that opened
        by itself."""
        if self.face._pointer_on_head():
            return 3
        if self.face.pinned or self.holding():
            return 2
        return 1 if self.user_owned() else 0

    def _others(self) -> list:
        faces = getattr(self.face.faces, "faces", {})
        return [face.bubble for face in faces.values() if face.bubble is not self and face.bubble.seen()]

    def seen(self) -> bool:
        """Open where you can see it. A bubble left see-through with no growth to fade it in is not: it must
        not push the others aside or make them give way."""
        return self.isVisible() and (self._growth is not None or self.windowOpacity() > 0.01)

    def _body_rect(self, x, y, w, h) -> QRect:
        return QRect(round(x + PAD_SVG), round(y + PAD_SVG), max(1, w - 2 * PAD_SVG), max(1, h - PAD_SVG - TAIL_ROOM))

    def _clear_spot(self, x, y, w, h, bounds=None) -> tuple:
        """Off the other bubbles: pushed aside on the side where they overlap least, so two never sit on each
        other. bounds is the screen it has to stay on, if it can."""
        for _ in range(4):
            moved = False
            for other in self._others():
                dx = other.x() + other.width() / 2 - (x + w / 2)
                dy = other.y() + other.height() / 2 - (y + h / 2)
                over_x = (w + other.width()) / 2 - abs(dx)
                over_y = (h + other.height()) / 2 - abs(dy)
                if over_x <= 0 or over_y <= 0:
                    continue
                if over_x <= over_y:
                    x += -over_x if dx > 0 else over_x
                else:
                    y += -over_y if dy > 0 else over_y
                moved = True
            if not moved:
                break
        if bounds:
            gx, gy, gw, gh = bounds
            x = max(gx + 4, min(x, gx + gw - w - 4))
            y = max(gy + 4, min(y, gy + gh - h - 4))
        return x, y

    def _covering(self, x, y, w, h) -> list:
        rect = self._body_rect(x, y, w, h)
        return [o for o in self._others() if rect.intersects(self._body_rect(o.x(), o.y(), o.width(), o.height()))]

    def _must_yield(self) -> bool:
        """Every place covers another bubble: the one the user is busy with wins, else the older one."""
        if not desktops.face_here(self.face):
            return True  # the face is on another desktop: its sound is enough until you go there
        mine = self.rank()
        return any(o.rank() > mine or o.rank() == mine and o._opened <= self._opened
                   for o in self._covering(*self._spot))

    def takes_input(self) -> bool:
        return self._input

    def type_text(self, text: str):
        """Words in the field, as if typed, with the cursor behind them."""
        self._entry.setText(text)
        cursor = self._entry.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._entry.setTextCursor(cursor)

    def edit_text(self, text: str, files: list = ()):
        """A message back in the field: in front of what was already typed."""
        self._attachments += list(files)
        self._show_attachments()
        draft = self._entry.text()
        self._entry.setText(text + ("\n" + draft if draft else ""))
        cursor = self._entry.textCursor()
        cursor.setPosition(len(text))
        self._entry.setTextCursor(cursor)

    def set_queueing(self, queueing: bool, waiting: int = 0, answering: bool = False):
        """While the bot works, what is typed waits in line instead of going out at once; with a question
        open, it is the answer."""
        if answering:
            self._entry.setPlaceholderText("Type your answer…")
        elif not queueing:
            self._entry.setPlaceholderText("Send a message…")
        else:
            self._entry.setPlaceholderText(f"Queue a message… ({waiting} waiting)" if waiting else "Queue a message…")

    def _extras(self) -> int:
        """Height below the text for the link row and the input field."""
        if self._list_only:
            return self._commands_h()
        attached = ATTACH_H if self._attachments else 0
        return (LINKS_H if self._links else 0) + (
            attached + self._commands_h() + self._entry_h() + ENTRY_GAP if self._input else 0)

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
        """Tied to this face: one extra face of chat, then scroll. Width can still grow.

        Input, slash list and chips sit in extras on top of that band so they still fit.
        """
        return self._height_cap() + self._extras()

    def _height_cap(self) -> int:
        """The face's band for chat; a page of the menu may use most of the screen."""
        cap = bubble_height_cap(self.face.height())
        if getattr(self.face, "_menu_page", None) is None:
            return cap
        fx, fy = self.face.spot()
        return menu_height_cap(cap, screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)[3])

    def _apply_flags(self):
        """Same stacking as the face: above normal windows only when the bot is always-on-top.

        The bubble can still raise above other bot faces; it must not sit above ordinary apps
        when its face is behind them.
        """
        layer = Qt.WindowStaysOnTopHint if always_on_top() else Qt.WindowStaysOnBottomHint
        # It takes focus, or nothing can be typed in its field: the window manager gives the keyboard only to a
        # window that accepts focus. Opening by itself takes none (WA_ShowWithoutActivating); a click does.
        set_flags(self, Qt.FramelessWindowHint | Qt.Tool | layer | Qt.NoDropShadowWindowHint)

    def restack(self):
        """After always-on-top changes: new flags need a show if the bubble is already open."""
        shown = self.isVisible()
        self._apply_flags()
        if shown:
            self.show()

    def _paint_chrome(self):
        if self._geom is None:
            self._geom = self._parts()
        _panels, box_w, inner = self._geom
        tip, side = self._tip or (None, "above")
        args = (self._shown_w(box_w) + 2 * PAD_BODY, self._body_h(inner), tip, side)
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
        self._card.resize(size)
        self._fit_window()
        x, y = PAD_SVG + PAD_BODY, PAD_SVG + PAD_BODY
        if self._list_only:
            self._scroll.hide()
            self._entry.hide()
            self._link_row.hide()
            self._slash.setGeometry(x, y, box_w, max(1, self._commands_h() - COMMANDS_GAP))
            return
        view_h = max(1, self._body_h(inner) - 2 * PAD_BODY - self._extras())
        self._scroll.setGeometry(x, y, box_w + SCROLLBAR_W, view_h)
        below = y + view_h
        if self._links:
            self._link_row.setGeometry(x, below + 4, box_w, LINKS_H - 4)
            below += LINKS_H
        if self._input:
            if self._attachments:
                self._attachment_row.setGeometry(x, below + ENTRY_GAP, box_w, ATTACH_H)
                below += ATTACH_H
            if self._slash.rows:
                self._slash.setGeometry(x, below + ENTRY_GAP, box_w, self._commands_h() - COMMANDS_GAP)
                below += self._commands_h()
            self._entry.setGeometry(x, below + ENTRY_GAP, box_w, self._entry_h())
        self._scroll.show()
        self._link_row.setVisible(bool(self._links))
        # Not while the bubble is still tiny: a field alone looks odd.
        # Not while the bubble is still tiny, but never taken away from a field that is already there:
        # hiding it would drop the cursor at every new thought.
        self._entry.setVisible(self._input and (self._growth is None or self._growth.opening
                                                or self._growth.progress >= 0.35 or self._entry.isVisible()))
        if self._wants_keys and self._entry.isVisible():
            self._wants_keys = False
            self._entry.setFocus()
        self._move_notice()
        self._place_controls()

    def _set_text(self):
        """The shapes behind the text; the words themselves are the text document."""
        panels, box_w, inner = self._geom
        pix = svg_pixmap(bubble_deco_svg(panels, box_w))
        self._text.setPixmap(pix)
        size = pix.deviceIndependentSize().toSize()
        if size != self._text.size():
            # Resizing puts the text back in the corner of the scroll area, which would undo a bounce.
            self._text.resize(size)
        # One panel padding lower: the shapes keep the text of the first panel at that spot.
        top = panel_pad(panels[0]) if panels else 0
        self._doc.setGeometry(0, top, box_w, max(1, inner - top))
        self._doc.setVisible(self.kind != "")
        self._place_controls()

    def _place_controls(self):
        """Real switches and buttons over the lines the menu page reserved for them."""
        if self._geom is None:
            return
        panels, box_w, _inner = self._geom
        shown_w = self._shown_w(box_w)
        wanted = []
        for (top, _height), panel in zip(panel_rects(panels), panels):
            y = top + panel_pad(panel)
            for line in panel["lines"]:
                if line["kind"] == "control":
                    wanted.append((line, QRect(PAD_PANEL_X + line["indent"], y, shown_w - 2 * PAD_PANEL_X,
                                               line_height(line))))
                y += line_height(line)
        key = tuple((line["control"], line["label"], line["command"], line["on"]) for line, _rect in wanted)
        if key != self._controls_key:
            for widget in self._control_widgets:
                widget.hide()
                widget.deleteLater()
            self._control_widgets = [self._make_control(line) for line, _rect in wanted]
            self._controls_key = key
        for widget, (line, rect) in zip(self._control_widgets, wanted):
            if line["control"] == "button":
                rect.setWidth(min(rect.width(), widget.sizeHint().width()))
                rect.setHeight(BUTTON_H)
                rect.moveTop(rect.top() + (line_height(line) - BUTTON_H) // 2)
            widget.setGeometry(rect)
            widget.raise_()
            widget.show()

    def _make_control(self, line: dict):
        if line["control"] == "toggle":
            widget = Switch(line["label"], bool(line["on"]), self._text)
        else:
            widget = ActionButton(line["label"], self._text)
        widget.clicked.connect(lambda _checked=False, command=line["command"]: self.command.emit(command))
        return widget

    def _set_doc(self):
        panels, box_w, _inner = self._geom
        fill_document(self._doc.document(), panels, box_w)

    def show_blocks(self, blocks: list, kind: str, input: bool = False, links: list | None = None,
                    older: bool = False, keep_scroll: bool = False):
        """New content; a bubble that gets smaller under the pointer keeps the area it covered, see _hold_after."""
        old = self._area_under_pointer()
        try:
            self._show_blocks(blocks, kind, input, links, older, keep_scroll)
        finally:
            self._hold_after(old)

    def _show_blocks(self, blocks: list, kind: str, input: bool = False, links: list | None = None,
                     older: bool = False, keep_scroll: bool = False):
        """Put blocks in the bubble, read from the top. With older, a message was added above;
        with keep_scroll the same page is shown again, where it was. A thought is followed down as it
        grows, until you scroll up in it."""
        bar = self._scroll.verticalScrollBar()
        # While the cloud is still growing the bar says little about where you are: keep what was.
        self._follow = kind == "think" and (self.kind != "think" or not self.isVisible()
                                            or (self._follow and self._growth is not None)
                                            or bar.value() >= bar.maximum() - FOLLOW_SLACK)
        self._scroll_target = bar.value() if keep_scroll or (kind == "think" and not self._follow) else 0
        visible = self.isVisible()
        if visible and self.kind and ((kind == "think") != (self.kind == "think")
                                      or (kind == "think" and input != self._input)):
            # A speech bubble and a thinking cloud do not grow into each other, nor do the dots and the thought with
            # its field: the old one goes, the new one opens.
            self.hide()
            visible = False
        # The size it has on screen now, the command list included: a new page grows from there. Measured after
        # _list_only went off it was a sliver, which left the pointer outside and closed the bubble at once.
        start = (self._shown_w(self._geom[1]), self._body_h(self._geom[2])) if self._geom and visible else None
        if self._list_only:
            # The new content takes the list's place in this very step: its size carries over (start), its rows
            # do not. Left visible they were drawn over the page.
            self._slash.show_rows([])
            self._entry.commands_open = False
            self._commands_forced = False
        self._list_only = False
        if not self._toggling:
            self._more_open = False  # new content: the arrow for the message before shows again when asked for
        key = (kind, block_text(blocks), input, tuple(links or []), self._height_cap(), self._more_open)
        if key == self._built and not self._dots_lines:
            # The same bubble as before, only hidden: showing it again needs no new layout or shadow.
            self.changed = time.monotonic()
            if not visible and not self._yielding:
                self._growth = self._opening_growth()
                self.setWindowOpacity(0.0)
                self.place(kind)
                self._slide.start()
            return
        old_inner = self._geom[2] if self._geom else 0
        # stop() does not finish an animation that has not started, so the bubble would stay invisible.
        self._slide.stop()
        self._growth = None
        self.setWindowOpacity(1.0)
        content_changed, self._built = key != self._built, key
        self._was_near = False
        self._links = links or []
        self._input = input
        self._link_row.setText(" &nbsp;·&nbsp; ".join(
            f'<a href="{url}" style="color:{SAND_ACCENT}">{label} ↗</a>' for label, url in self._links))
        self.blocks = blocks
        self.full_text = block_text(blocks)
        # A new thought updates the cloud that is already open. It does not start the open again.
        same_think = visible and self.kind == "think" and kind == "think"
        if not same_think:
            self.changed = time.monotonic()
        restyle = kind != self.kind
        self.kind = kind
        self._geom = self._parts()
        if self._dots_lines and not self._dots_on:
            self._dots_on = True
            self._dots.start()
        # same_think skips a fresh open. A longer thought still grows the cloud that is already there.
        if not visible and not self._yielding:
            self._growth = self._opening_growth()
            self.setWindowOpacity(0.0)
        elif start != (self._geom[1], self._body_h(self._geom[2])) and not self._yielding:
            added = max(0, self._geom[2] - old_inner) if older and visible else 0
            self._growth = Growth(*start, added=added)
        pix = self._paint_chrome()
        self._layout_children(pix)
        self._set_text()
        self._set_doc()
        if older:
            self._move_notice()
        else:
            self._notice_from_end = 0
            self._notice.dismiss()
        if restyle or not visible:
            self.place(kind)
        if self._growth is not None:
            self._growth.older = older and visible
            self._slide.start()
            return
        self._scroll_to_top()
        QTimer.singleShot(0, self._scroll_to_top)

    def _on_pulled(self, momentum: bool):
        """Scrolling up at the top. On a page of the menu that goes back; in the chat it shows the arrow for the
        message before, and holding on loads it."""
        now = time.monotonic()
        back = next((panel["back"] for panel in self._geom[0] if panel.get("back")), "") if self._geom else ""
        if back:
            if self._growth is None and now >= self._older_until:
                self._older_until = now + OLDER_PAUSE_S
                self.command.emit(back)
            return
        if self.kind != "say" or not self._has_older:
            return
        self._more_engaged = now
        if not self._more_open:
            self._set_more(True)
        if momentum:
            return
        if now - self._pull_last > WHEEL_RUN_GAP_S:
            self._pull_since = now
        self._pull_last = now
        if now - self._pull_since >= HOLD_LOAD_S and self._growth is None:
            self._load_older()

    def _arrow_clicked(self):
        back = next((panel["back"] for panel in self._geom[0] if panel.get("back")), "") if self._geom else ""
        if back:
            if self._growth is None and time.monotonic() >= self._older_until:
                self._older_until = time.monotonic() + OLDER_PAUSE_S
                self.command.emit(back)
        elif self.kind == "say" and self._growth is None:
            self._load_older()

    def _load_older(self):
        """The message before comes in above, sliding down from the top; the arrow has done its job."""
        self._pull_since = self._pull_last = 0.0
        self._set_progress(0.0)
        self.older.emit()

    def _set_more(self, on: bool):
        """Show or hide the arrow for the message before: the bubble grows or shrinks by its row."""
        if on == self._more_open or not self._has_older or self.kind != "say" or not self.isVisible():
            return
        self._more_open = on
        self._pull_since = self._pull_last = 0.0
        self._toggling = True
        try:
            self.show_blocks(self.blocks, self.kind, self._input, self._links, keep_scroll=True)
        finally:
            self._toggling = False

    def _set_progress(self, progress: float):
        """How far the hold on the arrow has come, drawn as an arc round it."""
        self._more_progress = progress
        for panel in self._geom[0] if self._geom else []:
            if panel["role"] == "more" and not panel.get("back"):
                for line in panel["lines"]:
                    if line["kind"] == "more":
                        line["progress"] = progress
        if self._geom:
            self._set_text()

    def _watch_arrow(self, now: float):
        """The pointer in the top of the bubble brings the arrow; away from it, it goes again."""
        if self.kind != "say" or not self._has_older or self._growth is not None:
            return
        bar = self._scroll.verticalScrollBar()
        card = self.card()
        reach = MORE_KEEP_PX if self._more_open else MORE_ZONE_PX
        near = False
        if bar.value() <= 0 and self.face.pointer_known():
            px, py = self.face._pointer()
            near = card.left() <= px <= card.right() and card.top() - 6 <= py <= card.top() + reach
        if near or (self._pull_last and now - self._pull_last < WHEEL_RUN_GAP_S):
            self._more_engaged = now
            if not self._more_open:
                self._set_more(True)
        elif self._more_open and bar.value() <= 0 and now - self._more_engaged > MORE_LINGER_S:
            self._set_more(False)
        if self._more_open:
            holding = bool(self._pull_since) and now - self._pull_last < WHEEL_RUN_GAP_S
            progress = min(1.0, (now - self._pull_since) / HOLD_LOAD_S) if holding else 0.0
            if abs(progress - self._more_progress) >= 0.03 or (progress == 0.0 and self._more_progress):
                self._set_progress(progress)

    def _opening_growth(self) -> Growth:
        """A bubble that opens has its full size at once: the text does not wrap again at every step and the shadow
        is drawn once. It fades in and slides out from the face."""
        self._growth = None
        return Growth(self._geom[1], self._body_h(self._geom[2]), opening=True)

    def _growth_step(self, progress):
        """The bubble grows to its size: upward from the face, the older message sliding in from the top."""
        growth = self._growth
        if growth is None or not self.kind:
            return
        growth.progress = float(progress)
        # The tail is drawn for the size the window is about to have, so it points at the face all the way.
        size = (self._shown_w(self._geom[1]) + 2 * PAD_BODY + 2 * PAD_SVG,
                self._body_h(self._geom[2]) + PAD_SVG + TAIL_ROOM)
        tx, ty, self._tip = self._goal(size)
        if growth.opening:
            toward_x, toward_y = OPEN_TOWARD.get(self._tip[1], (0, 0))
            tx += toward_x * OPEN_SLIDE * (1 - growth.progress)
            ty += toward_y * OPEN_SLIDE * (1 - growth.progress)
        self._layout_children(self._paint_chrome())
        self._vx = self._vy = 0.0
        self._put(tx, ty)
        bar = self._scroll.verticalScrollBar()
        bar.setValue(min(bar.maximum(), round(growth.added * (1 - progress))) if getattr(growth, "older", False)
                     else self._scroll_value())
        if growth.opening:
            self.setWindowOpacity(min(1.0, progress * 1.25))

    def _growth_done(self):
        if self._growth is None:
            return
        older = getattr(self._growth, "older", False)
        self._growth = None
        self.setWindowOpacity(1.0)
        if self.kind:
            self._layout_children(self._paint_chrome())
            self._scroll.verticalScrollBar().setValue(self._scroll_value())
            # The range of the scroll bar follows the new size a moment later.
            QTimer.singleShot(0, self._scroll_to_top)

    def _scroll_value(self) -> int:
        """Where the text sits: at the top of a message, or at the end of a thought that is being followed."""
        return self._scroll.verticalScrollBar().maximum() if self._follow and self._growth is None \
            else self._scroll_target

    def _scroll_to_top(self):
        self._scroll.verticalScrollBar().setValue(self._scroll_value())

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

    # ── Position and movement ───────────────────────────────────

    def _goal(self, size: tuple | None = None):
        """Where the window goes, and how its tail points. size is the window size it is about to get.

        Above the face if it fits there, else to the right of it, else to the left, and below only
        when that is the one place left; the thinking cloud goes beside the face first, then above. A bubble is judged by the size it will grow to, so it does
        not swing to another side while it is still growing.
        """
        fx, fy = self.face.spot()
        bw, bh = size or (self._card.width() or 80, self._card.height() or 48)
        final_w, final_h = self._final_size()
        if size is None and not self.isVisible():
            bw, bh = final_w, final_h
        gx, gy, gw, gh = screens.rect_at(fx + AVATAR_SIZE // 2, fy + AVATAR_SIZE // 2)
        cx, cy = fx + AVATAR_SIZE / 2, fy + AVATAR_SIZE / 2
        # A thought keeps more distance: the balls between it and the face need the room.
        keep = THINK_GAP if self.kind == "think" else 0
        reach = CIRCLE_R + 4 + TAIL_LENGTH + keep  # from the middle of the face to where the white area may begin
        body_h = bh - PAD_SVG - TAIL_ROOM
        final_body_h = final_h - PAD_SVG - TAIL_ROOM
        right = cx + reach
        left = cx - reach
        fits = {"above": fy - final_h + 6 + self.face.head_top >= gy + 4,
                "right": right - PAD_SVG + final_w <= gx + gw - 4 and final_body_h <= gh - 8,
                "left": left - (final_w - PAD_SVG) >= gx + 4 and final_body_h <= gh - 8}

        def spot(side):
            if side in ("above", "below"):
                tx = round(fx + (AVATAR_SIZE - bw) / 2)
                ty = (fy - bh + 6 + self.face.head_top - keep if side == "above"
                      else fy + self.face.head_bottom - 8 + keep)
            else:
                tx = round(right - PAD_SVG if side == "right" else left - (bw - PAD_SVG))
                ty = round(cy - PAD_SVG - body_h / 2)
            return max(gx + 4, min(tx, gx + gw - bw - 4)), max(gy + 4, min(ty, gy + gh - bh - 4))

        # A thought drifts up beside the head. Speech stays above the bot when the screen allows it.
        order = ("right", "left", "above") if self.kind == "think" else ("above", "right", "left")
        sides = [place for place in order if fits[place]] or ["below"]
        if self.kind != "think" and "above" in sides:
            side = "above"
        else:
            side = next((place for place in (*sides, *(["below"] if "below" not in sides else []))
                         if not self._covering(*spot(place), final_w, final_h)), sides[0])
        tx, ty = self._clear_spot(*spot(side), final_w, final_h, bounds=(gx, gy, gw, gh))
        self._spot = (tx, ty, final_w, final_h)
        return tx, ty, (round(cx - tx) if side in ("above", "below") else round(cy - ty), side)

    def _show_at(self, tx, ty):
        self._vx = self._vy = 0.0
        self._put(tx, ty)
        desktops.apply(self)  # before it shows: it opens on this desktop, it does not take you to its last one
        self.show()
        desktops.apply(self)

    def setVisible(self, visible: bool):
        if visible and not self.isVisible():
            mark_before_show(self)
        super().setVisible(visible)
        if not visible:
            drop_hidden(self)

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None:
            handle.setTransientParent(None)
        if not always_on_top():
            send_behind_windows(native_id(self))
        faces = getattr(self.face, "faces", None)
        if faces is not None:
            faces.raise_bubbles()
        else:
            self.raise_()

    def _final_size(self) -> tuple:
        """The window size once it has grown to its size."""
        if not self._geom or (self._growth is None and self.isVisible()):
            return self._card.width() or 80, self._card.height() or 48
        growth, self._growth = self._growth, None
        try:
            return (self._geom[1] + 2 * PAD_BODY + 2 * PAD_SVG,
                    self._body_h(self._geom[2]) + PAD_SVG + TAIL_ROOM)
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
              and QApplication.activeWindow() not in (self, self.face) and not self.engaged()):
            # Clicked into another window with nothing typed: the bubble goes, pinned or not. Clicking on its own
            # words or on the face is not leaving, and nor is focus taken away while the pointer is still here.
            self.face.unpin()
            self.close_bubble("focus_elsewhere")
            return
        tx, ty, tip = self._goal()
        was_yielding, self._yielding = self._yielding, self._must_yield()
        if self._yielding:
            # Out of the way of a bubble the user is busy with: it comes back when that one is gone.
            self.changed = now
            self._release_hold()
            self.hide()
            return
        if was_yielding:
            # There is room now: it opens the way a new bubble does, not with a jump.
            self._growth = self._opening_growth()
            self.setWindowOpacity(0.0)
            self._show_at(tx, ty)
            self._slide.start()
            return
        pointer = self.face.pointer_near(self)
        if pointer and self._held is not None and self._pointer_on_card():
            self._release_hold()  # on the card: the window can be the card again, the pointer stays inside
        # A bubble the pointer really was on goes the moment it leaves, a thinking cloud of a busy bot too.
        # Only a bubble kept up for another reason waits for its answer before it counts as seen.
        # No timer keeps a bubble the pointer has left: the hover margin (the transparent edge of the window,
        # BUBBLE_HOVER_MARGIN where the pointer is known everywhere) is the slack, and leaving it closes at once.
        if pointer or self.holding():
            self.changed = now
            self._was_near = self._was_near or bool(pointer) or not awaiting
            if pointer:
                self._near_at = now
        elif self._was_near:
            # The pointer left the bubble: close it straight away. A thinking cloud of a bot that is still busy
            # shrinks back to its dots instead, which go by themselves after a while.
            # Moving from the face onto its own bubble is already handled by
            # face.pointer_near(self) being true, which is caught above.
            if self.kind == "think" and self.face.shrink_think():
                self.changed = now
                self._was_near = False
                return
            if self.close_bubble("left"):
                return
        elif self.changed and now - self.changed > reading_seconds(self.full_text):
            # Nobody pointed at it and nothing new came: it goes away after a while.
            if self.close_bubble("unread"):
                return
        self._watch_arrow(now)
        if tip != self._tip:
            self._tip = tip
            self._layout_children(self._paint_chrome())
            tx, ty, _tip = self._goal()
        if self._growth is not None:
            return
        x, y = self._card_at.x(), self._card_at.y()
        self._vx = (self._vx + (tx - x) * 0.16) * 0.7
        self._vy = (self._vy + (ty - y) * 0.16) * 0.7
        nx, ny = x + self._vx, y + self._vy
        if abs(tx - nx) < 0.6 and abs(self._vx) < 0.35 and abs(ty - ny) < 0.6 and abs(self._vy) < 0.35:
            nx, ny, self._vx, self._vy = tx, ty, 0.0, 0.0
        self._put(nx, ny)

    # ── Open and closed: one state, one rule, one door out ─────────────
    #
    # The state is kind ("" is closed) plus _yielding; the window follows it, never the other way round:
    #   closed    kind == ""                      window hidden (and on X without a native window)
    #   open      kind set, not yielding          window shown
    #   yielding  kind set, yielding              window hidden, physics on, back when there is room
    # place(kind) is the only way in and place("") the only way out; _tick hides and shows for yielding.
    # Everything that wants a bubble gone calls close_bubble(reason). Reasons in CLOSE_UNLESS_ENGAGED happen by
    # themselves (time, a poll, focus elsewhere) and never take a bubble the pointer is engaged with; the others are
    # things the user did (Escape, another face, a drag) and close at once.

    CLOSE_UNLESS_ENGAGED = frozenset({"left", "unread", "empty", "focus_elsewhere", "quiet"})

    def state(self) -> str:
        if not self.kind:
            return "closed"
        return "yielding" if self._yielding else "open"

    def consistent(self) -> bool:
        """Does the window match the state?"""
        visible = self.isVisible()
        return {"closed": not visible, "open": visible and self._physics.isActive(),
                "yielding": not visible and self._physics.isActive()}[self.state()]

    def engaged(self) -> bool:
        """The one rule for the pointer being with this bubble: on the face, on the bubble or within its hover
        margin, or in the area a bigger bubble covered before a page change (see _hold_after). Words typed
        or selected count too."""
        return self.isVisible() and (bool(self.face.pointer_near(self)) or self.holding())

    def close_bubble(self, reason: str) -> bool:
        """Close the bubble, unless it closes by itself and the pointer is still engaged. True when it closed."""
        if not self.kind and not self.isVisible():
            return False
        if reason in self.CLOSE_UNLESS_ENGAGED and self.engaged():
            return False
        if reason in ("left", "unread"):
            self.face.pinned = False
        self.place("")
        return True

    def heal(self) -> bool:
        """Backstop: the bubble's state and its window disagree (open without a window, a window without being
        open, open without the physics that closes it). Close it for real, so pointing at the face or a
        right-click opens it again instead of the bot looking stuck. True when something was wrong."""
        if self.consistent():
            return False
        self.place("")
        return True

    def place(self, kind: str):
        """Show or hide the bubble. The face stays."""
        self._opened = (self._opened or time.monotonic()) if kind else 0.0
        if self.kind == "think" and kind != "think":
            self.face._think_quiet = True
        self.kind = kind
        if kind == "":
            self._release_hold()
            self._yielding = False
            self._slide.stop()
            self._growth = None
            self.setWindowOpacity(1.0)
            self._was_near = False
            self._near_at = 0.0
            self._had_focus = False
            self._wants_keys = False
            self._physics.stop()
            self._physics_on = False
            self._commands_forced = False
            self._show_commands([])
            self.hide()
            self._list_only = False
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
        self._yielding = self._must_yield()
        if self._yielding:
            self._slide.stop()
            self._growth = None
            self._commands_forced = False
            self._show_commands([])
            self._release_hold()
            self.hide()
        elif not self.isVisible():
            self._show_at(tx, ty)
        if not self._physics_on:
            self._physics_on = True
            self._physics.start()
