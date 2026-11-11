"""One face per enabled bot, plus what the menu in the bubble shows and does."""

import json
import math
import os
import sys
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QGuiApplication, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from botwidget import __version__, acp_bots, acplink, channel, checkout, grok_relay, grokbot, hermesbot, startup, updates
from botwidget.config import (
    APP_DIR,
    GROKBOT_URL,
    HERMES_URL,
    OPENBOT_URL,
    STATE_PATH,
    UNLINKED_ID,
    UNLINKED_NAME,
    all_desktops,
    always_on_top,
    auto_update,
    automation_ready,
    check_updates,
    replace_widget_config,
    save_battery,
    muted_bots,
    save_widget_config,
    set_muted,
    set_source_enabled,
    source_enabled,
    sources_off,
    widget_config,
)
from botwidget.openbot import gbot_installed, grok_bot_status, list_bots, openbot_installed
from botwidget.qt_ui import desktops, glass
from botwidget.qt_ui.bubble_window import mark_before_show
from botwidget.qt_ui.native import native_id, raise_window, set_flags
from botwidget.qt_ui.prewarm import prewarm
from botwidget.qt_ui.face import FaceWindow, global_pointer
from botwidget.system.current import (
    CAN_PICK_DESKTOPS,
    HOTKEY_LABEL,
    activate_app,
    can_install_update,
    send_behind_windows,
)


UPDATE_TICK_MS = 10 * 60 * 1000
RECHECK_S = 6 * 3600
CHECKOUT_RECHECK_S = 15 * 60  # code in a checkout changes more often than releases
# Semicircle constants
SEMICIRCLE_RADIUS = 120   # pixels from top-centre
SEMICIRCLE_SLOT_SIZE = 48  # bot diameter in the semicircle
ARC_CATCH_X = 100  # half-width of the 200px top-edge catch rectangle
ARC_CATCH_Y = 70   # depth of the 70px top-edge catch rectangle below the top edge
NAP_S = 5 * 60             # a bot that left the desktop keeps its agent this long, so dragging it back is instant
SEMICIRCLE_GAP = 16        # gap between bot slots
ARC_STEP_S = 0.12          # pause before the next bot leaves the centre
ARC_MOVE_S = 0.26          # one bot's trip


def arc_drag_size(inside: bool, guest: bool, full: int, small: int = SEMICIRCLE_SLOT_SIZE) -> int:
    """A face dragged into the arc shrinks, so it is obvious it is leaving the desktop."""
    if guest or inside:
        return small
    return full


def arc_drop(inside: bool, guest: bool) -> str:
    """What a drop does: turn off into the arc, turn on outside it, or leave it."""
    if guest and not inside:
        return "on"
    if not guest and inside:
        return "off"
    if not guest and not inside:
        return "out"
    return "snap"


def arc_progress(elapsed: float, rank: int, step: float = ARC_STEP_S, move: float = ARC_MOVE_S) -> float:
    """0 before this bot's turn, then 0..1. rank 0 goes first."""
    local = elapsed - rank * step
    if local <= 0 or move <= 0:
        return 0.0
    return min(1.0, local / move)


def arc_catcher_region(width: int, height: int, faces: list) -> QRegion:
    """The opener still feels the pointer. Gaps between the bots do not take clicks."""
    whole = QRegion(0, 0, width, height)
    bots = QRegion()
    for dx, dy, mask in faces:
        bots = bots.united(mask.translated(int(dx), int(dy)))
    if bots.isEmpty():
        return whole
    return whole.subtracted(QRegion(bots.boundingRect())).united(bots)


def bot_source(bot_id: str) -> str:
    """Which app the bot lives in, as the /bots page shows it."""
    if grokbot.is_grok(bot_id):
        return "Grok Bot"
    if hermesbot.is_hermes(bot_id):
        return "Hermes"
    if acplink.is_acp(bot_id):
        return "Harness"
    return "OpenBot"


def _avatar(bot: dict):
    """The face and colour a harness bot asked for. Empty means the seed picks them."""
    shape, colour = bot.get("face") or "", bot.get("color") or ""
    if not shape and not colour:
        return None
    return {"shape": shape, "color": colour}


def _source_name(bot_id: str) -> str:
    """The /connections switch that owns this bot, or empty for harness ACP bots."""
    label = bot_source(bot_id)
    return {"OpenBot": "openbot", "Grok Bot": "grokbot", "Hermes": "hermesbot"}.get(label, "")


def _all_bots() -> list:
    """Every bot the widget can show a face for: the local ones, Grok Bot, Hermes Bot, and the ACP
    bots the user configured in widget.json. A source turned off on /connections is left out."""
    bots = list(list_bots()) if source_enabled("openbot") else []
    if gbot_installed() and source_enabled("grokbot"):
        target = grokbot.target()
        bots.append({"id": grokbot.face_id(target), "name": target, "threadId": None,
                     "hue": None, "seed": grokbot.face_id(target), "status": "ready"})
    if hermesbot.is_hermes_installed() and source_enabled("hermesbot"):
        bots.append({"id": hermesbot.face_id(), "name": "Hermes Bot", "threadId": None,
                     "hue": None, "seed": hermesbot.face_id(), "status": "ready"})
    for bot in acplink.configured_bots():
        bots.append({"id": bot["id"], "name": bot["name"], "threadId": None,
                     "hue": None, "seed": bot["id"], "status": "ready",
                     "face": bot.get("face") or "", "color": bot.get("color") or ""})
    return bots


