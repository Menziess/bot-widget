"""Real form elements for the menu pages: a switch with its label, and a button."""

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QWidget

from botwidget.qt_ui.text_doc import color
from botwidget.theme import BUBBLE_FONT, CONTROL_SWITCH_W, SAND_ACCENT, SAND_INK, SAND_INK_SOFT, SAND_SANS

TRACK_W, TRACK_H, KNOB_PAD = 34, 20, 2


class PointerWatch:
    """Qt sends no hover to a window of an app that is not in front, which is the normal state of this widget, so
    the pointer is looked up while the control shows. A control gives _pointer_moved: where the pointer is on it, or
    None."""

    def _watch_pointer(self):
        self._watch = QTimer(self)
        self._watch.setInterval(50)
        self._watch.timeout.connect(self._follow_pointer)

    def _follow_pointer(self):
        point = self.mapFromGlobal(QCursor.pos())
        on = self.rect().contains(point) and self.window().isVisible()
        self._pointer_moved(point if on else None)

    def showEvent(self, event):
        super().showEvent(event)
        self._watch.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._watch.stop()


class Switch(QAbstractButton):
    """An on/off switch with its label next to it; the whole row can be clicked."""

    def __init__(self, label: str, on: bool, parent=None):
        super().__init__(parent)
        self.setText(label)
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        top = (self.height() - TRACK_H) / 2
        track = QRectF(0, top, TRACK_W, TRACK_H)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color(SAND_ACCENT) if self.isChecked() else QColor(28, 28, 28, 64))
        painter.drawRoundedRect(track, TRACK_H / 2, TRACK_H / 2)
        knob = TRACK_H - 2 * KNOB_PAD
        x = TRACK_W - KNOB_PAD - knob if self.isChecked() else KNOB_PAD
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, top + KNOB_PAD, knob, knob))
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        painter.setFont(font)
        painter.setPen(color(SAND_INK))
        painter.drawText(QRectF(CONTROL_SWITCH_W, 0, self.width() - CONTROL_SWITCH_W, self.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self.text())


class ItemRow(PointerWatch, QWidget):
    """One bot or one connection: its switch, its name, and only the actions that belong to it."""

    chosen = Signal(str)

    def __init__(self, title: str, on: bool, toggle: str, actions: list, parent=None):
        super().__init__(parent)
        self._title = title
        self._on = bool(on)
        self._toggle = toggle
        self._actions = [(str(action["label"]), str(action["command"])) for action in actions]
        self._hits: list[tuple[str, str, QRectF]] = []
        self._title_w = 0
        self._hover: str | None = None
        self._watch_pointer()
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self):
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        metrics = QFontMetrics(font)
        x = float(self.width())
        hits = []
        for label, command in reversed(self._actions):
            width = metrics.horizontalAdvance(label) + 28
            x -= width
            hits.append((label, command, QRectF(x, (self.height() - 28) / 2, width - 6, 28)))
            x -= 4
        hits.reverse()
        self._hits = hits
        self._title_w = max(0, x - CONTROL_SWITCH_W - 8)

    def mousePressEvent(self, event):
        # Painted above the text. A press this row ignores never comes back as a release.
        if event.button() == Qt.LeftButton:
            event.accept()
        else:
            event.ignore()

    def _pointer_moved(self, point):
        self._follow(None if point is None else point.x())

    def mouseMoveEvent(self, event):
        self._follow(event.position().x())

    def leaveEvent(self, event):
        self._follow(None)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.press_at(event.position().x())

    def _command_at(self, x: float) -> str | None:
        if self._actions and not self._hits:
            self._place()
        for _label, command, rect in self._hits:
            if rect.left() <= x <= rect.right():
                return command
        return None

    def _follow(self, x: float | None):
        hover = None if x is None else self._command_at(x)
        if hover != self._hover:
            self._hover = hover
            self.update()

    def press_at(self, x: float):
        """x is in this row: its own click, or one the text still forwards."""
        command = self._command_at(x)
        self.chosen.emit(self._toggle if command is None else command)

    def paintEvent(self, _event):
        if self._actions and not self._hits:
            self._place()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        top = (self.height() - TRACK_H) / 2
        track = QRectF(0, top, TRACK_W, TRACK_H)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color(SAND_ACCENT) if self._on else QColor(28, 28, 28, 64))
        painter.drawRoundedRect(track, TRACK_H / 2, TRACK_H / 2)
        knob = TRACK_H - 2 * KNOB_PAD
        knob_x = TRACK_W - KNOB_PAD - knob if self._on else KNOB_PAD
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, top + KNOB_PAD, knob, knob))
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        painter.setFont(font)
        painter.setPen(color(SAND_INK))
        title = QFontMetrics(font).elidedText(self._title, Qt.ElideRight, max(1, int(self._title_w)))
        painter.drawText(QRectF(CONTROL_SWITCH_W, 0, max(1, self._title_w), self.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, title)
        for label, command, rect in self._hits:
            # "Again" is the second click that really removes; "Unmute" means the bot is muted.
            marked = label in ("Again", "Unmute")
            # Drawn by hand, so the stylesheet hover of a normal button does not apply here.
            hovered = command == self._hover and not marked
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(11, 109, 211, 26) if hovered else
                             color(SAND_ACCENT) if marked else QColor(28, 28, 28, 14))
            painter.drawRoundedRect(rect, 14, 14)
            painter.setPen(color(SAND_ACCENT) if hovered else QColor("#ffffff") if marked else color(SAND_INK))
            painter.drawText(rect, Qt.AlignCenter, label)


