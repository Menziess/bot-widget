"""The pages of the menu that opens in the bubble: home, /settings, /bots, /connections, /refresh and /feedback.

Pure blocks, no toolkit. A clickable row is a piece with the style "cmd:<command>"; markdown never
produces that style, so no message from a bot can make a row of its own.
"""

import time
import urllib.parse

from botwidget.config import QUIET_FROM, QUIET_TO
from botwidget.markdown import control_block, plain_block, role_panel, text_block
from botwidget.theme import BUBBLE_FONT

PAGES = ("settings", "bots", "connections", "bot", "connection", "widget-json", "memory")
# What typing it in the field opens.
SLASH = {"/settings": "settings", "/bots": "bots", "/connections": "connections", "/memory": "memory"}
# What the list offers when a message starts with a slash, which is also what a right-click shows.
# No /home: a right-click shows this list on its own. A page steps back to the screen before it.
COMMANDS = (("/settings", "sound, updates"), ("/bots", "which bots show"),
            ("/connections", "what was found"), ("/memory", "view/edit memories"),
            ("/refresh", "reload every bot"), ("/feedback", "open a GitHub issue"))


def commands() -> tuple:
    """The commands the list offers. A sample thought is a switch in Settings, and only in a checkout."""
    return COMMANDS


DEBUG_THOUGHT = "Debug: this is what a thought looks like while the bot works…"
DEBUG_MESSAGE = """# Header one
## Header two
### Header three

Plain text with **bold**, *italic*, `inline code`, a [link](https://openbot.run/) and a bare URL https://example.com/page.

> A quote that goes on for a while, so you can see how a quoted line wraps over more than one line.

- A bullet with **bold** in it
- A second bullet
1. A numbered line
2. Another numbered line

---

| Name | Kind | Notes |
|--|--|--|
| Short | text | fits in one line |
| A long cell | markdown | this cell has so many words in it that it has to wrap over several lines in the table |
| `code` | **bold** | *italic* and a [link](https://x.ai/bot) |

```python
def greet(name):
    return f"Hi, {name}!"

print(greet("world"))
```

A file path: ~/Projects/private/bot-widget/README.md"""
FEEDBACK_ISSUE = "https://github.com/Menziess/bot-widget/issues/new"


def feedback_issue_url(version: str, system: str, install: str) -> str:
    """A new-issue page, filled in. The browser signs the user in; the app has no GitHub token."""
    body = f"Widget version: {version}\nOS: {system}\nInstall: {install}\n\n"
    return FEEDBACK_ISSUE + "?" + urllib.parse.urlencode({"title": "Feedback", "body": body})


def _row(*chunks) -> dict:
    return text_block(BUBBLE_FONT, 0, "", False, list(chunks))


def _command(label: str, command: str) -> tuple:
    return (label, f"cmd:{command}")


def _heading(title: str) -> dict:
    # On the heading, so the title is on screen when the page opens. The line above it fades away.
    return _row((title, "b"))


def _toggle(label: str, command: str, on: bool) -> dict:
    return control_block("toggle", label, command, bool(on))


def _button(label: str, command: str) -> dict:
    return control_block("button", label, command)


def _item(label: str, command: str, on: bool, actions: list) -> dict:
    """One element: the switch is the command, and each action belongs to this row alone."""
    return {**control_block("item", label, command, bool(on)),
            "actions": [{"label": text, "command": action} for text, action in actions]}


def _field(label: str, command: str, value: str) -> dict:
    return {**control_block("field", label, command), "value": value}


def _back(where: str = "page/commands") -> list:
    """The line on top of a page. Pulling it or clicking it goes to the screen before this one."""
    return [role_panel("more", back=where), plain_block("more"), role_panel("bot")]


