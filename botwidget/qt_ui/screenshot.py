"""Screenshot mode overlay.

Double-click a face → that face aims big eyes at the mouse → a fullscreen overlay
lets the user drag a rectangle → all faces are hidden for the grab → the selected
region is captured → the face receives it as an attachment.

Escape or right-click on the overlay cancels.
"""

from PySide6.QtCore import QPoint, QBuffer, QByteArray, QRect, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from botwidget.avatar import AVATAR_SIZE, eye_aim


def pixmap_png_bytes(pixmap: QPixmap) -> bytes | None:
    """Encode a QPixmap as PNG bytes. Returns None on failure."""
    image = pixmap.toImage()
    if image.isNull():
        return None
    buffer = QByteArray()
    qbuf = QBuffer(buffer)
    qbuf.open(QBuffer.WriteOnly)
    if not image.save(qbuf, "PNG"):
        qbuf.close()
        return None
    qbuf.close()
    return bytes(buffer.data())


class ScreenshotOverlay(QWidget):
    """Fullscreen transparent overlay: drag to select, Escape/right-click to cancel."""

    def __init__(self, target_face):
        super().__init__()
        self.target_face = target_face
        self._start = None
        self._rect = None
        self._mouse_down = False
        self._done_callback = None  # (rect) → None  or  None (cancel)
        self._cancel_callback = None

        # Full-screen, topmost, translucent background.
        # No WindowTransparentForInput so mouse events reach us.
        # No WindowDoesNotAcceptFocus so Escape works.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self._apply_flags()
        self._position()
        self.show()
        self.activateWindow()
        self.raise_()

    def _apply_flags(self):
        """Reapply flags after the base class set them."""
        flags = (
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setWindowFlags(flags)

    def _position(self):
        """Cover the entire virtual desktop."""
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.raise_()

    def grab_region(self) -> "QtGui.QPixmap | None":
        """Grab the selected rectangle from the screen. Returns None on cancel."""
        if self._rect is None:
            return None
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.grabWindow(0, *self._rect)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Dim the background
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))
        if self._rect is not None:
            painter.setPen(QPen(QColor(255, 255, 255, 220), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(*self._rect))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._cancel()
            return
        if event.button() != Qt.LeftButton:
            return
        self._mouse_down = True
        self._start = (int(event.position().x()), int(event.position().y()))
        self._rect = None

    def mouseMoveEvent(self, event):
        if not self._mouse_down or self._start is None:
            return
        gx, gy = int(event.position().x()), int(event.position().y())
        x = min(self._start[0], gx)
        y = min(self._start[1], gy)
        w = abs(gx - self._start[0])
        h = abs(gy - self._start[1])
        self._rect = (x, y, w, h)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._mouse_down = False
        if self._rect is not None and self._rect[2] > 2 and self._rect[3] > 2:
            self._done(self._rect)
        else:
            # Too small to be intentional: treat as cancel
            self._cancel()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def _done(self, rect):
        """User released: hide faces, grab, then restore."""
        from botwidget.qt_ui.screenshot import _restore_faces

        # Hide the overlay itself (so it's not in the shot) and all faces.
        self.hide()
        all_faces = list(getattr(self.target_face.faces, "faces", {}).values())
        for f in all_faces:
            f.hide()
        self.target_face.hide()
        QApplication.processEvents()

        pixmap = self.grab_region()
        if self._done_callback is not None and pixmap is not None:
            self._done_callback(rect, pixmap)
        else:
            # No pixmap or callback: restore faces and cancel
            _restore_faces(all_faces)
            self.target_face.show()
            if self._cancel_callback is not None:
                self._cancel_callback()
        self.close()

    def _cancel(self):
        """User cancelled: close overlay and call the cancel callback."""
        self.close()
        if self._cancel_callback is not None:
            self._cancel_callback()

    def set_done_callback(self, callback):
        self._done_callback = callback

    def set_cancel_callback(self, callback):
        self._cancel_callback = callback


def screen_grab(rect):
    """Grab a screen region. Wraps QScreen.grabWindow for test injection."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    return screen.grabWindow(0, *rect)


def enter_screenshot_mode(face):
    """Enter screenshot mode for *face*. Returns the overlay."""
    from botwidget.qt_ui.screenshot import ScreenshotOverlay

    face.screenshot_face = face
    face._screenshot_active = True

    overlay = ScreenshotOverlay(face)

    all_faces = list(getattr(face.faces, "faces", {}).values())
    all_faces.append(face)

    def on_done(rect, pixmap):
        try:
            _finalize_screenshot(face, all_faces, rect, pixmap)
        finally:
            _cleanup_screenshot_mode(face)

    def on_cancel():
        _restore_faces(all_faces)
        _cleanup_screenshot_mode(face)

    overlay.set_done_callback(on_done)
    overlay.set_cancel_callback(on_cancel)
    face._screenshot_overlay = overlay
    return overlay


def _finalize_screenshot(face, all_faces, rect, pixmap):
    """Store the screenshot and send it to the face. Then restore faces."""
    try:
        _restore_faces(all_faces)
        from botwidget import attachments

        png_bytes = pixmap_png_bytes(pixmap)
        if png_bytes is None:
            # Capture failed — restore already happened above; just clean up.
            return
        path = attachments.store_bytes("screenshot.png", png_bytes)
        face.on_user_message("Screenshot", files=[path])
    finally:
        _cleanup_screenshot_mode(face)


def _restore_faces(all_faces):
    """Show every face that was hidden for the grab."""
    for f in all_faces:
        f.show()
        f.update()


def _cleanup_screenshot_mode(face):
    """Clear all screenshot-mode state from the face."""
    face.screenshot_face = None
    face._screenshot_active = False
    overlay = getattr(face, "_screenshot_overlay", None)
    if overlay is not None:
        face._screenshot_overlay = None
        overlay.close()
    QTimer.singleShot(0, face._render)
