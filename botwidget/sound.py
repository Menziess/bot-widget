"""A beep on a new answer; the sound itself comes from the OS layer."""

import datetime

from botwidget.config import quiet_now, widget_config
from botwidget.system.current import play_notification


def play_sound():
    """Only if widget.json sets sound to true, and not during quiet hours."""
    config = widget_config()
    if config.get("sound") is True and not quiet_now(datetime.datetime.now().hour, config.get("quiet_hours") is True):
        play_notification()
