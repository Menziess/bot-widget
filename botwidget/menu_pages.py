"""The pages of the menu that opens in the bubble: /settings, /bots, /connections, /memory and /approvals.

Pure blocks, no toolkit. A clickable row is a piece with the style "cmd:<command>"; markdown never
produces that style, so no message from a bot can make a row of its own.
"""

import time
import urllib.parse

from botwidget.config import QUIET_FROM, QUIET_TO
from botwidget.markdown import control_block, plain_block, role_panel, text_block
from botwidget.theme import BUBBLE_FONT, CONTROL_SWITCH_W

PAGES = ("settings", "bots", "connections", "bot", "connection", "widget-json", "memory", "approvals", "vault")
# What typing it in the field opens.
SLASH = {"/settings": "settings", "/bots": "bots", "/connections": "connections", "/memory": "memory", "/approvals": "approvals", "/vault": "vault"}
# What the list offers when a message starts with a slash, which is also what a right-click shows.
# No /home: a right-click shows this list on its own. A page steps back to the screen before it.
COMMANDS = (("/settings", "Sound, updates, startup, look"), ("/bots", "Show, hide, add or edit bots"),
            ("/connections", "Apps and models the bots use"), ("/memory", "See, add or forget memories"),
            ("/approvals", "What bots may do without asking"), ("/screenshot", "Capture a region, or double-click a face"),
            ("/feedback", "Report a problem on GitHub"), ("/vault", "Secrets stored in the keychain"))


def _slash_name(name: str) -> str:
    """One command token: a leading slash, lower case, no blank name."""
    word = str(name or "").strip().split(" ", 1)[0] if str(name or "").strip() else ""
    word = word.lstrip("/").strip().lower()
    return f"/{word}" if word else ""


def commands(available=(), *, dev: bool = False) -> tuple:
    """Built-in commands, then this bot's skill commands.

    /demo is offered only while the widget was started with --dev. A skill whose
    name is empty or already a built-in (such as /screenshot) is left out.
    """
    rows = list(COMMANDS)
    if dev:
        rows.append(("/demo", "Play the chat demo"))
    if not available:
        return tuple(rows)
    taken = {name.lower() for name, _note in rows}
    for item in available:
        if isinstance(item, (tuple, list)):
            name = item[0] if item else ""
            description = item[1] if len(item) > 1 else ""
        else:
            name, description = getattr(item, "name", ""), getattr(item, "description", "")
        slash = _slash_name(name)
        if not slash or slash in taken:
            continue
        taken.add(slash)
        rows.append((slash, str(description or "").strip()))
    return tuple(rows)


FEEDBACK_ISSUE = "https://github.com/Menziess/bot-widget/issues/new"


def feedback_issue_url(version: str, system: str, install: str,
                       title: str = "", body: str = "") -> str:
    """A new-issue page, filled in. The browser signs the user in; the app has no GitHub token.

    When *title* and *body* are non-empty they override the defaults, so a
    confirmed draft can be sent straight into the URL.
    """
    version = str(version or "")
    system = str(system or "")
    install = str(install or "")
    user_title = (title or "").strip()
    user_body = (body or "").strip()
    if user_body:
        # Prepend the version info lines when the user also supplied a body.
        base_body = f"Widget version: {version}\nOS: {system}\nInstall: {install}\n\n{user_body}"
    else:
        base_body = f"Widget version: {version}\nOS: {system}\nInstall: {install}\n\n"
    final_title = user_title or "Feedback"
    return FEEDBACK_ISSUE + "?" + urllib.parse.urlencode({"title": final_title, "body": base_body})


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


