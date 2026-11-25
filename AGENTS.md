# bot-widget

- Stay on the default branch. Do not create a branch unless asked. A branch that is asked for starts with `feature/`. Ask before committing. Never push on your own: wait until the owner says push, also after a green check or an earlier yes, because a yes covers that push only. Commits may pile up locally; the owner often pushes several of them in one go.
- `botwidget/` is toolkit-free logic; `botwidget/qt_ui/` is the PySide6 UI.
- Test: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -t .` (unittest, not pytest; logic plus a few offscreen Qt tests).
- An output glitch (repeated text, a leaked tool name, a skill-nudge leftover) is fixed in the one sanitizing stage, `harness/stream_text.py`, and locked with a replay fixture under `tests/replay/`. Keep improving that stage and folding the next glitch into it, instead of adding another one-off patch.
- `git config core.hooksPath .githooks` so `.githooks/pre-push` runs that command when main is pushed and rejects the push when it fails.
- Run live: `botwidget --dev` (restarts on .py changes). Check UI changes by eye.
- Restart the live widget after a change under `harness/` (the dev supervisor watches only `botwidget/`, and the `harness.agent` subprocess never reloads). Check first that the bot is idle (`.venv/bin/python -m botwidget read acp:local`, `active` false): a restart cuts a turn off, though it is picked up again afterwards. Then `.venv/bin/python -m botwidget --instances` lists the supervisor and its child: `kill` both pids, wait 3 seconds, and start `(nohup .venv/bin/python -m botwidget --dev > /tmp/bw-dev.log 2>&1 &)` from the checkout, never the `botwidget` on PATH (the uv install, another copy). After 20 seconds `.venv/bin/python -m botwidget ask acp:local "Zeg alleen: pong"` must answer. Killing only the agent leaves the link closed (`Connection closed`) and it does not come back. The agent command in `widget.json` already uses this checkout through `PYTHONPATH`. Ask the owner before restarting a widget that was running before the session started.
- One widget: `python -m botwidget --instances` (a `--dev` supervisor and its child are one). Do not use `pgrep` for that check.
- Fix a bug only with a general fix: one mechanism that covers the whole class of failure (any tool, any phrasing), never a patch for the one tool, word or case that showed it. A list of words per tool is a patch; when a heuristic is unavoidable, one shared list, not one per case. Example: a bot that ends on "ik ga het doen" without a tool call is nudged for every tool (`PROMISE_NUDGE` in `harness/agent/agent.py`), not only for browser questions.
- Findings from a bot or from the owner always go on the roadmap (`roadmap/` on main; there are no other long-lived branches), in the phase they belong to.
- To talk to a running widget's bot from a shell (the widget needs `"remote_control": true` in widget.json, off by default), use `botwidget bots | ask BOT TEXT | read BOT` (`botwidget/remote.py`; README, Talking to a bot from a shell). From a checkout run `.venv/bin/python -m botwidget ...`: the `botwidget` on PATH may be the uv install, which is another copy.
- `site/` is the static website (no build, deployed by Pages on push to main). `site/face.js` ports `avatar.py` and `animation.py` to canvas; keep them in step.
- Release: a tag `vX.Y.Z` pushed to origin builds and publishes (see README, Releasing). Bump the patch number of the latest tag (v0.1.0 becomes v0.1.1), not the minor one, unless told otherwise; when unsure, ask for the version before tagging, since a pushed tag starts the build at once.
- Pushing: stage only the hunks of the change itself (`git add -p`, or `git apply --cached`); a whole-file `git add` takes along unfinished work of the owner that sits in the same file, and its tests then fail on CI because their code is not pushed
- Pushing: the macOS run skips tests that Linux and Windows run (`skipIf darwin`), and the pre-push hook only runs on macOS. Do not run `scripts/test-linux` by default: push, and let the GitHub run say. Run it only when that run shows a failing Linux or Windows test, to reproduce the Linux side on this Mac and to check the fix before the next push (README, Testing on Linux from a Mac). Run it on its own, in the background, and never chain `orb stop` after it or run another `orb` or `docker` command while it runs: stopping OrbStack in the middle shows up as `Error waiting for container: Canceled: grpc: the client connection is closing`, which is no test failure. Run `orb stop` as a separate command once it has finished. Windows only runs on GitHub
- Pushing: one push is one CI run. Do not start a second run for the same commit (a re-run, or the release workflow by hand) while the first one runs, and do not push again before it has finished. A run for an older commit that a newer push replaced is cancelled
- Releasing: tag a commit only when a build-only run of the release workflow has succeeded for that exact commit (`gh workflow run release.yml --ref main`, which publishes nothing without a tag). Check that the run's `headSha` is the commit you tag: `gh run list --workflow release --json event,headSha,conclusion`. A green CI run does not count, because it tests and builds no app; a build of an older commit does not count either; a push after the build makes it an older commit. The CI run of that commit must be green too. Never tag to find out whether the build works
- Releasing: a tag whose release failed or never happened is deleted on origin and locally, and its number is used again. The next version is the patch number after the latest published release
- Windows SmartScreen: unsigned until `WINDOWS_CERTIFICATE` and `WINDOWS_CERT_PASSWORD` GitHub secrets exist. Buy a standard Authenticode cert, set those secrets, re-tag. Do not spend money from this agent. See README, Windows Authenticode.

## Keep these true

Each of these went wrong once. A test or a rule holds it now; keep both.

- A test run gets a temporary `HOME` (`tests/__init__.py`, checked by `tests/test_isolation.py`). A test never reads or writes the real home, and never assumes OpenBot, Grok Bot or Hermes is installed: a CI runner has none.
- Code that only works on POSIX (process groups, `sh`, file modes, adopting a job after a restart) has `skipIf(os.name == "nt")` tests, because Windows runs only on GitHub. Check `gh run view` after a push.
- A key goes only to `https://`, or `http://` to a machine of your own, never after a redirect, never in an error (`harness/agent/netsafe.py`). Every call that carries a key uses `open_url`, not `urlopen`.
- Stopping a process stops its whole group (`harness/agent/procs.py`). Never `proc.kill()` alone for a command that can start others.
- The dev supervisor ignores `_version.py`: a wheel build rewrites it, and a restart cuts a bot off in the middle of a turn.
- The stream stage (`harness/stream_text.py`) looks only at the end of the text: it runs on every piece of an answer, and a pattern over the whole text made a long answer quadratic (`tests/test_stream_text.py` holds the window).
- Always allow never saves a program that runs other code or commands, in any version or spelling (`never_saved` in `harness/agent/workspace.py`); a rule for one is a regex written by hand.
- A model name is never written in the code: ask the service (`acp_bots.fetch_models`).
- Ruff checks imports, pyflakes and bugbear (an `except` that raises says `from` what; a `zip` says its `strict=`). A dead-code scan (`uvx vulture`) must also read `scripts/`: files there have no `.py`.

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
- The bubble closes at once on Escape, when another face opens one, when a face is dragged, when the pointer clicks outside it, and when /screenshot starts
- The bubble closes when another window is clicked into with nothing typed, and where the pointer position is unknown (Wayland) it closes the moment the pointer is not on it
- An unread answer closes after its reading time unless the pointer was on it
- Clicking inside the bubble never opens or closes it
- Clicking the face while its bubble is open pins the bubble: it stays when the pointer leaves or another window is clicked, and the face keeps looking straight at you. Clicking the face again lets it go, and it then closes the usual way
- When the pointer leaves a menu page, the bubble closes the way it always did. The next hover, within page_memory_s seconds (60 when that key is absent from widget.json), opens that same page. After that many seconds the next hover opens the normal chat. A click away closes the bubble and forgets the page at once. Escape on a page or any sub-screen returns straight to the chat bubble and forgets the page (never one level up). A page shown under the pointer asks to be activated (`requestActivate`), including one that page memory restored, because a tool window otherwise never receives Escape. A line on that page does not swallow the key. Escape on the chat closes the bubble. The page is not written to config. A click on the face, or the line back to the command list, also forgets it
- The chat input field has a "/" button at the far right. Clicking it shows the slash-command list inline under the field. Typing "/" in the field does the same. Right-click on the face also opens this inline list (there is no separate command screen). While the command list is visible, the bubble's chat text (messages) is hidden; it returns when the list closes (Escape, picking a command, or deleting the "/"). The "/" button is hidden while the list is open. A list taller than the chat band scrolls inside the bubble. The field accepts typing only when no command list is up

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

## Desktop accessibility

- The user never runs an install command for this. Linux reads AT-SPI through PyGObject and the Atspi 2.0 typelib a GNOME desktop already ships (`gir1.2-atspi-2.0` and `python3-gi` in `botwidget/system/a11y.py`). `python3-pyatspi` is not a dependency. `botwidget doctor` links that system `gi` into the venv when it is missing. Importing `botwidget` does not. When `gi` is missing the probe says to run `botwidget doctor`.
- Startup logs once whether accessibility is available and why. The same line is in the harness runtime facts, and the read-only `accessibility` tool can name a running application.
- Windows (UI Automation) and macOS (AX) are named in that module and not implemented. A PolicyKit install is only for a desktop that is actually missing the typelib, and only after the user agrees in the widget. Do not print a sudo line.
