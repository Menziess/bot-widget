"""The face as a floating window: avatar, dragging, gaze, notification dot and bubble."""

import datetime
import hashlib
import math
import threading
import time
import uuid

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from botwidget.animation import IDLE_MS, FaceAnimator, frame_ms
from botwidget.avatar import (
    AVATAR_SIZE,
    CIRCLE_R,
    FACE,
    GAZE_NEAR,
    ON_FACE,
    LIFT,
    POSES,
    avatar_profile,
    eye_aim,
    face_svg,
)
from botwidget.config import (
    DOT_COLOR,
    WARN_COLOR,
    GROKBOT_URL,
    OPENBOT_URL,
    POLL_INTERVAL,
    WORK_POLL_INTERVAL,
    always_on_top,
    automation_ready,
    muted_bots,
    set_muted,
)
from botwidget.delivery import Outbox
from botwidget.markdown import (
    block_text,
    code_block,
    control_block,
    conversation_blocks,
    md_blocks,
    plain_block,
    role_panel,
    status_block,
    text_block,
    thought_blocks,
)
from botwidget.openbot import (
    AUTOMATION_OFF,
    ApiResult,
    api_get,
    api_post,
    gbot_installed,
    latest_chat,
    openbot_installed,
)
from botwidget import attachments, menu_pages
from botwidget.qt_ui import desktops, screens
from botwidget.qt_ui.bubble_window import BubbleWindow
from botwidget.qt_ui.render import svg_pixmap
from botwidget.sound import play_sound
from botwidget.system.current import activate_app, send_behind_windows
from botwidget.theme import BUBBLE_FONT

DOT_SIZE = 14
CLICK_SLOP = 5
RETRY_NOTE = "No connection to OpenBot — retrying…"
REFUSED_NOTE = "I couldn't send that. OpenBot answered: {why}."
# OpenBot only opens its local API once this switch is on, per bot.
AUTOMATION_NOTE = ("OpenBot's local API is off for {name}. In OpenBot open {name}'s settings and turn on "
                   '"Local scripts"; messages wait here until then.')
WELCOME_S = 9.0
FOCUS_DWELL_S = 0.25
# After a queued message went out, the next one waits at most this long for the bot to start on it.
QUEUE_HOLD_S = 30.0
MENU_KEEP_S = 2.5  # a menu page stays this long after it opened, pointer or not
BUBBLE_HOVER_MARGIN = 24  # the pointer counts as on the bubble this far outside it
HOVER_RETRY_S = 0.5
# After you closed the bubble on purpose it stays closed this long; if the pointer is still on the face it comes back.
REOPEN_AFTER_S = 3.0


def ticker(parent, ms: int, step) -> QTimer:
    """Repeating timer that stops as soon as step() returns False."""
    timer = QTimer(parent)
    timer.setInterval(ms)

    def fire():
        if not step():
            timer.stop()

    timer.timeout.connect(fire)
    return timer


