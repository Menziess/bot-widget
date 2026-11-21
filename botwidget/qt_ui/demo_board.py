"""Checklist window for the --dev demo. It only shows rows a verifier has written."""

import json
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from botwidget.qt_ui.native import set_flags

BOARD = os.environ.get("BOTWIDGET_DEMO_BOARD") or "/tmp/t-demo/checklist.json"


def demo_wanted() -> bool:
    root = os.environ.get("BOTWIDGET_DEMO_ROOT") or "/tmp/t-demo"
    return "--demo" in sys.argv[1:] or os.path.exists(os.path.join(root, "enable"))


class DemoBoard(QWidget):
    """A tool window, same as the face: no taskbar button."""

    def __init__(self):
        super().__init__()
        set_flags(self, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("botwidget demo")
        self._label = QLabel("demo")
        self._label.setWordWrap(True)
        self._label.setMargin(12)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        self.resize(460, 240)
        self.move(48, 48)
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(400)
        self.refresh()
        self.show()

    def refresh(self) -> None:
        try:
            with open(BOARD, encoding="utf-8") as fh:
                tasks = json.load(fh).get("tasks") or []
        except (OSError, ValueError):
            tasks = []
        if not tasks:
            self._label.setText("Demo checklist\nwaiting")
            return
        lines = ["Demo checklist"]
        for row in tasks:
            mark = "x" if row.get("ticked") else " "
            lines.append(f"[{mark}] {row.get('label')}: {row.get('detail') or ''}")
        self._label.setText("\n".join(lines))
