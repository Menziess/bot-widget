"""Windows: no ps or /proc, sound through winsound."""

import os


def hide_from_dock() -> None:
    pass


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
