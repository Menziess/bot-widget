"""Offline page read for the direct-CDP choice.

A live Chrome socket is faster when a debugging port is open. Tests and a
machine with no browser use a fixture file instead. No network.
"""

import os
import re


def fixture_title(path: str) -> str:
    """The <title> of a local HTML file. Empty when the file has none."""
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    found = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return found.group(1).strip() if found else ""


def read_page(path: str) -> dict:
    return {"url": os.path.abspath(path), "title": fixture_title(path), "transport": "fixture"}
