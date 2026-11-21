# bot-widget

- Stay on the default branch. Do not create a branch unless asked. A branch that is asked for starts with `feature/`. Ask before committing. Never push on your own: wait until the owner says push, also after a green check or an earlier yes, because a yes covers that push only. Commits may pile up locally; the owner often pushes several of them in one go.
- `botwidget/` is toolkit-free logic; `botwidget/qt_ui/` is the PySide6 UI.
- Test: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -t .` (unittest, not pytest; logic plus a few offscreen Qt tests).
- An output glitch (repeated text, a leaked tool name, a skill-nudge leftover) is fixed in the one sanitizing stage, `harness/stream_text.py`, and locked with a replay fixture under `tests/replay/`. Keep improving that stage and folding the next glitch into it, instead of adding another one-off patch.
- `git config core.hooksPath .githooks` so `.githooks/pre-push` runs that command when main is pushed and rejects the push when it fails.
- Run live: `botwidget --dev` (restarts on .py changes). Check UI changes by eye.
- To talk to a running widget's bot from a shell (the widget needs `"remote_control": true` in widget.json, off by default), use `botwidget bots | ask BOT TEXT | read BOT` (`botwidget/remote.py`; README, Talking to a bot from a shell). From a checkout run `.venv/bin/python -m botwidget ...`: the `botwidget` on PATH may be the uv install, which is another copy.
- `site/` is the static website (no build, deployed by Pages on push to main). `site/face.js` ports `avatar.py` and `animation.py` to canvas; keep them in step.
- Release: a tag `vX.Y.Z` pushed to origin builds and publishes (see README, Releasing). Bump the patch number of the latest tag (v0.1.0 becomes v0.1.1), not the minor one, unless told otherwise; when unsure, ask for the version before tagging, since a pushed tag starts the build at once.
- Pushing: stage only the hunks of the change itself (`git add -p`, or `git apply --cached`); a whole-file `git add` takes along unfinished work of the owner that sits in the same file, and its tests then fail on CI because their code is not pushed
- Pushing: the macOS run skips tests that Linux and Windows run (`skipIf darwin`), and the pre-push hook only runs on macOS. Do not run `scripts/test-linux` by default: push, and let the GitHub run say. Run it only when that run shows a failing Linux or Windows test, to reproduce the Linux side on this Mac and to check the fix before the next push (README, Testing on Linux from a Mac). Run it on its own, in the background, and never chain `orb stop` after it or run another `orb` or `docker` command while it runs: stopping OrbStack in the middle shows up as `Error waiting for container: Canceled: grpc: the client connection is closing`, which is no test failure. Run `orb stop` as a separate command once it has finished. Windows only runs on GitHub
- Pushing: one push is one CI run. Do not start a second run for the same commit (a re-run, or the release workflow by hand) while the first one runs, and do not push again before it has finished. A run for an older commit that a newer push replaced is cancelled
- Releasing: tag a commit only when a build-only run of the release workflow has succeeded for that exact commit (`gh workflow run release.yml --ref main`, which publishes nothing without a tag). Check that the run's `headSha` is the commit you tag: `gh run list --workflow release --json event,headSha,conclusion`. A green CI run does not count, because it tests and builds no app; a build of an older commit does not count either; a push after the build makes it an older commit. The CI run of that commit must be green too. Never tag to find out whether the build works
- Releasing: a tag whose release failed or never happened is deleted on origin and locally, and its number is used again. The next version is the patch number after the latest published release
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
- The bubble also stays while words are typed or selected, a draft is in the field, a file waits to be sent, a form was typed in, or the bot works
- Keyboard focus that came from resting the pointer on the face never keeps the bubble open, only typing, a click in the field or one of the reasons above does
- The bubble closes shortly after the pointer left: 0.4 seconds, longer while the pointer moves faster than 300 pixels a second, never beyond 1.5 seconds
- The bubble closes at once on Escape, when another face opens one, when a face is dragged, and when /screenshot starts
- The bubble closes when another window is clicked into with nothing typed, and where the pointer position is unknown (Wayland) it closes the moment the pointer is not on it
- An unread answer closes after its reading time unless the pointer was on it
- Clicking inside the bubble never opens or closes it
- Clicking the face while its bubble is open pins the bubble: it stays when the pointer leaves or another window is clicked, and the face keeps looking straight at you. Clicking the face again lets it go, and it then closes the usual way

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
- An approval shows a dot and a cloud with Accept and Decline, and Always allow when the agent offers to remember the command. The cloud opens by itself when the approval comes, also when the pointer is elsewhere, and goes by itself after the time it takes to read unless the pointer is on it; the dot stays. It waits ten minutes, and is logged with who answered
- A relay status of stuck or needs you shows that same dot. start and done do not. With no local approval the bubble shows the status line, not Accept or Decline
- A turn that a restart cut off is picked up again when the widget is back
- The eyes follow the pointer wherever it is
