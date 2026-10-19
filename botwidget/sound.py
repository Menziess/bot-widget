"""A beep on a new answer; the sound itself comes from the OS layer."""

from botwidget.config import widget_config
from botwidget.system.current import play_notification


def play_sound():
    """Only if widget.json sets sound to true."""
    if widget_config().get("sound") is True:
        play_notification()
