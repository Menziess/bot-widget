# Roadmap, risks and open decisions

A plan in small steps. Each step ends in something that can be tried and a test that proves it. The effort figures are rough guesses by one person who has not built it, so treat them as ordering, not as promises.

## Phases

### 0. Spike, one or two days

**Status: Done 2026-10-30. `harness/spike.py`; `hermes-acp` tried for real, a fake agent for the rest.**

A script, not the widget, speaks ACP to an existing agent, following the flow below.

```text
spawn the agent -> initialize -> session/new -> session/prompt -> print each session/update -> answer a permission request -> session/cancel
```

Done when these hold.

- Thought chunks, message chunks and tool calls print as they arrive
- A permission request is answered from the script
- A turn is cancelled and ends with the cancelled stop reason
- Startup time of each agent is known, because the face must not wait on it

Try at least two different agents, to see how much they differ in practice.

### 1. The widget adapter, two to four days

**Status: Done 2026-10-30. `botwidget/acplink.py`, driven in tests by `tests/fake_acp_agent.py`. Since then: an agent that leaves the desktop stays alive five minutes, closing never waits on the agent, and a message sent during an approval declines it.**

A link class with the same calls as the existing Grok and Hermes links, filled from ACP events.

Done when these hold.

- A message sent from the bubble shows the cloud with the latest thought as its activity
- The answer opens the bubble and plays the sound once
- A permission request shows Accept and Decline, and the choice reaches the agent
- A running turn can be cancelled
- A fake agent subprocess drives the tests, so no real model is needed

Rather than touching the face code, the adapter should hide behind the calls listed in 02-widget-contract.md, so the face stays unaware of which backend it has.

### 2. Lean agent v0, two to three days

**Status: Done 2026-10-30. Sqlite store per bot, `usage.jsonl`. The default model is now a local llama.cpp on :8081.**

An ACP agent with the chat completions adapter, no tools, a sqlite session store and a usage log.

Done when these hold.

- It answers through a local model and through one hosted provider
- A restart keeps the conversation
- Every turn appends a usage line
- The widget uses it as one more backend without a code change in the face

### 3. Tools and permissions, three to five days

**Status: Done 2026-11-02, and grown since. Built-in file and shell tools, one MCP server, three permission modes (ask, allow_session, allow), Copilot-style `approve` rules in `widget.json`, Always allow in the bubble, an approval log the bot can read, and an Edit approvals page (2026-11-16) that removes what was allowed for good.**

An MCP client, a few read-only built-ins, and permission requests for everything that writes.

Done when these hold.

- Tools from a configured MCP server work
- A write is refused until the user allows it
- Tool output is labelled as data in the prompt

### 4. Context builder, three to five days

**Status: Done 2026-11-02 to 2026-11-10. Stable prefix, pinned facts, context meter, Anthropic adapter measured against a fake API (95% cached by turn 20), a background extract so compaction keeps facts, large tool output spilled to a file, and topic-scoped durable memory with a `/memory` page.**

Stable prefix, trimming of old tool results, rolling summary, pinned facts, the Anthropic adapter with cache marks.

Done when these hold.

- A replayed twenty-turn script shows a high cached share on every turn after the first
- A session survives compaction with its pinned facts intact
- The context meter and the compaction notice reach the widget

### 5. Compare and decide, one or two days

**Status: Done 2026-11-10 with a scripted benchmark and a live llama.cpp mode. Decision: keep OpenBot for broad work, use the lean agent for short, read-mostly bots. Provisional until a hosted model is run behind both backends.**

Run the measurement plan from 04-efficiency.md and write down the result.

Done when a decision is recorded, keep OpenBot for everything, use the lean agent for some bots, or drop the idea.

### 6. Self-modify, one to two weeks

**Status: not started.**

The widget picks up a task itself, builds it, restarts with rollback, and self-tests. No teacher sends the task.

Done when these hold.

- A task written on this roadmap is taken by the running widget with no teacher message
- The widget builds that task in a worktree, runs the suite, and restarts the existing `--dev` process only with SIGUSR1
- A red suite or a failed health check resets the checkout to the last good commit and restarts again
- After a green restart the widget runs one check that reads a file it just wrote, and the file matches
- Three tasks in a row finish this way, and the scoreboard shows the widget as the one that took them

