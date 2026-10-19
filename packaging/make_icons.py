"""The face as app icon, in all formats the operating systems ask for.

Usage: python packaging/make_icons.py <output folder>
Writes icon.png, icon.ico and (macOS only) icon.icns.
"""

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from botwidget.avatar import avatar_svg  # noqa: E402

SEED = "bot-widget"


def render(size: int) -> QImage:
    svg = avatar_svg("rest", SEED, None)
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def main(out: str):
    _app = QGuiApplication([])
    os.makedirs(out, exist_ok=True)
    render(512).save(os.path.join(out, "icon.png"))
    render(256).save(os.path.join(out, "icon.ico"))
    if sys.platform == "darwin":
        iconset = os.path.join(out, "icon.iconset")
        os.makedirs(iconset, exist_ok=True)
        for base in (16, 32, 128, 256, 512):
            render(base).save(os.path.join(iconset, f"icon_{base}x{base}.png"))
            render(base * 2).save(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(out, "icon.icns")], check=True)


if __name__ == "__main__":
    main(sys.argv[1])
