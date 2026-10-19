"""Windows: geen ps of /proc, geluid via winsound."""

import os


def prepare_gui_environment() -> None:
    pass


def process_cmdline(pid: int) -> bytes:
    # Nog niet te lezen; de single-instance check slaat het stoppen dan over.
    return b""


def play_notification() -> None:
    import winsound
    winsound.MessageBeep()


def data_home() -> str:
    return os.environ.get("APPDATA") or os.path.expanduser("~")


def send_behind_windows(win_id: int) -> None:
    # Qt zet het venster zelf onderaan (HWND_BOTTOM).
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
    """Een waarde onder Run in het register van de gebruiker."""
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
