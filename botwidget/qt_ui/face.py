"""Het gezicht als zwevend venster: avatar, slepen, blik, meldingsstip en bubbel."""

import datetime
import hashlib
import math
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import QWidget

from botwidget.animation import FaceAnimator
from botwidget.avatar import (
    AVATAR_SIZE,
    CIRCLE_R,
    FACE,
    GAZE_NEAR,
    LIFT,
    POSES,
    avatar_profile,
    eye_aim,
    face_svg,
)
from botwidget.config import (
    DOT_COLOR,
    GROKBOT_URL,
    OPENBOT_URL,
    POLL_INTERVAL,
    WORK_POLL_INTERVAL,
    always_on_top,
)
from botwidget.markdown import block_text, conversation_blocks, plain_block, role_panel
from botwidget.openbot import api_get, api_post, gbot_installed, latest_chat, openbot_installed
from botwidget.qt_ui import screens
from botwidget.qt_ui.bubble_window import BubbleWindow
from botwidget.qt_ui.render import svg_pixmap
from botwidget.sound import play_sound
from botwidget.system.current import send_behind_windows

DOT_SIZE = 14
CLICK_SLOP = 5
# Rustig 30 beelden per seconde; 60 zodra je het gezicht vastpakt, dan zie je het verschil.
IDLE_MS = 33
BUSY_MS = 16
# Ademhaling: de kop zwelt traag een paar procent; dat hoeft niet 60 keer per seconde getekend.
BREATH = 0.012
BREATH_PERIOD = 3.8
BREATH_STEP = 0.003


def ticker(parent, ms: int, step) -> QTimer:
    """Herhalende timer die stopt zodra step() False geeft."""
    timer = QTimer(parent)
    timer.setInterval(ms)

    def fire():
        if not step():
            timer.stop()

    timer.timeout.connect(fire)
    return timer