def settings(state: dict) -> list:
    blocks = _back() + [_heading("Settings"), plain_block("gap")]
    if state.get("staged_update"):
        blocks.append(_button(f"Restart to update to v{state['staged_update']}", "action/update"))
    elif state.get("update"):
        blocks.append(_button(f"Update available: v{state['update']} ↗", "open/download"))
    blocks.append(_row((f"Running the {state['channel']} version, v{state['version']}", "dim")))
    if state.get("hotkey"):
        blocks.append(_row((f"Open the chat from any app with {state['hotkey']}", "dim")))
    if state.get("switch_label"):
        blocks.append(_button(state["switch_label"], "action/switch"))
    blocks.append(plain_block("gap"))
    if state.get("can_glass"):
        blocks.append(control_block("slider", "Glass transparency", "slider/glass", state["glass_clear"]))
    blocks += [
        _toggle("Sound on a new answer", "toggle/sound", state["sound"]),
        _toggle(f"No sound from {QUIET_FROM}:00 to {QUIET_TO:02d}:00", "toggle/quiet_hours", state["quiet_hours"]),
        _toggle("Face stays above other windows", "toggle/always_on_top", state["always_on_top"]),
        _toggle("Fewer animations on battery or in low power mode", "toggle/save_battery", state["save_battery"]),
    ]
    if state.get("can_pick_desktops"):
        blocks.append(_toggle("Show on all desktops", "toggle/all_desktops", state["all_desktops"]))
    blocks += [
        _toggle("Start at login", "toggle/login", state["login"]),
        _toggle("Check for updates", "toggle/check_updates", state["check_updates"]),
    ]
    if state.get("can_install_updates"):
        blocks.append(_toggle("Install updates automatically", "toggle/auto_update", state["auto_update"]))
    if state.get("dev"):
        blocks.append(_toggle("Sample thought, click the face for a sample message", "toggle/debug",
                              bool(state.get("debug"))))
    blocks += [plain_block("gap"), _button("Quit Bot Widget", "action/quit")]
    return blocks


def _remove_button(state: dict, command: str, name: str) -> dict:
    """The first click arms it. It is gone only after the second click of this same row."""
    label = "Click again to remove" if state.get("confirm_remove") == command else name
    return _button(label, command)


def bots(state: dict) -> list:
    blocks = _back() + [_heading("Bots"),
                        _row(("Shift+click a bot's face to mute or unmute its thinking.", "dim")),
                        plain_block("gap")]
    for bot in state["bots"]:
        # Where the bot lives: OpenBot, Grok Bot, Hermes or a harness bot.
        label = f"{bot['name']} · {bot['source']}" if bot.get("source") else bot["name"]
        actions = [("Unmute" if bot.get("muted") else "Mute", f"mute/{bot['id']}")]
        if bot.get("acp"):
            actions.append(("Edit", f"page/bot/{bot['id']}"))
            remove = f"bot-remove/{bot['id']}"
            actions.append(("Again" if state.get("confirm_remove") == remove else "Remove", remove))
        blocks.append(_item(label, f"bot/{bot['id']}", bot["on"], actions))
    if not state["bots"]:
        blocks.append(_row(("No bots found yet", "dim")))
    blocks += [plain_block("gap"), _button("New bot", "page/bot"), _button("Edit widget.json", "page/widget-json")]
    return blocks


def _face_preview(form: dict) -> dict:
    """The face and colour as they will be drawn. The value is what the picture is of."""
    face, colour = form.get("face") or "", form.get("color") or ""
    seed = form.get("id") or form.get("name") or "new"
    return {**control_block("preview", "", "preview"), "value": f"{face}|{colour}|{seed}"}


def _connection_label(state: dict, form: dict) -> str:
    chosen = str(form.get("connection") or "")
    for row in state.get("connections") or []:
        if row.get("id") == chosen:
            return f"Connection: {row.get('name') or chosen}"
    return "Connection: none yet"


