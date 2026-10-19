"""Is er een nieuwere versie? Eén anonieme vraag aan GitHub; een mislukte vraag is stil."""

import json
import re
import urllib.error
import urllib.request

from botwidget import __version__

LATEST_URL = "https://api.github.com/repos/Menziess/bot-widget/releases/latest"
DOWNLOAD_URL = "https://bot-widget.com"


def parse_version(tag: str) -> tuple:
    """'v0.2.1' wordt (0, 2, 1); zonder cijfers is het (0,)."""
    return tuple(int(part) for part in re.findall(r"\d+", tag)[:3]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def newer_release(current: str = __version__, timeout: float = 5.0) -> str | None:
    """Het versienummer van een nieuwere release, of None."""
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"botwidget/{current}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            tag = json.loads(response.read().decode()).get("tag_name", "")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return tag.lstrip("v") if tag and is_newer(tag, current) else None
