# bot-widget

- Work on `main`; no branches or PRs. Ask before committing or pushing.
- `botwidget/` is toolkit-free logic; `botwidget/qt_ui/` is the PySide6 UI.
- Test: `.venv/bin/python -m unittest discover -s tests -t .` (unittest, not pytest; logic plus a few offscreen Qt tests).
- Run live: `botwidget --dev` (restarts on .py changes). Check UI changes by eye.
- `site/` is the static website (no build, deployed by Pages on push to main). `site/face.js` ports `avatar.py` and `animation.py` to canvas; keep them in step.
- Release: a tag `vX.Y.Z` pushed to origin builds and publishes (see README, Releasing). Bump the patch number of the latest tag (v0.1.0 becomes v0.1.1), not the minor one, unless told otherwise; when unsure, ask for the version before tagging, since a pushed tag starts the build at once.
- Windows SmartScreen: unsigned until `WINDOWS_CERTIFICATE` and `WINDOWS_CERT_PASSWORD` GitHub secrets exist. Buy a standard Authenticode cert, set those secrets, re-tag. Do not spend money from this agent. See README, Windows Authenticode.
