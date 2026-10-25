"""One face per enabled bot, plus what the menu in the bubble shows and does."""

import json
import math
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from botwidget import __version__, channel, checkout, grokbot, hermesbot, startup, updates
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
from botwidget.qt_ui.bubble_window import mark_before_show
from botwidget.qt_ui.native import native_id, set_flags
from botwidget.qt_ui.face import FaceWindow
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
SEMICIRCLE_GAP = 16        # gap between bot slots
ARC_STEP_S = 0.12          # pause before the next bot leaves the centre
ARC_MOVE_S = 0.26          # one bot's trip


def arc_drag_size(inside: bool, guest: bool, enabled: int, full: int,
                  small: int = SEMICIRCLE_SLOT_SIZE) -> int:
    """A face dragged into the arc shrinks, so it is obvious it is leaving the desktop."""
    if guest or (inside and enabled > 1):
        return small
    return full


def arc_drop(inside: bool, guest: bool, enabled: int) -> str:
    """What a drop does: turn off into the arc, turn on outside it, or leave it."""
    if guest and not inside:
        return "on"
    if not guest and inside and enabled > 1:
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


def _all_bots() -> list:
    """Every bot the widget can show a face for: the local ones, Grok Bot, and Hermes Bot."""
    bots = list(list_bots())
    if gbot_installed():
        target = grokbot.target()
        bots.append({"id": grokbot.face_id(target), "name": target, "threadId": None,
                     "hue": None, "seed": grokbot.face_id(target), "status": "ready"})
    if hermesbot.is_hermes_installed():
        bots.append({"id": hermesbot.face_id(), "name": "Hermes Bot", "threadId": None,
                     "hue": None, "seed": hermesbot.face_id(), "status": "ready"})
    return bots