## Order and cut points

Stopping after phase 1 still has value, because the widget then supports many existing agents. Stopping after phase 2 gives a minimal own backend. Phases 3 and 4 are where the savings come from, and also where most of the work and the risk sit.

## Risks

| Risk | Why it matters | What reduces it |
| - | - | - |
| Adapters of other agents differ in quality | The widget inherits their bugs | Test with two or three, keep a list of which behave |
| ACP is shaped for coding sessions | Chat bots have no working directory | Fixed directory per bot, tools chosen by the agent |
| Permission prompts are noisy | A chat bubble is a small place | Start with read-only tools |
| An own agent must be kept up to date | Provider APIs change often | Few adapters, one internal item model, tests per adapter |
| Safety moves from OpenBot to us | A loop with tools can do damage | Read-only first, permission for writes, no secrets in context |
| The saving is smaller than hoped | Hosted agents may be well tuned | Measure first, compare cost per finished task |
| ACP remote transport is unfinished | A daemon would need it | Start with a subprocess, keep the store on disk |

## Open decisions

Questions only the owner can answer. Settled so far: the lean agent is one process per bot, memory has user, project and topic scopes, and a local model is the default.

- Which backends matter first, among Pi, OpenCode, Hermes, Claude Code and Codex
- Which models to offer besides the local default
- Whether the widget should keep OpenBot as the default backend
- Where the code lives, as a separate package or repository so that the widget stays thin
- How much of OpenBot's feature set is wanted at all, teammates, routines, browser

## What is next

- Run one hosted model behind both OpenBot and the lean agent on twenty tasks each, to settle cost per finished task
- Try a second real ACP agent (OpenCode, Claude Code or Codex), to see how much adapters differ. OpenCode is done: `18cf2e5` (2026-11-17), OpenCode 2.1.3 over `opencode acp`, protocol 1, stop reason end_turn. It sent available_commands_update with an empty command list before the answer. The client leaves that update off the first-answer clock. Since `edab6ed` the lean agent sends the same update when it has skills. A one-word prompt on the local model took about 209 seconds to the first text. Claude Code and Codex are not tried.
- Decide whether approvals should be removable per bot, not only for all bots at once
- Attach to the running everyday Chrome over CDP, browser-use-style. Chrome's "Allow remote debugging?" consent once, then the existing session: his own tabs and logins. No extension, no separate profile, and no `--remote-debugging-port` relaunch. The base stays the direct-CDP reader in `harness/browser_local.py`, not the browser-use package, Playwright, or an extension.
- Requirements: `list_tabs`/`switch_tab` to reuse existing tabs; never open a new window (a new tab in the existing window only when needed); `goto_url` + `wait_for_load`; read via `document.body.innerText` plus background-tab screenshots; click via JS `element.click()` on an element found by its text; `fetch()` inside the page using the logged-in session, and never display or store tokens.
- OpenCode Browse (`anomalyco/browse`) is the fallback only, and it needs an extension.
- Chrome, read only: done 2026-11-17. The lean agent has `browser_tabs` and `browser_read` (`harness/agent/tools.py`) over the direct-CDP reader in `harness/browser_local.py`. Chrome's "Allow remote debugging?" consent once per connection, then the existing session: his own tabs and logins. No extension, no separate profile, no `--remote-debugging-port` relaunch. One socket is kept for the life of the agent, so Chrome asks once and not per question. The port comes from `lsof`, because macOS keeps other apps out of Chrome's own folder (`DevToolsActivePort` gave "Operation not permitted" without Full Disk Access); Chrome takes `/devtools/browser` without the id from that file. The port file stays as the fallback, with the macOS, Linux and Windows paths. Tried on macOS only: Linux and Windows are not tried.

### Feature requests, 2026-11-17

Still open, except the line marked done. In the order the owner asked.

