"""Rules for sending a key over the network: where it may go, and what must never follow it.

Standard library only, like the rest of the agent.
"""

import ipaddress
import os
import stat
import urllib.parse
import urllib.request

PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would send the Authorization header on to wherever a 3xx points, another host or plain http included.
    A refusal turns the 3xx into an error that says where it pointed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def open_url(request, timeout: float):
    """urlopen that never follows a redirect, for every call that carries a key."""
    return _OPENER.open(request, timeout=timeout)


def private_host(host: str) -> bool:
    """A machine on this computer or its own network: no dot in the name, a local suffix, or a private address."""
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(PRIVATE_SUFFIXES)
    return address.is_loopback or address.is_private or address.is_link_local


def key_may_travel(url: str) -> bool:
    """https anywhere, plain http only to a machine of your own: on the internet it would show the key to everyone
    on the way."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.username or parts.password:
        return False  # credentials in the address end up in logs
    return parts.scheme == "https" or (parts.scheme == "http" and private_host(parts.hostname or ""))


def redact(text: str, secret: str) -> str:
    """A server may quote the key in its error: it never reaches the screen or a log."""
    return text.replace(secret, "[key]") if secret and len(secret) >= 6 else text


def key_file_problem(path: str) -> str:
    """What is wrong with where a key is kept, or "". A key file other users can read is as good as shared."""
    path = os.path.expanduser(path)
    try:
        mode = os.stat(path).st_mode
        if os.name != "nt" and os.path.getsize(path) and mode & (stat.S_IRWXG | stat.S_IRWXO):
            return f"The key file {path} can be read by other users. Run: chmod 600 {path}"
    except OSError:
        pass
    return ""