class ArcCatcher(QWidget):
    """Sits in the top middle. On XWayland the pointer is only known over our own windows."""

    travels = True  # it belongs to the desktop you are on, see desktops.apply

    def __init__(self, faces):
        super().__init__()
        self.faces = faces
        set_flags(self, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._drag = None

    def _face_at(self, gx, gy):
        """The bot shape under this screen point. A guest wins when it sits on a desktop face."""
        hit = None
        for face in list(self.faces.faces.values()) + list(self.faces._arc_guests.values()):
            if not face.isVisible():
                continue
            local = QPoint(int(gx - face.x()), int(gy - face.y()))
            if not face.rect().contains(local):
                continue
            mask = face.mask()
            if not mask.isEmpty() and not mask.contains(local):
                continue
            hit = face
        return hit

    def mousePressEvent(self, event):
        # This window covers the arc, so a press on a small bot arrives here.
        # A press in a gap never arrives: the mask lets it through.
        if event.button() == Qt.LeftButton:
            point = event.globalPosition()
            self._drag = self._face_at(point.x(), point.y())
        elif event.button() == Qt.RightButton:
            point = event.globalPosition()
            face = self._face_at(point.x(), point.y())
            if face is not None:
                face.mousePressEvent(event)
                return
            super().mousePressEvent(event)
            return
        if self._drag is not None:
            self._drag.mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self._drag.mouseMoveEvent(event)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        face = self._drag
        self._drag = None
        if face is not None:
            face.mouseReleaseEvent(event)
            return
        super().mouseReleaseEvent(event)

    def setVisible(self, visible: bool):
        if visible:
            mark_before_show(self)
        super().setVisible(visible)

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None:
            handle.setTransientParent(None)
        self.faces.raise_bubbles()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.faces.show_semicircle()
        self.faces._semicircle_hide_timer.stop()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        # Debounced: a dock popup that briefly covers the catcher must not flicker the arc.
        self.faces.semicircle_pointer_left()

    def paintEvent(self, _event):
        # A fully clear window gets no pointer events. One invisible pixel of paint is enough.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))


class Faces(QObject):
    grok_probed = Signal()  # the roster came back, so the Grok Bot face can take its own avatar
    relay_message = Signal(object)  # a relay message, handled on the Qt thread

    def __init__(self):
        super().__init__()
        self.pos = {}
        if QGuiApplication.platformName() != "offscreen":
            QTimer.singleShot(1500, prewarm)
        enabled = self._load()
        self.faces = {}
        self.grok = {"connected": False, "bots": [], "note": "not tried yet"}
        self.avatar = grokbot.pick_avatar(None, grokbot.target(), self.grok_avatars)
        self.update = None
        self.staged = None
        self.wanted = set()  # connections turned on that were not found: the page is open, the toggle stays on
        self.hotkey_on = False
        # ── semicircle state ────────────────────────────────────
        self._semicircle_phase = "idle"  # idle / showing / hiding
        self._arc_from_bots = False  # the arc was opened for /bots, so closing that page hides it
        self._semicircle = {}  # bot_id → where it sits on the arc right now
        self._arc_order = []
        self._arc_guests = {}  # hidden bots, shown only while the arc is up
        self._naps = {}  # bot_id → the agent of a bot that left the desktop, kept for a moment
        self._arc_t0 = 0.0
        self._arc_mode = "out"
        self._semicircle_timer = QTimer(self)
        self._semicircle_timer.setInterval(16)
        self._semicircle_timer.setTimerType(Qt.PreciseTimer)
        self._semicircle_timer.timeout.connect(self._semicircle_tick)
        self._catcher = ArcCatcher(self)
        self._place_catcher()
        desktops.apply(self._catcher)
        if sys.platform != "darwin":
            self._catcher.show()
            desktops.apply(self._catcher)
        self.raise_bubbles()
        app = QGuiApplication.instance()
        if app is not None:
            app.primaryScreenChanged.connect(self._place_catcher)
        self._semicircle_hide_timer = QTimer(self)
        self._semicircle_hide_timer.setInterval(500)
        self._semicircle_hide_timer.timeout.connect(self._semicircle_hide)
        if sys.platform == "darwin":
            # macOS keeps windows below the menu bar, so the catcher never gets the pointer at the top edge.
            self._edge_timer = QTimer(self)
            self._edge_timer.setInterval(100)
            self._edge_timer.timeout.connect(self._edge_tick)
            self._edge_timer.start()
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
        self.relay_message.connect(self.apply_relay)
        self.relay = grok_relay.Relay(self.relay_message.emit)
        self.relay.start()

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
        cached = data.get("grok_avatars")
        self.grok_avatars = cached if isinstance(cached, dict) else {}
        return enabled

    def _save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        with open(STATE_PATH, "w") as fh:
            json.dump({"enabled": list(self.faces), "pos": self.pos, "grok_avatars": getattr(self, "grok_avatars", {})}, fh)

    def _probe_grok(self):
        """Ask gbot once; no loop, gbot warns about that itself."""
        self.grok = grok_bot_status()
        self.live_avatar = grokbot.avatar_of(self.grok.get("bots"), grokbot.target())
        self.grok_probed.emit()

    def _take_grok_avatar(self):
        """The roster arrived: the Grok Bot face wears the shape and colour Grok Bot gives that bot.

        What Grok Bot said is kept, so that the face still looks right when it cannot be asked.
        """
        target = grokbot.target()
        live = getattr(self, "live_avatar", None)
        if live and self.grok_avatars.get(target) != live:
            self.grok_avatars[target] = live
            self._save()
        self.avatar = grokbot.pick_avatar(live, target, self.grok_avatars)
        face = self.faces.get(grokbot.face_id(target))
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
        elif time.monotonic() - self._probed > (CHECKOUT_RECHECK_S if startup.from_checkout() else RECHECK_S):
            self._start_probe()

    def _probe_update(self):
        """Is there a newer version? If so, and allowed, stage it already. A checkout pulls its own code instead."""
        if startup.from_checkout():
            if auto_update():
                checkout.pull(startup.PACKAGE_ROOT)
            return
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
        if sys.platform != "darwin":
            desktops.bring_here(self._catcher)
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
        if "avatar" in bot:
            avatar = bot["avatar"]
        elif grokbot.is_grok(bot["id"]) or hermesbot.is_hermes(bot["id"]):
            avatar = self.avatar
        else:
            avatar = _avatar(bot)
        face = FaceWindow(bot["id"], bot["name"], spot, slot, bot.get("threadId"), self,
                          bot.get("hue"), bot.get("seed"), avatar, link=self._naps.pop(bot["id"], None))
        self.faces[bot["id"]] = face
        face.show()

    def _nap(self, bot_id: str, link):
        """The agent of a bot that left the desktop keeps running; it stops if nobody asked for the bot back."""
        if link is None:
            return
        self._naps[bot_id] = link
        QTimer.singleShot(NAP_S * 1000, lambda: self._sleep(bot_id, link))

    def _sleep(self, bot_id: str, link):
        if self._naps.get(bot_id) is not link:
            return
        if link.active():
            QTimer.singleShot(30_000, lambda: self._sleep(bot_id, link))  # an answer is still on its way
            return
        self._stop_nap(bot_id)

    def _stop_nap(self, bot_id: str):
        link = self._naps.pop(bot_id, None)
        if link is not None:
            link.close()

    def apply_relay(self, raw):
        """A roster opens a Grok face per bot. A status line shows on the face that bot already has."""
        if isinstance(raw, dict) and raw.get("kind") in ("roster", "status"):
            message = raw
        else:
            message = grok_relay.parse(raw)
        if not isinstance(message, dict):
            return
        if message.get("kind") == "roster":
            for bot in message.get("bots") or []:
                self._show_roster_bot(bot)
        elif message.get("kind") == "status":
            face = self._relay_face(message.get("bot") or "")
            if face is not None:
                face.show_live_status(message["state"], message["summary"])

    def _relay_face(self, name: str):
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        for face in self.faces.values():
            if grokbot.is_grok(face.agent_id) and face.bot_name.strip().lower() == wanted:
                return face
        return None

    def _show_roster_bot(self, bot: dict):
        name = bot.get("name")
        if not isinstance(name, str) or not name.strip():
            return
        name = name.strip()
        live = {}
        for key, field in (("shape", "face"), ("color", "color")):
            value = bot.get(field)
            if isinstance(value, str) and value.strip():
                live[key] = value.strip()
        avatar = grokbot.pick_avatar(live or None, name, self.grok_avatars)
        face = self._relay_face(name)
        if face is None:
            self._open({"id": grokbot.face_id(name), "name": name, "avatar": avatar}, len(self.faces))
            return
        face.set_avatar(avatar)

    def remember(self, agent_id: str, x: int, y: int):
        self.pos[agent_id] = [int(x), int(y)]
        self._save()

    def toggle(self, agent_id: str, on: bool):
        bots = {bot["id"]: bot for bot in _all_bots()}
        if on and agent_id not in self.faces and agent_id in bots:
            self._open(bots[agent_id], len(self.faces))
        if not on and agent_id in self.faces:
            gone = self.faces.pop(agent_id)
            page = gone._menu_page
            gone.close_face(keep_acp=True)
            self._nap(agent_id, gone.acp)
            if page and self.faces:
                # The page was in the bubble of the face that went: it carries on in the bubble of another.
                next(iter(self.faces.values())).open_menu(page)
        self._save()

    def refresh_others(self, agent_id: str):
        """/refresh reloads every bot, not only the one it was typed into; Grok Bot is asked again too."""
        for other_id, face in self.faces.items():
            if other_id != agent_id:
                face.reload_quietly()
        threading.Thread(target=self._probe_grok, daemon=True).start()

    def close_bubbles_except(self, agent_id: str):
        """The bubble of one face is open: the others close, so that only one is up at a time."""
        for other_id, face in self.faces.items():
            if other_id != agent_id and face.bubble.isVisible():
                face.pinned = False
                face.bubble.close_bubble("other_face")

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
            "can_glass": glass.available(), "glass_clear": glass.clear_percent(),
            "all_desktops": all_desktops(), "login": startup.is_enabled(), "check_updates": check_updates(),
            "save_battery": save_battery(),
            "can_install_updates": can_install_update() or startup.from_checkout(), "auto_update": auto_update(),
            "bots": [{"id": bot["id"], "name": bot["name"], "on": bot["id"] in self.faces,
                      "muted": bot["id"] in muted_bots(), "source": bot_source(bot["id"]),
                      "acp": acplink.is_acp(bot["id"])} for bot in bots],
            "bot_form": getattr(self, "_bot_draft", None), "bot_error": getattr(self, "_bot_error", ""),
            "connections": acp_bots.public_connections(config.get("connections")),
            "connection_form": getattr(self, "_connection_draft", None),
            "connection_error": getattr(self, "_connection_error", ""),
            "dev": startup.from_checkout(),
            "debug": startup.from_checkout() and config.get("debug") is True,
            "confirm_remove": getattr(self, "_confirm_remove", ""),
            "json_text": getattr(self, "_json_text", ""), "json_error": getattr(self, "_json_error", ""),
            "openbot": openbot_installed(), "automation_ready": automation_ready(),
            "sources_off": sorted(sources_off()),
            "gbot": gbot_installed(), "grok": self.grok_line(),
            "grok_target": grokbot.target(),
            "hermes": hermesbot.is_hermes_installed(),
            "wanted": sorted(self.wanted),
            "grok_relay": grok_relay.channel(),
            "memory_error": getattr(self, "_memory_error", ""),
            "_memory_text": getattr(self, "_memory_text", ""),
            "_memory_scope": getattr(self, "_memory_scope", "user"),
            "_memory_topic": getattr(self, "_memory_topic", ""),
        }

    TOGGLES = {
        "sound": lambda faces, on: save_widget_config(sound=on),
        "quiet_hours": lambda faces, on: save_widget_config(quiet_hours=on),
        "always_on_top": lambda faces, on: faces._set_always_on_top(on),
        "all_desktops": lambda faces, on: faces._set_all_desktops(on),
        "login": lambda faces, on: startup.set_enabled(on),
        "check_updates": lambda faces, on: save_widget_config(check_updates=on),
        "save_battery": lambda faces, on: save_widget_config(save_battery=on),
        "auto_update": lambda faces, on: save_widget_config(auto_update=on),
        "debug": lambda faces, on: faces._set_debug(on),
    }
    CONNECTIONS = {"openbot": "openbot", "grokbot": "gbot", "hermesbot": "hermes"}
    LINKS = {"openbot": OPENBOT_URL, "grokbot": GROKBOT_URL, "hermesbot": HERMES_URL, "download": updates.DOWNLOAD_URL}

    def _stop_guest(self, ident: str):
        guest = self._arc_guests.pop(ident, None)
        self._semicircle.pop(ident, None)
        if ident in self._arc_order:
            self._arc_order.remove(ident)
        if guest is not None:
            guest.close_face()

    def _apply_bots(self, before: list):
        """Open, restyle or restart only the bots this save changed. The widget itself stays up."""
        after = {bot["id"]: bot for bot in acplink.configured_bots()}
        for action, ident in acp_bots.plan(before, list(after.values())):
            if action == "close":
                if ident in self.faces:
                    self.toggle(ident, False)
                self._stop_nap(ident)
                self._stop_guest(ident)
            elif action == "open":
                self._stop_guest(ident)
                self._stop_nap(ident)
                self.toggle(ident, True)
            elif action == "restart":
                # The old process is the face, or a hidden guest. Either way only this bot stops.
                page = getattr(self.faces.get(ident), "_menu_page", None)
                if ident in self.faces:
                    self.toggle(ident, False)
                self._stop_nap(ident)
                self._stop_guest(ident)
                self.toggle(ident, True)
                if page and ident in self.faces:
                    self.faces[ident].open_menu("bots")
            elif action == "restyle":
                bot = after[ident]
                face = self.faces.get(ident) or self._arc_guests.get(ident)
                if face is None:
                    continue
                face.bot_name = bot["name"]
                face.setWindowTitle(bot["name"])
                face.set_avatar(_avatar(bot))

    def _take(self, fields: dict | None, page: str):
        if not fields:
            return
        if page == "bot" or (isinstance(page, str) and page.startswith("bot/")):
            draft = getattr(self, "_bot_draft", None) or acp_bots.blank()
            for command, value in fields.items():
                if command.startswith("field/"):
                    draft[command[len("field/"):]] = value
            self._bot_draft = draft
        elif page == "widget-json" and "editor" in fields:
            self._json_text = fields["editor"]
        elif page == "connection" or (isinstance(page, str) and page.startswith("connection/")):
            draft = getattr(self, "_connection_draft", None) or acp_bots.blank_connection()
            for command, value in fields.items():
                if command.startswith("field/"):
                    draft[command[len("field/"):]] = value
            self._connection_draft = draft
        elif page == "memory" or (isinstance(page, str) and page.startswith("memory/")):
            if "field/memory_text" in fields:
                self._memory_text = fields.get("field/memory_text", "")
            if "field/memory_scope" in fields:
                self._memory_scope = fields.get("field/memory_scope", "user")
            if "field/memory_topic" in fields:
                self._memory_topic = fields.get("field/memory_topic", "")

    def _open_bot_form(self, face_id: str):
        bots = {bot["id"]: bot for bot in acplink.configured_bots()}
        if face_id in bots:
            self._bot_draft = acp_bots.fields_of(bots[face_id])
        else:
            draft = acp_bots.blank()
            draft["connection"] = acp_bots.first_connection(widget_config().get("connections"))
            self._bot_draft = draft
        self._bot_error = ""

    def _open_connection_form(self, conn_id: str):
        rows = {row["id"]: row for row in acp_bots.public_connections(widget_config().get("connections"))}
        self._connection_draft = (acp_bots.fields_of_connection(rows[conn_id]) if conn_id in rows
                                  else acp_bots.blank_connection())
        self._connection_error = ""

    def _commit_bot(self) -> str:
        previous = acplink.configured_bots()
        entries, error = acp_bots.commit(self._bot_draft or acp_bots.blank(), widget_config().get("acp_bots"),
                                         widget_config().get("connections"))
        if error:
            return error
        save_widget_config(acp_bots=entries)
        if widget_config().get("acp_bots") != entries:
            return "Could not save widget.json."
        self._apply_bots(previous)
        return ""

    def _commit_json(self) -> str:
        data, error = acp_bots.parse_editor(getattr(self, "_json_text", "") or "")
        if error:
            return error
        previous = acplink.configured_bots()
        error = replace_widget_config(data)
        if error:
            return error
        self._apply_bots(previous)
        return ""

    def _commit_connection(self) -> str:
        previous = acplink.configured_bots()
        rows, error = acp_bots.commit_connection(self._connection_draft or acp_bots.blank_connection(),
                                                 widget_config().get("connections"))
        if error:
            return error
        save_widget_config(connections=rows)
        if widget_config().get("connections") != rows:
            return "Could not save widget.json."
        self._apply_bots(previous)
        return ""

    def _set_connection_on(self, conn_id: str):
        """The same kind of switch as OpenBot: on runs the bots that pick it, off stops them."""
        rows = acp_bots.public_connections(widget_config().get("connections"))
        current = next((row for row in rows if row["id"] == conn_id), None)
        if current is None:
            return
        previous = acplink.configured_bots()
        saved = acp_bots.set_connection_on(widget_config().get("connections"), conn_id, not current["on"])
        save_widget_config(connections=saved)
        self._apply_bots(previous)

    def _remove_connection(self, conn_id: str) -> str:
        previous = acplink.configured_bots()
        rows, error = acp_bots.drop_connection(widget_config().get("connections"), conn_id,
                                               widget_config().get("acp_bots"))
        if error:
            return error
        save_widget_config(connections=rows)
        self._apply_bots(previous)
        return ""

    def _remove_bot(self, face_id: str):
        previous = acplink.configured_bots()
        save_widget_config(acp_bots=acp_bots.without(widget_config().get("acp_bots"), face_id))
        self._apply_bots(previous)

    def menu_command(self, command: str, page: str, fields: dict | None = None) -> str | None:
        """Do what a menu row asks; the page to show next, or None to leave the bubble as it is."""
        kind, _, name = command.partition("/")
        if kind not in ("bot-remove", "connection-remove"):
            self._confirm_remove = ""
        if command in ("action/save-bot", "action/save-json", "action/save-connection") or kind == "cycle":
            self._take(fields, page)
        if kind == "page" and (name == "bot" or name.startswith("bot/")):
            self._open_bot_form(name.split("/", 1)[1] if name.startswith("bot/") else "")
            return name
        if kind == "page" and (name == "connection" or name.startswith("connection/")):
            self._open_connection_form(name.split("/", 1)[1] if name.startswith("connection/") else "")
            return name
        if kind == "page" and name == "widget-json":
            self._json_text = acp_bots.public_text(widget_config())
            self._json_error = ""
            return name
        if kind == "page":
            return name
        if kind == "cycle" and name in ("face", "color"):
            draft = self._bot_draft or acp_bots.blank()
            draft[name] = acp_bots.cycle(name, draft.get(name) or "")
            self._bot_draft = draft
            return page
        if kind == "cycle" and name == "workspace_permission":
            draft = self._bot_draft or acp_bots.blank()
            draft["workspace_permissions"] = acp_bots.cycle(
                "workspace_permission", draft.get("workspace_permissions") or "ask")
            self._bot_draft = draft
            return page
        if kind == "cycle" and name == "connection":
            draft = self._bot_draft or acp_bots.blank()
            draft["connection"] = acp_bots.cycle_connection(draft.get("connection") or "",
                                                           widget_config().get("connections"))
            self._bot_draft = draft
            return page
        if kind == "action" and name == "save-bot":
            self._bot_error = self._commit_bot()
            return page if self._bot_error else "bots"
        if kind == "action" and name == "save-json":
            self._json_error = self._commit_json()
            return page if self._json_error else "bots"
        if kind == "action" and name == "save-connection":
            self._connection_error = self._commit_connection()
            return page if self._connection_error else "connections"
        if kind in ("bot-remove", "connection-remove"):
            if getattr(self, "_confirm_remove", "") != command:
                self._confirm_remove = command
                return page
            self._confirm_remove = ""
            if kind == "bot-remove":
                self._remove_bot(name)
                return "bots"
            self._connection_error = self._remove_connection(name)
            return page if self._connection_error else "connections"
        if kind == "connection-toggle":
            self._set_connection_on(name)
            return page
        if kind == "toggle" and name in self.TOGGLES:
            state = self.menu_state()
            self.TOGGLES[name](self, not state[name])
            return page  # re-render the page to show the new state
        elif kind == "slider" and name.startswith("glass/") and name[6:].isdigit():
            self._set_glass(min(100, int(name[6:])))
        elif kind == "bot":
            self.toggle(name, name not in self.faces)
        elif kind == "mute":
            if name in self.faces:
                self.faces[name].toggle_muted()
            else:
                set_muted(name, name not in muted_bots())
            return page
        elif kind == "connect" and name in self.CONNECTIONS:
            if self.menu_state()[self.CONNECTIONS[name]]:
                # Installed: persist on/off separately from whether the app is present.
                on = source_enabled(name)
                set_source_enabled(name, not on)
                if on:
                    self._stop_source(name)
            elif name in self.wanted:
                self.wanted.discard(name)
            else:
                self.wanted.add(name)
                QDesktopServices.openUrl(QUrl(self.LINKS[name]))
            return page
        elif kind == "open" and name in self.LINKS:
            QDesktopServices.openUrl(QUrl(self.LINKS[name]))
        elif kind == "action" and name == "update":
            self.install_update()
        elif kind == "action" and name == "switch":
            self.switch_channel()
        elif kind == "action" and name == "quit":
            QApplication.quit()
        elif kind == "action" and name == "link-grok":
            linked = grok_relay.link_channel()
            if getattr(self, "relay", None) is not None:
                self.relay.start()
            QApplication.clipboard().setText(linked["prompt"])
            return "connections"
        elif kind == "action" and name == "copy-grok-prompt":
            topic = grok_relay.channel()
            if topic:
                QApplication.clipboard().setText(grok_relay.chief_prompt(topic))
            return "connections"
        elif kind == "action" and name == "memory-save":
            self._save_memory()
            return "memory"
        elif kind == "memory-forget":
            self._forget_memory(name)
            return "memory"
        return None

    def _set_debug(self, on: bool):
        """Sample thoughts. An installed copy has no such switch, and a flag left in the file does nothing there."""
        if not startup.from_checkout():
            return
        save_widget_config(debug=bool(on))

    def _save_memory(self) -> None:
        """Persist a new memory from the form fields."""
        try:
            from harness.agent.memory import write_memory
            text = str(getattr(self, "_memory_text", "") or "").strip()
            if not text:
                self._memory_error = "Memory text is required."
                return
            scope = str(getattr(self, "_memory_scope", "user") or "user")
            topic = str(getattr(self, "_memory_topic", "") or "")
            write_memory(text, scope, topic)
            self._memory_error = ""
        except Exception as error:
            self._memory_error = str(error)[:200]

    def _forget_memory(self, memory_id: str) -> None:
        """Forget a memory by ID."""
        try:
            from harness.agent.memory import forget_memory
            forget_memory(memory_id)
        except Exception:
            pass

    def _set_glass(self, percent: int):
        save_widget_config(glass_clear=percent)
        for face in [*self.faces.values(), *self._arc_guests.values()]:
            face.bubble.restyle()

    def _set_all_desktops(self, on: bool):
        save_widget_config(all_desktops=on)
        for face in self.faces.values():
            face.apply_desktops()

    def _set_always_on_top(self, on: bool):
        save_widget_config(always_on_top=on)
        for face in self.faces.values():
            face.restack()

    # ── semicircle ──────────────────────────────────────────────
    def _hotspot(self) -> tuple:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 0.0, 0.0
        geo = screen.geometry()
        return geo.x() + geo.width() / 2, geo.y()

    def _in_hotspot(self, px, py) -> bool:
        cx, cy = self._hotspot()
        return (px - cx) ** 2 + (py - cy) ** 2 <= SEMICIRCLE_RADIUS ** 2

    def _pointer_over_arc(self, px, py) -> bool:
        """The pointer opens the arc from the whole top-middle, not only the 120px dome."""
        cx, cy = self._hotspot()
        return abs(px - cx) < ARC_CATCH_X and cy <= py <= cy + ARC_CATCH_Y

    def _edge_tick(self):
        pos = QCursor.pos()
        near = self._pointer_over_arc(pos.x(), pos.y()) or self._in_hotspot(pos.x(), pos.y())
        # Only the top middle opens the arc. Once it is open, a pointer on a bot or on the arc keeps it open too.
        if near or (self._semicircle_phase != "idle" and (
                self._pointer_on_arc() or self._over_arc_area(pos.x(), pos.y()))):
            self.show_semicircle()
            self._semicircle_hide_timer.stop()
        else:
            self.semicircle_pointer_left()

    def _place_catcher(self, *_args):
        cx, cy = self._hotspot()
        self._catcher.setGeometry(int(cx - ARC_CATCH_X), int(cy), ARC_CATCH_X * 2, ARC_CATCH_Y)

    def _semicircle_tick(self):
        """Move one bot at a time between the centre and its slot."""
        snapping = self._tick_snaps()
        if self._semicircle_phase in ("idle", "visible"):
            if snapping:
                self._emit_semicircle()
            else:
                self._semicircle_timer.stop()
            return
        elapsed = time.monotonic() - self._arc_t0
        inward = self._arc_mode == "in"
        done = True
        for bid in self._arc_order:
            info = self._semicircle.get(bid)
            if not info or info.get("rank") is None:
                continue
            u = arc_progress(elapsed, info["rank"])
            ease = u * u * (3 - 2 * u)
            info["x"] = info["from_x"] + (info["to_x"] - info["from_x"]) * ease
            info["y"] = info["from_y"] + (info["to_y"] - info["from_y"]) * ease
            info["visible"] = u < 1 if inward else u > 0
            if u < 1:
                done = False
        if done:
            if inward:
                self._finish_arc()
                return
            self._semicircle_phase = "visible"
            self._semicircle_timer.stop()
        self._emit_semicircle()

    def _tick_snaps(self) -> bool:
        """Bots let go inside the arc glide back to their slot. True while one of them moved."""
        now = time.monotonic()
        moved = False
        for info in self._semicircle.values():
            t0 = info.get("snap_t0")
            if t0 is None:
                continue
            u = min(1.0, (now - t0) / ARC_MOVE_S) if ARC_MOVE_S > 0 else 1.0
            ease = u * u * (3 - 2 * u)
            fx, fy = info["snap_from"]
            info["x"] = fx + (info["slot_x"] - fx) * ease
            info["y"] = fy + (info["slot_y"] - fy) * ease
            moved = True
            if u >= 1:
                del info["snap_t0"]
        return moved

    def _snap_back(self, face):
        """A bot of the arc let go inside the arc goes back to its own slot, the way a drag-in lands."""
        info = self._semicircle[face.agent_id]
        x = face.x() + face.width() / 2
        y = face.y() + face.height() / 2
        info["x"], info["y"] = x, y
        info["snap_from"] = (x, y)
        info["snap_t0"] = time.monotonic()
        info["visible"] = True
        self._emit_semicircle()
        self._semicircle_timer.start()

    def _emit_semicircle(self):
        """Tell every face on the arc where it is."""
        for face in list(self.faces.values()) + list(self._arc_guests.values()):
            face._set_semicircle(self._semicircle)
        self._fit_catcher_mask()

    def _fit_catcher_mask(self):
        """While the arc is up, only the edge and the bots take clicks. Gaps fall through."""
        catcher = self._catcher
        if self._semicircle_phase == "idle":
            if not catcher.mask().isEmpty():
                catcher.clearMask()
            return
        shapes = []
        ox, oy = catcher.x(), catcher.y()
        for face in list(self.faces.values()) + list(self._arc_guests.values()):
            if not face.isVisible():
                continue
            mask = face.mask()
            shape = mask if not mask.isEmpty() else QRegion(face.rect())
            shapes.append((face.x() - ox, face.y() - oy, shape))
        region = arc_catcher_region(catcher.width(), catcher.height(), shapes)
        if region != catcher.mask():
            catcher.setMask(region)

    def _spawn_guest(self, bot: dict):
        avatar = self.avatar if (grokbot.is_grok(bot["id"]) or hermesbot.is_hermes(bot["id"])) else _avatar(bot)
        face = FaceWindow(bot["id"], bot["name"], None, 0, bot.get("threadId"), self,
                          bot.get("hue"), bot.get("seed"), avatar, guest=True)
        face._arc_guest = True
        face._poll_timer.stop()
        # The catcher stays above ordinary windows. A guest on the bottom layer can never be grabbed.
        set_flags(face, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self._arc_guests[bot["id"]] = face

    def _stop_source(self, name: str) -> None:
        """Close running faces that come from a source the user just turned off."""
        for ident in list(self.faces):
            if _source_name(ident) == name:
                self.toggle(ident, False)

    def _arc_open(self) -> bool:
        return self._semicircle_phase != "idle"

    def _restack_open_bubbles(self) -> None:
        """While the arc is open, bubbles share the top layer so they sit above guest faces.

        set_flags can unmap a window; restack() reapplies flags and shows a bubble that was already open,
        so a /bots page does not vanish and start the hide timer.
        """
        for ident in list(self.faces):
            face = self.faces.get(ident)
            if face is None:
                continue
            for window in (getattr(face, "bubble", None), getattr(face, "thinking", None)):
                if window is None:
                    continue
                restack = getattr(window, "restack", None)
                if callable(restack) and window.isVisible():
                    restack()
                    continue
                apply_flags = getattr(window, "_apply_flags", None)
                if callable(apply_flags):
                    apply_flags()
        self.raise_bubbles()

    def show_semicircle(self):
        """Hidden bots leave the top centre one by one and sit on the arc. Desktop faces stay put."""
        self._watch_arc_pointer()
        if self._semicircle_phase == "hiding":
            cx, cy = self._hotspot()
            for i, bid in enumerate(self._arc_order):
                info = self._semicircle.get(bid)
                if not info:
                    continue
                info["from_x"], info["from_y"] = info["x"], info["y"]
                info["to_x"], info["to_y"] = info["slot_x"], info["slot_y"]
                info["rank"] = i
            self._arc_mode = "out"
            self._arc_t0 = time.monotonic()
            self._semicircle_phase = "showing"
            self._semicircle_timer.start()
            self._restack_open_bubbles()
            return
        if self._semicircle_phase != "idle":
            return
        bots = {bot["id"]: bot for bot in _all_bots()}
        hidden = [bot for bot in bots.values() if bot["id"] not in self.faces]
        for bot in hidden:
            if bot["id"] not in self._arc_guests:
                self._spawn_guest(bot)
        self._arc_order = [bot["id"] for bot in hidden]
        pos = self._semicircle_positions(self._arc_order)
        cx, cy = self._hotspot()
        self._semicircle = {}
        for i, bid in enumerate(self._arc_order):
            sx, sy = pos[bid]
            self._semicircle[bid] = {
                "x": cx, "y": cy, "slot_x": sx, "slot_y": sy,
                "from_x": cx, "from_y": cy, "to_x": sx, "to_y": sy,
                "rank": i, "visible": False, "size": SEMICIRCLE_SLOT_SIZE,
            }
        self._arc_mode = "out"
        self._arc_t0 = time.monotonic()
        self._semicircle_phase = "showing"
        self._semicircle_timer.start()
        self._emit_semicircle()
        self._restack_open_bubbles()

    def hide_semicircle(self):
        """Back to the centre, last arrival first."""
        if self._semicircle_phase == "idle":
            return
        cx, cy = self._hotspot()
        shown = [bid for bid in self._arc_order if self._semicircle.get(bid, {}).get("visible")]
        for bid in self._arc_order:
            info = self._semicircle.get(bid)
            if not info:
                continue
            info["from_x"], info["from_y"] = info["x"], info["y"]
            info["to_x"], info["to_y"] = cx, cy
            info["rank"] = None
        for rank, bid in enumerate(reversed(shown)):
            self._semicircle[bid]["rank"] = rank
        self._arc_mode = "in"
        self._arc_t0 = time.monotonic()
        self._semicircle_phase = "hiding"
        self._semicircle_timer.start()

    def _finish_arc(self):
        guests = list(self._arc_guests.values())
        self._arc_guests = {}
        self._semicircle = {}
        self._arc_order = []
        self._semicircle_phase = "idle"
        self._semicircle_timer.stop()
        self._unwatch_arc_pointer()
        self._emit_semicircle()
        for face in guests:
            face.close_face()
        self._restack_open_bubbles()

    def drop_arc(self, face) -> bool:
        """Drop inside the arc turns a face off. A drop outside turns a hidden bot on."""
        if self._semicircle_phase == "idle":
            return False
        cx = face.x() + face.width() / 2
        cy = face.y() + face.height() / 2
        kind = arc_drop(self._in_hotspot(cx, cy), getattr(face, "_arc_guest", False))
        if kind == "off":
            self._disable_into_arc(face)
            return True
        if kind == "on":
            self._enable_outside(face)
            return True
        if kind == "out":
            self._leave_arc(face)
            return True
        if face.agent_id in self._semicircle:
            self._snap_back(face)
            return True
        return False

    def _park(self, face) -> tuple:
        """Full-size top-left that keeps the face where it was dropped."""
        from botwidget.avatar import AVATAR_SIZE
        x = face.x() + face.width() / 2 - AVATAR_SIZE / 2
        y = face.y() + face.height() / 2 - AVATAR_SIZE / 2
        return int(x), int(y)

    def _leave_arc(self, face):
        """An enabled face dropped outside the arc stays on, at that spot."""
        from botwidget.avatar import AVATAR_SIZE
        bid = face.agent_id
        self._semicircle.pop(bid, None)
        if bid in self._arc_order:
            self._arc_order.remove(bid)
        x, y = self._park(face)
        face._semicircle_visible = False
        face.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        face._move_icon(x, y)
        face._home = (x, y)
        face.show()
        self.remember(bid, x, y)

    def _disable_into_arc(self, face):
        """The dropped face turns off and stays in the arc as a hidden bot."""
        bid = face.agent_id
        x, y = face.x() + face.width() / 2, face.y() + face.height() / 2
        bots = {bot["id"]: bot for bot in _all_bots()}
        face.setWindowOpacity(0.0)  # macOS fades a closing window out, which shows as a ghost where the guest left
        self.toggle(bid, False)
        bot = bots.get(bid)
        if bot and bid not in self._arc_guests:
            self._spawn_guest(bot)
        if bid not in self._semicircle:
            self._arc_order.append(bid)
            self._semicircle[bid] = {
                "x": x, "y": y, "slot_x": x, "slot_y": y,
                "from_x": x, "from_y": y, "to_x": x, "to_y": y,
                "rank": None, "visible": True, "size": SEMICIRCLE_SLOT_SIZE,
            }
        self._glide_to_slots()
        self._emit_semicircle()

    def _glide_to_slots(self):
        """The bots of the arc moved up for one that came or went: each glides from where it is to its new slot."""
        now = time.monotonic()
        for bid, (sx, sy) in self._semicircle_positions(self._arc_order).items():
            info = self._semicircle.get(bid)
            if info is None:
                continue
            info["snap_from"] = (info["x"], info["y"])
            info["slot_x"], info["slot_y"] = sx, sy
            info["snap_t0"] = now
        self._semicircle_timer.start()

    def _enable_outside(self, face):
        """A hidden bot dropped outside the arc becomes a normal face there."""
        from botwidget.avatar import AVATAR_SIZE
        bid = face.agent_id
        x, y = self._park(face)
        self.pos[bid] = [x, y]
        guest = self._arc_guests.pop(bid, None)
        self._semicircle.pop(bid, None)
        if bid in self._arc_order:
            self._arc_order.remove(bid)
        if guest is not None:
            guest._semicircle_visible = False
            guest.close_face()
        self._glide_to_slots()
        self.toggle(bid, True)
        live = self.faces.get(bid)
        if live is not None:
            live._semicircle_visible = False
            live.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            live._move_icon(x, y)
            live._home = (x, y)
            live.show()

    def adopt_arc_guest(self, agent_id: str):
        """A hidden bot was clicked in the arc: it becomes a normal face."""
        guest = self._arc_guests.pop(agent_id, None)
        self._semicircle.pop(agent_id, None)
        if agent_id in self._arc_order:
            self._arc_order.remove(agent_id)
        if guest is not None:
            guest._semicircle_visible = False
            guest.close_face()
        self.toggle(agent_id, True)

    def raise_bubbles(self):
        """Open bubbles stay above the faces. Faces rise only while they should cover other windows.

        A raise on a 'stay behind' face pulls it back over Finder. Arc guests still rise:
        they only exist while the semicircle is open.
        """
        on_top = always_on_top()
        guests = getattr(self, "_arc_guests", {})
        faces = list(getattr(self, "faces", {}).values()) + list(guests.values())
        for face in faces:
            if not face.isVisible():
                pass
            elif on_top or getattr(face, "_arc_guest", False):
                raise_window(face)
            else:
                face.lower()
                send_behind_windows(native_id(face))
        # After every face, so an arc guest cannot sit on top of a menu that was just opened.
        for face in faces:
            bubble = getattr(face, "bubble", None)
            if bubble is not None and bubble.isVisible():
                raise_window(bubble)

    def _drag_in_progress(self) -> bool:
        held = list(getattr(self, "faces", {}).values()) + list(getattr(self, "_arc_guests", {}).values())
        return any(getattr(face, "_drag_origin", None) is not None for face in held)

    def offer_semicircle(self, px, py):
        """A face was dragged here. On Wayland this is the only pointer we can see."""
        if self._in_hotspot(px, py):
            self.show_semicircle()
            self._semicircle_hide_timer.stop()
        elif self._drag_in_progress():
            # Leaving the dome is the drag out. Closing now would destroy the bot under the pointer.
            self._semicircle_hide_timer.stop()
        elif self._semicircle_phase != "idle" and not self._semicircle_hide_timer.isActive():
            self._semicircle_hide_timer.start()

    def semicircle_pointer_here(self):
        self._semicircle_hide_timer.stop()

    def drag_let_go(self):
        """The arc stays up while a bot is dragged out, and may close once the mouse lets go."""
        if self._semicircle_phase == "idle" or self._drag_in_progress():
            return
        self.semicircle_pointer_left()

    def hold_arc(self):
        """Show the hidden bots. Only the /bots page calls this, and it keeps them up until that page closes."""
        self._arc_from_bots = True
        self.show_semicircle()
        self._semicircle_hide_timer.stop()

    def _bots_page_open(self) -> bool:
        return any(getattr(face, "_menu_page", None) == "bots" and face.bubble.isVisible()
                   for face in self.faces.values())

    def release_bots_arc(self):
        """The /bots page closed: the arc it opened leaves on the same short timer as the top edge.

        No hover over the bots is required. The timer is what lets the pointer reach them from the bubble.
        """
        if not getattr(self, "_arc_from_bots", False) or self._bots_page_open() or self._drag_in_progress():
            return
        self._arc_from_bots = False
        if self._semicircle_phase != "idle":
            self._semicircle_hide_timer.start()

    def _arc_bubble_open(self) -> bool:
        """A bot of the arc has its bubble up: the arc stays for as long as you are busy with it."""
        return any(face.bubble.isVisible() for face in self._arc_guests.values())

    def _pointer_on_arc(self) -> bool:
        """The pointer is on a face or on a bot of the arc."""
        if self._arc_bubble_open():
            return True
        catcher = getattr(self, "_catcher", None)
        if catcher is not None and catcher.underMouse():
            # A drag that started on a bot of the arc ran through the catcher, which never hears the pointer leave.
            # Where the platform knows the pointer, its position says whether it is still there.
            pos = QCursor.pos()
            if not global_pointer() or self._over_arc_area(pos.x(), pos.y()):
                return True
        for face in list(self.faces.values()) + list(self._arc_guests.values()):
            if not face.isVisible():
                continue
            over = face.pointer_over() if hasattr(face, "pointer_over") else face.underMouse()
            if over:
                return True
        return False

    def _over_arc_area(self, gx: float, gy: float) -> bool:
        """A click here is on the face or the arc, so it does not dismiss the arc."""
        if self._in_hotspot(gx, gy) or self._pointer_over_arc(gx, gy):
            return True
        widgets = list(self.faces.values()) + list(self._arc_guests.values())
        widgets += [face.bubble for face in self._arc_guests.values()]
        catcher = getattr(self, "_catcher", None)
        if catcher is not None:
            widgets.append(catcher)
        for widget in widgets:
            if widget.isVisible() and widget.geometry().contains(int(gx), int(gy)):
                return True
        return False

    def _watch_arc_pointer(self):
        app = QApplication.instance()
        if app is None or getattr(self, "_arc_watched", False):
            return
        app.installEventFilter(self)
        self._arc_watched = True

    def _unwatch_arc_pointer(self):
        app = QApplication.instance()
        if app is None or not getattr(self, "_arc_watched", False):
            return
        app.removeEventFilter(self)
        self._arc_watched = False

    def eventFilter(self, _watched, event):
        # Wayland never reports the pointer once it has left our windows, so a click or Esc is the other way out.
        if self._semicircle_phase == "idle":
            return False
        kind = event.type()
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide_semicircle()
        elif kind == QEvent.ApplicationDeactivate:
            self.hide_semicircle()
        elif kind == QEvent.MouseButtonPress and not self._over_arc_area(
                event.globalPosition().x(), event.globalPosition().y()):
            self.hide_semicircle()
        return False

    def semicircle_pointer_left(self):
        if self._drag_in_progress() or self._pointer_on_arc() or self._bots_page_open():
            return
        if self._semicircle_phase != "idle" and not self._semicircle_hide_timer.isActive():
            self._semicircle_hide_timer.start()

    def _semicircle_hide(self):
        """The pointer stayed away from the face and the arc, unless /bots still holds it."""
        self._semicircle_hide_timer.stop()
        if self._bots_page_open() or self._arc_bubble_open() or self._drag_in_progress():
            return
        if self._pointer_on_arc():
            return
        pos = QCursor.pos()
        if self._over_arc_area(pos.x(), pos.y()):
            return
        self.hide_semicircle()

    def _semicircle_positions(self, ids=None) -> dict:
        """Face centres along the lower half of a circle under the top middle of the screen."""
        ids = list(self.faces) if ids is None else list(ids)
        cx, cy = self._hotspot()
        n = len(ids)
        pos = {}
        for i, bid in enumerate(ids):
            angle = math.pi * (i + 1) / (n + 1) if n else 0
            pos[bid] = (cx + SEMICIRCLE_RADIUS * math.cos(angle),
                        cy + SEMICIRCLE_RADIUS * math.sin(angle))
        return pos