def bot_form(state: dict) -> list:
    """Name, face, colour, workspace and permission mode. The address lives on that connection."""
    from botwidget.acp_bots import blank
    form = state.get("bot_form") or blank()
    editing = bool(form.get("stored_id"))
    blocks = _back("page/bots") + [_heading("Edit bot" if editing else "New bot")]
    blocks += [
        _field("Name", "field/name", form.get("name") or ""),
        _button(f"Face: {form.get('face') or 'automatic'}", "cycle/face"),
        _button(f"Colour: {form.get('color') or 'automatic'}", "cycle/color"),
        _face_preview(form),
        _button(_connection_label(state, form), "cycle/connection"),
    ]
    # Workspace
    ws = form.get("workspace") or ""
    blocks.append(_field("Workspace", "field/workspace", ws))
    ws_perm = form.get("workspace_permissions") or "ask"
    ws_perms = ("ask", "allow", "allow_session")
    if ws_perm not in ws_perms:
        ws_perm = "ask"
    blocks.append(_button(f"Permission: {ws_perm}", "cycle/workspace_permission"))
    # Next to Save: an error at the top stayed off screen once the form had been scrolled down.
    if state.get("bot_error"):
        blocks.append(_row((state["bot_error"], "b")))
    blocks += [
        plain_block("gap"),
        _button("Save bot", "action/save-bot"),
    ]
    if editing:
        blocks.append(_remove_button(state, f"bot-remove/{form['id']}", "Remove bot"))
    return blocks


def widget_json(state: dict) -> list:
    """The whole settings file, for a change the form does not cover. The key is not in the text."""
    blocks = _back("page/bots") + [_heading("widget.json"),
                        _row(("Checked before saving. The previous file is kept as widget.json.bak. "
                              "A key pasted here is refused; only key_file belongs in this file.", "dim"))]
    if state.get("json_error"):
        blocks.append(_row((state["json_error"], "dim")))
    blocks.append({**control_block("editor", "widget.json", "editor"), "value": state.get("json_text") or ""})
    blocks += [plain_block("gap"), _button("Save widget.json", "action/save-json")]
    return blocks


def connections(state: dict) -> list:
    blocks = _back() + [_heading("Connections"),
                        _row(("Turning one on that was not found opens its page.", "dim")),
                        plain_block("gap")]
    wanted = state.get("wanted", ())
    off = set(state.get("sources_off") or ())
    openbot = state["openbot"]
    blocks.append(_toggle("OpenBot", "connect/openbot", "openbot" not in off and (openbot or "openbot" in wanted)))
    if "openbot" in off and openbot:
        note = "Off. OpenBot is installed, but its bots are not shown."
    elif openbot and state["automation_ready"]:
        note = "Detected, local API ready"
    elif openbot:
        note = "Detected, but the local API is off: in OpenBot open the bot's settings and turn on \"Local scripts\""
    else:
        note = "Waiting for OpenBot to be installed" if "openbot" in wanted else "Not found"
    blocks.append({**_row((note, "dim")), "indent": 44})
    blocks.append(plain_block("gap"))
    gbot = state["gbot"]
    blocks.append(_toggle("Grok Bot", "connect/grokbot", "grokbot" not in off and (gbot or "grokbot" in wanted)))
    if "grokbot" in off and gbot:
        line = ""
        note = "Off. Grok Bot is installed, but its bots are not shown."
    elif gbot:
        line = state["grok"]
        if line.startswith("Grok Bot"):
            line = line[len("Grok Bot"):].strip()
        target = state.get("grok_target")
        if target and "talks to" not in line:
            line = f"{line} · talks to {target}"
        note = f"Detected, {line}" if line else "Detected"
    else:
        note = "Waiting for Grok Bot to be installed" if "grokbot" in wanted else "Not found"
    blocks.append({**_row((note, "dim")), "indent": 44})
    blocks.append(plain_block("gap"))
    relay = state.get("grok_relay") or ""
    if relay:
        blocks.append({**_row((f"Linked via ntfy · {relay}", "dim")), "indent": 0})
        blocks.append(_button("Copy chief prompt", "action/copy-grok-prompt"))
    else:
        blocks.append(_button("Link Grok bots", "action/link-grok"))
    blocks.append(plain_block("gap"))
    hermes = state.get("hermes")
    blocks.append(_toggle("Hermes Bot", "connect/hermesbot", "hermesbot" not in off and (hermes or "hermesbot" in wanted)))
    if "hermesbot" in off and hermes:
        note = "Off. Hermes Bot is installed, but its bots are not shown."
    elif hermes:
        note = "Detected"
    else:
        note = "Waiting for Hermes Bot to be installed" if "hermesbot" in wanted else "Not found"
    blocks.append({**_row((note, "dim")), "indent": 44})
    blocks += [plain_block("gap"), _heading("Model connections"),
               _row(("Each one is on or off, like OpenBot. Off stops the bots that use it. "
                     "The key stays in its file.", "dim"))]
    if state.get("connection_error"):
        blocks.append(_row((state["connection_error"], "b")))
    for conn in state.get("connections") or []:
        label = conn["name"] if conn.get("on", True) else f"{conn['name']} · off"
        if conn.get("model"):
            label = f"{label} · {conn['model']}"
        remove = f"connection-remove/{conn['id']}"
        blocks.append(_item(label, f"connection-toggle/{conn['id']}", conn.get("on", True), [
            ("Edit", f"page/connection/{conn['id']}"),
            ("Again" if state.get("confirm_remove") == remove else "Remove", remove),
        ]))
    blocks.append(_button("New connection", "page/connection"))
    return blocks


