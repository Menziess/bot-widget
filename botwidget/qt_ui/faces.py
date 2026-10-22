"""One face per enabled bot, plus what the menu in the bubble shows and does."""

import json
import os
import threading
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from botwidget import __version__, channel, grokbot, startup, updates
from botwidget.config import (
    APP_DIR,
    GROKBOT_URL,
    OPENBOT_URL,
    STATE_PATH,
    UNLINKED_ID,
    UNLINKED_NAME,
    all_desktops,
    always_on_top,
    auto_update,
    automation_ready,
    check_updates,
    muted_bots,
    save_widget_config,
    set_muted,
    widget_config,
)
from botwidget.openbot import gbot_installed, grok_bot_status, list_bots, openbot_installed
from botwidget.qt_ui.face import FaceWindow
from botwidget.system.current import CAN_PICK_DESKTOPS, HOTKEY_LABEL, activate_app, can_install_update


UPDATE_TICK_MS = 10 * 60 * 1000
RECHECK_S = 6 * 3600


def _all_bots() -> list:
    """Every bot the widget can show a face for: the local ones and Grok Bot."""
    bots = list(list_bots())
    if gbot_installed():
        target = grokbot.target()
        bots.append({"id": grokbot.face_id(target), "name": target, "threadId": None,
                     "hue": None, "seed": grokbot.face_id(target), "status": "ready"})
    return bots


