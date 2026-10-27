"""Windows: no ps or /proc, sound through winsound."""

import ctypes
import os
import sys


HOTKEY_LABEL = ""
CAN_PICK_DESKTOPS = False
# Windows only flashes the taskbar for a window that takes focus without a click.
FOCUS_ON_HOVER = False
# A face is a tool window: no taskbar button. (Linux keeps a normal window, see linux.FACE_IS_TOOL.)
FACE_IS_TOOL = True

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000


def _user32():
    if sys.platform != "win32":
        return None
    try:
        return ctypes.WinDLL("user32", use_last_error=True)
    except (AttributeError, OSError):
        return None


def hide_from_taskbar(win_id: int, user32=None) -> None:
    """No taskbar button: tool window on, app window off. Qt.Tool asks for the same; this holds also when Qt
    made the native window again."""
    user32 = user32 if user32 is not None else _user32()
    if user32 is None or not win_id:
        return
    get = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    put = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    get.restype = put.restype = ctypes.c_ssize_t
    get.argtypes = [ctypes.c_void_p, ctypes.c_int]
    put.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    style = get(ctypes.c_void_p(int(win_id)), GWL_EXSTYLE)
    wanted = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if wanted != style:
        put(ctypes.c_void_p(int(win_id)), GWL_EXSTYLE, wanted)


def set_desktops(win_id: int, everywhere: bool, travels: bool = False) -> None:
    pass


CAN_BLUR = False


def set_backdrop(win_id: int, x: float, y: float, w: float, h: float, mask_png: bytes) -> bool:
    """No blur behind a window here."""
    return False


def clear_backdrop(win_id: int) -> None:
    pass


def on_active_space(win_id: int) -> bool:
    return True


def is_shown_here(win_id: int) -> bool:
    return True


def move_to_active_space(win_id: int) -> None:
    pass


def activate_app() -> None:
    pass


def hide_from_dock() -> None:
    pass


def register_hotkey(callback) -> bool:
    """No global key combination here yet."""
    return False


def prepare_gui_environment() -> None:
    pass


def process_cmdline(pid: int) -> bytes:
    # Not readable yet; the single-instance check then skips stopping.
    return b""


def play_notification() -> None:
    import winsound
    winsound.MessageBeep()


def data_home() -> str:
    return os.environ.get("APPDATA") or os.path.expanduser("~")


def before_show(win_id: int, layer: str = "") -> None:
    """Right before a window of ours is shown: no taskbar button for it."""
    hide_from_taskbar(win_id)


def pointer_window() -> int | None:
    """Only needed under XWayland; here the pointer position is known."""
    return None


def send_behind_windows(win_id: int) -> None:
    # Qt puts the window at the bottom itself (HWND_BOTTOM).
    pass


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_at_login() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "BotWidget")
    except OSError:
        return False
    return True


def set_launch_at_login(command: list, on: bool) -> None:
    """A value under Run in the user's registry."""
    import subprocess
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, "BotWidget", 0, winreg.REG_SZ, subprocess.list2cmdline(command))
        else:
            try:
                winreg.DeleteValue(key, "BotWidget")
            except OSError:
                pass


UPDATE_ASSET = "BotWidget-Windows-Setup.exe"


def can_install_update() -> bool:
    import sys
    return getattr(sys, "frozen", False)


def install_update(installer: str) -> bool:
    """The installer closes the running widget itself and starts it again afterwards."""
    import subprocess
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], creationflags=detached)
    return True


def stable_app_command() -> list | None:
    import os
    path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Bot Widget", "Bot Widget.exe")
    return [path] if os.path.exists(path) else None
