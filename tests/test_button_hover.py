import unittest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

from botwidget.qt_ui.controls import ActionButton, ItemRow


class ButtonHover(unittest.TestCase):
    def test_a_button_lights_up_when_the_pointer_is_on_it_without_a_hover_event(self):
        app = QApplication.instance() or QApplication([])
        window = QWidget()
        window.resize(200, 100)
        button = ActionButton("Accept", window)
        button.setGeometry(10, 10, 100, 28)
        window.show()
        self.addCleanup(window.close)
        before = button.grab().toImage().pixelColor(50, 14).name()
        QCursor.setPos(button.mapToGlobal(QPoint(50, 14)))
        button._follow_pointer()
        app.processEvents()
        self.assertNotEqual(button.grab().toImage().pixelColor(50, 14).name(), before)
        QCursor.setPos(window.mapToGlobal(QPoint(190, 90)))
        button._follow_pointer()
        self.assertEqual(button.grab().toImage().pixelColor(50, 14).name(), before)

    def test_an_action_of_a_row_is_hovered_by_the_pointer_position_alone(self):
        app = QApplication.instance() or QApplication([])
        window = QWidget()
        window.resize(300, 60)
        row = ItemRow("Bot", True, "toggle", [{"label": "Edit", "command": "edit"}], window)
        row.setGeometry(0, 0, 300, 40)
        window.show()
        self.addCleanup(window.close)
        row._place()
        rect = row._hits[0][2]
        QCursor.setPos(row.mapToGlobal(rect.center().toPoint()))
        row._follow_pointer()
        self.assertEqual(row._hover, "edit")
        QCursor.setPos(row.mapToGlobal(QPoint(5, 20)))
        row._follow_pointer()
        self.assertIsNone(row._hover)


if __name__ == "__main__":
    unittest.main()
