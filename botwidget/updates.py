"""Updates: vragen of er een nieuwere versie is, hem klaarzetten en installeren.

Eén anonieme vraag aan GitHub. Het bestand voor dit besturingssysteem wordt
gedownload en gecontroleerd tegen SHA256SUMS.txt van dezelfde release; de
installatie zelf doet de OS-laag. Een mislukte stap is stil: dan blijft de
huidige versie gewoon draaien.
"""

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass

from botwidget import __version__
from botwidget.config import APP_DIR
from botwidget.system.current import UPDATE_ASSET, can_install_update, install_update

LATEST_URL = "https://api.github.com/repos/Menziess/bot-widget/releases/latest"
DOWNLOAD_URL = "https://bot-widget.com"
SUMS_ASSET = "SHA256SUMS.txt"
STAGING = os.path.join(APP_DIR, "updates")
VERIFIED = ".verified"


@dataclass
class Release:
    version: str
    assets: dict  # bestandsnaam -> downloadlink


def parse_version(tag: str) -> tuple:
    """'v0.2.1' wordt (0, 2, 1); zonder cijfers is het (0,)."""
    return tuple(int(part) for part in re.findall(r"\d+", tag)[:3]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _open(url: str, timeout: float, accept: str = "*/*"):
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"botwidget/{__version__}"})
    return urllib.request.urlopen(request, timeout=timeout)


def newer_release(current: str = __version__, timeout: float = 5.0) -> Release | None:
    """De nieuwere release, of None."""
    try:
        with _open(LATEST_URL, timeout, "application/vnd.github+json") as response:
            data = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    tag = data.get("tag_name") or ""
    if not tag or not is_newer(tag, current):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])
              if "name" in a and "browser_download_url" in a}
    return Release(tag.lstrip("v"), assets)


def parse_sums(text: str) -> dict:
    """De uitvoer van sha256sum: 'hash  naam' of 'hash *naam'."""
    sums = {}
    for line in text.splitlines():
        match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if match:
            sums[match.group(2)] = match.group(1).lower()
    return sums


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, path: str, timeout: float):
    with _open(url, timeout) as response, open(path, "wb") as out:
        shutil.copyfileobj(response, out)


def stage(release: Release, timeout: float = 60.0) -> str | None:
    """Download en controleer het bestand voor dit systeem; het pad, of None."""
    url, sums_url = release.assets.get(UPDATE_ASSET), release.assets.get(SUMS_ASSET)
    if not (url and sums_url):
        return None
    folder = os.path.join(STAGING, release.version)
    path = os.path.join(folder, UPDATE_ASSET)
    if os.path.exists(path + VERIFIED):
        return path
    try:
        with _open(sums_url, timeout) as response:
            expected = parse_sums(response.read().decode()).get(UPDATE_ASSET)
        if not expected:
            return None
        os.makedirs(folder, exist_ok=True)
        _download(url, path, timeout)
        if sha256_of(path) != expected:
            raise OSError("checksum mismatch")
    except (OSError, urllib.error.URLError, ValueError):
        shutil.rmtree(folder, ignore_errors=True)
        return None
    open(path + VERIFIED, "w").close()
    return path


def staged_update(current: str = __version__) -> tuple | None:
    """(versie, pad) van de nieuwste klaargezette update die nieuwer is dan current."""
    found = []
    for name in os.listdir(STAGING) if os.path.isdir(STAGING) else []:
        path = os.path.join(STAGING, name, UPDATE_ASSET)
        if is_newer(name, current) and os.path.exists(path + VERIFIED):
            found.append((parse_version(name), name, path))
    return max(found)[1:] if found else None


def clean_staging(current: str = __version__):
    """Ruim klaargezette updates op die niet nieuwer zijn dan wat er nu draait."""
    for name in os.listdir(STAGING) if os.path.isdir(STAGING) else []:
        if not is_newer(name, current):
            shutil.rmtree(os.path.join(STAGING, name), ignore_errors=True)


def install_staged(current: str = __version__) -> bool:
    """Installeer een klaargezette update; True als de widget nu moet afsluiten.

    De controlemarkering gaat eerst weg: een installatie die mislukt wordt zo
    niet bij elke start opnieuw geprobeerd.
    """
    found = staged_update(current)
    if not (found and can_install_update()):
        return False
    _version, path = found
    os.remove(path + VERIFIED)
    return install_update(path)
