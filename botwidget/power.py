"""When to save power: on battery or in the low power mode of the system, if the setting asks for it. Fewer
frames, longer rests."""

import os
import re
import subprocess
import sys
import time

from botwidget.config import save_battery

CHECK_EVERY_S = 30.0
REDUCED_FRAME_MS = 66  # about 15 frames a second for what plays by itself
_seen = [-1e9, False]


def parse_pmset(text: str) -> bool:
    return "Battery Power" in text


def parse_low_power(text: str) -> bool:
    """macOS: the line of `pmset -g` that says whether the Low Power Mode is on."""
    return re.search(r"lowpowermode\s+1\b", text) is not None


def _probe() -> bool:
    """Is this computer on its battery or in a low power mode? False when it cannot tell: no saving is better than a
    face that stays sluggish on the mains."""
    try:
        if sys.platform == "darwin":
            battery = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=2).stdout
            settings = subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=2).stdout
            return parse_pmset(battery) or parse_low_power(settings)
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                            ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

            status = Status()
            return bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))) and (
                status.ACLineStatus == 0 or status.SystemStatusFlag == 1)  # 1: Battery Saver
        try:
            if subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True,
                              timeout=2).stdout.strip() == "power-saver":
                return True
        except (OSError, subprocess.SubprocessError):
            pass  # no power profiles daemon here: the battery tells
        root = "/sys/class/power_supply"
        discharging = False
        for name in os.listdir(root):
            folder = os.path.join(root, name)
            kind = open(os.path.join(folder, "type")).read().strip()
            if kind == "Mains" and open(os.path.join(folder, "online")).read().strip() == "1":
                return False
            if kind == "Battery" and open(os.path.join(folder, "status")).read().strip() == "Discharging":
                discharging = True
        return discharging
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return False


def constrained() -> bool:
    now = time.monotonic()
    if now - _seen[0] > CHECK_EVERY_S:
        _seen[0], _seen[1] = now, _probe()
    return _seen[1]


def reduced() -> bool:
    """Draw less: the setting is on and the computer runs on its battery or in a low power mode."""
    return save_battery() and constrained()
