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
