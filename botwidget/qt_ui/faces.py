"""One face per enabled bot, plus the right-click menu to manage them."""

import json
import os
import threading
import time

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QAction, QCursor, QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu

from botwidget import __version__, channel, startup, updates
from botwidget.config import (
    APP_DIR,
    GROKBOT_URL,
    OPENBOT_URL,
    QUIET_FROM,
    QUIET_TO,
    STATE_PATH,
    UNLINKED_ID,
    UNLINKED_NAME,
    always_on_top,
    auto_update,
    check_updates,
    save_widget_config,
    widget_config,
)
from botwidget.openbot import gbot_installed, grok_bot_status, list_bots, openbot_installed
from botwidget.qt_ui.face import FaceWindow
from botwidget.system.current import HOTKEY_LABEL, activate_app, can_install_update


UPDATE_TICK_MS = 10 * 60 * 1000
RECHECK_S = 6 * 3600


class Faces(QObject):
    def __init__(self):
        super().__init__()
        self.pos = {}
        enabled = self._load()
        self.faces = {}
        self._menu = None
        self.grok = {"connected": False, "bots": [], "note": "not tried yet"}
        self.update = None
        self.staged = None
        self.hotkey_on = False
        threading.Thread(target=self._probe_grok, daemon=True).start()
        self._probed = 0.0
        if check_updates():
            self._start_probe()
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(UPDATE_TICK_MS)
            self._update_timer.timeout.connect(self._update_tick)
            self._update_timer.start()
        bots = {bot["id"]: bot for bot in list_bots()}
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
        if face.pinned:
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
        face = FaceWindow(bot["id"], bot["name"], spot, slot, bot.get("threadId"), self,
                          bot.get("hue"), bot.get("seed"))
        self.faces[bot["id"]] = face
        face.show()

    def remember(self, agent_id: str, x: int, y: int):
        self.pos[agent_id] = [int(x), int(y)]
        self._save()

    def toggle(self, agent_id: str, on: bool):
        bots = {bot["id"]: bot for bot in list_bots()}
        if on and agent_id not in self.faces and agent_id in bots:
            self._open(bots[agent_id], len(self.faces))
        if not on and agent_id in self.faces:
            self.faces.pop(agent_id).close_face()
        self._save()

    def _link(self, menu: QMenu, label: str, url: str):
        action = menu.addAction(f"{label} ↗")
        action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(url)))

    def _platform_entries(self, menu: QMenu):
        """Which bot apps were found; missing ones get a link."""
        if openbot_installed():
            menu.addAction("OpenBot · detected").setEnabled(False)
        else:
            self._link(menu, "OpenBot not found · get it", OPENBOT_URL)
        if gbot_installed():
            menu.addAction(self.grok_line()).setEnabled(False)
        else:
            self._link(menu, "Grok Bot not found · get it", GROKBOT_URL)

    def _settings_entries(self, menu: QMenu):
        settings = menu.addMenu("Settings")
        settings.addAction(f"Running the {channel.running()} version, v{__version__}").setEnabled(False)
        if self.hotkey_on:
            settings.addAction(f"Open the chat from any app with {HOTKEY_LABEL}").setEnabled(False)
        label = channel.switch_label()
        if label:
            settings.addAction(label).triggered.connect(self.switch_channel)
        settings.addSeparator()
        sound = QAction("Sound on a new answer", settings, checkable=True)
        sound.setChecked(widget_config().get("sound") is True)
        sound.toggled.connect(lambda on: save_widget_config(sound=on))
        settings.addAction(sound)
        quiet = QAction(f"No sound from {QUIET_FROM}:00 to {QUIET_TO:02d}:00", settings, checkable=True)
        quiet.setChecked(widget_config().get("quiet_hours") is True)
        quiet.toggled.connect(lambda on: save_widget_config(quiet_hours=on))
        settings.addAction(quiet)
        top = QAction("Face stays above other windows", settings, checkable=True)
        top.setChecked(always_on_top())
        top.toggled.connect(self._set_always_on_top)
        settings.addAction(top)
        login = QAction("Start at login", settings, checkable=True)
        login.setChecked(startup.is_enabled())
        login.toggled.connect(startup.set_enabled)
        settings.addAction(login)
        check = QAction("Check for updates", settings, checkable=True)
        check.setChecked(check_updates())
        check.toggled.connect(lambda on: save_widget_config(check_updates=on))
        settings.addAction(check)
        if can_install_update():
            auto = QAction("Install updates automatically", settings, checkable=True)
            auto.setChecked(auto_update())
            auto.toggled.connect(lambda on: save_widget_config(auto_update=on))
            settings.addAction(auto)
        settings.addSeparator()
        settings.addAction("Quit Bot Widget").triggered.connect(QApplication.quit)

    def _set_always_on_top(self, on: bool):
        save_widget_config(always_on_top=on)
        for face in self.faces.values():
            face.restack()

    def show_menu(self, face=None):
        """The right-click menu at the mouse. A normal menu, so it responds immediately."""
        menu = QMenu()
        if self.staged:
            menu.addAction(f"Restart to update to v{self.update.version}").triggered.connect(self.install_update)
            menu.addSeparator()
        elif self.update:
            self._link(menu, f"Update available: v{self.update.version}", updates.DOWNLOAD_URL)
            menu.addSeparator()
        self._platform_entries(menu)
        bots = list_bots()
        if bots:
            menu.addSeparator()
        for bot in bots:
            action = QAction(bot["name"], menu, checkable=True)
            action.setChecked(bot["id"] in self.faces)
            action.toggled.connect(lambda on, agent_id=bot["id"]: self.toggle(agent_id, on))
            menu.addAction(action)
        menu.addSeparator()
        self._settings_entries(menu)
        self._menu = menu
        menu.popup(QCursor.pos())
