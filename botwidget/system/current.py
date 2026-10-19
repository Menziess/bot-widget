"""Kiest de module van het huidige besturingssysteem.

Elke OS-module (linux, macos, windows) levert dezelfde functies; de rest van de
app importeert ze alleen hier en kent geen sys.platform. De imports zijn statisch,
zodat PyInstaller alle drie de modules ziet.
"""

import sys

if sys.platform == "win32":
    from botwidget.system import windows as _os
elif sys.platform == "darwin":
    from botwidget.system import macos as _os
else:
    from botwidget.system import linux as _os

data_home = _os.data_home
play_notification = _os.play_notification
prepare_gui_environment = _os.prepare_gui_environment
process_cmdline = _os.process_cmdline
send_behind_windows = _os.send_behind_windows
