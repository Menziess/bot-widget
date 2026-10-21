"""Picks the module of the current operating system.

Every OS module (linux, macos, windows) provides the same functions; the rest of
the app imports them only here and knows no sys.platform. The imports are static,
so PyInstaller sees all three modules.
"""

import sys

if sys.platform == "win32":
    from botwidget.system import windows as _os
elif sys.platform == "darwin":
    from botwidget.system import macos as _os
else:
    from botwidget.system import linux as _os

HOTKEY_LABEL = _os.HOTKEY_LABEL
UPDATE_ASSET = _os.UPDATE_ASSET
activate_app = _os.activate_app
can_install_update = _os.can_install_update
data_home = _os.data_home
hide_from_dock = _os.hide_from_dock
install_update = _os.install_update
launch_at_login = _os.launch_at_login
play_notification = _os.play_notification
prepare_gui_environment = _os.prepare_gui_environment
process_cmdline = _os.process_cmdline
register_hotkey = _os.register_hotkey
send_behind_windows = _os.send_behind_windows
stable_app_command = _os.stable_app_command
set_launch_at_login = _os.set_launch_at_login