class ActionButton(PointerWatch, QPushButton):
    """A button for something that happens once: an update, a link, quitting."""

    # A soft pill like the track of a switch. No min-height or tall padding: the page reserves one line
    # (CONTROL_H) for it, and a taller button spilled over the switch below.
    STYLE = (f"QPushButton {{ background: rgba(28, 28, 28, 14); color: {SAND_INK}; border: none;"
             f" border-radius: 14px; padding: 0px 14px; min-height: 0px; font-family: '{SAND_SANS}';"
             f" font-size: {BUBBLE_FONT}px; }}"
             f" QPushButton[hot=\"true\"] {{ background: rgba(11, 109, 211, 26); color: {SAND_ACCENT}; }}"
             f" QPushButton:pressed {{ background: rgba(11, 109, 211, 46); }}")

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setStyleSheet(self.STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._watch_pointer()

    def _pointer_moved(self, point):
        hot = point is not None
        if hot != self.property("hot"):
            self.setProperty("hot", hot)
            self.style().unpolish(self)
            self.style().polish(self)


class SlashList(QWidget):
    """The commands that fit what is typed after a slash, as a list that opens upward from the field."""

    ROW_H = 36
    chosen = Signal(str)
    wheeled = Signal(float, bool, bool)  # pixels scrolled (up is positive), coasting, a finger on the pad

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.index = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def height_for(self, count: int) -> int:
        return count * self.ROW_H + 8

    def show_rows(self, rows: list, index: int = 0):
        self.rows, self.index = rows, min(index, max(0, len(rows) - 1))
        self.setVisible(bool(rows))
        self.update()

    def move_selection(self, step: int):
        if self.rows:
            self.index = (self.index + step) % len(self.rows)
            self.update()

    def current(self) -> str:
        return self.rows[self.index][0] if self.rows else ""

    def _row_at(self, y: float) -> int:
        return min(max(int((y - 4) // self.ROW_H), 0), max(0, len(self.rows) - 1))

    def wheelEvent(self, event):
        phase = event.phase()
        pixels = event.pixelDelta().y() or event.angleDelta().y() / 120 * 40  # one notch, as in the bubble
        self.wheeled.emit(float(pixels), phase == Qt.ScrollMomentum, phase in (Qt.ScrollBegin, Qt.ScrollUpdate))
        event.accept()

    def mouseMoveEvent(self, event):
        self.index = self._row_at(event.position().y())
        self.update()

    def mouseReleaseEvent(self, event):
        if self.rows:
            self.chosen.emit(self.rows[self._row_at(event.position().y())][0])

    PAD_X = 12  # text inset; the highlight runs 4px from the edge
    GAP = 14  # between a command and its note

    @staticmethod
    def _fonts() -> tuple:
        command_font = QFont(SAND_SANS)
        command_font.setPixelSize(BUBBLE_FONT)
        command_font.setBold(True)
        note_font = QFont(SAND_SANS)
        note_font.setPixelSize(BUBBLE_FONT - 1)
        return command_font, note_font

    def command_w(self) -> int:
        """The command column fits the longest command, so /connections is not cut."""
        command_font, _note_font = self._fonts()
        metrics = QFontMetrics(command_font)
        return max((metrics.horizontalAdvance(command) for command, _note in self.rows), default=0) + self.GAP

    def wanted_width(self) -> int:
        """Wide enough for every command and its whole note."""
        _command_font, note_font = self._fonts()
        notes = QFontMetrics(note_font)
        widest = max((notes.horizontalAdvance(note) for _command, note in self.rows), default=0)
        return 2 * self.PAD_X + self.command_w() + widest

    def paintEvent(self, _event):
        """Flat rows on the bubble's own white: the bubble is the only outline."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        command_font, note_font = self._fonts()
        command_w = self.command_w()
        note_x = self.PAD_X + command_w
        notes = QFontMetrics(note_font)
        for i, (command, note) in enumerate(self.rows):
            top = 4 + i * self.ROW_H
            if i == self.index:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(11, 109, 211, 26))
                painter.drawRoundedRect(QRectF(4, top, self.width() - 8, self.ROW_H), 7, 7)
            painter.setFont(command_font)
            painter.setPen(color(SAND_ACCENT))
            painter.drawText(QRectF(self.PAD_X, top, command_w, self.ROW_H), Qt.AlignVCenter | Qt.AlignLeft, command)
            painter.setFont(note_font)
            painter.setPen(color(SAND_INK_SOFT))
            room = max(0, self.width() - note_x - self.PAD_X)
            painter.drawText(QRectF(note_x, top, room, self.ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                             notes.elidedText(note, Qt.ElideRight, room))


class ValueSlider(QWidget):
    """A label with a slider from 0 to 100 next to it; changed says the value at every step."""

    changed = Signal(int)
    STYLE = (f"QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: rgba(28, 28, 28, 38); }}"
             f" QSlider::sub-page:horizontal {{ background: {SAND_ACCENT}; border-radius: 2px; }}"
             f" QSlider::handle:horizontal {{ background: #ffffff; border: 1px solid rgba(28, 28, 28, 56);"
             f" width: 16px; height: 16px; margin: -7px 0; border-radius: 9px; }}")

    def __init__(self, label: str, value: int, parent=None):
        super().__init__(parent)
        self._label = label
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(value))
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setStyleSheet(self.STYLE)
        self.slider.valueChanged.connect(self.changed.emit)

    def resizeEvent(self, _event):
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        label_w = QFontMetrics(font).horizontalAdvance(self._label)
        self.slider.setGeometry(label_w + 14, 0, max(40, self.width() - label_w - 14), self.height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        painter.setFont(font)
        painter.setPen(color(SAND_INK))
        painter.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._label)


FIELD_STYLE = (f"QLineEdit, QPlainTextEdit {{ background: rgba(28, 28, 28, 14); color: {SAND_INK}; border: none;"
               f" border-radius: 8px; padding: 0px 8px; font-family: '{SAND_SANS}'; font-size: {BUBBLE_FONT}px; }}")


class TextField(QWidget):
    """A labelled line. The page reads it when you save, so a click on Save still sees the last letter."""

    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.command = ""
        self.edit = QLineEdit(value, self)
        self.edit.setStyleSheet(FIELD_STYLE)
        self.edit.setFocusPolicy(Qt.StrongFocus)
        self._initial = value

    def text_value(self) -> str:
        return self.edit.text()

    def in_use(self) -> bool:
        """Changed, or being typed in: the page around it must not go away."""
        return self.edit.hasFocus() or self.edit.text() != self._initial

    def resizeEvent(self, _event):
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        label_w = QFontMetrics(font).horizontalAdvance(self._label)
        self.edit.setGeometry(label_w + 14, 4, max(40, self.width() - label_w - 14), max(16, self.height() - 8))

    def paintEvent(self, _event):
        painter = QPainter(self)
        font = QFont(SAND_SANS)
        font.setPixelSize(BUBBLE_FONT)
        painter.setFont(font)
        painter.setPen(color(SAND_INK))
        painter.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._label)


class TextEditor(QPlainTextEdit):
    """The widget.json text. Taller than one row; the page reads it on Save."""

    def __init__(self, value: str, parent=None):
        super().__init__(value, parent)
        self.command = "editor"
        self.setStyleSheet(FIELD_STYLE)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setTabChangesFocus(True)
        self._initial = value

    def text_value(self) -> str:
        return self.toPlainText()

    def in_use(self) -> bool:
        return self.hasFocus() or self.toPlainText() != self._initial
