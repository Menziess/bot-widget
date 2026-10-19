"""Piep bij een nieuw antwoord; het geluid zelf komt uit de OS-laag."""

from botwidget.config import widget_config
from botwidget.system.current import play_notification


def play_sound():
    """Alleen als widget.json sound op true zet."""
    if widget_config().get("sound") is True:
        play_notification()
