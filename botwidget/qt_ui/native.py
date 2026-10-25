"""The native window behind a widget."""


def native_id(widget) -> int:
    """The id of the window the system really shows.

    After setWindowFlags (always-on-top switched, a face that becomes an arc guest) Qt makes a new native
    window, but QWidget.winId() can keep answering with the old, destroyed one. Skip-taskbar, the layer and
    send-behind then went to a window that no longer exists: a taskbar entry per bot, a bubble above other
    apps while its face stayed behind them.
    """
    wid = widget.winId()  # makes the native window when there is none yet
    handle = widget.windowHandle()
    return int(handle.winId()) if handle is not None else int(wid)


def set_flags(widget, flags) -> None:
    """New window flags, with the native window made again at the next show.

    Qt would otherwise swap the native window only after the show, behind our back: skip-taskbar, the layer
    and send-behind all went to the old one, and winId() kept naming it.
    """
    created = widget.windowHandle() is not None
    widget.setWindowFlags(flags)
    if created:
        widget.destroy()


def drop_hidden(widget) -> None:
    """X: a window that was just hidden gives up its native window; the next show makes a new one.

    A bubble that opens and closes again before the window manager handled its map request is mapped anyway
    once the manager gets to it, after Qt's unmap: Qt calls it hidden, the X server shows an invisible window
    on top of the face. That ghost takes the pointer (no hover-open) and the clicks (no right-click menu)
    until the bot is restarted. A destroyed window cannot be mapped late.
    """
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.platformName() == "xcb" and widget.windowHandle() is not None and not widget.isVisible():
        widget.destroy()


def mapped(widget) -> bool:
    """Is the window really on screen yet? The window manager maps a shown window a moment later (5-20 ms
    measured on XWayland); until Qt gets its expose, the X server knows nothing of it under the pointer."""
    handle = widget.windowHandle()
    return handle is not None and handle.isExposed()
