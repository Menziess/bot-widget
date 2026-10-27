# Ensure tests always run in offscreen mode, even when the desktop session
# already exports QT_QPA_PLATFORM (setdefault would then be a no-op)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Tests that pretend to run on X11 must not call the real desktop functions of this system on an offscreen window.
from botwidget.qt_ui import desktops  # noqa: E402

desktops.set_desktops = lambda *args: None
desktops.is_shown_here = lambda *args: True
desktops.on_active_space = lambda *args: True
desktops.move_to_active_space = lambda *args: None
