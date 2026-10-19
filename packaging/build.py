"""Bouwt de app voor dit besturingssysteem en pakt hem in voor download.

Gebruik: python packaging/build.py
Resultaat in dist/:
  macOS    BotWidget-macOS.zip          (Bot Widget.app, vindbaar via Spotlight)
  Windows  BotWidget-Windows-Setup.exe  (Startmenu-item; zip als Inno Setup ontbreekt)
  Linux    BotWidget-Linux.tar.gz       (met install.sh voor een menu-item)
"""

import os
import plistlib
import shutil
import subprocess
import sys
import tarfile

import tomllib

NAME = "Bot Widget"
BUNDLE_ID = "com.bot-widget.app"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
# Alles wat de widget niet gebruikt; houdt de download klein.
UNUSED_QT = ("QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtQml", "QtQuick", "QtPdf",
             "QtNetwork", "QtMultimedia", "Qt3DCore", "QtCharts", "QtSql", "QtTest")


def version() -> str:
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


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
    # Zonder (minstens een ad-hoc) handtekening start de app niet op Apple Silicon.
    run("codesign", "--force", "--deep", "--sign", "-", app)
    out = os.path.join(DIST, "BotWidget-macOS.zip")
    run("ditto", "-c", "-k", "--keepParent", app, out)
    return out


def windows():
    folder = os.path.join(DIST, NAME)
    iscc = shutil.which("iscc")
    if iscc:
        run(iscc, f"/DVersion={version()}", f"/DSourceDir={folder}", f"/DOutputDir={DIST}",
            os.path.join(ROOT, "packaging", "windows.iss"))
        return os.path.join(DIST, "BotWidget-Windows-Setup.exe")
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