class FaceWindow(QWidget):
    def __init__(self, agent_id: str, name: str,
                 spot=None, slot: int = 0, thread_id: str | None = None, faces=None,
                 hue: float | None = None, seed: str = ""):
        super().__init__()
        self.agent_id = agent_id
        self.bot_name = name
        self.thread_id = thread_id or ("openbot-thread-" + agent_id)
        self.faces = faces
        self._hue = hue
        self._seed = seed or agent_id
        profile = avatar_profile(self._seed, hue)
        self.head_top = AVATAR_SIZE / 2 - profile["top"] * CIRCLE_R
        self.head_bottom = AVATAR_SIZE / 2 + profile["bottom"] * CIRCLE_R
        self._alive = True

        self.has_pending = False
        self.pinned = False
        self._local = []
        self._hint_shown = False
        self._shown_text = ""
        self._press_pos = None
        self._drag_origin = None
        self._drag_sample = None
        self._dvx = self._dvy = 0.0
        self._wall_kick = (0.0, 0.0)
        self._coasting = False
        self._working = False
        self._mood = "idle"
        self._face_i = 0
        self._cycle_left = 0.0
        self._pose = "rest"
        self._last_bot = None
        self._happy_on = False
        self.anim = FaceAnimator()
        self._last_tick = time.monotonic()
        self._breath = 1.0

        self._apply_flags()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self.setWindowTitle(name)
        self.setToolTip(name)

        self._pixmap = None
        self._render()

        self.bubble = BubbleWindow(self)
        self.bubble.clicked.connect(self.pin)

        if spot:
            self.move(int(spot[0]), int(spot[1]))
        else:
            self._position_bottom_right(slot)

        self._coast_timer = ticker(self, 16, self._tick_coast)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(IDLE_MS)
        self._anim_timer.timeout.connect(self._animate)
        self._anim_timer.start()
        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(True)
        self._poll_timer.timeout.connect(self._poll_pending)
        self._poll_timer.start(300)

    # ── Tekenen ────────────────────────────────────────────────────

    def _apply_flags(self):
        """Los van de taakbalk; boven of onder gewone vensters volgens widget.json."""
        layer = Qt.WindowStaysOnTopHint if always_on_top() else Qt.WindowStaysOnBottomHint
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | layer)

    def restack(self):
        """Na een wijziging van de instelling: nieuwe vlaggen vragen het venster opnieuw te tonen."""
        self._apply_flags()
        self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if not always_on_top():
            send_behind_windows(int(self.winId()))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self._pixmap)
        if self.has_pending:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(DOT_COLOR))
            painter.drawEllipse(AVATAR_SIZE - DOT_SIZE - 2, 0, DOT_SIZE, DOT_SIZE)

    def _set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def spot(self) -> tuple:
        return self.x(), self.y()

    def _position_bottom_right(self, slot: int = 0):
        x, y, w, h = screens.rects()[0]
        self.move(x + w - AVATAR_SIZE - 20, y + h - AVATAR_SIZE - 60 - slot * (AVATAR_SIZE + 16))

    # ── Slepen ─────────────────────────────────────────────────────

    def _stay_on_screen(self, x, y, vx, vy):
        """Houd het icoon volledig op een scherm. Raakt het een rand, dan keert de snelheid om."""
        geos = screens.rects()
        if not geos or any(x >= gx and y >= gy and x + AVATAR_SIZE <= gx + gw
                           and y + AVATAR_SIZE <= gy + gh for gx, gy, gw, gh in geos):
            return x, y, vx, vy
        cx, cy = x + AVATAR_SIZE / 2, y + AVATAR_SIZE / 2

        def outside(g):
            nx = min(max(cx, g[0]), g[0] + g[2])
            ny = min(max(cy, g[1]), g[1] + g[3])
            return (cx - nx) ** 2 + (cy - ny) ** 2

        gx, gy, gw, gh = min(geos, key=outside)
        nx = min(max(x, gx), gx + gw - AVATAR_SIZE)
        ny = min(max(y, gy), gy + gh - AVATAR_SIZE)
        if nx != x:
            vx = -vx * 0.55
        if ny != y:
            vy = -vy * 0.55
        return nx, ny, vx, vy

    def _move_icon(self, x, y):
        self.move(int(x), int(y))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            if self.faces is not None:
                self.faces.show_list(self)
            return
        if event.button() != Qt.LeftButton:
            return
        self._coasting = False
        point = event.globalPosition()
        self._press_pos = (point.x(), point.y())
        self._drag_origin = [self.spot()]
        self._drag_sample = (time.monotonic(), *self.spot())
        self._dvx = self._dvy = 0.0
        self._wall_kick = (0.0, 0.0)
        # Blij gezicht: de ogen worden ^^ zodra de muis op de kop staat.
        self._happy_on = True
        self.anim.kick("sy", -0.8)

    def mouseMoveEvent(self, event):
        """Schuif het icoon mee, maar niet voorbij de rand van een scherm."""
        if self._drag_origin is None or not (event.buttons() & Qt.LeftButton):
            return
        point = event.globalPosition()
        ox, oy = self._drag_origin[0]
        raw_x = ox + point.x() - self._press_pos[0]
        raw_y = oy + point.y() - self._press_pos[1]
        x, y, _, _ = self._stay_on_screen(raw_x, raw_y, 0, 0)
        # Een stukje terug van de rand zolang de muis erbuiten trekt.
        inset_x = max(-18, min(18, (raw_x - x) * 0.3))
        inset_y = max(-18, min(18, (raw_y - y) * 0.3))
        x, y, _, _ = self._stay_on_screen(x - inset_x, y - inset_y, 0, 0)
        self._wall_kick = (
            700.0 if raw_x < x else -700.0 if raw_x > x else 0.0,
            700.0 if raw_y < y else -700.0 if raw_y > y else 0.0,
        )
        self._move_icon(x, y)
        now = time.monotonic()
        if self._drag_sample and now - self._drag_sample[0] >= 0.03:
            t, sx, sy = self._drag_sample
            self._dvx = (x - sx) / (now - t)
            self._dvy = (y - sy) / (now - t)
            self._drag_sample = (now, x, y)

    def mouseReleaseEvent(self, event):
        """Klik (bijna geen beweging) toggelt de chat."""
        if event.button() != Qt.LeftButton:
            return
        click = False
        if self._press_pos:
            point = event.globalPosition()
            moved = abs(point.x() - self._press_pos[0]) + abs(point.y() - self._press_pos[1])
            click = moved < CLICK_SLOP
            if click:
                self.toggle_pin()
        self._press_pos = None
        self._drag_origin = None
        if click:
            # De blije ogen blijven even staan; daarna pakt de cyclus weer op.
            QTimer.singleShot(600, self._happy_off)
        else:
            self._happy_off()
        if self._wall_kick != (0.0, 0.0):
            self._dvx, self._dvy = self._wall_kick
        if abs(self._dvx) > 500 or abs(self._dvy) > 500:
            self._coasting = True
            self._coast_timer.start()
        else:
            self._landed()
            self._remember_spot()

    def _tick_coast(self):
        """Na loslaten nog even door, en terugkaatsen op de rand."""
        if not self._alive:
            return False
        if self._drag_origin is not None or not self._coasting:
            self._coasting = False
            return False
        self._dvx *= 0.90
        self._dvy *= 0.90
        nx, ny, self._dvx, self._dvy = self._stay_on_screen(
            self.x() + self._dvx * 0.016, self.y() + self._dvy * 0.016, self._dvx, self._dvy)
        self._move_icon(nx, ny)
        if abs(self._dvx) < 80 and abs(self._dvy) < 80:
            self._coasting = False
            self._dvx = self._dvy = 0.0
            self._landed()
            self._remember_spot()
            return False
        return True

    def _remember_spot(self):
        if self.faces is not None:
            self.faces.remember(self.agent_id, self.x(), self.y())

    # ── Gezicht ────────────────────────────────────────────────────

    def _pointer(self) -> tuple:
        pos = QCursor.pos()
        return pos.x(), pos.y()

    def pointer_near(self, bubble) -> bool:
        """Muis binnen GAZE_NEAR van de kop, of boven de wolk?"""
        px, py = self._pointer()
        cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
        if (px - cx) ** 2 + (py - cy) ** 2 <= GAZE_NEAR ** 2:
            return True
        return bubble.isVisible() and bubble.frameGeometry().contains(QPoint(px, py))

    def _animate(self):
        """Eén beeld: doelen bepalen, de veren een stap, tekenen als er iets veranderd is."""
        if not self._alive:
            self._anim_timer.stop()
            return
        now = time.monotonic()
        dt, self._last_tick = now - self._last_tick, now
        busy = self._drag_origin is not None or self._coasting or self._happy_on
        if self._anim_timer.interval() != (BUSY_MS if busy else IDLE_MS):
            self._anim_timer.setInterval(BUSY_MS if busy else IDLE_MS)
        self._aim(dt * 1000)
        moving = self.anim.step(dt)
        # Ademhaling in stapjes van een tiende pixel: sneller tekenen ziet niemand.
        breath = round((1 + BREATH * math.sin(now * math.tau / BREATH_PERIOD)) / BREATH_STEP) * BREATH_STEP
        if moving or breath != self._breath:
            self._breath = breath
            self._render(breath)

    def _render(self, breath: float = 1.0):
        v = self.anim.value
        svg = face_svg(v["dx"], v["dy"], max(v["scale"], 0.05), v["converge"], self._seed, self._hue,
                       v["lift"], min(max(v["happy"], 0.0), 1.0), lean=v["lean"],
                       squash=(v["sx"] * breath, v["sy"] * breath))
        self._set_pixmap(svg_pixmap(svg))

    def _aim(self, dt_ms: float):
        """Waar wil het gezicht heen: slepen, blij, naar de muis kijken, of de gewone cyclus."""
        a = self.anim
        dragging = self._drag_origin is not None
        speed = math.hypot(self._dvx, self._dvy) if (dragging or self._coasting) else 0.0
        if speed:
            # Rekken langs de beweging en leunen in de richting ervan.
            stretch = min(speed / 1200, 0.10) * (abs(self._dvx) - abs(self._dvy)) / (speed + 1e-6)
            a.aim(sx=1 + stretch, sy=1 - stretch, lean=max(-12.0, min(12.0, self._dvx / 70)))
        else:
            a.aim(sx=1.0, sy=1.0, lean=0.0)
        if dragging or self._happy_on:
            # Blij gezicht: ^^ zodra de muis op de kop staat, half blij tijdens het slepen.
            moving = dragging and speed > 20
            look_x = max(-8.0, min(8.0, self._dvx / speed * 8)) if moving else 0.0
            look_y = max(-8.0, min(8.0, self._dvy / speed * 8)) if moving else 0.0
            a.aim(happy=0.5 if moving else 1.0, dx=look_x, dy=look_y, converge=0.0, scale=1.0, lift=0.0)
            return
        a.aim(happy=0.0)
        if not (self._working or self.has_pending):
            px, py = self._pointer()
            target = eye_aim(px - (self.x() + AVATAR_SIZE / 2), py - (self.y() + AVATAR_SIZE / 2))
            if target != (0.0, 0.0, 0.0, 1.0):
                dx, dy, converge, scale = target
                a.aim(dx=dx, dy=dy, converge=converge, scale=scale, lift=0.0)
                self._cycle_left = 0.0
                return
        self._cycle(dt_ms)

    def _cycle(self, dt_ms: float):
        """Volgende houding. Idle kijkt af en toe op, werk leest, een vraag kijkt aan."""
        mood = "ask" if self.has_pending else ("work" if self._working else "idle")
        if mood != self._mood:
            self._mood = mood
            self._face_i = 0
            self._cycle_left = 0.0
        self._cycle_left -= dt_ms
        if self._cycle_left <= 0:
            pose, self._cycle_left = FACE[mood][self._face_i % len(FACE[mood])]
            self._face_i += 1
            self._set_pose(pose)

    def _set_pose(self, pose: str):
        dx, dy, scale = POSES[pose]
        self.anim.aim(dx=dx, dy=dy, scale=scale, converge=0.0, lift=LIFT.get(pose, 0.0))
        if pose == "hop":
            self.anim.kick("sy", 0.8)
        elif self._pose == "hop":
            self.anim.kick("sy", -1.2)
        self._pose = pose

    def _landed(self):
        """Na het slepen: een kleine landing."""
        self.anim.kick("sy", -1.2)

    def _happy_off(self):
        """Terug naar de gewone ogen en de gewone cyclus."""
        self._happy_on = False

    # ── Bubbel vastzetten ──────────────────────────────────────────

    def toggle_pin(self):
        if self.pinned:
            self.unpin()
        else:
            self.pin()

    def pin(self):
        """Klik op het gezicht: de praatwolk blijft staan, met een invoerveld."""
        self.pinned = True
        self.has_pending = False
        self.update()
        self._sync_bubble(latest_chat(thread_id=self.thread_id))
        self.bubble.focus_entry()

    def unpin(self):
        self.pinned = False
        if self._working:
            self._sync_bubble(latest_chat(thread_id=self.thread_id))
        else:
            self.bubble.place("")

    def close_face(self):
        """Verberg dit gezicht en stop zijn timers."""
        self._alive = False
        self._poll_timer.stop()
        self.bubble.close()
        self.close()

    # ── Peilen ─────────────────────────────────────────────────────

    def _poll_pending(self):
        """Peil of er een vraag of goedkeuring wacht en ververs de bubbel.

        De timer herplant zichzelf: elke seconde zolang de beurt loopt, anders
        elke POLL_INTERVAL seconden. Eén timer, geen tweede lus ernaast.
        """
        if not self._alive:
            return
        data = api_get(f"/v1/agents/{self.agent_id}/pending")
        if isinstance(data, dict):
            has_pending = bool(data.get("prompts") or data.get("approvals")
                               or data.get("browserTakeovers"))
            if has_pending != self.has_pending:
                self.has_pending = has_pending
                self._update_notification()
        self._sync_bubble(latest_chat(thread_id=self.thread_id))
        self._poll_timer.start((WORK_POLL_INTERVAL if self._working else POLL_INTERVAL) * 1000)

    def _with_local(self, messages: list) -> list:
        """Het gesprek uit de store plus wat hier net is verstuurd of misgegaan is."""
        now = time.monotonic()
        stored = {m["text"] for m in messages if m.get("role") == "user"}
        self._local = [m for m in self._local
                       if m["until"] > now and not (m["role"] == "user" and m["text"] in stored)]
        return messages + [{"role": m["role"], "text": m["text"]} for m in self._local]

    def _hint_blocks(self) -> list:
        text = ("Hey! I live inside **OpenBot** or **Grok Bot**, and I can't find either on this computer. "
                "Install one and I'll come alive.")
        return conversation_blocks([{"role": "bot", "text": text}], self.bot_name)

    def _sync_bubble(self, chat: dict):
        """Wolk tijdens een lopende beurt, het gesprek zolang de bubbel vastzit of vers is."""
        self._working = bool(chat.get("activity"))
        stored = chat.get("messages") or []
        bots = [msg["text"] for msg in stored if msg.get("role") == "bot" and msg.get("text")]
        last = bots[-1] if bots else ""
        if self._last_bot is None:
            self._last_bot = last  # gesprek dat er al stond: geen piep
        elif last and last != self._last_bot:
            self._last_bot = last
            play_sound()
        if self._drag_origin is not None:
            return
        if not (openbot_installed() or gbot_installed()):
            if self.pinned or not self._hint_shown:
                self._hint_shown = True
                self.bubble.show_blocks(self._hint_blocks(), "hint",
                                        links=[("Get OpenBot", OPENBOT_URL), ("Get Grok Bot", GROKBOT_URL)])
            return
        messages = self._with_local(stored)
        if self.pinned:
            blocks = conversation_blocks(messages, self.bot_name)
            if not blocks:
                blocks = conversation_blocks([{"role": "bot", "text": f"Hi, I'm {self.bot_name}. Ask me anything."}],
                                             self.bot_name)
            if self._working:
                blocks += [role_panel("bot"), plain_block("dots")]
            self._shown_text = block_text(blocks)
            if not self.bubble.shows("say", self._shown_text, True):
                self.bubble.show_blocks(blocks, "say", input=True)
            return
        if self._working:
            # Wat je net vroeg, met drie pulserende puntjes eronder.
            asked = [m for m in messages if m.get("role") == "user"][-1:]
            blocks = conversation_blocks(asked, self.bot_name) + [role_panel("bot"), plain_block("dots")]
            if not self.bubble.shows("think", block_text(blocks), False):
                self.bubble.show_blocks(blocks, "think")
            return
        blocks = conversation_blocks(messages, self.bot_name)
        text = block_text(blocks)
        if blocks and text != self._shown_text:
            # Alleen nieuwe tekst haalt de bubbel terug; na het wegglijden blijft hij weg.
            self._shown_text = text
            self.bubble.show_blocks(blocks, "say")
        elif not blocks and self.bubble.kind:
            self.bubble.place("")

    def _update_notification(self):
        self.setWindowTitle("Bot Widget 🔔" if self.has_pending else "Bot Widget")
        self.update()

    # ── Berichten versturen ────────────────────────────────────────

    def on_user_message(self, text: str):
        """Een bericht uit de bubbel versturen."""
        if text.strip() == "/settings":
            if self.faces is not None:
                self.faces.show_menu(self)
            return
        now = time.monotonic()
        self._local.append({"role": "user", "text": text[:500], "until": now + 30})
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        cid = hashlib.sha256(f"{self.agent_id}\n{text}\n{day}".encode()).hexdigest()[:32]
        result = api_post(f"/v1/agents/{self.agent_id}/messages",
                          {"text": text, "clientMessageId": cid})
        if result is None:
            self._local.append({"role": "bot", "until": now + 12,
                                "text": "I couldn't send that. Is OpenBot running?"})
        self._sync_bubble(latest_chat(thread_id=self.thread_id))
        self._poll_timer.start(300)
