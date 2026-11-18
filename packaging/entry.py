"""Entry point for the packaged app; PyInstaller bundles this file."""

import sys

if __name__ == "__main__":
    if sys.argv[1:3] == ["-m", "harness.agent"]:
        # The app is the only interpreter here, and default_command() runs the lean agent as `app -m harness.agent`.
        from harness.agent.__main__ import main
    else:
        from botwidget.qt_ui.app import main
    raise SystemExit(main())
