# Daily MacBook wishes (t1141u)

Tests-first plan for five wishes Stefan asked for on 2026-11-24, because he uses bot-widget every day on his MacBook (and `--dev` on the PC). Nothing in this file is built yet. Each work block is one Grok Build `/goal` (or a local llama.cpp pass for logic and tests), small enough for the 3% Grok Bot budget cap. Prefer the local model for simple blocks. Stay on `main`. `widget.json` is never committed. A test widget uses a temporary config. Only one `--dev` widget at a time (`python -m botwidget --instances`). No manual sudo: a missing system package is installed only through the app's PolicyKit consent, after a yes in the widget (`botwidget/system/control.py`, `CONSENT`, and AGENTS.md).

Findings belong on `roadmap/` on main (AGENTS.md). This file is the plan; the design questions at the end are the only ones that need a General or Stefan decision before the matching block is built.

## What already exists (shared)

- Slash commands, including `/screenshot`, `/feedback` and `/demo` (dev only): `botwidget/menu_pages.py` `COMMANDS` (19–22), `commands()` (32–55); dispatch in `botwidget/qt_ui/face.py` `on_user_message` (1825–1852), `start_screenshot` (717), `open_feedback` (1672–1689), `_start_demo` (1874–1881). Tests: `tests/test_feedback.py`, `tests/test_screenshot_discoverable.py`, `tests/test_screenshot_mode.py`, `tests/test_skill_commands.py`, `tests/test_demo_command.py`, `tests/test_slash_button.py`.
- Approval and question cloud: Accept / Decline / Always allow, a pending dot, a ten-minute wait, typed answers to an open question (`face.py` `_attention_blocks` 1988–2028, `_attention_command` 1456–1466, `_open_question` 1969–1979, `_give_answer` 2044–2054). ACP decisions go through `AcpLink`; OpenBot approvals through `_send_attention`. The approval log is append-only from the widget (`harness/approvals.py`). Shell: `botwidget approve|decline` in `botwidget/remote.py` (needs `"remote_control": true`, off by default).
- Skills in the lean agent, advertised as slash commands: `harness/agent/agent.py` `_advertise_skills` (186–191), `_skill_target` / `_run_skill` (202–278), `SKILL_IDLE_S = 600` (73), nudges when a skill turn ends without a tool call. Tests: `tests/test_harness_skills.py`, `tests/test_skill_commands.py`.
- Background shell jobs that outlive the bubble and are adopted after a restart, with a timeout, a cap, and secret redaction, but no stall detector for a silent job: `harness/agent/jobs.py` (`JobRunner.start` 203, `_watch` 329, `adopt` 283). Tests: `tests/test_harness_jobs.py`.
- Scheduler-like behaviour today is only UI timers, start-at-login, and GitHub update checks: `botwidget/qt_ui/app.py`, `botwidget/updates.py` `newer_release` (53), `botwidget/startup.py` `set_enabled` (35–44), `botwidget/supervisor.py`. There is no widget-native routine list or watchdog.
- OpenBot already has routines of its own; the widget hides those messages from the chat (`botwidget/openbot.py` `_chat_text`, 206–207: `source == "routine"` returns empty). That is OpenBot's scheduler, not the widget's.
- Settings live in `widget.json` under the app data dir (`botwidget/config.py` `APP_DIR` / `CONFIG_PATH`, 10 and 66–67; `SETTING_KEYS` 70–72, comment: "no secrets go in here"). Paths: Linux `~/.config/botwidget` (`system/linux.py` `data_home` 168–170), macOS `~/Library/Application Support/botwidget` (`system/macos.py` 50–51), Windows `%APPDATA%\botwidget` (`system/windows.py` 135–136). Tests isolate `HOME` (`tests/__init__.py`, `tests/test_isolation.py`) and point `CONFIG_PATH` at a temp file (see `tests/test_skill_commands.py` `_temp_config`).
- Secrets today: OpenBot's Bearer token is read from OpenBot's own headers file (`config.py` `HEADERS_FILE` 16, `openbot.py` `read_auth_token`). The lean agent refuses private paths (`harness/agent/tools.py` 42–43) and redacts keys in job output (`jobs.py` `redact` 70). There is no OS keychain, and no consent gate before a secret is used. Computer-control PolicyKit consent is designed but the in-widget dialog is not built (`system/control.py` 14–21, `CONSENT["built"] is False`; still open in `roadmap/05-roadmap.md`).
- Phase 6 on the lean-backend roadmap ("Self-modify", `05-roadmap.md`) is a different idea: the widget taking a roadmap coding task itself. Do not fold these wishes into that phase.