class FaceWindow(QWidget):
    # Result of the POST from the sending thread back to the window.
    message_done = Signal(str, bool, bool, str)
    attention_done = Signal(bool, str)  # the answer to a question or approval went through, or why not

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
        self._outbox = Outbox()
        # Messages typed while the bot works: they wait here, can be edited, and go out one per finished turn.
        self._muted = agent_id in muted_bots()
        self._attention = {}
        self._answers = {}
        self._answering = set()
        self._attention_note = ""
        self.attention_done.connect(self._on_attention_done)
        self._queue = []
        self._queue_hold = False
        self._queue_hold_until = 0.0
        self._sending = False
        self._send_status = ""
        self._refused = False
        self.message_done.connect(self._on_message_done)
        self._hint_shown = False
        self._shown_text = ""
        self._welcome_until = 0.0
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
        self._pose = "idle"
        self._last_bot = None
        self._answer_pending = False
        self._happy_on = False
        self._hovered = False
        self._hover_since = 0.0
        self._hover_blocked_until = 0.0  # closed on purpose while the pointer is on the face
        self._hover_retry = 0.0
        self._menu_page = None  # a page of the menu is in the bubble
        self._depth = 1  # how many of the latest messages the bubble shows
        self._loading_older = False
        self._conversation = None
        self._messages = []
        self._chat = {}
        self._moving = False
        self.anim = FaceAnimator()
        self.anim.jump(dx=POSES["idle"][0], dy=POSES["idle"][1])
        self._last_tick = time.monotonic()

        self._apply_flags()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self.setWindowTitle(name)

        self._pixmap = None
        self._render()

        self.bubble = BubbleWindow(self)
        self.bubble.older.connect(self.show_older)
        self.bubble.edit_queued.connect(self._edit_queued)
        self.bubble.command.connect(self._menu_command)

        if spot:
            self.move(int(spot[0]), int(spot[1]))
        else:
            self._position_bottom_right(slot)
        # Where the user put the face: it goes back there when the screen it was on returns.
        self._home = self.spot()
        app = QGuiApplication.instance()
        for signal in (app.screenAdded, app.screenRemoved, app.primaryScreenChanged):
            signal.connect(self._screens_changed)
        QTimer.singleShot(0, self._settle)

        self._coast_timer = ticker(self, 16, self._tick_coast)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(IDLE_MS)
        self._anim_timer.setTimerType(Qt.PreciseTimer)
        self._anim_timer.timeout.connect(self._animate)
        self._anim_timer.start()
        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(True)
        self._poll_timer.timeout.connect(self._poll_pending)
        self._poll_timer.start(300)

    # ── Drawing ─────────────────────────────────────────────────

    def _apply_flags(self):
        """Separate from the taskbar; above or below normal windows according to widget.json."""
        layer = Qt.WindowStaysOnTopHint if always_on_top() else Qt.WindowStaysOnBottomHint
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | layer)

    def restack(self):
        """After a change of the setting: new flags ask the window to be shown again."""
        self._apply_flags()
        self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if not always_on_top():
            send_behind_windows(int(self.winId()))
        self.apply_desktops()

    def bring_here(self) -> bool:
        """The face, and the bubble if it is open, to the desktop you are on; True when the face moved."""
        moved = desktops.bring_here(self)
        if self.bubble.isVisible():
            desktops.bring_here(self.bubble)
        return moved

    def apply_desktops(self):
        """On every desktop, or only on this one; the bubble follows the face."""
        desktops.apply(self)
        if self.bubble.isVisible():
            desktops.apply(self.bubble)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self._pixmap)
        if self.has_pending:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(DOT_COLOR))
            painter.drawEllipse(AVATAR_SIZE - DOT_SIZE - 2, 0, DOT_SIZE, DOT_SIZE)
        if self.unsent():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(WARN_COLOR))
            painter.drawEllipse(AVATAR_SIZE - DOT_SIZE - 2, AVATAR_SIZE - DOT_SIZE - 2, DOT_SIZE, DOT_SIZE)

    def unsent(self) -> bool:
        """A message of yours is waiting for OpenBot, or was refused and you have not looked yet."""
        return bool(self._send_status) or self._refused

    def _set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def spot(self) -> tuple:
        return self.x(), self.y()

    def _position_bottom_right(self, slot: int = 0):
        x, y, w, h = screens.rects()[0]
        self.move(x + w - AVATAR_SIZE - 20, y + h - AVATAR_SIZE - 60 - slot * (AVATAR_SIZE + 16))

    # ── Dragging ────────────────────────────────────────────────

    def _stay_on_screen(self, x, y, vx, vy):
        """Keep the icon fully on a screen. If it hits an edge, the speed reverses."""
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
            self.open_commands()
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
        # Happy face: the eyes become ^^ as soon as the mouse is on the head.
        self._happy_on = True
        self.anim.kick("sy", -0.8)

    def mouseMoveEvent(self, event):
        """Move the icon along, but not beyond the edge of a screen."""
        if self._drag_origin is None or not (event.buttons() & Qt.LeftButton):
            return
        point = event.globalPosition()
        ox, oy = self._drag_origin[0]
        raw_x = ox + point.x() - self._press_pos[0]
        raw_y = oy + point.y() - self._press_pos[1]
        x, y, _, _ = self._stay_on_screen(raw_x, raw_y, 0, 0)
        # A little back from the edge while the mouse pulls beyond it.
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
        """A click (hardly any movement) puts the cursor in the field."""
        if event.button() != Qt.LeftButton:
            return
        click = False
        if self._press_pos:
            point = event.globalPosition()
            moved = abs(point.x() - self._press_pos[0]) + abs(point.y() - self._press_pos[1])
            click = moved < CLICK_SLOP
        # Clear the drag state first: _sync_bubble skips the bubble while a drag is running.
        self._press_pos = None
        self._drag_origin = None
        if click and event.modifiers() & Qt.ShiftModifier:
            self.toggle_muted()
        elif click:
            self.open_input()
            # The happy eyes stay a moment; then the cycle picks up again.
            QTimer.singleShot(600, self._happy_off)
        else:
            self._happy_off()
        if self._wall_kick != (0.0, 0.0):
            self._dvx, self._dvy = self._wall_kick
        if abs(self._dvx) > 500 or abs(self._dvy) > 500:
            self._coasting = True
            self.bubble.place("")  # it cannot keep up with a throw
            self._coast_timer.start()
        else:
            self._landed()
            self._remember_spot()

    def _tick_coast(self):
        """Keep going a bit after release, and bounce off the edge."""
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

    def _screens_changed(self, *_):
        # The system needs a moment to arrange the windows and screens itself.
        QTimer.singleShot(400, self._settle)

    def _settle(self):
        """Back to the remembered spot if it is on a screen again, else onto the nearest screen."""
        if not self._alive or self._drag_origin is not None or self._coasting:
            return
        x, y = self._home
        if not screens.fits(x, y, AVATAR_SIZE):
            x, y, _, _ = self._stay_on_screen(self.x(), self.y(), 0, 0)
        if (int(x), int(y)) != self.spot():
            self._move_icon(x, y)

    def _remember_spot(self):
        self._home = self.spot()
        if self.faces is not None:
            self.faces.remember(self.agent_id, self.x(), self.y())

    # ── Face ────────────────────────────────────────────────────

    def _pointer(self) -> tuple:
        pos = QCursor.pos()
        return pos.x(), pos.y()

    def pointer_near(self, bubble) -> bool:
        """Mouse within GAZE_NEAR of the head, or over the bubble?"""
        px, py = self._pointer()
        cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
        if (px - cx) ** 2 + (py - cy) ** 2 <= GAZE_NEAR ** 2:
            return True
        margin = BUBBLE_HOVER_MARGIN
        return bubble.isVisible() and bubble.frameGeometry().adjusted(-margin, -margin, margin, margin).contains(
            QPoint(px, py))

    def _pointer_on_head(self) -> bool:
        px, py = self._pointer()
        cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
        return (px - cx) ** 2 + (py - cy) ** 2 <= GAZE_NEAR ** 2

    def _check_hover(self):
        """Pointing at the face shows the bubble, also when the pointer was already there and did not move."""
        px, py = self._pointer()
        cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
        hovered = (px - cx) ** 2 + (py - cy) ** 2 <= ON_FACE ** 2
        self._hovered = hovered
        now = time.monotonic()
        if not hovered:
            self._hover_since = 0.0
            return
        if (not self.bubble.isVisible() and self._drag_origin is None and not self.pinned and not self._coasting
                and now >= self._hover_blocked_until and now >= self._hover_retry):
            self._hover_retry = now + HOVER_RETRY_S
            self._depth = 1
            self._sync_bubble(latest_chat(thread_id=self.thread_id), force=True)
            self._claim_bubble()
            self._hover_since = now if self.bubble.isVisible() else 0.0
        elif self._hover_since and now - self._hover_since >= FOCUS_DWELL_S and self._drag_origin is None:
            # Typing starts at once, but only when the pointer stays: passing over the face is not asking.
            self._hover_since = 0.0
            if self.bubble.isVisible() and self.bubble.takes_input() and self.bubble.kind == "say":
                activate_app()
                self.bubble.focus_entry()

    def _animate(self):
        """One frame: determine targets, step the springs, draw if something changed."""
        if not self._alive:
            self._anim_timer.stop()
            return
        now = time.monotonic()
        dt, self._last_tick = now - self._last_tick, now
        interval = frame_ms(held=self._drag_origin is not None or self._coasting or self._happy_on,
                            moving=self._moving, pointer_near=self._pointer_on_head())
        if self._anim_timer.interval() != interval:
            self._anim_timer.setInterval(interval)
        self._aim(dt * 1000)
        self._check_hover()
        self._moving = self.anim.step(dt)
        if self._moving:
            self._render()

    def _render(self):
        v = self.anim.value
        svg = face_svg(v["dx"], v["dy"], max(v["scale"], 0.05), v["converge"], self._seed, self._hue,
                       v["lift"], min(max(v["happy"], 0.0), 1.0), lean=v["lean"],
                       squash=(v["sx"], v["sy"]), muted=self._muted)
        self._set_pixmap(svg_pixmap(svg))

    def _aim(self, dt_ms: float):
        """Where the face wants to go: dragging, happy, looking at the mouse, or the normal cycle."""
        a = self.anim
        dragging = self._drag_origin is not None
        speed = math.hypot(self._dvx, self._dvy) if (dragging or self._coasting) else 0.0
        if speed:
            # Stretch along the movement and lean in its direction.
            stretch = min(speed / 1200, 0.10) * (abs(self._dvx) - abs(self._dvy)) / (speed + 1e-6)
            a.aim(sx=1 + stretch, sy=1 - stretch, lean=max(-12.0, min(12.0, self._dvx / 70)))
        else:
            a.aim(sx=1.0, sy=1.0, lean=0.0)
        if dragging or self._happy_on:
            # Happy face: ^^ as soon as the mouse is on the head, half happy while dragging.
            moving = dragging and speed > 20
            look_x = max(-8.0, min(8.0, self._dvx / speed * 8)) if moving else 0.0
            look_y = max(-8.0, min(8.0, self._dvy / speed * 8)) if moving else 0.0
            a.aim(happy=0.5 if moving else 1.0, dx=look_x, dy=look_y, converge=0.0, scale=1.0, lift=0.0)
            return
        a.aim(happy=0.0)
        if not (self._working or self.has_pending):
            px, py = self._pointer()
            target = eye_aim(px - (self.x() + AVATAR_SIZE / 2), py - (self.y() + AVATAR_SIZE / 2))
            if target is not None:
                dx, dy, converge, scale = target
                a.aim(dx=dx, dy=dy, converge=converge, scale=scale, lift=0.0)
                self._cycle_left = 0.0
                return
        self._cycle(dt_ms)

    def _cycle(self, dt_ms: float):
        """Next pose. Idle looks up now and then, work reads, a question looks at you."""
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
        """After dragging: a small landing."""
        self.anim.kick("sy", -1.2)

    def _happy_off(self):
        """Back to the normal eyes and the normal cycle."""
        self._happy_on = False

    # ── Pinning the bubble ──────────────────────────────────────

    def open_input(self):
        """Click on the face: the bubble is there and the cursor is in the field."""
        if not self.bubble.isVisible():
            self._depth = 1
            self._sync_bubble(latest_chat(thread_id=self.thread_id), force=True)
        self._claim_bubble()
        activate_app()
        self.bubble.focus_entry()

    def _claim_bubble(self):
        """One bubble at a time: when this face shows one on your say-so, the bubbles of the others close."""
        if self.faces is not None and self.bubble.isVisible():
            self.faces.close_bubbles_except(self.agent_id)

    def toggle_pin(self):
        if self.pinned:
            self.unpin()
        else:
            self.pin()

    def pin(self):
        """Click on the face: the speech bubble stays, with an input field."""
        self.pinned = True
        self._menu_page = None
        self.has_pending = False
        self._refused = False
        self.update()
        self._sync_bubble(latest_chat(thread_id=self.thread_id))
        self._claim_bubble()
        self.bubble.focus_entry()

    def unpin(self):
        self.pinned = False
        if self._hovered:
            self._hover_blocked_until = time.monotonic() + REOPEN_AFTER_S
        if self._working:
            self._sync_bubble(latest_chat(thread_id=self.thread_id))
        else:
            self.bubble.place("")

    def visible_to_user(self) -> bool:
        """On the screen in front of you, not covered by other windows or on another desktop."""
        handle = self.windowHandle()
        return bool(handle and handle.isExposed())

    def awaiting(self) -> bool:
        """A message of yours is on its way or being answered: the bubble stays until the answer is in."""
        return self._working or self._sending or bool(self._outbox.items)

    def idle(self) -> bool:
        """Nobody is dragging, typing or waiting on this face: a restart would go unnoticed."""
        return not (self.pinned or self._sending or self._working or self._coasting
                    or self._drag_origin is not None)

    def close_face(self):
        """Hide this face and stop its timers."""
        self._alive = False
        self._poll_timer.stop()
        self.bubble.close()
        self.close()

    # ── Polling ─────────────────────────────────────────────────

    def _poll_pending(self):
        """Check whether a question or approval is waiting and refresh the bubble.

        The timer reschedules itself: every second while the turn runs, otherwise every
        POLL_INTERVAL seconds. One timer, no second loop next to it.
        """
        if not self._alive:
            return
        data = api_get(f"/v1/agents/{self.agent_id}/pending")
        changed = False
        if isinstance(data, dict):
            has_pending = bool(data.get("prompts") or data.get("approvals")
                               or data.get("browserTakeovers"))
            if has_pending != self.has_pending:
                self.has_pending = has_pending
                self._update_notification()
            changed = self._set_attention(data)
        self._sync_bubble(latest_chat(thread_id=self.thread_id), force=changed)
        self._poll_timer.start((WORK_POLL_INTERVAL if self._working else POLL_INTERVAL) * 1000)

    def _waiting_note(self, error: str = "") -> str:
        """Why a message is waiting: the switch in OpenBot is off, or the link dropped."""
        if error == AUTOMATION_OFF or not automation_ready():
            return AUTOMATION_NOTE.format(name=self.bot_name)
        return RETRY_NOTE

    def _with_local(self, messages: list) -> list:
        """The conversation from the store plus whatever was just sent here or went wrong."""
        now = time.monotonic()
        stored = {m["text"] for m in messages if m.get("role") == "user"}
        self._local = [m for m in self._local
                       if m["until"] > now and not (m["role"] == "user" and m["text"] in stored)]
        # What was just typed shows at once, before OpenBot has confirmed it.
        waiting = [{"role": "user", "text": item["text"]} for item in self._outbox.items]
        waiting += [{"role": "user", "text": attachments.label_with(item["text"], item["files"]), "queued": item["id"]}
                    for item in self._queue]
        return messages + [{"role": m["role"], "text": m["text"]} for m in self._local] + waiting

    def welcome(self):
        """A short explanation on first start: starting at login can be turned off in Settings."""
        text = (f"Hi, I'm {self.bot_name}. I'll start whenever you log in. "
                "You can switch that off in Settings: right-click me.")
        self._welcome_until = time.monotonic() + WELCOME_S
        self._shown_text = text
        self.bubble.show_blocks(conversation_blocks([{"role": "bot", "text": text}], self.bot_name), "say")

    def _hint_blocks(self) -> list:
        text = ("Hey! I live inside **OpenBot** or **Grok Bot**, and I can't find either on this computer. "
                "Install one and I'll come alive.")
        return conversation_blocks([{"role": "bot", "text": text}], self.bot_name)

    def _sync_bubble(self, chat: dict, force: bool = False):
        """Cloud during a running turn, the conversation as long as the bubble is pinned or fresh."""
        self._working = bool(chat.get("activity")) or self._has_attention()
        self.bubble.set_queueing(self._working, len(self._queue), answering=self._open_question() is not None)
        self._next_queued()
        stored = chat.get("messages") or []
        bots = [msg["text"] for msg in stored if msg.get("role") == "bot" and msg.get("text")]
        last = bots[-1] if bots else ""
        if self._last_bot is None:
            self._last_bot = last  # conversation that was already there: no beep
        elif last and last != self._last_bot:
            self._last_bot = last
            self._answer_pending = True
        if self._answer_pending and not self._working:
            # Not on every step the bot says while it works: once, when the turn is over.
            self._answer_pending = False
            if not self.visible_to_user():
                play_sound()
        if self._drag_origin is not None or time.monotonic() < self._welcome_until:
            return
        if self._menu_page is not None:
            if self.bubble.isVisible():
                return  # a page of the menu is open: the conversation waits
            self._menu_page = None
        if not (openbot_installed() or gbot_installed()):
            if self.pinned or force or not self._hint_shown:
                self._hint_shown = True
                self.bubble.show_blocks(self._hint_blocks(), "hint",
                                        links=[("Get OpenBot", OPENBOT_URL), ("Get Grok Bot", GROKBOT_URL)])
            return
        messages = self._with_local(stored)
        self._chat, self._messages = chat, messages
        newest = (len(messages), messages[-1]["text"] if messages else "")
        if newest != self._conversation:
            # Something new came in: the latest message alone again, the older ones a scroll away.
            self._conversation = newest
            self._depth = 1
        if self._working and not self.pinned:
            if self._muted and not self._has_attention():
                # Thinking is silenced: no cloud, until the face is clicked again.
                self._shown_text = ""
                if self.bubble.kind == "think":
                    self.bubble.place("")
                return
            # The thought, what needs an answer, what waits in line, and last the pulsing dots: the cloud
            # follows the end of the text, so that is where the dots belong.
            blocks = [role_panel("bot")] + thought_blocks(chat.get("activity") or "")
            blocks += self._attention_blocks()
            if self._send_status:
                blocks.append(status_block(self._send_status))
            if self._queue:
                blocks.append(status_block("Queued, click one to edit it"))
                waiting = [{"role": "user", "text": attachments.label_with(item["text"], item["files"]),
                            "queued": item["id"]} for item in self._queue]
                blocks += conversation_blocks(waiting, self.bot_name, limit=len(waiting), max_chars=10 ** 9)
            blocks += [role_panel("bot"), plain_block("dots")]
            # Like an answer: only new things to think about bring the bubble back by themselves.
            text = block_text(blocks)
            if force or text != self._shown_text:
                self._shown_text = text
                self.bubble.show_blocks(blocks, "think", input=True)
            return
        blocks = self._chat_blocks(messages, greet=force or self.pinned)
        text = block_text(blocks)
        older, self._loading_older = self._loading_older, False
        if self.pinned:
            self._shown_text = text
            if not self.bubble.shows("say", text, True):
                self.bubble.show_blocks(blocks, "say", input=True, older=older)
        elif blocks and (force or text != self._shown_text):
            # Only new text brings the bubble back by itself; after it slid away it stays away.
            self._shown_text = text
            self.bubble.show_blocks(blocks, "say", input=True, older=older)
        elif not blocks and self.bubble.kind:
            self.bubble.place("")

    def open_commands(self):
        """Right-click, or the arrow on a page: the list of commands opens above the field, the same as typing a
        slash. What was typed in the field stays."""
        self._menu_page = None
        self.pin()
        self.bubble.open_command_list()
        activate_app()

    def open_menu(self, page: str = "settings"):
        """A page of the menu in the bubble: /settings, /bots or /connections typed or picked."""
        if self.faces is None:
            return
        again = page == self._menu_page and self.bubble.isVisible()
        self._menu_page = page
        # A page smaller than the one before may leave the pointer outside the bubble.
        self.bubble.keep_for(MENU_KEEP_S)
        self.bubble.show_blocks(menu_pages.page_blocks(page, self.faces.menu_state()), "say", keep_scroll=again)
        self._claim_bubble()

    def _menu_command(self, command: str):
        kind, _, rest = command.partition("/")
        if kind in ("answer", "approve"):
            self._attention_command(kind, rest)
            return
        if self.faces is None or self._menu_page is None:
            return
        if command == "page/commands":
            self.open_commands()
            return
        page = self.faces.menu_command(command, self._menu_page)
        if page and self._menu_page is not None:
            self.open_menu(page)

    def show_older(self):
        """Scrolled up past the top: one message more, which slides in."""
        if self.bubble.kind != "say" or self._depth >= len(self._messages):
            return
        self._depth += 1
        self._loading_older = True
        self._sync_bubble(self._chat, force=True)

    def _chat_blocks(self, messages: list, greet: bool) -> list:
        """The conversation, then the dots while a message is on its way, then why it is not going out."""
        shown = messages[-self._depth:]
        blocks = conversation_blocks(shown, self.bot_name, limit=len(shown), max_chars=10 ** 9)
        if blocks and len(messages) > len(shown):
            blocks[:0] = [role_panel("more"), plain_block("more")]
        if not blocks and greet:
            blocks = conversation_blocks([{"role": "bot", "text": f"Hi, I'm {self.bot_name}. Ask me anything."}],
                                         self.bot_name)
        if not blocks:
            return blocks
        if self._working or (self._outbox.items and not self._send_status):
            blocks += [role_panel("bot"), plain_block("dots")]
        blocks += self._attention_blocks()
        # Learn at once that sending is not possible yet.
        status = self._send_status or ("" if automation_ready() else self._waiting_note())
        if status:
            blocks.append(status_block(status))
        return blocks

    def _update_notification(self):
        self.setWindowTitle("Bot Widget 🔔" if self.has_pending else "Bot Widget")
        self.update()

    # ── Sending messages ────────────────────────────────────────

    def on_user_message(self, text: str, files: list = ()):
        """Send a message from the bubble; it only counts as sent once the POST succeeded."""
        files = list(files)
        page = None if files else menu_pages.SLASH.get(text.strip().lower())
        if page:
            self.open_menu(page)
            return
        text = text[:500]
        open_question = None if files else self._open_question()
        if open_question:
            self._give_answer(*open_question, [text])
            return
        if self._working:
            self._queue.append({"text": text, "files": files, "id": uuid.uuid4().hex[:8]})
            self._sync_bubble(latest_chat(thread_id=self.thread_id), force=True)
            self._poll_timer.start(300)
            return
        text = attachments.message_with(text, files)
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        cid = hashlib.sha256(f"{self.agent_id}\n{text}\n{day}".encode()).hexdigest()[:32]
        self._outbox.add(text, cid)
        self._pump_outbox()
        self._sync_bubble(latest_chat(thread_id=self.thread_id))
        self._poll_timer.start(300)

    def _next_queued(self):
        """The turn is over: the oldest queued message goes out, and the next waits for that turn to finish."""
        if self._working:
            self._queue_hold = False
        elif self._queue_hold and time.monotonic() > self._queue_hold_until:
            self._queue_hold = False
        if self._working or self._queue_hold or not self._queue or self._sending or self._outbox.items:
            return
        item = self._queue.pop(0)
        self._queue_hold, self._queue_hold_until = True, time.monotonic() + QUEUE_HOLD_S
        self.on_user_message(item["text"], files=item["files"])

    def _edit_queued(self, queued_id: str):
        """Click on a queued message: it leaves the queue and is back in the field to change."""
        item = next((i for i in self._queue if i["id"] == queued_id), None)
        if item is None:
            return
        self._queue.remove(item)
        self._sync_bubble(self._chat or latest_chat(thread_id=self.thread_id), force=True)
        self.bubble.edit_text(item["text"], item["files"])
        activate_app()
        self.bubble.focus_entry()

    # ── Mute ────────────────────────────────────────────────────

    def toggle_muted(self):
        """Shift+click on a face, thinking or not: its thinking goes quiet, with a cross for a mouth,
        and stays quiet until you do it again, also after a restart."""
        self._muted = not self._muted
        set_muted(self.agent_id, self._muted)
        self._render()
        self._sync_bubble(self._chat or latest_chat(thread_id=self.thread_id), force=True)

    # ── Questions and approvals ─────────────────────────────────

    def _has_attention(self) -> bool:
        return bool(self._attention.get("prompts") or self._attention.get("approvals")
                    or self._attention.get("browserTakeovers"))

    def _set_attention(self, data: dict) -> bool:
        """Remember what waits for you; True when that is something else than before."""
        known = {item.get("requestId") for kind in ("prompts", "approvals", "browserTakeovers")
                 for item in data.get(kind) or []}
        changed = known != {item.get("requestId") for kind in ("prompts", "approvals", "browserTakeovers")
                            for item in self._attention.get(kind) or []}
        self._attention = data
        self._answers = {rid: answers for rid, answers in self._answers.items() if rid in known}
        self._answering &= known
        if changed:
            self._attention_note = ""
        return changed

    def _answerable(self) -> list:
        """Questions this bubble can answer; the ones with a secret need OpenBot itself."""
        return [prompt for prompt in self._attention.get("prompts") or []
                if prompt.get("questions") and not prompt.get("requiresOpenBot")
                and prompt["requestId"] not in self._answering]

    def _open_question(self) -> tuple | None:
        """The first question nobody answered yet, as (request id, question id)."""
        for prompt in self._answerable():
            done = self._answers.get(prompt["requestId"], {})
            for question in prompt["questions"]:
                if question["id"] not in done:
                    return prompt["requestId"], question["id"]
        return None

    def _attention_blocks(self) -> list:
        """What the bot waits for: its questions with a button per option, and approvals to accept or decline."""
        blocks = []
        for prompt in self._attention.get("prompts") or []:
            if prompt["requestId"] in self._answering:
                continue
            if prompt.get("requiresOpenBot") or not prompt.get("questions"):
                blocks += [role_panel("bot"), status_block("A question for you: open OpenBot to answer it.")]
                continue
            chosen = self._answers.get(prompt["requestId"], {})
            for question in prompt["questions"]:
                blocks.append(role_panel("bot"))
                if question.get("header"):
                    blocks.append(text_block(BUBBLE_FONT, 0, "", False, [(question["header"], "b")]))
                blocks += md_blocks(question.get("question") or "")
                for index, option in enumerate(question.get("options") or []):
                    mark = "✓ " if option["label"] in chosen.get(question["id"], []) else ""
                    blocks.append(control_block(
                        "button", mark + option["label"], f"answer/{prompt['requestId']}/{question['id']}/{index}"))
                if not question.get("options"):
                    blocks.append(status_block("Type your answer below."))
        for approval in self._attention.get("approvals") or []:
            if approval["requestId"] in self._answering:
                continue
            title = {"command": "Run a command?", "file-change": "Change files?",
                     "permissions": "Give permissions?"}.get(approval.get("kind"), "Allow this?")
            blocks += [role_panel("bot"), text_block(BUBBLE_FONT, 0, "", False, [(title, "b")])]
            for field in ("reason", "grantRoot", "cwd"):
                if approval.get(field):
                    blocks.append(status_block(approval[field]))
            if approval.get("command"):
                blocks.append(code_block([approval["command"]]))
            blocks += [control_block("button", "Accept", f"approve/{approval['requestId']}/accept"),
                       control_block("button", "Decline", f"approve/{approval['requestId']}/decline")]
        if self._attention.get("browserTakeovers"):
            blocks += [role_panel("bot"), status_block("The browser needs you: open OpenBot to take over.")]
        if self._attention_note:
            blocks.append(status_block(self._attention_note))
        return blocks

    def _attention_command(self, kind: str, rest: str):
        if kind == "approve":
            request_id, _, decision = rest.rpartition("/")
            if any(a["requestId"] == request_id for a in self._attention.get("approvals") or []):
                self._send_attention(request_id, f"approvals/{request_id}/respond", {"decision": decision})
            return
        head, _, index = rest.rpartition("/")
        request_id, _, question_id = head.partition("/")
        prompt = next((p for p in self._answerable() if p["requestId"] == request_id), None)
        question = next((q for q in prompt["questions"] if q["id"] == question_id), None) if prompt else None
        options = (question or {}).get("options") or []
        if index.isdigit() and int(index) < len(options):
            self._give_answer(request_id, question_id, [options[int(index)]["label"]])

    def _give_answer(self, request_id: str, question_id: str, values: list):
        """One question answered; with all of them answered the answer goes to OpenBot."""
        prompt = next((p for p in self._answerable() if p["requestId"] == request_id), None)
        if prompt is None:
            return
        answers = self._answers.setdefault(request_id, {})
        answers[question_id] = values
        if all(question["id"] in answers for question in prompt["questions"]):
            self._send_attention(request_id, f"prompts/{request_id}/answer", {"answers": answers})
        else:
            self._sync_bubble(self._chat, force=True)

    def _send_attention(self, request_id: str, route: str, body: dict):
        self._answering.add(request_id)
        self._sync_bubble(self._chat, force=True)
        threading.Thread(target=self._post_attention, daemon=True,
                         args=(f"/v1/agents/{self.agent_id}/{route}", body)).start()

    def _post_attention(self, path: str, body: dict):
        result = api_post(path, body)
        if self._alive:
            self.attention_done.emit(result.ok, "" if result.ok else result.error)

    def _on_attention_done(self, ok: bool, error: str):
        if not ok:
            self._attention_note = f"That did not go through: {error}."
            self._answering.clear()
            self._answers.clear()
        self._poll_timer.start(200)

    # ── Sending ─────────────────────────────────────────────────

    def _pump_outbox(self):
        """POST the oldest message in a worker thread, so a timeout cannot freeze the face."""
        if self._sending or not self._alive:
            return
        item = self._outbox.current()
        if item is None:
            return
        self._sending = True
        threading.Thread(target=self._post_message, daemon=True,
                         args=(item["text"], item["cid"])).start()

    def _post_message(self, text: str, cid: str):
        if automation_ready():
            result = api_post(f"/v1/agents/{self.agent_id}/messages",
                              {"text": text, "clientMessageId": cid})
        else:
            # Nothing listens yet, so trying would only time out; keep the message and wait.
            result = ApiResult(None, None, AUTOMATION_OFF)
        if self._alive:
            self.message_done.emit(cid, result.ok, result.retryable, result.error)

    def _on_message_done(self, cid: str, ok: bool, retryable: bool, error: str):
        """A user line is local only after a successful POST; a blip is retried, not reported."""
        self._sending = False
        if not self._alive:
            return
        next_ready = True
        if ok:
            item = self._outbox.sent(cid)
            self._send_status = ""
            self._refused = False
            if item is not None:
                self._local.append({"role": "user", "text": item["text"],
                                    "until": time.monotonic() + 120})
        else:
            item = next((i for i in self._outbox.items if i["cid"] == cid), None)
            wait = self._outbox.failed(cid, retryable)
            if wait is None:
                self._send_status = ""
                self._refused = True
                if item is not None:
                    self._local.append({"role": "user", "text": item["text"], "until": time.monotonic() + 60})
                self._local.append({"role": "bot", "until": time.monotonic() + 60,
                                    "text": REFUSED_NOTE.format(why=error)})
            else:
                next_ready = False
                self._send_status = self._waiting_note(error)
                QTimer.singleShot(int(wait * 1000), self._pump_outbox)
        self.update()
        self._sync_bubble(latest_chat(thread_id=self.thread_id))
        if next_ready:
            self._pump_outbox()
