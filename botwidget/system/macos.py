"""macOS: ps voor processen, afplay voor geluid.

Het gezicht blijft onder gewone vensters, via het vensterniveau van het systeem.
"""

import ctypes
import ctypes.util
import os
import platform
import plistlib
import sys

from botwidget.system import posix

SOUND_FILE = "/System/Library/Sounds/Glass.aiff"
BUNDLE_ID = "com.bot-widget.app"
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
    """Net boven de bureaubladiconen en onder alle gewone vensters, op elk bureaublad.

    Qt's StaysOnBottomHint wordt hier genegeerd: tool-vensters krijgen het niveau
    van zwevende vensters. Via de Objective-C runtime, dus zonder extra pakket.
    """
    objc = _objc()
    cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
    cg.CGWindowLevelForKey.restype = ctypes.c_int32
    cg.CGWindowLevelForKey.argtypes = [ctypes.c_int32]
    level = cg.CGWindowLevelForKey(DESKTOP_ICON_LEVEL_KEY) + 1

    def send(restype, *argtypes):
        proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
        return proto(("objc_msgSend", objc))

    window = send(ctypes.c_void_p)(win_id, objc.sel_registerName(b"window"))
    send(None, ctypes.c_long)(window, objc.sel_registerName(b"setLevel:"), level)
    behavior = CAN_JOIN_ALL_SPACES | STATIONARY
    send(None, ctypes.c_ulong)(window, objc.sel_registerName(b"setCollectionBehavior:"), behavior)


def _launch_agent() -> str:
    return os.path.expanduser("~/Library/LaunchAgents/com.bot-widget.app.plist")


def launch_at_login() -> bool:
    return os.path.exists(_launch_agent())


def set_launch_at_login(command: list, on: bool) -> None:
    """Een LaunchAgent van de gebruiker; launchd leest hem bij de volgende aanmelding."""
    path = _launch_agent()
    if not on:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump({"Label": BUNDLE_ID, "ProgramArguments": command, "RunAtLoad": True,
                       # Zo toont macOS de app met naam en icoon in plaats van "python".
                       "AssociatedBundleIdentifiers": [BUNDLE_ID]}, fh)


UPDATE_ASSET = "BotWidget-macOS.zip"

# Wacht tot de widget weg is, wissel de app om en start hem opnieuw. Eerst uitpakken,
# dan pas wisselen: dat duurt een ogenblik en bij een fout blijft de oude app staan.
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
    """De .app waar deze widget uit draait, of None als dat geen app is."""
    bundle = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
    return bundle if getattr(sys, "frozen", False) and bundle.endswith(".app") else None


def can_install_update() -> bool:
    """Alleen de gebundelde app op Apple Silicon, op een plek waar we mogen schrijven."""
    bundle = _bundle_path()
    return bool(bundle) and platform.machine() == "arm64" and os.access(os.path.dirname(bundle), os.W_OK)


def apply_bundle_update(archive: str, bundle: str, pid: int) -> None:
    posix.spawn_script(_SWAP_SCRIPT, archive, bundle, str(pid))


def install_update(archive: str) -> bool:
    """Start de wissel; True als de widget nu moet afsluiten."""
    bundle = _bundle_path()
    if not bundle:
        return False
    apply_bundle_update(archive, bundle, os.getpid())
    return True
