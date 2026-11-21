"""Whether this desktop can be read through its accessibility API.

Linux uses PyGObject and the Atspi 2.0 typelib a GNOME desktop already ships
(`gir1.2-atspi-2.0` plus `python3-gi`). That is the same bus Orca uses. The
apt package `python3-pyatspi` is a second binding of that bus and is not used.

Windows (UI Automation) and macOS (the AX API) are named here so a later
computer-use tool has one place to look. They are not implemented.

shortcut: no in-widget PolicyKit install until a desktop is actually missing
the typelib, add the agree dialog when a real probe returns available false.
"""

import os
import sys

# Installed by the desktop, not by pip. Listed so a later agree step can ask
# for these names and never for python3-pyatspi.
LINUX_PACKAGES = ("gir1.2-atspi-2.0", "python3-gi")
SYSTEM_GI = "/usr/lib/python3/dist-packages"

# The in-widget dialog is not built. install_after_agree is the only install entry.
CONSENT = {
    "built": False,
    "title": "Desktop accessibility",
    "packages": LINUX_PACKAGES,
    "choices": ("Agree", "Not now"),
    "install": "install_after_agree",
}

_cached = None
_logged = False


def clear() -> None:
    """Drop the cached probe. Tests use this between cases."""
    global _cached, _logged
    _cached = None
    _logged = False


def accessibility(load=None) -> dict:
    """available, reason, and platform. The first real probe is kept.

    Pass load to force a fresh probe, which is how tests avoid the real bus.
    """
    global _cached
    if load is not None:
        return _probe(load)
    if _cached is None:
        _cached = _probe(_load_platform)
    return dict(_cached)


def log_once(write=None) -> dict:
    """Write one line the first time. Later calls stay quiet and return the same status."""
    global _logged
    row = accessibility()
    if not _logged:
        _logged = True
        word = "yes" if row["available"] else "no"
        (write or _write)(f"accessibility: {word} ({row['reason']})")
    return row


def application_names(load=None) -> list[str]:
    """Top-level application names on the accessibility bus. Empty when it is down."""
    if load is None:
        row = accessibility()
        if not row["available"]:
            return []
        try:
            bus = _load_platform()
        except Exception:
            return []
    else:
        bus = load()
    desktop = bus.get_desktop(0)
    names = []
    for index in range(desktop.get_child_count()):
        child = desktop.get_child_at_index(index)
        names.append(child.get_name() or "")
    return names


def install_command() -> list[str]:
    """PolicyKit install of the typelib. The caller must already have a yes from the user."""
    return ["pkexec", "apt-get", "install", "-y", *LINUX_PACKAGES]


def install_after_agree(agreed: bool, run=None) -> str:
    """Run the install only after an explicit agreement. Never called at startup."""
    if not agreed:
        return "not installed; the widget is still waiting for agreement"
    if run is None:
        import subprocess
        run = subprocess.run
    done = run(install_command(), check=False)
    code = getattr(done, "returncode", 0)
    if code:
        return f"install failed ({code})"
    clear()
    return "installed"


def _write(line: str) -> None:
    sys.stderr.write(line + "\n")


def _probe(load) -> dict:
    platform = _platform_name()
    if platform == "windows":
        return {"available": False, "reason": "UI Automation is not implemented", "platform": platform}
    if platform == "macos":
        return {"available": False, "reason": "the AX API is not implemented", "platform": platform}
    try:
        bus = load()
        desktop = bus.get_desktop(0)
    except Exception as error:
        return {"available": False, "reason": _linux_reason(error), "platform": platform}
    if desktop is None:
        return {"available": False, "reason": "AT-SPI has no desktop", "platform": platform}
    return {"available": True, "reason": "AT-SPI", "platform": platform}


def _platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def gi_missing(error: BaseException) -> bool:
    """True when Python cannot import the desktop gi the doctor step links in."""
    text = str(error)
    return isinstance(error, ImportError) and "No module named" in text and "gi" in text


def _linux_reason(error: BaseException) -> str:
    if gi_missing(error):
        return "gi is not on the path. Run `botwidget doctor`."
    text = f"{type(error).__name__}: {error}"
    return "AT-SPI typelib is not usable (" + text + "). The desktop packages are gir1.2-atspi-2.0 and python3-gi."


def doctor() -> str:
    """Link the desktop gi into this venv, then say whether accessibility works. Never called on import."""
    made = link_system_gi()
    clear()
    row = accessibility()
    link = "linked " + ", ".join(os.path.basename(path) for path in made) if made else "no new link"
    word = "yes" if row["available"] else "no"
    return f"{link}; accessibility: {word} ({row['reason']})"


def link_system_gi(site_packages: str | None = None, source: str = SYSTEM_GI) -> list[str]:
    """Symlink the desktop PyGObject into a venv. A fresh venv has no gi of its own.

    No-op outside a virtualenv when site_packages is omitted, and when the desktop has no gi.
    """
    if site_packages is None:
        if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
            return []
        import site
        found = [path for path in site.getsitepackages() if path.startswith(sys.prefix)]
        if not found:
            return []
        site_packages = found[0]
    gi = os.path.join(source, "gi")
    if not os.path.isdir(gi):
        return []
    os.makedirs(site_packages, exist_ok=True)
    made = []
    names = ["gi"]
    try:
        names.extend(name for name in os.listdir(source)
                     if name.startswith("PyGObject-") and name.endswith(".dist-info"))
    except OSError:
        pass
    for name in names:
        dest = os.path.join(site_packages, name)
        if os.path.lexists(dest):
            continue
        os.symlink(os.path.join(source, name), dest)
        made.append(dest)
    return made


def _load_platform():
    """Import Atspi and join the bus the session already started."""
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    if not Atspi.is_initialized():
        Atspi.init()
    return Atspi