- **Browser actions as tools.** Click by text, go to an address, open a tab, scroll and fill in forms. `Cdp` already has `click_text`, `goto_url`, `open_tab`, `screenshot` and `page_fetch`; scrolling and filling forms do not exist yet. Every action that changes a page asks first, like a write.
- **Other browsers.** Edge and Brave speak the same protocol and only need their folders and process names. Arc is probably the same. Firefox needs WebDriver BiDi. Safari has no equivalent.
- **Skills in the lean agent.** Done. `edab6ed` advertises each skill as a slash command and runs it. `ea42592` ends the skill on done, on a message that is not about it, on cancel, or after ten minutes, with no /stop. `ac7a6bb` hides the tools a skill names in deny-tools. The system prompt tells the bot when clicking and forms need the browser-use MCP server.
- **browser-use over MCP.** Tried 2026-11-17 through `HARNESS_MCP_SERVER="uvx --python 3.12 browser-use@latest --cli-mcp"`: the server starts, adds `browser_exec`, `browser_screenshot`, `browser_login` and `browser_feedback`, and `browser_exec` read the tabs of the local Chrome. It runs on this machine and drives the local Chrome; cloud browsers only start with `browser_login`. Open points: `browser_exec` runs any Python, so it must keep asking; `browser_login` and `browser_feedback` (sends text to the vendor) should not be offered; no model has decided between the built-ins and this server yet.
- **A permanent Allow.** Chrome has no setting for it. The ways round it are a native-messaging extension or a tool that clicks the dialog; both are against the choice in `browser-choice.md`.
- **A bot that repeats its last failure.** After a failed tool call the local model sometimes answers from history and never calls the tool again, so a fixed problem looks unfixed. Drop or mark failed tool results once they are stale. Not done: a declined write stays in the next request so the model still sees it.
- **Linux and Windows.** Try the port lookup (`lsof -c chrome`, the `%LOCALAPPDATA%` file) on those systems.

### Bubble, demo, sample thought, 2026-11-21

Done on main. Planned for /demo: show the checklist in a normal chat bubble instead of a separate DemoBoard window (which has no close button); add real CDP check for browser row (reuse existing tab); make process row wait until the chat turn finishes before reading the file; add computer-control task with a code verifier on a throwaway window.

- A click outside collapses the bubble and forgets the page. A hover-leave reopens that page for `page_memory_s` seconds (60 when widget.json has no such key), then the next hover is the normal chat. Escape on a page brings the chat back and forgets the page (`6039011`, after `0caa69d`).
- `/demo` is only there with `--dev`. It sends the six tasks through the chat. Code checks the outcome. The `/tmp/t-demo/enable` file no longer starts a run. `ffad165`.
- The "Sample thought..." settings switch is gone. An old `debug` key in widget.json is left in the file and ignored. `ffad165`.

### Desktop computer use, 2026-11-21

Update 2026-11-26: built, see "Turn loop, self-knowledge and the computer, 2026-11-26" below. The text here is the design it was built from, and the state of 2026-11-21.

Not built on 2026-11-21. Asked that day, the bot said it can only use the tools in the chat, and that is what the code did then.

Nothing in the tool list is a computer-use tool: move the pointer, press keys, then see what changed. Checked the builtins in `harness/agent/tools.py`, the workspace tools, and the MCP tools the agent forwards. `deny-tools` only hides tools a skill already has. `Cdp.screenshot` and `Cdp.click_text` are one Chrome tab, and the model is not offered them (see Browser actions as tools above). The widget screenshot is the user dragging a region; the picture waits as an attachment. `harness/capability.py` scores `computer_use` as zero because a blank session has no display.

Design, for when it is built:

- Each action asks in the existing approval bubble, Accept or Decline, one action at a time. Always allow is not offered for pointer or keyboard actions.
- After an action is allowed, see what changed through the operating system's accessibility API: AT-SPI on Linux, UI Automation on Windows, and the AX API on macOS, including the title of the focused window. A screenshot is only the fallback when that API is missing or empty, because a screenshot is slower and creates a file. Any screenshot file is deleted right after it has been used. The picture is shown to the model only when that model can see images. The tool does not watch the screen between actions.
- Linux under X11, macOS, and Windows. Where the platform cannot move the pointer, the tool says so and does nothing.
- Off unless the owner turns it on for that bot. It is not in the default tool list.

