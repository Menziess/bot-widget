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
