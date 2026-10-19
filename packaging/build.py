"""Builds the app for this operating system and packages it for download.

Usage: python packaging/build.py
Result in dist/:
  macOS    BotWidget-macOS.zip          (Bot Widget.app, findable via Spotlight)
  Windows  BotWidget-Windows-Setup.exe  (Start menu entry; zip if Inno Setup is missing)
  Linux    BotWidget-Linux.tar.gz       (with install.sh for a menu entry)

Signing only happens when the secrets are in the environment:
  macOS    MACOS_SIGN_IDENTITY, plus APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD for notarization
  Windows  WINDOWS_CERT_FILE and WINDOWS_CERT_PASSWORD
Without those secrets it stays an unsigned build.
"""

import glob
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile

NAME = "Bot Widget"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from botwidget.system.macos import BUNDLE_ID  # noqa: E402

BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
# Everything the widget does not use; keeps the download small.
UNUSED_QT = ("QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtQml", "QtQuick", "QtPdf",
             "QtNetwork", "QtMultimedia", "Qt3DCore", "QtCharts", "QtSql", "QtTest")


def version() -> str:
    """The number for installers: 0.1.1.dev3+gabc becomes 0.1.1, they only want digits."""
    from botwidget import __version__
    return re.match(r"\d+(\.\d+){0,2}", __version__).group(0)


def run(*cmd, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def icons() -> str:
    folder = os.path.join(BUILD, "icons")
    run(sys.executable, os.path.join(ROOT, "packaging", "make_icons.py"), folder,
        env={**os.environ, "PYTHONPATH": ROOT})
    return os.path.join(folder, {"darwin": "icon.icns", "win32": "icon.ico"}.get(sys.platform, "icon.png"))


def bundle(icon: str):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", NAME, "--icon", icon, "--paths", ROOT,
            "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyinstaller"), "--specpath", BUILD]
    for module in UNUSED_QT:
        args += ["--exclude-module", f"PySide6.{module}"]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", BUNDLE_ID]
    run(*args, os.path.join(ROOT, "packaging", "entry.py"))


def mac():
    app = os.path.join(DIST, f"{NAME}.app")
    plist_path = os.path.join(app, "Contents", "Info.plist")
    with open(plist_path, "rb") as fh:
        plist = plistlib.load(fh)
    plist.update({"LSUIElement": True, "CFBundleShortVersionString": version(), "CFBundleVersion": version()})
    with open(plist_path, "wb") as fh:
        plistlib.dump(plist, fh)
    out = os.path.join(DIST, "BotWidget-macOS.zip")
    identity = os.environ.get("MACOS_SIGN_IDENTITY")
    if not identity:
        # Without (at least an ad-hoc) signature the app does not start on Apple Silicon.
        run("codesign", "--force", "--deep", "--sign", "-", app)
        run("ditto", "-c", "-k", "--keepParent", app, out)
        return out
    run("codesign", "--force", "--deep", "--options", "runtime", "--timestamp",
        "--entitlements", os.path.join(ROOT, "packaging", "entitlements.plist"), "--sign", identity, app)
    run("ditto", "-c", "-k", "--keepParent", app, out)
    apple = {key: os.environ.get(key) for key in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_PASSWORD")}
    if all(apple.values()):
        run("xcrun", "notarytool", "submit", out, "--apple-id", apple["APPLE_ID"],
            "--team-id", apple["APPLE_TEAM_ID"], "--password", apple["APPLE_APP_PASSWORD"], "--wait")
        run("xcrun", "stapler", "staple", app)
        os.remove(out)
        run("ditto", "-c", "-k", "--keepParent", app, out)
    return out


def sign_windows(path: str):
    """Signs with signtool if the certificate is in the environment."""
    cert, password = os.environ.get("WINDOWS_CERT_FILE"), os.environ.get("WINDOWS_CERT_PASSWORD")
    if not (cert and password):
        return
    found = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe"))
    signtool = shutil.which("signtool") or (found[-1] if found else None)
    if not signtool:
        raise SystemExit("signtool not found")
    run(signtool, "sign", "/f", cert, "/p", password, "/fd", "sha256",
        "/tr", "http://timestamp.digicert.com", "/td", "sha256", path)


def windows():
    folder = os.path.join(DIST, NAME)
    iscc = shutil.which("iscc")
    if iscc:
        run(iscc, f"/DVersion={version()}", f"/DSourceDir={folder}", f"/DOutputDir={DIST}",
            os.path.join(ROOT, "packaging", "windows.iss"))
        installer = os.path.join(DIST, "BotWidget-Windows-Setup.exe")
        sign_windows(installer)
        return installer
    return shutil.make_archive(os.path.join(DIST, "BotWidget-Windows"), "zip", DIST, NAME)


def linux():
    folder = os.path.join(DIST, NAME)
    out = os.path.join(DIST, "BotWidget-Linux.tar.gz")
    shutil.copy(os.path.join(ROOT, "packaging", "install.sh"), os.path.join(DIST, "install.sh"))
    shutil.copy(os.path.join(BUILD, "icons", "icon.png"), os.path.join(DIST, "icon.png"))
    with tarfile.open(out, "w:gz") as tar:
        tar.add(folder, arcname="botwidget/app")
        tar.add(os.path.join(DIST, "install.sh"), arcname="botwidget/install.sh")
        tar.add(os.path.join(DIST, "icon.png"), arcname="botwidget/icon.png")
    return out


def main():
    shutil.rmtree(DIST, ignore_errors=True)
    bundle(icons())
    package = {"darwin": mac, "win32": windows}.get(sys.platform, linux)()
    print("Built", package, f"({os.path.getsize(package) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
