# Ensure tests always run in offscreen mode, even when the desktop session
# already exports QT_QPA_PLATFORM (setdefault would then be a no-op)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Nothing in a test may reach the real desktop of the person running it: bringing the app to the front took the
# keyboard away from whatever they were typing in, and a notification played a sound.
from botwidget.system import current as _current  # noqa: E402

for _name in ("activate_app", "play_notification", "hide_from_dock"):
    setattr(_current, _name, lambda *args, **kwargs: None)
    setattr(_current._os, _name, lambda *args, **kwargs: None)

# Tests that pretend to run on X11 must not call the real desktop functions of this system on an offscreen window.
from botwidget.qt_ui import desktops  # noqa: E402

desktops.set_desktops = lambda *args: None
desktops.is_shown_here = lambda *args: True
desktops.on_active_space = lambda *args: True
desktops.move_to_active_space = lambda *args: None