Linux check, 2026-11-21. The widget probes AT-SPI at startup through PyGObject and the Atspi 2.0 typelib (`gir1.2-atspi-2.0`), which this Ubuntu desktop already has. `python3-pyatspi` is not used. One log line, the same fact in the harness runtime facts, and a read-only `accessibility` tool that can name a top-level application (the widget's own name on the bus is `botwidget`). Windows UI Automation and macOS AX are named and not implemented.

Pointer and keyboard, 2026-11-21. The tools are `computer_click`, `computer_scroll`, `computer_type`, `computer_key`, `computer_drag`, `computer_move` and `computer_window` (minimize, restore, maximize; added 2026-11-27, macOS only). Each one is a write, so the existing approval bubble asks Accept or Decline and does not offer Always allow. A decline does not call the backend. Linux calls `xdotool` on X11 and `ydotool` on Wayland when that program is on `PATH`. This machine's session is Wayland and neither program is installed, so a global click says so and does nothing. `CONSENT` in `botwidget/system/control.py` names `xdotool` and `ydotool`. Nothing calls `pkexec`. The widget can move its own window without those programs. Windows and macOS raise not implemented. `/demo` adds a computer row that ticks only when a window the demo opened is at the asked position and the asked text is in its field. That window is closed again.

A fresh venv gets that system `gi` by a symlink from `botwidget doctor` (`link_system_gi`). Importing `botwidget` does not link it. When `gi` is missing the probe says to run `botwidget doctor`. Done 2026-11-21.

The in-widget consent dialog is not built. `CONSENT` in `botwidget/system/a11y.py` is the design: title, the two desktop packages, Agree or Not now, and `install_after_agree` as the only install entry. Nothing calls `pkexec` until that dialog exists and the user picks Agree. Add the dialog when a real probe returns available false.

The system prompt names `accessibility`, and a reply that skips the call is nudged once. The tool result lists application names even when query is empty. Self-modify is phase 6.

### Bubble page, demo checklist, and doctor, 2026-11-21

Asked as three changes. The page memory and the doctor step are on main. A row ticks only after a verifier checks the outcome. `/demo` (dev only, `ffad165`) sends the tasks through the chat. The old `/tmp/t-demo/enable` file does not start a run. `--demo` still opens the checklist window.

- The next hover after the pointer leaves a menu page opens that same page, for `page_memory_s` seconds (60 when the key is absent). After that the next hover opens the chat. A click away closes the bubble and forgets the page. Escape on a page returns to the chat and forgets the page. Escape on the chat closes the bubble. Session memory only, no config write. Done 2026-11-21 (`0caa69d`, `6039011`).
- `botwidget doctor` is the step that links the desktop `gi`. The probe no longer fixes a missing `gi` by itself. Done 2026-11-21.
- The local demo is a checklist of browser (CDP attach, reuse a tab, never a new window, blocked when CDP is down and Chrome is not started), a file written and read back, a script written and run, a background process started, checked and stopped, an accessibility read, and a seeded failing test that is repaired. `/demo` sends those prompts through the visible chat and ticks a row only from the code checkers. Done 2026-11-21 (`ffad165`).
- The Settings switch "Sample thought, click the face for a sample message" is gone. An old `debug` key in widget.json is left in place and ignored. Done 2026-11-21 (`ffad165`).

### Slash-command inline list, 2026-11-22

Replaced the separate slash-command screen with an inline list under the chat input field. Added a "/" button (SlashButton) at the far right of the field; clicking it, typing "/" in the field, or right-clicking the face all open the same list. While the list is visible, the bubble's chat text is hidden; it returns when the list closes. The old standalone command screen is removed. AGENTS.md and README updated with new bubble rules. Done 2026-11-22 (`f7483fc`).

### Menu, reset and /demo, 2026-11-23

Done: /refresh is gone, Reset is a button per bot on /bots (AcpLink.reset starts a fresh session); the slash list scrolls; /bots and /connections show a named element's buttons under its name; Memory and Approvals lead back to the command list; /demo plants the repair seed and clears old files, so a leftover no longer ticks a task; the stage drops a glued `done` while a skill runs; ruff checks F and I.

Open:
- Model providers. A Provider button on New connection fills the address of xAI, OpenAI, OpenRouter, Google Gemini, GitHub Models and Anthropic (the address picks the API); the models come from the service (`/models`), as in LibreChat and Goose. opencode instead reads the community catalog models.dev (about 7 MB, 300+ providers, cached on disk with a bundled snapshot); that would remove the addresses too but is heavy for this widget, and the big first-party services have no address in it either. A catalog could be an optional second source. Still open: a subscription login (Copilot, Claude) needs a token exchange; LiteLLM covers that but is a large dependency for an agent that is stdlib only on purpose. Anthropic has its own adapter in `harness/agent/models.py` that the connection form does not offer yet.
- A subscription login like `opencode auth login` (GitHub Copilot). opencode runs the OAuth device flow (RFC 8628) with its own registered GitHub OAuth app and then calls the Copilot API with that token. Not built here: the client id belongs to opencode's app (using it would show its name on the consent screen), the Copilot API for third parties is undocumented, and nothing here can be tested without a Copilot account. The documented route is GitHub Models (`models.github.ai/inference`) with a token that has `models: read`: a fine-grained personal access token works today in the key file. A device flow for your own GitHub App (expiring tokens, a refresh token, the client id in widget.json) is the secure way to automate it.
- Done 2026-11-23: /demo ticks Browser when the bot names the right number of open tabs (only Chrome can tell it; blocked when Chrome is not listening) and Computer by code after the chat tasks (a window of its own is moved and typed into).
- Animations, done 2026-11-23: a finished background job (Done_B), a reset (Blocked_C), a wink on accept, dazed eyes after a throw, a working mood while a tool runs, and a doze after five quiet minutes. Not yet: eyes for love.

### Turn loop, self-knowledge and the computer, 2026-11-26

Done on main (`dc5863f` to `8bb4e7b`; CI green on macOS, Linux and Windows).

The turn, as data (`harness/agent/turn.py`):
- A step is reasoning, text and tool calls. A step with tool calls is progress and goes to the cloud as a thought; only the closing step is the answer. A notice of the harness (a loop it stopped, the step limit) is a message of its own. Every chunk carries an ACP `message_id`, and the widget starts a new message when it changes.
- A request or a claim is an obligation that only a call of the right tool discharges: one `Obligation` class and a table (the desktop asked for, a tool named, a place named, a change asked for, a promise, a claim of done, a claim of written). A guard speaks at most once per reason, so a turn always ends. A guard that asks for exactly one tool makes the next request call it (`tool_choice`, both adapters).
- A skill left in the conversation by an older version is cleared each turn. A job the bot cancelled itself does not start a new turn. The same call three times inside one answer is one step for the loop detector.
- Measured and left alone: moving the changing context blocks after the history, to help the cache. On the local llama.cpp it was worse (680 new tokens against 112).

The bot knows itself, lazily:
- `about_me` answers one topic at a time (skills, bot, commands, settings, approvals); `run_command` runs any slash command and `change_setting` and `move_me` change a setting or the widget, each after Accept. The widget answers over an ACP extension method; the agent asks the widget for none of this up front.
- An approval reads `shell: ls -la`, not a dict. `search` takes a path. `write_file` says how the file ends. The tab list is numbered and counted.

Chrome:
- Chrome asks for Allow on every new connection and cannot remember it (open request ChromeDevTools/chrome-devtools-mcp#825). The browser tools use the browser-use daemon's connection when it runs, so one Allow serves `browser_exec` and `browser_tabs`; a declined connection is not tried again at another address of the same Chrome; a slow answer keeps the connection.

The demo (`/demo`, dev only) has ten chat rows and the computer row: browser, files, script, process, accessibility, repair, search outside the workspace, recover, order, commands. The checklist is a line in the conversation.

Computer use on macOS (`botwidget/system/macos_desktop.py`):
- Through osascript, with scripts that are constants and arguments in JSON. `accessibility` lists the running apps with their windows (title, place, size). `computer_click`, `computer_type`, `computer_key`, `computer_scroll` and `computer_drag` act anywhere; `computer_move` puts the window of another app somewhere, with a size. Tried live: on a Finder window move, resize, drag by the title bar and close with cmd+w; on a window of its own click (it becomes the active window), scroll (0 to 3 lines) and select-all plus typing (the text was replaced).
- macOS has to allow it once: Accessibility for the app that runs the widget, and Automation for System Events. Until then the tool says what to allow.

Open, in the order the owner asked on 2026-11-26. Bugs and todos are in `___/todo.md`.

- **Bring a window to the front.** Not built. The bot can list windows and move them, not raise one or switch to an app. On macOS that is `frontmost` of a System Events process, or `AXRaise` of a window; also open an app or a file the way `open -a` does.
- **Do what a user does.** The aim is that the bot can do anything a person does at the machine, each step after Accept: write in a text field, press a button, scroll, drag, enlarge, minimise, maximise, close, switch app, pick a menu item, open an app or a file. What it needs:
  - See the controls, not only the windows: the accessibility tree of an app (role, name, place, value), so a button is pressed by its name and not by a guessed coordinate. `AXPress` and setting `AXValue` are the right actions for a button and a text field; a coordinate click stays the fallback.
  - Window state: minimise, maximise (zoom), full screen and close, through the window's own buttons or attributes.
  - Menus: pick an item of the menu bar by its path.
  - See what changed after an action, through the same tree, and a screenshot only as the fallback (the design of 2026-11-21).
  - Another desktop (Space) and another display.
  - A limit the owner sets: which apps the bot may touch, and a refusal list for the ones that hold secrets (Keychain, password managers, System Settings).
  - Always allow for one app and one kind of action, not for the pointer in general.
- **Windows and Linux.** Windows is a stub. Linux has `xdotool` and `ydotool` for the pointer and keys, and no list of windows or move of another app's window (`wmctrl`, or AT-SPI on GNOME).
- **One approved Chrome connection for everything.** The MCP server and the daemon share one; `browser_tabs` uses it when it runs. When the daemon is down the agent opens its own, and Chrome asks again.

### Open from the teacher rounds, 2026-11-21

Skip what is already done (idle send, named python and unsigned commit, student-worktree approvals, the `gi` link, the instance check that ignores a prompt, false file and commit claims).

- Pointer and keyboard actions. The tools and the approval gate are in. Global input on Wayland still waits on `ydotool` (see Desktop computer use above). The widget moving itself does not.
- The consent dialog above. Design and `install_after_agree` only.
- A write outside the home workspace still raises the approval bubble. The supervisor may accept it when the title stays inside the student tree. A person should not see that bubble for a path the loop already allowed.
- Done 2026-11-23: after a tool call that failed, a closing message that does not own up to it is held back and nudged once (`FAILED_NUDGE`), whichever tool it was; and a line written before the accessibility call is never shown, because it guesses the result.

### Owner findings, 2026-11-26 (second round)

Done: the bot ran `/demo` for a task (the `run_command` text named /demo; it now says only on request by name), and the demo checklist stayed under every later answer (it goes with the next message); a promise like "laat me eerst even kijken" now counts as a promise without a tool call (`PROMISE`); "Waking" showed on every send (now only on a cold start); a thought or tool update that arrives after the turn ended left the cloud up (ignored when no turn runs); a question outranks the click that swaps the cloud for the last answer; a muted bot sleeps (lids mostly shut) instead of a cross for a mouth; the memory text is an editor, not one line; the demo's commands row also asks the bot to find its own source folder, and the system prompt asks for that.

Second pass, same day: the cloud is tighter (the dots of a cloud take a gap of 0 and a pad of 4 instead of 10 and 11, `PAD_DOTS_Y`). A memory page of 100 memories already stays inside 70% of the screen and scrolls (a test holds it); that cap is the "grows taller" the owner saw, and a smaller one for lists is the owner's call.

Open: macOS asks "python3.xx wants to control this computer" because the process that runs the code is the Python interpreter; macOS names the process, and the code cannot change that. A packaged app asks under its own name; a run from a checkout does not.

## Where to start (historical)

The spike in phase 0 costs the least and answers the largest unknown, which is how well existing agents behave through ACP. Everything after it depends on that answer.
