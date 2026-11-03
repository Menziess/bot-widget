"""Build an unsigned MSIX package of the PyInstaller app folder for Microsoft Store upload.

The Store signs the final package; this produces the un-signed .msix that the
release workflow uploads to Partner Center.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Asset definitions: filename -> (width, height)
# ---------------------------------------------------------------------------

ASSETS: dict[str, tuple[int, int]] = {
    "Square44x44Logo.png": (44, 44),
    "Square44x44Logo.targetsize-256_altform-unplated.png": (256, 256),
    "Square150x150Logo.png": (150, 150),
    "Wide310x150Logo.png": (310, 150),
    "StoreLogo.png": (50, 50),
}

# ---------------------------------------------------------------------------
# Namespace prefixes used in the manifest text
# ---------------------------------------------------------------------------

_NS = {
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "desktop": "http://schemas.microsoft.com/appx/manifest/desktop/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}

# Register the foundation namespace as the default namespace so the output is
# <Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10" ...>
# instead of <ns0:Package xmlns:ns0="...">.
ET.register_namespace("", "http://schemas.microsoft.com/appx/manifest/foundation/windows10")

for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "msix.json")

_NAME_RE = re.compile(r"^[A-Za-z0-9.-]{3,50}$")


def load_config(path=None, environ=None) -> dict:
    """Load msix.json, apply env overrides, validate and return a dict."""
    config_path = path or _CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    env = environ if environ is not None else os.environ

    # Apply env overrides (only when non-empty)
    for key, env_key in (
        ("identity_name", "MSIX_IDENTITY_NAME"),
        ("publisher", "MSIX_PUBLISHER"),
        ("publisher_display_name", "MSIX_PUBLISHER_DISPLAY_NAME"),
    ):
        value = env.get(env_key, "")
        if value:
            config[key] = value

    # Validate identity_name
    name = config.get("identity_name", "")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"identity_name must match ^[A-Za-z0-9.-]{{3,50}}$: got {name!r}"
        )

    # Validate publisher starts with CN=
    publisher = config.get("publisher", "")
    if not publisher.startswith("CN="):
        raise ValueError(
            f"publisher must start with CN=: got {publisher!r}"
        )

    return config


def identity_configured(environ=None) -> bool:
    """True when all three Partner Center identity variables are non-empty."""
    env = environ if environ is not None else os.environ
    return all(
        env.get(key)
        for key in (
            "MSIX_IDENTITY_NAME",
            "MSIX_PUBLISHER",
            "MSIX_PUBLISHER_DISPLAY_NAME",
        )
    )


def is_placeholder(config: dict) -> bool:
    """True when identity_name or publisher_display_name contains PLACEHOLDER
    or publisher is the all-zero GUID CN."""
    return (
        "PLACEHOLDER" in config.get("identity_name", "")
        or "PLACEHOLDER" in config.get("publisher_display_name", "")
        or config.get("publisher", "") == "CN=00000000-0000-0000-0000-000000000000"
    )


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def msix_version(version: str) -> str:
    """Normalise a version string to four parts, each 0..65535, ending with .0.

    Examples:
        "0.1.1"       -> "0.1.1.0"
        "1.2"         -> "1.2.0.0"
        "0.1.1.dev3"  -> "0.1.1.0"
    """
    # Strip pre-release / local parts: 0.1.1.dev3+gabc -> 0.1.1
    base = re.match(r"\d+(\.\d+)*", version)
    if base:
        base = base.group(0)
    else:
        raise ValueError(f"version must start with a digit: {version!r}")
    parts = base.split(".")
    while len(parts) < 4:
        parts.append("0")
    numeric = []
    for part in parts[:4]:
        try:
            val = int(part)
        except ValueError:
            raise ValueError(f"version part {part!r} is not an integer")
        if val < 0 or val > 65535:
            raise ValueError(
                f"version part {val} out of range 0..65535"
            )
        numeric.append(str(val))
    return ".".join(numeric)


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _ns(local: str) -> str:
    """Return a fully-qualified tag for the default (foundation) namespace."""
    return f"{{http://schemas.microsoft.com/appx/manifest/foundation/windows10}}{local}"


def manifest_xml(config: dict, version: str, executable: str = "Bot Widget.exe") -> str:
    """Return the full AppxManifest.xml text."""

    root = ET.Element(_ns("Package"))
    root.set("IgnorableNamespaces", "uap desktop rescap")

    # -- Identity --
    ET.SubElement(root, _ns("Identity"), {
        "Name": config["identity_name"],
        "Publisher": config["publisher"],
        "Version": msix_version(version),
        "ProcessorArchitecture": "x64",
    })

    # -- Properties --
    props = ET.SubElement(root, _ns("Properties"))
    ET.SubElement(props, _ns("DisplayName")).text = config.get("display_name", "")
    ET.SubElement(props, _ns("PublisherDisplayName")).text = config.get("publisher_display_name", "")
    ET.SubElement(props, _ns("Logo")).text = "Assets\\StoreLogo.png"

    # -- Dependencies --
    deps = ET.SubElement(root, _ns("Dependencies"))
    ET.SubElement(deps, _ns("TargetDeviceFamily"), {
        "Name": "Windows.Desktop",
        "MinVersion": config.get("min_version", "10.0.17763.0"),
        "MaxVersionTested": config.get("max_version_tested", "10.0.22621.0"),
    })

    # -- Resources --
    res = ET.SubElement(root, _ns("Resources"))
    ET.SubElement(res, _ns("Resource"), {"Language": "en-us"})

    # -- Applications --
    apps = ET.SubElement(root, _ns("Applications"))
    app = ET.SubElement(apps, _ns("Application"), {
        "Id": "BotWidget",
        "Executable": executable,
        "EntryPoint": "Windows.FullTrustApplication",
    })

    # uap:VisualElements
    uap_ve = ET.SubElement(app, f"{{{_NS['uap']}}}VisualElements", {
        "DisplayName": config.get("display_name", ""),
        "Description": config.get("description", ""),
        "BackgroundColor": "transparent",
        "Square150x150Logo": "Assets\\Square150x150Logo.png",
        "Square44x44Logo": "Assets\\Square44x44Logo.png",
    })
    ET.SubElement(uap_ve, f"{{{_NS['uap']}}}DefaultTile", {
        "Wide310x150Logo": "Assets\\Wide310x150Logo.png",
    })

    # -- Extensions: startupTask (desktop namespace, inside foundation Extensions) --
    exts = ET.SubElement(app, _ns("Extensions"))
    desktop_ext = ET.SubElement(exts, f"{{{_NS['desktop']}}}Extension", {
        "Category": "windows.startupTask",
        "Executable": executable,
        "EntryPoint": "Windows.FullTrustApplication",
    })
    ET.SubElement(desktop_ext, f"{{{_NS['desktop']}}}StartupTask", {
        "TaskId": "BotWidgetStartup",
        "Enabled": "true",
        "DisplayName": config.get("display_name", ""),
    })

    # -- Capabilities: runFullTrust --
    caps = ET.SubElement(root, _ns("Capabilities"))
    ET.SubElement(caps, f"{{{_NS['rescap']}}}Capability", {
        "Name": "runFullTrust",
    })

    # Build XML string
    rough_string = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + rough_string


# ---------------------------------------------------------------------------
# Asset rendering
# ---------------------------------------------------------------------------

def write_assets(folder: str) -> None:
    """Render each ASSETS icon and write it to folder."""
    from PySide6.QtGui import QGuiApplication

    # Make sure we can import make_icons from this package's directory.
    # When run as `python packaging/build.py --msix` or `python packaging/msix.py`,
    # sys.path[0] is packaging/, so "packaging" resolves to the pip packaging library.
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if _pkg_dir not in sys.path:
        sys.path.insert(0, _pkg_dir)
    _repo_root = os.path.dirname(_pkg_dir)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    import make_icons

    os.makedirs(folder, exist_ok=True)
    # QSvgRenderer / QPainter require a QGuiApplication instance.
    app = QGuiApplication.instance() or QGuiApplication([])
    try:
        for filename, (width, height) in ASSETS.items():
            if width == height:
                img = make_icons.render(width)
            else:
                img = make_icons.render_wide(width, height)
            img.save(os.path.join(folder, filename))
    finally:
        del app


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def stage(app_folder: str, out_folder: str, config: dict, version: str) -> None:
    """Copy app_folder contents into out_folder, write Assets and manifest."""
    if os.path.exists(out_folder):
        shutil.rmtree(out_folder)
    shutil.copytree(app_folder, out_folder, symlinks=True)

    # Write assets
    assets_folder = os.path.join(out_folder, "Assets")
    write_assets(assets_folder)

    # Write manifest
    manifest_path = os.path.join(out_folder, "AppxManifest.xml")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        fh.write(manifest_xml(config, version))


# ---------------------------------------------------------------------------
# find_makeappx
# ---------------------------------------------------------------------------

def find_makeappx():
    """Return the path to makeappx.exe, or None."""
    local = shutil.which("makeappx")
    if local:
        return local
    # Search Windows Kits
    base = r"C:\Program Files (x86)\Windows Kits\10\bin"
    if not os.path.isdir(base):
        return None
    found = []
    for entry in os.listdir(base):
        candidate = os.path.join(base, entry, "x64", "makeappx.exe")
        if os.path.isfile(candidate):
            found.append(candidate)
    found.sort()
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------

def pack(staging: str, out_path: str) -> None:
    """Run makeappx to create the MSIX package."""
    makeappx = find_makeappx()
    if not makeappx:
        raise SystemExit(
            "makeappx not found. Install the Windows 10 SDK or run on Windows."
        )
    subprocess.run(
        [makeappx, "pack", "/o", "/h", "SHA256", "/d", staging, "/p", out_path],
        check=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None, environ=None) -> bool:
    args = (argv if argv is not None else sys.argv[1:])
    env = environ if environ is not None else os.environ

    # Resolve paths relative to the repo root (parent of packaging/).
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_folder = args[0] if len(args) > 0 else os.path.join(_repo_root, "dist", "Bot Widget")
    out_path = args[1] if len(args) > 1 else os.path.join(_repo_root, "dist", "BotWidget-Windows.msix")
    staging = os.path.join(_repo_root, "build", "msix")

    # A release without Partner Center identity still ships the other installers.
    if not identity_configured(env):
        print(
            "::warning::MSIX skipped: set repo variables MSIX_IDENTITY_NAME, "
            "MSIX_PUBLISHER, MSIX_PUBLISHER_DISPLAY_NAME from Partner Center > Product identity"
        )
        return False

    config = load_config(environ=env)
    version = _get_version()

    if is_placeholder(config):
        print(
            "WARNING: identity placeholders detected: "
            "set repo variables MSIX_IDENTITY_NAME, MSIX_PUBLISHER, "
            "MSIX_PUBLISHER_DISPLAY_NAME from Partner Center > Product identity"
        )

    stage(app_folder, staging, config, version)
    pack(staging, out_path)

    print("Built", out_path)
    return True


def _get_version() -> str:
    """Get the version from botwidget.__version__."""
    try:
        from botwidget import __version__
        return __version__
    except ImportError:
        return "0.0.0"


if __name__ == "__main__":
    main()
