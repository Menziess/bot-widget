# bot-widget

- Stay on the default branch. Do not create a branch unless asked. A branch that is asked for starts with `feature/`. Ask before committing or pushing.
- `botwidget/` is toolkit-free logic; `botwidget/qt_ui/` is the PySide6 UI.
- Test: `.venv/bin/python -m unittest discover -s tests -t .` (unittest, not pytest; logic plus a few offscreen Qt tests).
- Run live: `botwidget --dev` (restarts on .py changes). Check UI changes by eye.
- To talk to a running widget's bot from a shell (the widget needs `"remote_control": true` in widget.json, off by default), use `botwidget bots | ask BOT TEXT | read BOT` (`botwidget/remote.py`; README, Talking to a bot from a shell). From a checkout run `.venv/bin/python -m botwidget ...`: the `botwidget` on PATH may be the uv install, which is another copy.
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

## How the bubble and the arc behave

The rules below are what the user expects. A change that breaks one is a bug, also when the tests still pass. A change that moves a rule changes this section and the README in the same commit.

### Bubble
- Pointing at a face opens its bubble with the latest answer, and the field only shows while the pointer is on the bubble or its face
- A new answer opens the bubble by itself and keeps it for the time it takes to read, unless the pointer is on it
- Sending a message shows the cloud with dots until the bot has answered
- The bubble stays while the pointer is on the face or the bubble, with a margin around it
- The bubble also stays while words are typed or selected, a draft is in the field, a file waits to be sent, a form was typed in, a question or approval waits, or the bot works
- Keyboard focus that came from resting the pointer on the face never keeps the bubble open, only typing, a click in the field or one of the reasons above does
- The bubble closes shortly after the pointer left: 0.4 seconds, longer while the pointer moves faster than 300 pixels a second, never beyond 1.5 seconds
- The bubble closes at once on Escape, when another face opens one, when a face is dragged, and when /screenshot starts
- The bubble closes when another window is clicked into with nothing typed, and where the pointer position is unknown (Wayland) it closes the moment the pointer is not on it
- An unread answer closes after its reading time unless the pointer was on it
- Clicking inside the bubble never opens or closes it

### Arc
- The arc opens when the pointer is near the top middle of the screen, on the /bots page, or when a face is dragged into it
- Pointing at a bot on the desktop never opens the arc
- An open arc stays while the pointer is on the arc or one of its bots, or a bot is dragged, and closes shortly after the pointer left all of them
- Escape or a click outside closes the arc

### Pointer
- The pointer position decides where the platform gives it; enter and leave events only back that up, because a drag ends without a leave
- Buttons and rows light up from the pointer position, because the widget is rarely the app in front

### Screenshot and attachments
- Double-click on a face or /screenshot closes the bubble, darkens every screen and cancels on Escape or a right-click
- The picture waits in the field as an attachment, the bubble stays open for it, and nothing goes out until the user sends

### The bot
- An approval shows a dot and a cloud with Accept and Decline, and Always allow when the agent offers to remember the command. It waits ten minutes, and is logged with who answered
- A turn that a restart cut off is picked up again when the widget is back
- The eyes follow the pointer wherever it is
