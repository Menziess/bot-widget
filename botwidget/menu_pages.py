"""The pages of the menu that opens in the bubble: home, /settings, /bots and /connections.

Pure blocks, no toolkit. A clickable row is a piece with the style "cmd:<command>"; markdown never
produces that style, so no message from a bot can make a row of its own.
"""

from botwidget.config import QUIET_FROM, QUIET_TO
from botwidget.markdown import control_block, plain_block, role_panel, text_block
from botwidget.theme import BUBBLE_FONT

PAGES = ("settings", "bots", "connections")
# What typing it in the field opens; "/" alone is the home page.
SLASH = {"/settings": "settings", "/bots": "bots", "/connections": "connections"}
# What the list offers when a message starts with a slash, which is also what a right-click shows.
COMMANDS = (("/settings", "sound, updates"), ("/bots", "which bots show"), ("/connections", "what was found"))


def _row(*chunks) -> dict:
    return text_block(BUBBLE_FONT, 0, "", False, list(chunks))


def _command(label: str, command: str) -> tuple:
    return (label, f"cmd:{command}")


def _heading(title: str) -> dict:
    return _row((title, "b"))


def _toggle(label: str, command: str, on: bool) -> dict:
    return control_block("toggle", label, command, bool(on))


def _button(label: str, command: str) -> dict:
    return control_block("button", label, command)


def _back() -> list:
    """The arrow on top of a page: the way back to the menu, as scrolling past the top is the way to older messages."""
    return [role_panel("more", back="page/commands"), plain_block("more"), role_panel("bot")]


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
    blocks += [
        _toggle("Sound on a new answer", "toggle/sound", state["sound"]),
        _toggle(f"No sound from {QUIET_FROM}:00 to {QUIET_TO:02d}:00", "toggle/quiet_hours", state["quiet_hours"]),
        _toggle("Face stays above other windows", "toggle/always_on_top", state["always_on_top"]),
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


def bots(state: dict) -> list:
    blocks = _back() + [_heading("Bots"), _row(("Shift+click a bot's face to mute or unmute its thinking.", "dim")),
                        plain_block("gap")]
    for bot in state["bots"]:
        blocks.append(_toggle(bot["name"], f"bot/{bot['id']}", bot["on"]))
        blocks.append({**_toggle("Thinking muted", f"mute/{bot['id']}", bot.get("muted", False)), "indent": 44})
    if not state["bots"]:
        blocks.append(_row(("No bots found yet", "dim")))
    return blocks


def connections(state: dict) -> list:
    blocks = _back() + [_heading("Connections"), _row(("Turning one on that was not found opens its page.", "dim")),
                        plain_block("gap")]
    wanted = state.get("wanted", ())
    openbot = state["openbot"]
    blocks.append(_toggle("OpenBot", "connect/openbot", openbot or "openbot" in wanted))
    if openbot and state["automation_ready"]:
        note = "Detected, local API ready"
    elif openbot:
        note = "Detected, but the local API is off: in OpenBot open the bot's settings and turn on \"Local scripts\""
    else:
        note = "Waiting for OpenBot to be installed" if "openbot" in wanted else "Not found"
    blocks.append({**_row((note, "dim")), "indent": 44})
    blocks.append(plain_block("gap"))
    gbot = state["gbot"]
    blocks.append(_toggle("Grok Bot", "connect/grokbot", gbot or "grokbot" in wanted))
    if gbot:
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
    return blocks


def page_blocks(page: str, state: dict) -> list:
    return {"settings": settings, "bots": bots, "connections": connections}.get(page, settings)(state)
