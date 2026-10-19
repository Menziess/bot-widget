#!/usr/bin/env python3
"""Desktop widget: an animated bot face with a speech bubble.

Shows a floating face with a notification dot when the bot waits for an answer or
approval. A click opens the chat bubble; messages go through OpenBot's local HTTP
API. The code lives in the botwidget/ package; this file stays the name the widget
is started with.

Requires: PySide6 (pip install PySide6)
"""

from botwidget.qt_ui.app import main

if __name__ == "__main__":
    main()