## Order

The consent/confirm primitive is the foundation of wishes 1, 3 and 5. Build in this order. Do not start a later wish until the earlier one's unit tests and smoke are green, except that later tests may be written as soon as the interfaces exist.

0. Confirm primitive (shared)
1. Wish 1 — feedback, confirm the exact text, send only after yes
2. Wish 5 — vault (OS keychain, consent before each use)
3. Wish 3 — suggest a widget action and run it only after yes
4. Wish 4 — long-running goals without slash commands, stall detection, report back
5. Wish 2 — self-wake routines and a watchdog (uses 4 to do the work, 0 to confirm a new routine)

## 0. Confirm primitive

**Why first.** `/feedback` sending the wrong text, a suggested `/screenshot`, and every vault read all need the same rule: show the exact payload, and act only after an explicit yes for that payload.

**What exists.** The approval cloud and OpenBot questions (citations above). `confirm_remove` on a menu row is a second click, not a payload confirm (`menu_pages.py` `_remove_button` 136–139). None of these hash a body of text and refuse a yes that no longer matches.

**Design.** A toolkit-free module `botwidget/confirm.py`. One pending `ConfirmRequest` per bot: `id`, `kind` (`feedback` / `action` / `vault` / `routine`), the exact `payload` string the user saw, a hash of that payload, the callback name, and an expiry (use the same ten-minute window as approvals unless a test needs a shorter one). The bubble renders the payload in a `code_block` (or wrapped text) plus Yes and No. A Yes is accepted only when the hash still matches; a typed "yes" in the field counts only while this request is the open question. No "Always allow" for `feedback` or `vault`. Decline, timeout, a changed payload, or a second request replacing the first, all leave the action unrun and write a line to the approval log (`harness/approvals.py` `record`). Logic stays out of `qt_ui/`; the face only shows blocks and forwards the click, the same way it does for approvals.

**Tests first**

- Unit (`tests/test_confirm.py`): yes with the same hash runs the action once; yes after the payload changed is refused; no / timeout / a second request never runs it; `feedback` and `vault` cannot be marked always-allow; a typed yes is ignored when no confirm is open.
- Offscreen smoke: a temp-config face shows the payload and the Yes/No row; clicking Yes calls the stub once; clicking No does not.

**Blocks**

- **0a.** Write the unit tests and the offscreen smoke (no implementation yet; they fail).
- **0b.** Implement `botwidget/confirm.py` and hook it into `_attention_blocks` / `_menu_command` so Yes/No and a typed answer work. Local model is enough.

**Depends on.** Nothing. **Unlocks.** 1, 3, 5, and the "save this routine?" step of 2.

## 1. The bot posts feedback itself, only after a yes for that exact text

**What exists.** `/feedback` opens a prefilled GitHub new-issue page in the browser. The title is always "Feedback". The body is only version, OS and install kind. The app has no GitHub token (`menu_pages.py` `feedback_issue_url` 58–64; `face.py` `open_feedback` 1672–1689). Tests lock that shape and the absence of a token (`tests/test_feedback.py`). The user is expected to type the report in the browser. That is how a report can go out without Stefan having agreed the wording in the widget, and also how the bot cannot "post feedback itself".

**Design.** `/feedback`, or a clear user ask such as "send this feedback: …", never posts on its own. The widget (or the bot) prepares a draft title and body, shows that exact text through the confirm primitive, and only then sends. If the user has not supplied the wording, the bot asks what to send and waits; it must not invent a report. After a yes for that exact text:

