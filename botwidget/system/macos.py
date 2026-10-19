"""macOS: ps for processes, afplay for sound.

The face stays below normal windows, through the system's window level.
"""

import ctypes
import ctypes.util
import os
import platform
import plistlib
import shlex
import sys

from botwidget.system import posix

SOUND_FILE = "/System/Library/Sounds/Glass.aiff"
BUNDLE_ID = "com.bot-widget.app"
DEV_LAUNCHER_NAME = "Bot Widget (dev)"
SM_ENABLED = 1  # SMAppServiceStatusEnabled
DESKTOP_ICON_LEVEL_KEY = 18  # kCGDesktopIconWindowLevelKey
CAN_JOIN_ALL_SPACES = 1 << 0
STATIONARY = 1 << 4

process_cmdline = posix.process_cmdline


def prepare_gui_environment() -> None:
    pass


def play_notification() -> None:
    posix.spawn_first((["afplay", SOUND_FILE],))


def data_home() -> str:
    return os.path.expanduser("~/Library/Application Support")


def _objc():
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc


def send_behind_windows(win_id: int) -> None:
    """Just above the desktop icons and below all normal windows, on every desktop.

    Qt's StaysOnBottomHint is ignored here: tool windows get the level of floating
    windows. Via the Objective-C runtime, so no extra package is needed.
    """
    objc = _objc()
    cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
    cg.CGWindowLevelForKey.restype = ctypes.c_int32
    cg.CGWindowLevelForKey.argtypes = [ctypes.c_int32]
    level = cg.CGWindowLevelForKey(DESKTOP_ICON_LEVEL_KEY) + 1

    window = _send(objc, ctypes.c_void_p)(win_id, objc.sel_registerName(b"window"))
    _send(objc, None, ctypes.c_long)(window, objc.sel_registerName(b"setLevel:"), level)
    behavior = CAN_JOIN_ALL_SPACES | STATIONARY
    _send(objc, None, ctypes.c_ulong)(window, objc.sel_registerName(b"setCollectionBehavior:"), behavior)


def _launch_agent() -> str:
    return os.path.expanduser("~/Library/LaunchAgents/com.bot-widget.app.plist")


def _dev_launcher() -> str:
    return os.path.join(data_home(), "botwidget", DEV_LAUNCHER_NAME)


def _send(objc, restype, *argtypes):
    """objc_msgSend with the right types for one call."""
    proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
    return proto(("objc_msgSend", objc))


def _login_service():
    """This app's SMAppService (macOS 13+), or None.

    Outside an .app it does not exist: then "this app" is the Python that runs us.
    """
    if not _bundle_path():
        return None
    objc = _objc()
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ServiceManagement.framework/ServiceManagement")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    cls = objc.objc_getClass(b"SMAppService")
    if not cls:
        return None
    return _send(objc, ctypes.c_void_p)(cls, objc.sel_registerName(b"mainAppService"))


def _remove_launch_agent():
    for path in (_launch_agent(), _dev_launcher()):
        if os.path.exists(path):
            os.remove(path)


def launch_at_login() -> bool:
    service = _login_service()
    if service:
        # A switch turned off in System Settings is also right here: the status is different then.
        return _send(_objc(), ctypes.c_long)(service, _objc().sel_registerName(b"status")) == SM_ENABLED
    return os.path.exists(_launch_agent())


def set_launch_at_login(command: list, on: bool) -> None:
    """The app as a login item, with its own name and icon in System Settings.

    As plain Python (development) that is a user LaunchAgent, through a small script
    with its own name so it does not show up as "python" in the list.
    """
    service = _login_service()
    if service:
        objc = _objc()
        selector = b"registerAndReturnError:" if on else b"unregisterAndReturnError:"
        _send(objc, ctypes.c_bool, ctypes.c_void_p)(service, objc.sel_registerName(selector), None)
        _remove_launch_agent()  # an old LaunchAgent is no longer needed
        return
    if not on:
        _remove_launch_agent()
        return
    launcher = _dev_launcher()
    os.makedirs(os.path.dirname(launcher), exist_ok=True)
    with open(launcher, "w") as fh:
        fh.write("#!/bin/sh\nexec " + shlex.join(command) + "\n")
    os.chmod(launcher, 0o755)
    os.makedirs(os.path.dirname(_launch_agent()), exist_ok=True)
    with open(_launch_agent(), "wb") as fh:
        plistlib.dump({"Label": BUNDLE_ID, "ProgramArguments": [launcher], "RunAtLoad": True}, fh)


UPDATE_ASSET = "BotWidget-macOS.zip"

# Wait until the widget is gone, swap the app and start it again. Unpack first, only then swap: that
# takes a moment, and on an error the old app stays in place.
_SWAP_SCRIPT = """#!/bin/sh
zip="$1"; bundle="$2"; pid="$3"
work="$(mktemp -d "$(dirname "$bundle")/.botwidget-update.XXXXXX")" || exit 1
ditto -x -k "$zip" "$work" || { rm -rf "$work"; exit 1; }
new="$work/Bot Widget.app"
[ -d "$new" ] || { rm -rf "$work"; exit 1; }
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
if ! mv "$bundle" "$work/old.app" || ! mv "$new" "$bundle"; then
  [ -d "$work/old.app" ] && mv "$work/old.app" "$bundle"
  rm -rf "$work"; exit 1
fi
xattr -dr com.apple.quarantine "$bundle" 2>/dev/null
rm -rf "$work"
[ -n "$BOTWIDGET_NO_RELAUNCH" ] || open "$bundle"
"""


def _bundle_path() -> str | None:
    """The .app this widget runs from, or None if that is not an app."""
    bundle = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
    return bundle if getattr(sys, "frozen", False) and bundle.endswith(".app") else None


def can_install_update() -> bool:
    """Only the packaged app on Apple Silicon, in a place where we may write."""
    bundle = _bundle_path()
    return bool(bundle) and platform.machine() == "arm64" and os.access(os.path.dirname(bundle), os.W_OK)


def apply_bundle_update(archive: str, bundle: str, pid: int) -> None:
    posix.spawn_script(_SWAP_SCRIPT, archive, bundle, str(pid))


def install_update(archive: str) -> bool:
    """Start the swap; True if the widget should quit now."""
    bundle = _bundle_path()
    if not bundle:
        return False
    apply_bundle_update(archive, bundle, os.getpid())
    return True


def stable_app_command() -> list | None:
    """This is how you start the installed app; arguments for the app come after it."""
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        bundle = os.path.join(base, "Bot Widget.app")
        if os.path.isdir(bundle):
            return ["open", bundle, "--args"]
    return None