class ArcCatcher(QWidget):
    """Sits in the top middle. On XWayland the pointer is only known over our own windows."""

    def __init__(self, faces):
        super().__init__()
        self.faces = faces
        set_flags(self, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._drag = None

    def _face_at(self, gx, gy):
        """The bot under this screen point. A guest wins when it sits on a desktop face."""
        hit = None
        for face in list(self.faces.faces.values()) + list(self.faces._arc_guests.values()):
            if not face.isVisible():
                continue
            if face.x() <= gx <= face.x() + face.width() and face.y() <= gy <= face.y() + face.height():
                hit = face
        return hit

    def mousePressEvent(self, event):
        # This window covers the arc, so a press on a small bot arrives here.
        if event.button() == Qt.LeftButton:
            point = event.globalPosition()
            self._drag = self._face_at(point.x(), point.y())
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
        if visible and not self.isVisible():
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
        # Start the debounce timer instead of closing immediately; a dock popup
        # that briefly covers the catcher would otherwise trigger a flicker loop.
        if self.faces._semicircle_phase != "idle" and not self.faces._semicircle_hide_timer.isActive():
            self.faces._semicircle_hide_timer.start()

    def paintEvent(self, _event):
        # A fully clear window gets no pointer events. One invisible pixel of paint is enough.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))


class Faces(QObject):
    grok_probed = Signal()  # the roster came back, so the Grok Bot face can take its own avatar

    def __init__(self):
        super().__init__()
        self.pos = {}
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
        self._semicircle = {}  # bot_id → where it sits on the arc right now
        self._arc_order = []
        self._arc_guests = {}  # hidden bots, shown only while the arc is up
        self._arc_t0 = 0.0
        self._arc_mode = "out"
        self._semicircle_timer = QTimer(self)
        self._semicircle_timer.setInterval(16)
        self._semicircle_timer.setTimerType(Qt.PreciseTimer)
        self._semicircle_timer.timeout.connect(self._semicircle_tick)
        self._catcher = ArcCatcher(self)
        self._place_catcher()
        self._catcher.show()
        self.raise_bubbles()
        app = QGuiApplication.instance()
        if app is not None:
            app.primaryScreenChanged.connect(self._place_catcher)
        self._semicircle_hide_timer = QTimer(self)
        self._semicircle_hide_timer.setInterval(500)
        self._semicircle_hide_timer.timeout.connect(self._semicircle_hide)
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
        avatar = self.avatar if (grokbot.is_grok(bot["id"]) or hermesbot.is_hermes(bot["id"])) else None
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
            gone = self.faces.pop(agent_id)
            page = gone._menu_page
            gone.close_face()
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
            "can_install_updates": can_install_update() or startup.from_checkout(), "auto_update": auto_update(),
            "bots": [{"id": bot["id"], "name": bot["name"], "on": bot["id"] in self.faces,
                      "muted": bot["id"] in muted_bots()} for bot in bots],
            "openbot": openbot_installed(), "automation_ready": automation_ready(),
            "gbot": gbot_installed(), "grok": self.grok_line(),
            "grok_target": grokbot.target(),
            "hermes": hermesbot.is_hermes_installed(),
            "wanted": sorted(self.wanted),
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
    CONNECTIONS = {"openbot": "openbot", "grokbot": "gbot", "hermesbot": "hermes"}
    LINKS = {"openbot": OPENBOT_URL, "grokbot": GROKBOT_URL, "hermesbot": updates.DOWNLOAD_URL, "download": updates.DOWNLOAD_URL}

    def menu_command(self, command: str, page: str) -> str | None:
        """Do what a menu row asks; the page to show next, or None to leave the bubble as it is."""
        kind, _, name = command.partition("/")
        if kind == "page":
            return name
        if kind == "toggle" and name in self.TOGGLES:
            state = self.menu_state()
            self.TOGGLES[name](self, not state[name])
            return page  # re-render the page to show the new state
        elif kind == "bot":
            self.toggle(name, name not in self.faces)
        elif kind == "mute":
            if name in self.faces:
                self.faces[name].toggle_muted()
            else:
                set_muted(name, name not in muted_bots())
            return page
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
        return None

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

    def _spawn_guest(self, bot: dict):
        avatar = self.avatar if (grokbot.is_grok(bot["id"]) or hermesbot.is_hermes(bot["id"])) else None
        face = FaceWindow(bot["id"], bot["name"], None, 0, bot.get("threadId"), self,
                          bot.get("hue"), bot.get("seed"), avatar)
        face._arc_guest = True
        face._poll_timer.stop()
        # The catcher stays above ordinary windows. A guest on the bottom layer can never be grabbed.
        set_flags(face, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self._arc_guests[bot["id"]] = face

    def show_semicircle(self):
        """Hidden bots leave the top centre one by one and sit on the arc. Desktop faces stay put."""
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
        self._emit_semicircle()
        for face in guests:
            face.close_face()

    def drop_arc(self, face) -> bool:
        """Drop inside the arc turns a face off. A drop outside turns a hidden bot on."""
        if self._semicircle_phase == "idle":
            return False
        cx = face.x() + face.width() / 2
        cy = face.y() + face.height() / 2
        kind = arc_drop(self._in_hotspot(cx, cy), getattr(face, "_arc_guest", False), len(self.faces))
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
        bots = {bot["id"]: bot for bot in _all_bots()}
        self.toggle(bid, False)
        bot = bots.get(bid)
        if bot and bid not in self._arc_guests:
            self._spawn_guest(bot)
        if bid not in self._semicircle:
            self._arc_order.append(bid)
            sx, sy = self._semicircle_positions(self._arc_order)[bid]
            self._semicircle[bid] = {
                "x": sx, "y": sy, "slot_x": sx, "slot_y": sy,
                "from_x": sx, "from_y": sy, "to_x": sx, "to_y": sy,
                "rank": None, "visible": True, "size": SEMICIRCLE_SLOT_SIZE,
            }
        self._emit_semicircle()

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
        for face in list(getattr(self, "faces", {}).values()) + list(guests.values()):
            if not face.isVisible():
                pass
            elif on_top or getattr(face, "_arc_guest", False):
                face.raise_()
            else:
                face.lower()
                send_behind_windows(native_id(face))
            bubble = getattr(face, "bubble", None)
            if bubble is not None and bubble.isVisible():
                bubble.raise_()
        for face in guests.values():
            if face.isVisible():
                face.raise_()

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

    def semicircle_pointer_left(self):
        if self._drag_in_progress() or self._catcher.underMouse():
            return
        here = list(self._arc_guests.values())
        if any(face.underMouse() for face in here if face.isVisible()):
            return
        if self._semicircle_phase != "idle" and not self._semicircle_hide_timer.isActive():
            self._semicircle_hide_timer.start()

    def _semicircle_hide(self):
        """The pointer stayed away: start the upward slide."""
        self._semicircle_hide_timer.stop()
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
