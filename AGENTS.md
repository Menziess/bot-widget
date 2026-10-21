# bot-widget

- Work on `main`; no branches or PRs. Ask before committing or pushing.
- `botwidget/` is toolkit-free logic; `botwidget/qt_ui/` is the PySide6 UI.
- Test: `.venv/bin/python -m unittest discover -s tests -t .` (unittest, not pytest; logic plus a few offscreen Qt tests).
- Run live: `botwidget --dev` (restarts on .py changes). Check UI changes by eye.
- `site/` is the static website (no build, deployed by Pages on push to main). `site/face.js` ports `avatar.py` and `animation.py` to canvas; keep them in step.