- Prefer `gh issue create` against `Menziess/bot-widget` when `gh auth status` is already good (gh's own store, not widget.json).
- Otherwise open the existing prefilled issue URL, now filled with the confirmed title and body, and tell the user the browser still needs Submit.
- Once the vault exists, a stored GitHub token may be used, and only after a second, vault-kind confirm for that use.

Keep the no-token browser path as the fallback so a machine without `gh` still works. Never put a token in the URL, in a log, or in the bubble. Do not offer Always allow.

**Tests first**

- Unit: a draft is required; an empty or model-invented body (no user-supplied wording and no confirmed edit) is refused; yes posts exactly the confirmed title and body (the sender is a stub); no / a changed body / a second yes does not call the sender; the URL still contains no token; `feedback_issue_url` accepts a confirmed title and body.
- Offscreen or subprocess smoke with a fake `gh`: `/feedback` with a given text, decline, assert the fake was not called; repeat with yes, assert one create with that exact body.

**Blocks**

- **1a.** Tests above, including an extended `feedback_issue_url`.
- **1b.** Draft + confirm + stubbed sender; browser fallback with the confirmed text. Local model.
- **1c.** Real `gh issue create` path, skipped in CI when `gh` is not logged in. Only after 1b is green. A live smoke is a `--dev` widget with a temp config, never the daily MacBook widget, and should target a dry-run or a throwaway issue only with Stefan's yes.

**Depends on.** 0. Vault (5) is optional and only for 1c's token fallback.

## 2. Self-wake via routines, with a watchdog

**What exists.** Start at login, update checks, Qt timers, the `--dev` supervisor (`supervisor.py`, `instance.py`: a supervisor and its child are one widget). OpenBot routine messages are hidden in the chat (citation above). Grok Bot routines live in Grok Bot, not here. Jobs have a timeout and adopt-after-restart, not a routine schedule. Phase 6 is not this.

**Design.** Widget-native routines, in the widget process, so they run whenever the widget is running (including after login). They do not wake a powered-off machine and they do not install launchd, systemd or Task Scheduler units in v1. A routine has an id, a name, a schedule or a trigger (cron-like interval, or an event such as "widget started"), a bot, a prompt or a goal id, and enabled/disabled. When it fires, the widget asks that bot, or starts a wish-4 goal, and reports in the bubble with a clear "this was a routine" line (do not silently hide it the way OpenBot routine source is hidden).

Watchdog: a heartbeat file under `APP_DIR` (last progress time, routine id, pid). If a run makes no progress for a set interval, mark it stalled, tell the bubble, and refuse a second overlap of the same routine. A `--dev` reload must adopt or drop the run cleanly, the same way jobs are adopted. Saving or enabling a new routine uses the confirm primitive.

Storage is a design question (below). Do not put routine payloads in `widget.json`, and do not put secrets there.

**Tests first**

- Unit (`tests/test_routines.py`): parse a schedule; a due routine fires once and not again until the next due time; a disabled routine does not fire; a hung run with a frozen heartbeat is stalled and reported; a second overlap is refused; a reload adopts a still-running run; a confirm is required to enable a new routine.
- Smoke: a `--dev` widget with a temp config and a +20 s routine; it fires, the bubble shows the routine line, the watchdog marks a stuck fake run. Not on the daily config. Check `python -m botwidget --instances` first.

**Blocks**

- **2a.** Tests for the store, the scheduler clock, and the watchdog (fake clock).
- **2b.** Store + in-process scheduler behind a `--dev` flag or a hidden setting until the smoke is green.
- **2c.** Wire firing to a bot prompt or a wish-4 goal, the bubble line, and the confirm on save. Smoke on the PC with a temp config.

**Depends on.** 0 for "save this routine?". 4 for "run this goal", otherwise a plain prompt is enough for a first smoke. **Unlocked by.** 4, but 2a/2b can start after 0 if 4 is still in flight.

## 3. Suggest a widget action and carry it out with a built-in feature

**What exists.** The bot can already *use* tools and the user can already pick `/screenshot` (citations above). There is no path for the bot to propose "shall I take a screenshot?" and, after yes, call `start_screenshot()`. Computer-control actions already require an approval (`system/control.py` `perform(..., approved)` 236). Windows and macOS computer control are named and not implemented (`system/control.py` 5–6); do not suggest those there.

**Design.** A small allow-list of *widget features* the bot may propose, each mapped to an existing handler: `/screenshot` → `start_screenshot`, `/settings` → `open_menu("settings")`, and later others that already exist. The model (or a deterministic hint) may only *suggest*. The confirm primitive shows the action name and what it will do ("I'll open screenshot mode; you still pick the region, and nothing is sent until you send"). On yes, the face runs that handler. On no, it does nothing. Screenshot mode stays as it is today: the picture waits in the field and nothing goes out until the user sends (AGENTS.md, Screenshot and attachments). Feedback, vault, quit, install, and sending a message are never auto-run from this list. Whether a later "Always allow for /settings" exists is a design question; v1 can confirm every time.

**Tests first**

- Unit: a suggestion for `/screenshot` does not start mode until yes; yes calls `start_screenshot` once; no does not; an unknown or disallowed action (quit, feedback, vault, send) is refused even if "yes" is injected; a suggestion is just a confirm, not a user message in the outbox.
- Offscreen smoke: temp-config face, inject "shall I take a screenshot?", Yes, screenshot mode starts and the bubble closes the way `/screenshot` already does (`test_screenshot_mode.py` is the pattern).

**Blocks**

- **3a.** Tests and the feature map (no model required).
- **3b.** Hook suggestions from the lean-agent tool side or a widget-side "propose_action" the face understands; dispatch only through confirm. Local model for the wording; the gate is deterministic.

**Depends on.** 0. **Unlocks.** 4, which may suggest the next step of a goal.

## 4. Work on a goal for a long time without slash commands

**What exists.** Skills start when the message begins with `/name` (`agent.py` `_skill_target` 202–212). A skill that waits more than `SKILL_IDLE_S` (600 s) is dropped so the chat can answer (73, 220–223). Skill nudges cover a turn that ends without a tool call, not a long silence. Jobs cover background shell work with a timeout, not a user-level goal. There is no intent recognizer that starts a skill without a slash, and no stall report in the bubble.

**Design.** This is not phase 6 self-modify. A "goal" is a user intention that may run for minutes to hours: recognize it, start (or attach) a skill or a job, watch progress, detect a stall, and report.

Intent: a small, toolkit-free classifier in the lean agent. Prefer a tight rule first (clear task verbs plus an object, and not a short question) and only then a local-model check. If unsure, ask "Shall I start this as a background goal: …?" through the confirm primitive, rather than starting a skill by accident. Starting a skill still loads the same skill body as a slash command, so existing skill tests stay the source of truth.

Progress and stall: reuse `skill_active` and job heartbeats. If there is no tool call, job output, or user reply for a stall interval (shorter than `SKILL_IDLE_S` for the watchdog ping, longer before giving up), post a status line in the bubble ("this goal has made no progress for N minutes") and optionally nudge once. A finish calls `done` as today and reports the result. A restart adopts the goal the way jobs are adopted.

**Tests first**

- Unit: "please keep refactoring X until the tests pass" starts (or proposes) a goal without a slash; "what time is it?" does not; a slash skill still wins when the message starts with `/name`; a frozen heartbeat is a stall and produces one report; a later tool call clears the stall; adopt after restart still reports.
- Smoke: `--dev` temp config, a fake skill that sleeps without progress, the bubble shows the stall line, then a finish report. Local model or a scripted fake agent (`tests/fake_acp_agent.py`).

**Blocks**

- **4a.** Tests for intent (rule-based) and stall accounting, against the existing skill store.
- **4b.** Rule-based intent + "shall I start this as a goal?" confirm; start the existing skill runner.
- **4c.** Stall monitor + bubble report + adopt on restart. Keep `SKILL_IDLE_S` as the "give up waiting for the user" timer; do not overload it as the stall timer.

**Depends on.** 0 (and 3 if a goal step is a widget action). **Unlocks.** 2c's "run this goal".

## 5. Vault: secrets in the OS keychain, consent before each use

**What exists.** No keychain wrapper. `widget.json` is not for secrets (`config.py` 66). Private paths are refused; job output is redacted. OpenBot's token stays in OpenBot's headers file; do not silently migrate it in v1. Tests must never touch the real keychain of the daily login (temp `HOME` already isolates most tests; still use a fake backend by default).

**Design.** A thin `botwidget/vault.py` over the platform stores: macOS Keychain, freedesktop Secret Service, Windows Credential Manager. The recommended backend is the `keyring` library, which already maps to those three, plus a fake backend for tests. The service name is fixed (e.g. `botwidget.vault`). Values never go to disk under `APP_DIR`, never into `widget.json`, never into logs, never into the bubble, and never into a model prompt. `get` requires a confirm of kind `vault` that names the secret's id and the reason ("post the confirmed GitHub issue", "log in to …"), not the secret itself. There is no Always allow on `get` in v1. `set` and `delete` also ask, and show only the id. Cross-platform: one module, three OS backends through `keyring`, CI uses the fake. A live smoke on the MacBook or the PC writes a throwaway secret, reads it after a yes, and deletes it.

**Tests first**

- Unit with a fake backend: set/get/delete; get without a matching yes returns nothing; a yes for secret A cannot read secret B; a declined get is logged without the value; redaction still applies if a value ever crosses a log path; the fake is the default in tests, so the real keychain is never opened under the isolated `HOME`.
- Live smoke (manual, not CI): one throwaway secret on the real Keychain or Secret Service of a test profile, yes to read, then delete. Confirm in the widget. Not the daily `widget.json`.

**Blocks**

- **5a.** Tests and the fake backend.
- **5b.** `botwidget/vault.py` + `keyring`, confirm on get/set/delete, no secret in logs. Local model.
- **5c.** Optional: a `/vault` or `/settings` row that lists secret *ids* only. Live smoke. Then, if wanted, the GitHub-token fallback for 1c.

**Depends on.** 0. **Unlocks.** 1c's token fallback, and any later login the bot must use.

## Build rules (every block)

- Tests first, then the code that makes them pass. Unittest, not pytest: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -t .` (AGENTS.md). A logic change lives in `botwidget/` or `harness/`, not in `qt_ui/`, unless it is a bubble hook.
- One general mechanism, not a one-off for `/screenshot` or `/feedback` (AGENTS.md: "Fix a bug only with a general fix").
- Temporary `HOME` and a temporary `CONFIG_PATH` in tests. Never read or write the real widget.json. Never assume OpenBot, Grok Bot or Hermes is installed.
- Cross-platform: Linux, macOS, Windows. POSIX-only behaviour needs `skipIf(os.name == "nt")`. The macOS CI run skips some tests; Windows runs only on GitHub.
- Pushing main runs ruff and the suite (`.githooks/pre-push`). Stage only the hunks of the change (`git add -p`). Do not commit `widget.json`. Ask before a commit if this plan does not already cover that push.
- A live smoke uses `python -m botwidget --instances` first, a temp config, and never a second `--dev` next to the daily widget.
- System packages: PolicyKit consent in the widget, no sudo line (AGENTS.md, `system/control.py`). The PolicyKit dialog itself is a separate open item and is not required for 0–5a unless a block actually needs a missing typelib or tool.

## Design questions (for General / Stefan)

Only these need a decision. The plan can start on 0, 1a/1b, 3a, 4a and 5a with the recommendations below.

### Q1. How does a confirmed feedback report actually go out?

- **A.** Only open the prefilled GitHub issue page (user still clicks Submit in the browser). Safest, but the bot does not "post itself".
- **B.** After yes, `gh issue create` when `gh` is already logged in; otherwise fall back to A.
- **C.** After yes, GitHub API with a token from the vault (needs 5, and a vault confirm for that use).

**Recommendation:** B for the first send path, A as the fallback, C only after the vault is in. The hard rule in every option is the confirm of the exact text. Do not invent wording.

### Q2. Do suggested widget actions need a yes every time, or may some be always-allowed?

- **A.** Every suggested action needs a yes, every time (v1).
- **B.** A tight allowlist may be "Always allow" per action, never for feedback, vault get, send, quit, or install. Screenshot mode still needs a yes, because it captures the screen; the user still has to send the picture afterwards.
- **C.** The model chooses when to ask. Rejected: that is how unconfirmed feedback happens.

**Recommendation:** A now, B later if the yes-prompts get noisy, with the exclusions in B. Not C.

### Q3. Where are routines stored?

- **A.** `routines.json` (or a sibling) under `APP_DIR`, next to `widget.json`, not inside it.
- **B.** A sqlite file, like the lean-agent session store.
- **C.** OS schedulers (launchd / systemd user units / Task Scheduler).

**Recommendation:** A in v1. The widget is already a login item, so an in-process scheduler is enough and stays cross-platform. B is fine if the file grows, but it is more machinery. C needs extra privileges, differs per OS, and is harder to test in the isolated `HOME`. Revisit C only if routines must fire when the widget is not running.

### Q4. Which vault backend?

- **A.** The `keyring` library (macOS Keychain, Secret Service, Windows Credential Manager), plus a fake backend for tests.
- **B.** Hand-written ctypes/native wrappers for each OS.
- **C.** An encrypted file under `APP_DIR`.

**Recommendation:** A. It is the cross-platform standard and keeps tests off the real store. Not C for real secrets. Not B unless `keyring` fails on one of Stefan's machines. OpenBot's existing headers file stays where it is in v1; do not copy that token into the vault unless Stefan asks.

## Settled decisions (2026-11-24)

General approved these on 2026-11-24. The recommendations are now the design; only the open-question history remains above.

### Q1. Feedback send path: B
After a yes for the exact text, `gh issue create` when `gh` is already logged in; otherwise open the prefilled GitHub issue page (user still clicks Submit). A (browser-only) is the fallback. C (GitHub API with a vault token) only after the vault is in, and only with a vault-kind confirm for that use. The hard rule: confirm the exact text. Do not invent wording.

### Q2. Suggested actions: A
Every suggested action needs a yes, every time, in v1. Not C. A later tight allowlist (B) may be considered if prompts get noisy, still excluding feedback, vault get, send, quit, and install, and still confirming screenshot.

### Q3. Routine storage: A
`routines.json` (or a sibling) under `APP_DIR`, next to `widget.json`, not inside it. In-process scheduler. Not OS schedulers in v1.

### Q4. Vault backend: A
The `keyring` library plus a fake backend for tests. OpenBot's headers file stays where it is in v1.
