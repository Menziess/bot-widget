"""Real form elements for the menu pages: a switch with its label, and a button."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractButton, QPushButton, QWidget

from botwidget.qt_ui.text_doc import color
from botwidget.theme import BUBBLE_FONT, CONTROL_SWITCH_W, SAND_ACCENT, SAND_INK, SAND_INK_SOFT, SAND_SANS

TRACK_W, TRACK_H, KNOB_PAD = 34, 20, 2


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


class ActionButton(QPushButton):
    """A button for something that happens once: an update, a link, quitting."""

    STYLE = (f"QPushButton {{ background: #ffffff; color: {SAND_INK}; border: 1px solid rgba(28, 28, 28, 40);"
             f" border-radius: 8px; padding: 4px 12px; font-family: '{SAND_SANS}'; font-size: {BUBBLE_FONT}px; }}"
             f" QPushButton:hover {{ border-color: {SAND_ACCENT}; color: {SAND_ACCENT}; }}"
             f" QPushButton:pressed {{ background: rgba(11, 109, 211, 20); }}")

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setStyleSheet(self.STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)


class SlashList(QWidget):
    """The commands that fit what is typed after a slash, as a list that opens upward from the field."""

    ROW_H = 30
    chosen = Signal(str)

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

    def mouseMoveEvent(self, event):
        self.index = self._row_at(event.position().y())
        self.update()

    def mouseReleaseEvent(self, event):
        if self.rows:
            self.chosen.emit(self.rows[self._row_at(event.position().y())][0])

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(28, 28, 28, 46))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 10, 10)
        command_font = QFont(SAND_SANS)
        command_font.setPixelSize(BUBBLE_FONT)
        command_font.setBold(True)
        note_font = QFont(SAND_SANS)
        note_font.setPixelSize(BUBBLE_FONT - 1)
        for i, (command, note) in enumerate(self.rows):
            top = 4 + i * self.ROW_H
            if i == self.index:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(11, 109, 211, 26))
                painter.drawRoundedRect(QRectF(4, top, self.width() - 8, self.ROW_H), 7, 7)
            painter.setFont(command_font)
            painter.setPen(color(SAND_ACCENT))
            painter.drawText(QRectF(12, top, 104, self.ROW_H), Qt.AlignVCenter | Qt.AlignLeft, command)
            painter.setFont(note_font)
            painter.setPen(color(SAND_INK_SOFT))
            painter.drawText(QRectF(118, top, self.width() - 126, self.ROW_H), Qt.AlignVCenter | Qt.AlignLeft, note)
