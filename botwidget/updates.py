"""Updates: ask whether there is a newer version, stage it and install it.

One anonymous request to GitHub. The file for this operating system is downloaded
and checked against SHA256SUMS.txt of the same release; the OS layer does the
installation itself. A failed step is silent: the current version just keeps
running.
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
    assets: dict  # file name -> download link


def parse_version(tag: str) -> tuple:
    """'v0.2.1' becomes (0, 2, 1, 1); a development version like 0.2.1.dev3 becomes (0, 2, 1, 0).

    The last slot makes a development version sort below the release that follows it.
    """
    numbers = [int(part) for part in re.findall(r"\d+", tag.split("+")[0].split(".dev")[0])[:3]]
    return tuple(numbers + [0] * (3 - len(numbers))) + (0 if ".dev" in tag else 1,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _open(url: str, timeout: float, accept: str = "*/*"):
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"botwidget/{__version__}"})
    return urllib.request.urlopen(request, timeout=timeout)


def newer_release(current: str = __version__, timeout: float = 5.0) -> Release | None:
    """The newer release, or None."""
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
    """The output of sha256sum: 'hash  name' or 'hash *name'."""
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
    """Download and verify the file for this system; the path, or None."""
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
    """(version, path) of the newest staged update that is newer than current."""
    found = []
    for name in os.listdir(STAGING) if os.path.isdir(STAGING) else []:
        path = os.path.join(STAGING, name, UPDATE_ASSET)
        if is_newer(name, current) and os.path.exists(path + VERIFIED):
            found.append((parse_version(name), name, path))
    return max(found)[1:] if found else None


def clean_staging(current: str = __version__):
    """Clean up staged updates that are not newer than what is running now."""
    for name in os.listdir(STAGING) if os.path.isdir(STAGING) else []:
        if not is_newer(name, current):
            shutil.rmtree(os.path.join(STAGING, name), ignore_errors=True)


def install_staged(current: str = __version__) -> bool:
    """Install a staged update; True if the widget should quit now.

    The verification marker goes first: an installation that fails is then not
    retried at every start.
    """
    found = staged_update(current)
    if not (found and can_install_update()):
        return False
    _version, path = found
    try:
        os.remove(path + VERIFIED)
    except OSError:
        pass
    return install_update(path)