def connection_form(state: dict) -> list:
    """One model endpoint: address, model name and the file the key is read from."""
    from botwidget.acp_bots import blank_connection
    form = state.get("connection_form") or blank_connection()
    editing = bool(form.get("stored_id"))
    blocks = _back("page/connections") + [_heading("Edit connection" if editing else "New connection")]
    blocks += [
        _field("Name", "field/name", form.get("name") or ""),
        _field("Model address", "field/base_url", form.get("base_url") or ""),
        _field("Model", "field/model", form.get("model") or ""),
        _field("Key file", "field/key_file", form.get("key_file") or ""),
    ]
    if state.get("connection_error"):
        blocks.append(_row((state["connection_error"], "b")))
    blocks += [plain_block("gap"), _button("Save connection", "action/save-connection")]
    if editing:
        blocks.append(_remove_button(state, f"connection-remove/{form['id']}", "Remove connection"))
    return blocks


def memory_page(state: dict) -> list:
    """View, add, and forget memories."""
    try:
        from harness.agent import memory as memory_mod
        memories = memory_mod.list_memories()
    except Exception:
        memories = []

    blocks = _back("page/bots") + [_heading("Memory")]
    if not memories:
        blocks.append(_row(("No memories stored yet", "dim")))
    else:
        for m in memories:
            scope = m.get("scope", "?")
            topic = f" [{m['topic']}]" if m.get("topic") else ""
            mem_id = m.get("id", "")
            ts = m.get("ts", 0)
            time_str = time.strftime("%b %d %H:%M", time.localtime(ts)) if ts else ""
            label = f"[{scope}{topic}] {m.get('text', '')} · {time_str}"
            blocks.append({**_row((label, "dim")), "actions": [
                ("Forget", f"cmd:memory-forget/{mem_id}"),
            ]})
    blocks += [plain_block("gap"),
               _button("New memory", "page/memory/new"),
               _button("Back to memories", "page/memory/list")]
    return blocks


def memory_add(state: dict) -> list:
    """Add a new memory."""
    blocks = _back("page/memory/list") + [_heading("New memory")]
    error = state.get("memory_error", "")
    if error:
        blocks.append(_row((error, "b")))
    blocks += [
        _field("Text", "field/memory_text", state.get("_memory_text", "")),
        _field("Scope (user/project/topic)", "field/memory_scope", state.get("_memory_scope", "user")),
        _field("Topic (optional)", "field/memory_topic", state.get("_memory_topic", "")),
        plain_block("gap"),
        _button("Save memory", "action/memory-save"),
    ]
    return blocks


def memory_list(state: dict) -> list:
    """Back to the memory list."""
    return memory_page(state)


def page_blocks(page: str, state: dict) -> list:
    if page == "widget-json":
        return widget_json(state)
    if page == "bot" or (isinstance(page, str) and page.startswith("bot/")):
        return bot_form(state)
    if page == "connection" or (isinstance(page, str) and page.startswith("connection/")):
        return connection_form(state)
    if page == "memory":
        return memory_page(state)
    if page == "memory/new":
        return memory_add(state)
    if page == "memory/list":
        return memory_list(state)
    return {"settings": settings, "bots": bots, "connections": connections}.get(page, settings)(state)