def _item(label: str, command: str, on: bool | None, actions: list) -> dict:
    """One element: the switch is the command, and each action belongs to this row alone. Without a state (None)
    there is no switch."""
    return {**control_block("item", label, command, None if on is None else bool(on)),
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
    blocks += [plain_block("gap"), _button("Quit Bot Widget", "action/quit")]
    return blocks


def _armed(state: dict, command: str, label: str, sure: str = "Sure?") -> str:
    """What a destructive control says: the first click arms it, and it runs on the second click of this same one."""
    return sure if state.get("armed") == command else label


def _remove_button(state: dict, command: str, name: str) -> dict:
    return _button(_armed(state, command, name, "Click again to remove"), command)


def bots(state: dict) -> list:
    blocks = _back() + [_heading("Bots"),
                        _row(("Shift+click a face to mute its thinking. Reset clears a bot's conversation and restarts it.", "dim")),
                        plain_block("gap")]
    for bot in state["bots"]:
        # Where the bot lives: OpenBot, Grok Bot, Hermes or a harness bot.
        label = f"{bot['name']} · {bot['source']}" if bot.get("source") else bot["name"]
        actions = [("Unmute" if bot.get("muted") else "Mute", f"mute/{bot['id']}")]
        if bot.get("acp"):
            actions.append(("Edit", f"page/bot/{bot['id']}"))
        if bot["on"]:
            reset = f"reset/{bot['id']}"
            actions.append((_armed(state, reset, "Done" if state.get("reset_done") == reset else "Reset"), reset))
        if bot.get("acp"):
            remove = f"bot-remove/{bot['id']}"
            actions.append((_armed(state, remove, "Remove"), remove))
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


def _app(state: dict, label: str, key: str, found: bool, ready: str) -> list:
    """An app that has bots of its own: its switch, and one grey line on where it stands."""
    wanted, off = key in state.get("wanted", ()), key in (state.get("sources_off") or ())
    if found and off:
        note = "Off"
    elif found:
        note = ready
    else:
        note = "Waiting for it to be installed" if wanted else "Not installed. Turn on to open its page"
    return [_toggle(label, f"connect/{key}", not off and (found or wanted)),
            {**_row((note, "dim")), "indent": CONTROL_SWITCH_W}]


def connections(state: dict) -> list:
    openbot = state["openbot"]
    blocks = _back() + [_heading("Apps"),
                        _row(("Programs that bring their own bots. Turn one on to show its bots here.", "dim"))]
    blocks += _app(state, "OpenBot", "openbot", openbot,
                   "Ready" if state["automation_ready"]
                   else "Turn on \"Local scripts\" in the bot's settings in OpenBot")
    line = state["grok"].removeprefix("Grok Bot").strip()
    if state.get("grok_target") and "talks to" not in line:
        line = f"{line} · talks to {state['grok_target']}"
    blocks += _app(state, "Grok Bot", "grokbot", state["gbot"], line or "Ready")
    # Under its app, in line with the app's grey note.
    if state.get("grok_relay"):
        blocks += [{**_row((f"Linked via ntfy · {state['grok_relay']}", "dim")), "indent": CONTROL_SWITCH_W},
                   {**_button("Copy chief prompt", "action/copy-grok-prompt"), "indent": CONTROL_SWITCH_W}]
    else:
        blocks.append({**_button("Link Grok bots", "action/link-grok"), "indent": CONTROL_SWITCH_W})
    blocks += _app(state, "Hermes Bot", "hermesbot", state.get("hermes"), "Ready")
    blocks += [plain_block("gap"), _heading("Models"),
               _row(("The AI services your own bots think with. Add one here (address, model, key file), then pick it "
                     "when you make a bot. Turn one off to pause every bot that uses it.", "dim"))]
    if state.get("connection_error"):
        blocks.append(_row((state["connection_error"], "b")))
    for conn in state.get("connections") or []:
        label = f"{conn['name']} · {conn['model']}" if conn.get("model") else conn["name"]
        remove = f"connection-remove/{conn['id']}"
        blocks.append(_item(label, f"connection-toggle/{conn['id']}", conn.get("on", True), [
            ("Edit", f"page/connection/{conn['id']}"),
            (_armed(state, remove, "Remove"), remove),
        ]))
    blocks.append(_button("New connection", "page/connection"))
    return blocks


def _model_list(state: dict, form: dict) -> list:
    """Ask the service for its models, then step through the list; typing a name in Model works as well."""
    asked = state.get("models") or {}
    if asked.get("base") != str(form.get("base_url") or "").rstrip("/"):
        asked = {}
    if asked.get("loading"):
        return [_row(("Asking the service for its models…", "dim"))]
    if asked.get("ids"):
        return [_button(f"Next model ({len(asked['ids'])} offered)", "cycle/model")]
    rows = [_button("List models", "action/models")]
    if asked.get("error"):
        rows.append(_row((asked["error"], "dim")))
    return rows


def connection_form(state: dict) -> list:
    """One model endpoint: address, model name and the file the key is read from."""
    from botwidget import acp_bots
    form = state.get("connection_form") or acp_bots.blank_connection()
    editing = bool(form.get("stored_id"))
    blocks = _back("page/connections") + [_heading("Edit connection" if editing else "New connection")]
    blocks += [
        _button(f"Provider: {acp_bots.provider_of(form)}", "cycle/provider"),
        _field("Name", "field/name", form.get("name") or ""),
        _field("Model address", "field/base_url", form.get("base_url") or ""),
        _field("Model", "field/model", form.get("model") or ""),
        *_model_list(state, form),
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

    blocks = _back() + [_heading("Memory")]
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
            blocks.append(_row((label, "dim")))
            forget = f"memory-forget/{mem_id}"
            blocks.append(_item("", "", None, [("Edit", f"page/memory/edit/{mem_id}"),
                                               (_armed(state, forget, "Remove"), forget)]))
    blocks += [plain_block("gap"),
               _button("New memory", "page/memory/new")]
    return blocks


def approvals_page(state: dict) -> list:
    """What may run without a question: "*" for every bot, then one entry per bot."""
    blocks = _back() + [_heading("approvals.json"),
                                   _row(("true runs without asking, false always asks and wins. \"*\" counts for every bot. "
                                         "Checked before saving. The previous file is kept as approvals.json.bak.", "dim"))]
    if state.get("approvals_error"):
        blocks.append(_row((state["approvals_error"], "dim")))
    blocks.append({**control_block("editor", "approvals.json", "editor"), "value": state.get("approvals_text") or ""})
    blocks += [plain_block("gap"), _button("Save approvals.json", "action/save-approvals")]
    return blocks


def vault_page(state: dict) -> list:
    """List the secret IDs stored in the vault. Only IDs are shown: no values, no secrets."""
    from botwidget.vault import list_secret_ids

    blocks = _back() + [_heading("Vault")]
    ids = list_secret_ids()
    if not ids:
        blocks.append(_row(("No secrets stored yet", "dim")))
    else:
        for sid in ids:
            remove = f"vault-delete/{sid}"
            blocks.append(_item(sid, "", None, [(_armed(state, remove, "Remove"), remove)]))
    blocks += [plain_block("gap"),
               _button("New secret", "vault-new")]
    return blocks


def vault_new_page(state: dict) -> list:
    """Add a new secret to the vault. Shows ID and value fields."""
    blocks = _back("page/vault") + [_heading("New secret")]
    error = state.get("vault_error", "")
    if error:
        blocks.append(_row((error, "b")))
    blocks += [
        _field("Secret ID", "field/vault_new_id", state.get("_vault_new_id", "")),
        _field("Secret value", "field/vault_new_value", state.get("_vault_new_value", "")),
        plain_block("gap"),
        _button("Save secret", "vault-save"),
    ]
    return blocks


def memory_add(state: dict) -> list:
    """Add a new memory, or change the one in _memory_id."""
    editing = bool(state.get("_memory_id"))
    blocks = _back("page/memory/list") + [_heading("Edit memory" if editing else "New memory")]
    error = state.get("memory_error", "")
    if error:
        blocks.append(_row((error, "b")))
    blocks += [
        _row(("Text", "dim")),
        {**control_block("editor", "Text", "field/memory_text"), "value": state.get("_memory_text", "")},
    ]
    if not editing:
        blocks.append(_field("Scope (user/project/topic)", "field/memory_scope", state.get("_memory_scope", "user")))
    blocks += [
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
    if page == "approvals":
        return approvals_page(state)
    if page == "vault" or (isinstance(page, str) and page.startswith("vault/")):
        if page == "vault/new" or page.startswith("vault/new"):
            return vault_new_page(state)
        return vault_page(state)
    if page == "memory":
        return memory_page(state)
    if page == "memory/new" or (isinstance(page, str) and page.startswith("memory/edit/")):
        return memory_add(state)
    if page == "memory/list":
        return memory_list(state)
    return {"settings": settings, "bots": bots, "connections": connections}.get(page, settings)(state)
