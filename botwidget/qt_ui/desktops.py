"""Which desktops a window lives on; only a real window of the system has that to set."""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from botwidget.config import all_desktops
from botwidget.qt_ui.native import native_id
from botwidget.system.current import is_shown_here, move_to_active_space, on_active_space, set_desktops


def _real() -> bool:
    return QGuiApplication.platformName() in ("cocoa", "windows", "xcb", "wayland")


def apply(window) -> None:
    """A window that has travels = True (a bubble) opens on the desktop you are on; the others stay where they are."""
    if _real():
        set_desktops(native_id(window), all_desktops(), getattr(window, "travels", False))


def shown_here(window) -> bool:
    """Is a window that Qt calls visible really on the screen you are looking at?"""
    return not _real() or is_shown_here(native_id(window))


def bring_here(window) -> bool:
    """A window that Qt shows but macOS has on no desktop you are on comes to the one you are on; True when it had
    to move. A new desktop closing (a full-screen app) can leave windows opened afterwards on none, also with
    all_desktops on."""
    if not _real() or on_active_space(native_id(window)):
        return False
    move_to_active_space(native_id(window))
    QTimer.singleShot(500, lambda: apply(window))  # back to its own setting once it is here
    return True


def face_here(face) -> bool:
    """Is the face on the desktop you are looking at? A face that lives on one desktop has bubbles only there."""
    return not _real() or all_desktops() or on_active_space(native_id(face))

