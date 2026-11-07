# bot-widget

- Stay on the default branch. Do not create a branch unless asked. A branch that is asked for starts with `feature/`. Ask before committing or pushing.
- `botwidget/` is toolkit-free logic; `botwidget/qt_ui/` is the PySide6 UI.
- Test: `.venv/bin/python -m unittest discover -s tests -t .` (unittest, not pytest; logic plus a few offscreen Qt tests).
- Run live: `botwidget --dev` (restarts on .py changes). Check UI changes by eye.
- `site/` is the static website (no build, deployed by Pages on push to main). `site/face.js` ports `avatar.py` and `animation.py` to canvas; keep them in step.
- Release: a tag `vX.Y.Z` pushed to origin builds and publishes (see README, Releasing). Bump the patch number of the latest tag (v0.1.0 becomes v0.1.1), not the minor one, unless told otherwise; when unsure, ask for the version before tagging, since a pushed tag starts the build at once.
- Windows SmartScreen: unsigned until `WINDOWS_CERTIFICATE` and `WINDOWS_CERT_PASSWORD` GitHub secrets exist. Buy a standard Authenticode cert, set those secrets, re-tag. Do not spend money from this agent. See README, Windows Authenticode.

## Taskbar

Widget windows never appear in the taskbar, dock or alt-tab; only the tray icon. Do not change these window flags without updating the test.

```python
set_flags(self, Qt.FramelessWindowHint | Qt.Tool | layer)
```

- That call lives in `botwidget/qt_ui/face.py` (`_apply_flags`), `bubble_window.py` (`_apply_flags` and `Trail`), and `faces.py` (`ArcCatcher`, `_spawn_guest`).
- The `Qt.Tool` flag keeps the window out of the taskbar on Linux, Windows and macOS.
- Linux also writes skip-taskbar in `botwidget/system/linux.py` (`before_show`) before each map.
- The regression test is `NoTaskbarButton` in `tests/test_logic.py`.
