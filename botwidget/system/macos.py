"""macOS: ps voor processen, afplay voor geluid.

Het gezicht blijft onder gewone vensters, via het vensterniveau van het systeem.
"""

import ctypes
import ctypes.util
import os
import plistlib

from botwidget.system import posix

SOUND_FILE = "/System/Library/Sounds/Glass.aiff"
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
        plistlib.dump({"Label": "com.bot-widget.app", "ProgramArguments": command, "RunAtLoad": True}, fh)