class Faces(QObject):
    grok_probed = Signal()  # the roster came back, so the Grok Bot face can take its own avatar

    def __init__(self):
        super().__init__()
        self.pos = {}
        enabled = self._load()
        self.faces = {}
        self.grok = {"connected": False, "bots": [], "note": "not tried yet"}
        self.avatar = None
        self.update = None
        self.staged = None
        self.wanted = set()  # connections turned on that were not found: the page is open, the toggle stays on
        self.hotkey_on = False
        self.grok_probed.connect(self._take_grok_avatar)
        threading.Thread(target=self._probe_grok, daemon=True).start()
        self._probed = 0.0
        if check_updates():
            self._start_probe()
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(UPDATE_TICK_MS)
            self._update_timer.timeout.connect(self._update_tick)
            self._update_timer.start()
        bots = {bot["id"]: bot for bot in _all_bots()}
        ids = [agent_id for agent_id in enabled if agent_id in bots] or list(bots)[:1] or [UNLINKED_ID]
        for slot, agent_id in enumerate(ids):
            bot = bots.get(agent_id) or {
                "id": agent_id,
                "name": UNLINKED_NAME,
                "threadId": "openbot-thread-" + agent_id,
                "hue": None,
            }
            self._open(bot, slot)

    def _load(self) -> list:
        try:
            with open(STATE_PATH) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        enabled = data.get("enabled")
        if not isinstance(enabled, list) or not all(isinstance(i, str) for i in enabled) or not enabled:
            enabled = []
        pos = data.get("pos")
        self.pos = pos if isinstance(pos, dict) else {}
        return enabled

    def _save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        with open(STATE_PATH, "w") as fh:
            json.dump({"enabled": list(self.faces), "pos": self.pos}, fh)

    def _probe_grok(self):
        """Ask gbot once; no loop, gbot warns about that itself."""
        self.grok = grok_bot_status()
        self.avatar = grokbot.avatar_of(self.grok.get("bots"), grokbot.target())
        self.grok_probed.emit()

    def _take_grok_avatar(self):
        """The roster arrived: the Grok Bot face wears the shape and colour Grok Bot gives that bot."""
        face = self.faces.get(grokbot.face_id(grokbot.target()))
        if face is not None and self.avatar:
            face.set_avatar(self.avatar)

    def _start_probe(self):
        self._probed = time.monotonic()
        threading.Thread(target=self._probe_update, daemon=True).start()

    def _update_tick(self):
        """A widget that stays open for days still moves to the newest release, once nobody is using it."""
        if self.staged:
            if all(face.idle() for face in self.faces.values()):
                self.install_update()
        elif time.monotonic() - self._probed > RECHECK_S:
            self._start_probe()

    def _probe_update(self):
        """Is there a newer version? If so, and allowed, stage it already."""
        release = updates.newer_release()
        if release is None:
            return
        self.update = release
        if auto_update() and can_install_update():
            self.staged = updates.stage(release)

    def hotkey(self):
        """The global key combination: open the chat of the first face, or close it again."""
        face = next(iter(self.faces.values()), None)
        if face is None:
            return
        # Living on one desktop, the face first comes to the one you are on.
        moved = any([other.bring_here() for other in self.faces.values()])
        if face.pinned and not moved:
            face.unpin()
        else:
            activate_app()
            face.pin()

    def switch_channel(self):
        if channel.switch():
            QApplication.exit(channel.HANDOVER_EXIT if channel.running() == "local" else 0)

    def install_update(self):
        self.staged = None
        if updates.install_staged():
            QApplication.quit()

    def welcome(self, first_run: bool):
        """The first time: the first face says the widget will now start at login."""
        if first_run and self.faces:
            next(iter(self.faces.values())).welcome()

    def grok_line(self) -> str:
        if self.grok.get("connected"):
            return f"Grok Bot · connected ({len(self.grok.get('bots') or [])} bots)"
        return "Grok Bot · no route"

    def _open(self, bot: dict, slot: int):
        spot = self.pos.get(bot["id"])
        if not (isinstance(spot, (list, tuple)) and len(spot) == 2):
            spot = None
        avatar = self.avatar if grokbot.is_grok(bot["id"]) else None
        face = FaceWindow(bot["id"], bot["name"], spot, slot, bot.get("threadId"), self,
                          bot.get("hue"), bot.get("seed"), avatar)
        self.faces[bot["id"]] = face
        face.show()

    def remember(self, agent_id: str, x: int, y: int):
        self.pos[agent_id] = [int(x), int(y)]
        self._save()

    def toggle(self, agent_id: str, on: bool):
        bots = {bot["id"]: bot for bot in _all_bots()}
        if on and agent_id not in self.faces and agent_id in bots:
            self._open(bots[agent_id], len(self.faces))
        if not on and agent_id in self.faces:
            self.faces.pop(agent_id).close_face()
        self._save()

    def close_bubbles_except(self, agent_id: str):
        """The bubble of one face is open: the others close, so that only one is up at a time."""
        for other_id, face in self.faces.items():
            if other_id != agent_id and face.bubble.isVisible():
                face.pinned = False
                face.bubble.place("")

    def menu_state(self) -> dict:
        """What the menu pages show: the settings as they are now, the bots, and what was found."""
        config = widget_config()
        bots = _all_bots()
        return {
            "version": __version__, "channel": channel.running(), "switch_label": channel.switch_label(),
            "hotkey": HOTKEY_LABEL if self.hotkey_on else "",
            "update": self.update.version if self.update else "",
            "staged_update": self.update.version if self.staged and self.update else "",
            "sound": config.get("sound") is True, "quiet_hours": config.get("quiet_hours") is True,
            "always_on_top": always_on_top(), "can_pick_desktops": CAN_PICK_DESKTOPS,
            "all_desktops": all_desktops(), "login": startup.is_enabled(), "check_updates": check_updates(),
            "can_install_updates": can_install_update(), "auto_update": auto_update(),
            "bots": [{"id": bot["id"], "name": bot["name"], "on": bot["id"] in self.faces,
                      "muted": bot["id"] in muted_bots()} for bot in bots],
            "openbot": openbot_installed(), "automation_ready": automation_ready(),
            "gbot": gbot_installed(), "grok": self.grok_line(),
            "grok_target": grokbot.target(), "wanted": sorted(self.wanted),
        }

    TOGGLES = {
        "sound": lambda faces, on: save_widget_config(sound=on),
        "quiet_hours": lambda faces, on: save_widget_config(quiet_hours=on),
        "always_on_top": lambda faces, on: faces._set_always_on_top(on),
        "all_desktops": lambda faces, on: faces._set_all_desktops(on),
        "login": lambda faces, on: startup.set_enabled(on),
        "check_updates": lambda faces, on: save_widget_config(check_updates=on),
        "auto_update": lambda faces, on: save_widget_config(auto_update=on),
    }
    CONNECTIONS = {"openbot": "openbot", "grokbot": "gbot"}
    LINKS = {"openbot": OPENBOT_URL, "grokbot": GROKBOT_URL, "download": updates.DOWNLOAD_URL}

    def menu_command(self, command: str, page: str) -> str | None:
        """Do what a menu row asks; the page to show next, or None to leave the bubble as it is."""
        kind, _, name = command.partition("/")
        if kind == "page":
            return name
        if kind == "toggle" and name in self.TOGGLES:
            state = self.menu_state()
            self.TOGGLES[name](self, not state[name])
        elif kind == "bot":
            self.toggle(name, name not in self.faces)
        elif kind == "mute":
            if name in self.faces:
                self.faces[name].toggle_muted()
            else:
                set_muted(name, name not in muted_bots())
        elif kind == "connect" and name in self.CONNECTIONS:
            if not self.menu_state()[self.CONNECTIONS[name]]:
                if name in self.wanted:
                    self.wanted.discard(name)
                else:
                    self.wanted.add(name)
                    QDesktopServices.openUrl(QUrl(self.LINKS[name]))
        elif kind == "open" and name in self.LINKS:
            QDesktopServices.openUrl(QUrl(self.LINKS[name]))
        elif kind == "action" and name == "update":
            self.install_update()
        elif kind == "action" and name == "switch":
            self.switch_channel()
        elif kind == "action" and name == "quit":
            QApplication.quit()
        return page

    def _set_all_desktops(self, on: bool):
        save_widget_config(all_desktops=on)
        for face in self.faces.values():
            face.apply_desktops()

    def _set_always_on_top(self, on: bool):
        save_widget_config(always_on_top=on)
        for face in self.faces.values():
            face.restack()
