"""The face as a floating window: avatar, dragging, gaze, notification dot and bubble."""

import datetime
import hashlib
import math
import os
import platform
import random
import threading
import time
import uuid

from PySide6.QtCore import QEasingCurve, QPoint, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from botwidget.animation import IDLE_MS, FaceAnimator, frame_ms
from botwidget.avatar import (
    AVATAR_SIZE,
    CIRCLE_R,
    GAZE_NEAR,
    ON_FACE,
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
from botwidget.motion import STILL, Motion, offsets
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
from botwidget import attachments, grokbot, hermesbot, menu_pages, __version__
from botwidget.qt_ui import desktops, glass, screens
from botwidget.qt_ui.bubble_window import BubbleWindow, mark_before_show, pointer_on, pointer_on_no_window
from botwidget.qt_ui.native import native_id, set_flags
from botwidget.qt_ui.render import svg_pixmap
from botwidget.sound import play_sound
from botwidget.system.current import FACE_IS_TOOL, FOCUS_ON_HOVER, activate_app, send_behind_windows
from botwidget.theme import BUBBLE_FONT

DOT_SIZE = 14
CLICK_SLOP = 5
RETRY_NOTE = "No connection to OpenBot — retrying…"
REFUSED_NOTE = "I couldn't send that. OpenBot answered: {why}."
GROK_REFUSED_NOTE = "I couldn't send that. {why}."
HERMES_REFUSED_NOTE = "I couldn't send that. {why}."
# OpenBot only opens its local API once this switch is on, per bot.
AUTOMATION_NOTE = ("OpenBot's local API is off for {name}. In OpenBot open {name}'s settings and turn on "
                   '"Local scripts"; messages wait here until then.')
WELCOME_S = 9.0
FOCUS_DWELL_S = 0.25
# After a queued message went out, the next one waits at most this long for the bot to start on it.
QUEUE_HOLD_S = 30.0
BUBBLE_HOVER_MARGIN = 24  # the pointer counts as on the bubble this far outside it
HOVER_RETRY_S = 0.5
# After you closed the bubble on purpose it stays closed this long; if the pointer is still on the face it comes back.
REOPEN_AFTER_S = 3.0
# A face dragged into or out of the arc shrinks or grows over this long instead of jumping.
DRAG_RESIZE_MS = 160
# Stacking the bubbles costs X round trips: during a drag at most this often.
DRAG_RESTACK_S = 0.25
# How long the line on how a /refresh went stays under the chat.
REFRESH_NOTE_S = 8.0


def global_pointer() -> bool:
    """Whether the platform tells us where the pointer is anywhere on screen.

    A Wayland client only hears about its own windows, and so does XWayland: QCursor.pos() keeps its last
    value, which reads as a pointer parked on the bubble, so the bubble never closes.
    """
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and QGuiApplication.platformName() in ("wayland", "xcb"):
        return False
    return QGuiApplication.platformName() != "wayland"


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
    grok_polled = Signal()  # Grok Bot was asked for new answers

    def __init__(self, agent_id: str, name: str,
                 spot=None, slot: int = 0, thread_id: str | None = None, faces=None,
                 hue: float | None = None, seed: str = "", avatar: dict | None = None):
        super().__init__()
        self.agent_id = agent_id
        self.bot_name = name
        self.thread_id = thread_id or ("openbot-thread-" + agent_id)
        # A Grok Bot face talks to the gbot command instead of the local OpenBot.
        self.grok = grokbot.GrokLink(name) if grokbot.is_grok(agent_id) else None
        self.hermes = hermesbot.HermesLink(name) if hermesbot.is_hermes(agent_id) else None
        self.faces = faces
        self._hue = hue
        self._seed = seed or agent_id
        self._avatar = avatar
        profile = avatar_profile(self._seed, hue, avatar)
        self.head_top = AVATAR_SIZE / 2 - profile["top"] * CIRCLE_R
        self.head_bottom = AVATAR_SIZE / 2 + profile["bottom"] * CIRCLE_R
        self._alive = True
        self._semicircle_visible = False
        self._semicircle_raised = False
        # Pointer state from Qt's own enter/leave events. On XWayland underMouse() can stay true
        # after the pointer has gone, so a leave newer than the last enter means "not over".
        self._entered_at = None
        self._left_at = None

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
        self.grok_polled.connect(self._on_grok_polled)
        self._hint_shown = False
        self._shown_text = ""
        self._welcome_until = 0.0
        self._seeded = False
        self._press_pos = None
        self._drag_origin = None
        self._drag_sample = None
        self._dvx = self._dvy = 0.0
        self._wall_kick = (0.0, 0.0)
        self._coasting = False
        self._working = False
        # Calm idle, and Grok Bot's clips when something happens (botwidget.motion).
        # Every face its own seed, so that faces started together never move in step.
        self.motion = Motion(seed=f"{agent_id}:{time.time_ns()}:{random.random()}")
        self._faces = ("neutral", "neutral")  # the face the eyes come from and go to
        self._asked = False  # a message went out: the next answer is its reply
        self._asked_at = 0.0  # when, as a time since the epoch
        self._think_quiet = False  # the cloud closed itself: a new thought does not open it again
        # You just sent something: the cloud stays at its dots, also with the pointer on it, until the pointer has
        # left and comes back, or you click the face. Only then do the thought and the field open.
        self._think_held = False
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
        self._refreshing = False  # /refresh asked; the next poll says how it went
        self._refresh_note, self._refresh_note_until = "", 0.0
        self._conversation = None
        self._messages = []
        self._chat = {}
        self._moving = False
        self.anim = FaceAnimator()
        self.anim.jump(pitch=STILL[0], yaw=STILL[1], roll=STILL[2])
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
        self._poll_thread = None  # reference to keep the poll thread alive

    # ── Drawing ─────────────────────────────────────────────────

    def _apply_flags(self):
        """Separate from the taskbar; above or below normal windows according to widget.json."""
        layer = Qt.WindowStaysOnTopHint if always_on_top() else Qt.WindowStaysOnBottomHint
        # Windows: Qt.Tool, no taskbar button. Linux: a normal window, kept out of the taskbar by skip-taskbar
        # written before each map (a tool window there would rise above other apps).
        tool = Qt.Tool if FACE_IS_TOOL else Qt.WindowType(0)
        set_flags(self, Qt.FramelessWindowHint | layer | tool)

    def restack(self):
        """After a change of the setting: new flags ask the window to be shown again."""
        self._apply_flags()
        self.show()
        self.bubble.restack()

    def setVisible(self, visible: bool):
        if visible and not self.isVisible():
            mark_before_show(self)
        super().setVisible(visible)

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        # Not a child of whichever window was in front, so minimizing that one leaves the face up.
        if handle is not None:
            handle.setTransientParent(None)
        if not always_on_top():
            send_behind_windows(native_id(self))
        self.apply_desktops()
        if self.faces is not None:
            self.faces.raise_bubbles()

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

    def _set_semicircle(self, semicircle: dict):
        """Park this face on the arc, or send it home when the arc is gone.

        The face being dragged is left where the pointer holds it.
        """
        info = semicircle.get(self.agent_id) if semicircle else None
        if self._drag_origin is not None and info:
            return
        if not info or not info.get("visible"):
            waiting = info is not None
            if waiting:
                self._semicircle_visible = True
                self.pinned = False
                self.bubble.close_bubble("semicircle")
                # Leave the desktop spot before hiding, so the old picture does not stay behind.
                size = int(info["size"])
                self._move_icon(info["x"] - size / 2, info["y"] - size / 2)
                self.hide()
                return
            if self._semicircle_visible or getattr(self, "_arc_guest", False):
                self._semicircle_visible = False
                if getattr(self, "_arc_guest", False):
                    self.hide()
                    return
                self.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
                self._move_icon(*self._home)
                self.show()
            return
        self._semicircle_visible = True
        self.pinned = False
        self.bubble.close_bubble("semicircle")
        size = int(info["size"])
        if self.width() != size:
            self.setFixedSize(size, size)
        self._move_icon(info["x"] - size / 2, info["y"] - size / 2)
        if not self.isVisible():
            self.show()
        if always_on_top() or getattr(self, "_arc_guest", False):
            if not getattr(self, "_semicircle_raised", False):
                self._semicircle_raised = True
                self.raise_()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self.width(), self.height(), self._pixmap)
        if self.has_pending:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(DOT_COLOR))
            painter.drawEllipse(self.width() - DOT_SIZE - 2, 0, DOT_SIZE, DOT_SIZE)
        if self.unsent():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(WARN_COLOR))
            painter.drawEllipse(self.width() - DOT_SIZE - 2, self.height() - DOT_SIZE - 2, DOT_SIZE, DOT_SIZE)

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

    def _bounce_off_faces(self, x, y, vx, vy):
        """Two heads do not share a spot: a face that runs into another bounces off it, as off a wall."""
        half = AVATAR_SIZE / 2
        for other in getattr(self.faces, "faces", {}).values():
            if other is self or not other.isVisible():
                continue
            dx, dy = x + half - (other.x() + half), y + half - (other.y() + half)
            gap = math.hypot(dx, dy)
            if gap >= AVATAR_SIZE:
                continue
            nx, ny = (dx / gap, dy / gap) if gap else (1.0, 0.0)
            x, y = other.x() + nx * AVATAR_SIZE, other.y() + ny * AVATAR_SIZE
            speed = vx * nx + vy * ny
            if speed < 0:
                vx, vy = (vx - 2 * speed * nx) * 0.55, (vy - 2 * speed * ny) * 0.55
        return self._stay_on_screen(x, y, vx, vy)

    def _make_room(self):
        """Dropped on another face: it steps aside, the way the bounce would have put it."""
        x, y, _, _ = self._bounce_off_faces(self.x(), self.y(), 0.0, 0.0)
        self._move_icon(x, y)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.bubble.isVisible():
            self.unpin()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.open_command_menu()
            return
        if event.button() != Qt.LeftButton:
            return
        self._coasting = False
        point = event.globalPosition()
        self._press_pos = (point.x(), point.y())
        self._drag_origin = [self.spot()]
        self._drag_box = self.width()
        self.raise_()
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
        if self.faces is not None:
            from botwidget.qt_ui.faces import arc_drag_size
            box = getattr(self, "_drag_box", AVATAR_SIZE)
            cx = x + box / 2
            cy = y + box / 2
            size = arc_drag_size(self.faces._in_hotspot(cx, cy), getattr(self, "_arc_guest", False),
                                 len(self.faces.faces), AVATAR_SIZE)
            if size < AVATAR_SIZE and self.bubble.isVisible():
                self.pinned = False
                self.bubble.close_bubble("drag")
            self._drag_center = (cx, cy)
            self._resize_to(size)
            self._move_icon(cx - self.width() / 2, cy - self.height() / 2)
            now = time.monotonic()
            if now - getattr(self, "_restacked_at", 0.0) >= DRAG_RESTACK_S:
                self._restacked_at = now
                self.faces.raise_bubbles()
            self.faces.offer_semicircle(cx, cy)
        now = time.monotonic()
        if self._drag_sample and now - self._drag_sample[0] >= 0.03:
            t, sx, sy = self._drag_sample
            self._dvx = (x - sx) / (now - t)
            self._dvy = (y - sy) / (now - t)
            self._drag_sample = (now, x, y)

    def _resize_to(self, size: int):
        """Grow or shrink around the centre the pointer holds, over DRAG_RESIZE_MS."""
        goal = getattr(self, "_size_goal", None)
        if size == (self.width() if goal is None else goal):
            return
        self._size_goal = size
        anim = getattr(self, "_size_anim", None)
        if anim is None:
            anim = self._size_anim = QVariantAnimation(self)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._apply_drag_size)
        anim.stop()
        anim.setDuration(DRAG_RESIZE_MS)
        anim.setStartValue(float(self.width()))
        anim.setEndValue(float(size))
        anim.start()

    def _apply_drag_size(self, value):
        side = max(1, int(round(value)))
        cx, cy = getattr(self, "_drag_center", (self.x() + self.width() / 2, self.y() + self.height() / 2))
        if self.width() != side:
            self.setFixedSize(side, side)
        self._move_icon(cx - side / 2, cy - side / 2)

    def _finish_resize(self):
        """Let go: the size the drag was heading for, at once, so a drop works on the real size."""
        anim = getattr(self, "_size_anim", None)
        if anim is not None and anim.state() == QVariantAnimation.Running:
            anim.stop()
            self._apply_drag_size(self._size_goal)
        self._size_goal = None

    def mouseReleaseEvent(self, event):
        """A click (hardly any movement) puts the cursor in the field."""
        if event.button() != Qt.LeftButton:
            return
        self._finish_resize()
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
        elif click and getattr(self, "_arc_guest", False) and self.faces is not None:
            self.faces.adopt_arc_guest(self.agent_id)
        elif click and self._semicircle_visible:
            pass
        elif click:
            self.react("click")
            self.open_input()
            # The happy eyes stay a moment; then the cycle picks up again.
            QTimer.singleShot(600, self._happy_off)
        else:
            self._happy_off()
            if self.faces is not None and self.faces.drop_arc(self):
                self.faces.drag_let_go()
                return
        if self.faces is not None:
            self.faces.drag_let_go()
        if self._wall_kick != (0.0, 0.0):
            self._dvx, self._dvy = self._wall_kick
        if abs(self._dvx) > 500 or abs(self._dvy) > 500:
            self._coasting = True
            self.bubble.close_bubble("throw")  # it cannot keep up with a throw
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
        nx, ny, self._dvx, self._dvy = self._bounce_off_faces(nx, ny, self._dvx, self._dvy)
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
        if not self._alive or self._drag_origin is not None or self._coasting or self._semicircle_visible:
            return
        x, y = self._home
        if not screens.fits(x, y, AVATAR_SIZE):
            x, y, _, _ = self._stay_on_screen(self.x(), self.y(), 0, 0)
        if (int(x), int(y)) != self.spot():
            self._move_icon(x, y)

    def _remember_spot(self):
        if self._semicircle_visible:
            return
        self._home = self.spot()
        if self.faces is not None:
            self.faces.remember(self.agent_id, self.x(), self.y())

    # ── Face ────────────────────────────────────────────────────

    def enterEvent(self, event):
        super().enterEvent(event)
        self._entered_at = time.monotonic()
        if self._semicircle_visible and self.faces is not None:
            self.faces.semicircle_pointer_here()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._left_at = time.monotonic()
        # Wayland cannot see the pointer in the gaps, so leaving a small face starts the hide.
        if self._semicircle_visible and self.isVisible() and self.faces is not None:
            self.faces.semicircle_pointer_left()

    def pointer_over(self) -> bool:
        """Whether the pointer is over this window, trusting a leave that came after the last enter."""
        on = pointer_on(self)
        if on is not None:
            return on
        if self._left_at is not None and (self._entered_at is None or self._left_at > self._entered_at):
            return False
        if pointer_on_no_window():
            return False
        return self.underMouse()

    def _pointer(self) -> tuple:
        pos = QCursor.pos()
        return pos.x(), pos.y()

    def pointer_near(self, bubble, margin: int = BUBBLE_HOVER_MARGIN) -> bool:
        """Mouse within GAZE_NEAR of the head, or over the bubble?"""
        # When the app is inactive the user is in another window; a stale underMouse() would otherwise keep
        # the bubble open forever. Where X says which window the pointer is on, that answer counts instead:
        # on GNOME our app is inactive whenever another app has the focus (the Grok Bot app, a terminal),
        # and every bubble that hover or a click opened closed again at once.
        x_knows = not global_pointer() and pointer_on(self) is not None
        if not x_knows and QGuiApplication.applicationState() == Qt.ApplicationInactive:
            return False
        if not global_pointer():
            # Wayland: QCursor.pos() is unreliable (stale), so we only trust
            # Qt's own hit-testing.  underMouse() on the face window tells us
            # whether the pointer is hovering the icon, and on the bubble
            # whether it is hovering the bubble itself.
            if self.pointer_over():
                return True
            return bubble.isVisible() and bubble.pointer_over()
        px, py = self._pointer()
        cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
        if (px - cx) ** 2 + (py - cy) ** 2 <= GAZE_NEAR ** 2:
            return True
        return bubble.isVisible() and bubble.frameGeometry().adjusted(-margin, -margin, margin, margin).contains(
            QPoint(px, py))

    def pointer_known(self) -> bool:
        """Whether the platform says where the pointer is outside our own windows."""
        return global_pointer()

    def _show_think(self) -> bool:
        """Open after you send. Hover brings it back while this turn lasts, not when the bot is idle."""
        if not (self._working or self._sending or self._outbox.items or self._asked):
            return False
        if self._think_expanded():
            return True
        if self._think_quiet:
            return False
        return True

    def shrink_think(self) -> bool:
        """The pointer left the thought: back to the dots while the turn lasts. False when there is nothing to shrink."""
        if self.pinned or self._chat is None or not self._show_think():
            return False
        if getattr(self, "_think_on_bot", False):
            self._sync_bubble(self._chat, force=True)
        return self.bubble.kind == "think" and not getattr(self, "_think_on_bot", False)

    def _think_expanded(self) -> bool:
        """Thought text and the field, while the pointer is on the bot or its bubble."""
        near = self._pointer_on_head() or self.pointer_near(self.bubble)
        if self._think_held:
            if not near:
                self._think_held = False
            return False
        return near

    def _pointer_on_head(self) -> bool:
        if not global_pointer():
            return self.pointer_over()
        px, py = self._pointer()
        cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
        return (px - cx) ** 2 + (py - cy) ** 2 <= ON_FACE ** 2

    def _pointer_is_busy(self) -> bool:
        """The pointer drags another face, or already has the bubble of another face open: pointing at this one
        as well, because the faces overlap, asks for nothing."""
        others = [face for face in getattr(self.faces, "faces", {}).values() if face is not self]
        return any(face._drag_origin is not None or face._coasting or (face._pointer_on_head() and face.bubble.isVisible())
                   for face in others)

    def _check_hover(self):
        """Pointing at the face shows the bubble, also when the pointer was already there and did not move."""
        if self._semicircle_visible:
            return
        on_bot = self._think_expanded()
        pending = self._show_think()
        if pending and not self.pinned and on_bot != getattr(self, "_think_on_bot", False):
            self._think_on_bot = on_bot
            if self._chat is not None:
                self._sync_bubble(self._chat, force=True)
                return
        if not global_pointer():
            on = pointer_on(self)
            hovered = on if on is not None else self.underMouse() and not pointer_on_no_window()
        else:
            px, py = self._pointer()
            cx, cy = self.x() + AVATAR_SIZE / 2, self.y() + AVATAR_SIZE / 2
            hovered = (px - cx) ** 2 + (py - cy) ** 2 <= ON_FACE ** 2
        self._hovered = hovered
        now = time.monotonic()
        if hovered:
            self.bubble.heal()
        if not hovered:
            self._hover_since = 0.0
            return
        self._keep_bubble_here()
        if (not self.bubble.isVisible() and self._drag_origin is None and not self.pinned and not self._coasting
                and now >= self._hover_blocked_until and now >= self._hover_retry and not self._pointer_is_busy()):
            self._hover_retry = now + HOVER_RETRY_S
            self._depth = 1
            self._sync_bubble(self._latest(), force=True)
            self._claim_bubble()
            self.bubble.shown_by_pointer()
            self._hover_since = now if self.bubble.isVisible() else 0.0
        elif (self._hover_since and now - self._hover_since >= FOCUS_DWELL_S and self._drag_origin is None
              and FOCUS_ON_HOVER):
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
                            moving=self._moving, pointer_near=self._pointer_on_head(), playing=self.motion.active)
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
                       squash=(v["sx"], v["sy"]), muted=self._muted, avatar=self._avatar, zoom=v["zoom"],
                       roll=v["roll"], pitch=v["pitch"], yaw=v["yaw"], shift=v["shift"],
                       expression=(*self._faces, min(max(v["morph"], 0.0), 1.0)))
        self._set_pixmap(svg_pixmap(svg))

    def set_avatar(self, avatar: dict | None):
        """Grok Bot told us the bot's own avatar: draw that face from now on."""
        if avatar == self._avatar:
            return
        self._avatar = avatar
        profile = avatar_profile(self._seed, self._hue, avatar)
        self.head_top = AVATAR_SIZE / 2 - profile["top"] * CIRCLE_R
        self.head_bottom = AVATAR_SIZE / 2 + profile["bottom"] * CIRCLE_R
        self._render()

    def _aim(self, dt_ms: float):
        """Where the face wants to go: dragging, happy, looking at the mouse, or what motion plays."""
        a = self.anim
        self.motion.set_mood(self._motion_mood())
        pose = self.motion.step(dt_ms / 1000)
        lift, shift = offsets(pose, CIRCLE_R)
        moved = {"shift": shift, "lift": lift, "zoom": pose["zoom"]}
        dragging = self._drag_origin is not None
        speed = math.hypot(self._dvx, self._dvy) if (dragging or self._coasting) else 0.0
        if speed:
            # Stretch along the movement and lean in its direction.
            stretch = min(speed / 1200, 0.10) * (abs(self._dvx) - abs(self._dvy)) / (speed + 1e-6)
            a.aim(sx=pose["sx"] * (1 + stretch), sy=pose["sy"] * (1 - stretch),
                  lean=max(-12.0, min(12.0, self._dvx / 70)))
        else:
            a.aim(sx=pose["sx"], sy=pose["sy"], lean=0.0)
        if dragging or self._happy_on:
            # Happy face: ^^ as soon as the mouse is on the head, half happy while dragging.
            moving = dragging and speed > 20
            look_x = max(-8.0, min(8.0, self._dvx / speed * 8)) if moving else 0.0
            look_y = max(-8.0, min(8.0, self._dvy / speed * 8)) if moving else 0.0
            a.aim(happy=0.5 if moving else 1.0, dx=look_x, dy=look_y, converge=0.0, scale=1.0,
                  pitch=0.0, yaw=0.0, roll=0.0, **moved)
            self._show_face("neutral")
            return
        a.aim(happy=0.0)
        if self.motion.playing is None and not (self._working or self.has_pending):
            px, py = self._pointer()
            target = eye_aim(px - (self.x() + AVATAR_SIZE / 2), py - (self.y() + AVATAR_SIZE / 2))
            if target is not None:
                dx, dy, converge, scale = target
                a.aim(dx=dx, dy=dy, converge=converge, scale=scale * (1 - pose["lids"]),
                      pitch=0.0, yaw=0.0, roll=0.0, **moved)
                self._show_face(pose["face"])
                return
        a.aim(dx=0.0, dy=0.0, converge=0.0, scale=1 - pose["lids"],
              pitch=pose["pitch"], yaw=pose["yaw"], roll=pose["roll"], **moved)
        # A full turn (Idle_A's spin) ends where it started: no turning back the long way.
        for name in ("pitch", "yaw", "roll"):
            off = a.value[name] - a.target[name]
            if abs(off) > 180:
                a.value[name] -= 360 * round(off / 360)
        self._show_face(pose["face"])

    def _send_status_or_note(self) -> str:
        """Send status or bot note (Grok Bot or Hermes Bot)."""
        if self.grok:
            try:
                return self.grok.note()
            except Exception:
                return ""
        if self.hermes:
            try:
                return self.hermes.note()
            except Exception:
                return ""
        return getattr(self, "_failed_note", "")

    def _failed_since_asked(self, ended: str | None) -> bool:
        """Did the failed turn end after the message went out? An older failure says nothing about this one."""
        try:
            return datetime.datetime.fromisoformat(str(ended).replace("Z", "+00:00")).timestamp() >= self._asked_at - 2
        except ValueError:
            return False

    def _has_grok_or_hermes(self) -> bool:
        return bool(self.grok or self.hermes)

    def _motion_mood(self) -> str:
        """What the face shows while it lasts: a question waits, the bot thinks, there is no route."""
        if self.has_pending:
            return "ask"
        if self._working:
            return "thinking"
        if self._send_status or self._send_status_or_note():
            return "offline"
        return "idle"

    def _show_face(self, face: str):
        """Morph the eyes to one of Grok Bot's faces."""
        if face == self._faces[1]:
            return
        self._faces = (self._faces[1], face)
        self.anim.jump(morph=0.0)
        self.anim.aim(morph=1.0)

    def react(self, event: str):
        """Something happened: play its clip (botwidget.motion.EVENTS) and draw at once."""
        self.motion.event(event)
        if hasattr(self, "_anim_timer") and self._anim_timer.interval() > IDLE_MS:
            self._anim_timer.setInterval(IDLE_MS)

    def _landed(self):
        """After dragging: a small landing, and off any face it was dropped on."""
        self._make_room()
        self.anim.kick("sy", -1.2)

    def _happy_off(self):
        """Back to the normal eyes and the normal cycle."""
        self._happy_on = False

    # ── Pinning the bubble ──────────────────────────────────────

    def open_input(self):
        """Click on the face: the bubble is there and the cursor is in the field."""
        menu = self._menu_page is not None or self.bubble._list_only
        if menu or not self.bubble.isVisible():
            # Clicking the face from a page of the menu, or its command list, is asking for the chat again.
            self._menu_page = None
            self._depth = 1
            self._sync_bubble(self._latest(), force=True, replace_menu=menu)
        self._claim_bubble()
        activate_app()
        self.bubble.focus_entry()

    def _keep_bubble_here(self):
        """A bubble that Qt calls open but that is not on the screen, because macOS took it off or it stayed on
        the desktop you left, never opens again by itself: take it away so that it can open here."""
        bubble = self.bubble
        if not bubble.isVisible() or desktops.shown_here(bubble):
            return
        desktops.apply(bubble)
        if not desktops.shown_here(bubble):
            bubble.close_bubble("other_desktop")
            self._shown_text = ""

    def _claim_bubble(self):
        """One bubble at a time: when this face shows one on your say-so, the bubbles of the others close."""
        if self.faces is not None and self.bubble.isVisible():
            self.faces.close_bubbles_except(self.agent_id)
        if self.bubble.isVisible():
            self._grok_fetch()

    def toggle_pin(self):
        if self.pinned:
            self.unpin()
        else:
            self.pin()

    def pin(self):
        """Click on the face: the speech bubble stays, with an input field."""
        self.pinned = True
        self._think_held = False
        self._menu_page = None
        self.has_pending = False
        self._refused = False
        self.update()
        self._sync_bubble(self._latest())
        self._claim_bubble()
        self.bubble.focus_entry()

    def unpin(self):
        self.pinned = False
        if self._hovered:
            self._hover_blocked_until = time.monotonic() + REOPEN_AFTER_S
        if self._working:
            self._sync_bubble(self._latest())
        else:
            self.bubble.close_bubble("unpin")

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
        glass.clear(self.bubble)
        self.bubble.close()
        self.close()

    # ── Polling ─────────────────────────────────────────────────

    def _cleanup_local(self):
        """Remove expired entries from the local conversation buffer."""
        now = time.monotonic()
        self._local = [item for item in self._local if item.get("until", 0) > now]

    def _latest(self) -> dict:
        """The latest chat of this bot: from Grok Bot or from the local OpenBot."""
        self._cleanup_local()
        return self.grok.chat() if self.grok else (self.hermes.chat() if self.hermes else latest_chat(thread_id=self.thread_id))

    def _poll_pending(self):
        """Check whether a question or approval is waiting and refresh the bubble.

        The timer reschedules itself: every second while the turn runs, otherwise every
        POLL_INTERVAL seconds. One timer, no second loop next to it.
        """
        if not self._alive:
            return
        self._keep_bubble_here()
        if self.grok:
            # Grok Bot is only asked while an answer is awaited or the bubble just opened: no idle timer.
            if self.grok.due() and not self.grok.is_polling:
                if self._poll_thread is None or not self._poll_thread.is_alive():
                    self._poll_thread = threading.Thread(target=self._poll_grok, daemon=True)
                    self._poll_thread.start()
            if self._refreshing and not self.grok.is_polling and (
                    self._poll_thread is None or not self._poll_thread.is_alive()):
                # Nothing went out to Grok Bot after all: say so rather than wait for an answer that never comes.
                self._refreshed(self.grok.note() or "Refreshed.")
            self._sync_bubble(self._latest())
            if self.grok.active():
                self._poll_timer.start(1000)
            return
        if self.hermes:
            # Hermes Bot uses --oneshot mode, no polling needed after send.
            if self._refreshing:
                self._refreshed(self.hermes.note() or "Refreshed.")
                return
            self._sync_bubble(self._latest())
            return
        try:
            data = api_get(f"/v1/agents/{self.agent_id}/pending")
        except Exception:
            data = None
        changed = False
        if isinstance(data, dict):
            has_pending = bool(data.get("prompts") or data.get("approvals")
                               or data.get("browserTakeovers"))
            if has_pending != self.has_pending:
                self.has_pending = has_pending
            changed = self._set_attention(data)
        if self._refreshing:
            self._refreshed("Refreshed." if data is not None else "Could not reach OpenBot.")
        else:
            self._sync_bubble(self._latest(), force=changed)
        self._poll_timer.start((WORK_POLL_INTERVAL if self._working else POLL_INTERVAL) * 1000)

    def _poll_grok(self):
        """Ask Grok Bot for new answers, in a thread so the face keeps moving."""
        self.grok.poll()
        if self._alive:
            self.grok_polled.emit()

    def _refreshed(self, note: str):
        """The refresh is done: the chat comes back with one line on how it went."""
        if not self._refreshing:
            return
        self._refreshing = False
        self._refresh_note, self._refresh_note_until = note, time.monotonic() + REFRESH_NOTE_S
        self._depth = max(self._depth, 1)
        self._sync_bubble(self._latest(), force=True)

    def _on_grok_polled(self):
        if self._alive and self._refreshing:
            self._refreshed(self.grok.note() or "Refreshed.")
            return
        if self._alive:
            self._sync_bubble(self._latest())
            if self.grok.active() and not self._poll_timer.isActive():
                self._poll_timer.start(1000)

    def _grok_fetch(self):
        """The bubble opened: look once for what came in."""
        if self.grok and self._alive:
            self.grok.request_fetch()
            if not self._poll_timer.isActive():
                self._poll_timer.start(0)
        if self.hermes and self._alive:
            self.hermes.request_fetch()
            if not self._poll_timer.isActive():
                self._poll_timer.start(0)

    def _waiting_note(self, error: str = "") -> str:
        """Why a message is waiting: the switch in OpenBot is off, or the link dropped."""
        if self.grok:
            return self.grok.note()
        if self.hermes:
            return self.hermes.note()
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

    def _sync_bubble(self, chat: dict, force: bool = False, replace_menu: bool = False):
        """Cloud during a running turn, the conversation as long as the bubble is pinned or fresh."""
        self._working = bool(chat.get("activity")) or self._has_attention()
        # OpenBot: the last turn failed (a spent provider, say). The face shows it like Grok Bot offline.
        self._failed_note = chat.get("failed") or ""
        if self._asked and self._failed_note and not self._working and self._failed_since_asked(chat.get("failed_at")):
            # The turn for the message that went out ended in failure: no answer is coming, so no more thinking.
            self._asked = False
            self.react("error")
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
        visible = self._with_local(stored)
        if (self._answer_pending and not self._working and visible
                and visible[-1].get("role") == "bot"):
            # The reply is in. A pause while the question is still the latest line is not the end:
            # the cloud would otherwise flip to the chat and back.
            self._answer_pending = False
            self.react("reply" if self._asked else "new_message")
            self._asked = False
            if not self.visible_to_user():
                play_sound()
        if self._drag_origin is not None or time.monotonic() < self._welcome_until:
            return
        if self._menu_page is not None:
            if self.bubble.isVisible():
                return  # a page of the menu is open: the conversation waits
            self._menu_page = None
        if self.bubble._list_only and self.bubble.isVisible() and not replace_menu:
            return  # the right-click menu is open: a busy bot's thinking cloud must not replace it
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
        pending = self._show_think()
        # Clear _asked so the conversation can appear even when the bot's answer
        # has the same text as the last one (so _answer_pending never fires).
        if self._asked and self.grok and self.grok.stopped:
            self._asked = False
            pending = False
        if self._asked and self.hermes and self.hermes.stopped:
            self._asked = False
            pending = False
        if self._asked and not self.grok and not self.hermes and not self._working and not self._sending and not self._outbox.items and not self._queue:
            # Do not clear _asked: the dots should stay until an answer arrives.
            pass
        if pending and not self.pinned:
            if self._muted and not self._has_attention():
                # Thinking is silenced: no cloud, until the face is clicked again.
                self._shown_text = ""
                if self.bubble.kind == "think":
                    self.bubble.close_bubble("quiet")
                return
            # Dots from the moment you ask, before the bot is marked as thinking.
            # Hover shows the thought and the field. Leaving shrinks it back to the dots.
            expanded = self._think_expanded()
            self._think_on_bot = expanded
            if expanded:
                blocks = [role_panel("bot")] + thought_blocks(chat.get("activity") or "")
                blocks += self._attention_blocks()
                if self._send_status:
                    blocks.append(status_block(self._send_status))
                elif self.grok and self.grok.note():
                    blocks.append(status_block(self.grok.note()))
                elif self.hermes and self.hermes.note():
                    blocks.append(status_block(self.hermes.note()))
                if self._queue:
                    blocks.append(status_block("Queued, click one to edit it"))
                    waiting = [{"role": "user", "text": attachments.label_with(item["text"], item["files"]),
                                "queued": item["id"]} for item in self._queue]
                    blocks += conversation_blocks(waiting, self.bot_name, limit=len(waiting), max_chars=10 ** 9)
                blocks += [role_panel("bot"), plain_block("dots")]
            else:
                blocks = [role_panel("bot"), plain_block("dots")]
            text = block_text(blocks) + ("|field" if expanded else "")
            if force or text != self._shown_text or self.bubble.kind != "think":
                self._shown_text = text
                self.bubble.show_blocks(blocks, "think", input=expanded)
            return
        if self._asked and self.grok and self.grok.stopped:
            self._asked = False
        if self._asked and self.hermes and self.hermes.stopped:
            self._asked = False
        # Do not clear _asked here: keep the dots showing until an answer arrives or _answer_pending clears it.
        if (self._working or self._sending or self._outbox.items or self._asked) and not self.pinned:
            # The cloud closed itself. The chat stays away until this turn is over.
            return
        blocks = self._chat_blocks(messages, greet=force or self.pinned)
        text = block_text(blocks)
        older, self._loading_older = self._loading_older, False
        first, self._seeded = not self._seeded, True
        if first and not force and not self.pinned:
            # The conversation as it was when the widget started is old news: only what comes after opens the bubble.
            self._shown_text = text
            self._prepare_bubble(blocks)
            return
        if self.pinned:
            self._shown_text = text
            if not self.bubble.shows("say", text, True):
                self.bubble.show_blocks(blocks, "say", input=True, older=older, hover_field=True)
        elif blocks and (force or text != self._shown_text):
            # Only new text brings the bubble back by itself; after it slid away it stays away.
            self._shown_text = text
            self.bubble.show_blocks(blocks, "say", input=True, older=older, hover_field=True)
        elif not blocks and self.bubble.kind and not self.bubble._list_only:
            # The conversation is gone (a new chat): the bubble goes too, unless the pointer is engaged with it.
            self.bubble.close_bubble("empty")
        else:
            self._prepare_bubble(blocks)

    def _prepare_bubble(self, blocks: list):
        """The bubble that pointing at the face opens next, laid out while nobody waits for it, so opening it is
        instant. Later, in an idle moment: this runs in the middle of a poll."""
        if blocks and not self.bubble.kind:
            QTimer.singleShot(0, lambda: self.bubble.prepare(blocks, "say", True))

    def open_feedback(self):
        """Open a prefilled GitHub issue in the browser. The user logs in there.

        The bubble says what happens and then how it went, and goes by itself: never an empty bubble.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from botwidget.startup import install_kind
        self._menu_page = None
        self.pinned = False
        self.bubble.show_blocks([status_block("Opening a GitHub issue in your browser…")], "say")
        url = menu_pages.feedback_issue_url(__version__, platform.system(), install_kind())
        opened = QDesktopServices.openUrl(QUrl(url))
        note = ("Opened in your browser: describe what happened there." if opened
                else "Could not open the browser. The issue page is github.com/Menziess/bot-widget/issues.")
        self.bubble.show_blocks([status_block(note)], "say")
        self.bubble.shown_by_pointer()

    def refresh(self):
        """Reload every bot now: this one says it is busy at once and how it went once the chat is in (never an
        empty bubble); the others reload quietly. A bot that got stuck is reset along the way."""
        if self.faces is not None and hasattr(self.faces, "refresh_others"):
            self.faces.refresh_others(self.agent_id)
        self._reset_state()
        self._menu_page = None
        self._refreshing = True
        self._refresh_note = ""
        self.bubble.show_blocks([status_block("Refreshing…"), role_panel("bot"), plain_block("dots")], "say")
        if self.grok:
            self.grok.request_fetch()
        if self.hermes:
            self.hermes.request_fetch()
        self._poll_timer.start(0)

    def _reset_state(self):
        """What can keep a bubble from opening: a pin nobody can take off, a quiet thought, a hover pause."""
        self.pinned = False
        self._think_quiet = False
        self._think_held = False
        self._hover_blocked_until = 0.0
        self._hover_retry = 0.0

    def reload_quietly(self):
        """/refresh typed into another bot: reset and reload this one without opening its bubble."""
        self._reset_state()
        self.bubble.close_bubble("refresh")
        if self.grok:
            self.grok.request_fetch()
        if self.hermes:
            self.hermes.request_fetch()
        self._poll_timer.start(0)

    def open_commands(self):
        """The arrow on top of a page: the list of commands on its own, exactly what a first right-click shows.
        Not the conversation: that is what hovering the face is for."""
        self.open_command_menu()

    def open_command_menu(self):
        """Right-click, or back from a page: the command list in the bubble. Asked for on purpose, so the other
        bubbles close and it never gives way to one of them."""
        self.bubble.heal()
        self._menu_page = None
        self.pinned = False
        if self.faces is not None:
            self.faces.close_bubbles_except(self.agent_id)
        self.bubble.show_command_menu()

    def open_menu(self, page: str = "settings"):
        """A page of the menu in the bubble: /settings, /bots or /connections typed or picked."""
        if self.faces is None:
            return
        again = page == self._menu_page and self.bubble.isVisible()
        self._menu_page = page
        # A page goes away by itself like any bubble, and with Escape.
        self.pinned = False
        # The others close first: a tall page would otherwise give way to a bubble it is about to replace.
        self.faces.close_bubbles_except(self.agent_id)
        self.bubble.show_blocks(menu_pages.page_blocks(page, self.faces.menu_state()), "say", keep_scroll=again)
        self._claim_bubble()
        self.bubble.activateWindow()
        self.bubble.setFocus()

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
        if page is not None:
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
            # A Grok face says why it stopped even with nothing in the chat yet.
            note = self.grok.note() if self.grok else (self.hermes.note() if self.hermes else "")
            return [status_block(note)] if note else blocks
        if self._working or (self._outbox.items and not self._send_status):
            blocks += [role_panel("bot"), plain_block("dots")]
        blocks += self._attention_blocks()
        # Learn at once that sending is not possible yet.
        if self.grok:
            status = self._send_status or self.grok.note()
        elif self.hermes:
            status = self._send_status or self.hermes.note()
        else:
            status = (self._send_status or ("" if automation_ready() else self._waiting_note())
                      or getattr(self, "_failed_note", ""))
        if not status and self._refresh_note and time.monotonic() < self._refresh_note_until:
            status = self._refresh_note
        if status:
            blocks.append(status_block(status))
        return blocks

    # ── Sending messages ────────────────────────────────────────

    def on_user_message(self, text: str, files: list = ()):
        """Send a message from the bubble; it only counts as sent once the POST succeeded."""
        files = list(files)
        page = None if files else menu_pages.SLASH.get(text.strip().lower())
        if page:
            self.open_menu(page)
            return
        if not files and text.strip().lower() == "/refresh":
            self.refresh()
            return
        if not files and text.strip().lower() == "/feedback":
            self.open_feedback()
            return
        if not files and text.strip().lower() == "/pin":
            # Toggle pin: pinned keeps the bubble open, unpinned lets it close naturally.
            self.toggle_pin()
            return
        if not files and text.strip().lower() == "/settings":
            self.open_settings()
            return
        self._think_quiet = False
        text = text[:500]
        open_question = None if files else self._open_question()
        if open_question:
            self._give_answer(*open_question, [text])
            return
        if self._working:
            self._queue.append({"text": text, "files": files, "id": uuid.uuid4().hex[:8]})
            self._sync_bubble(self._latest(), force=True)
            self._poll_timer.start(300)
            return
        if self.grok:
            # A new message is a fresh attempt: the link that stopped tries again.
            self.grok.resume()
        if self.hermes:
            # A new message is a fresh attempt: the link that stopped tries again.
            self.hermes.resume()
        self.pinned = False
        # Not for a message that waits in the queue: the cloud is open for that and shows the queue.
        self._think_held = True
        text = attachments.message_with(text, files)
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        cid = hashlib.sha256(f"{self.agent_id}\n{text}\n{day}".encode()).hexdigest()[:32]
        self._outbox.add(text, cid)
        self._pump_outbox()
        self._sync_bubble(self._latest())
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
        self._sync_bubble(self._chat or self._latest(), force=True)
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
        self._sync_bubble(self._chat or self._latest(), force=True)

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
        try:
            result = api_post(path, body)
            if self._alive:
                self.attention_done.emit(result.ok, "" if result.ok else result.error)
        except Exception:
            if self._alive:
                self.attention_done.emit(False, "the request failed")

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
        if self.grok:
            ok, error = self.grok.send(text)
            if self._alive:
                self.message_done.emit(cid, ok, False, error)
            return
        if self.hermes:
            ok, error = self.hermes.send(text)
            if self._alive:
                self.message_done.emit(cid, ok, False, error)
            return
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
            self._asked = True
            self._asked_at = time.time()
            self.react("sent")
            # Grok Bot keeps the line the user sent itself.
            if item is not None and not self.grok and not self.hermes:
                self._local.append({"role": "user", "text": item["text"],
                                    "until": time.monotonic() + 120})
        else:
            item = next((i for i in self._outbox.items if i["cid"] == cid), None)
            wait = self._outbox.failed(cid, retryable)
            if wait is None:
                self._send_status = ""
                self._refused = True
                self.react("error")
                if item is not None:
                    self._local.append({"role": "user", "text": item["text"], "until": time.monotonic() + 60})
                note = GROK_REFUSED_NOTE if self.grok else (HERMES_REFUSED_NOTE if self.hermes else REFUSED_NOTE)
                self._local.append({"role": "bot", "until": time.monotonic() + 60,
                                    "text": note.format(why=error)})
            else:
                next_ready = False
                if not self._send_status:
                    self.react("no_route")
                self._send_status = self._waiting_note(error)
                QTimer.singleShot(int(wait * 1000), self._pump_outbox)
        self.update()
        self._sync_bubble(self._latest())
        if (self.grok or self.hermes) and (self.grok and self.grok.active() or self.hermes and self.hermes.active()) and not self._poll_timer.isActive():
            self._poll_timer.start(300)
        if next_ready:
            self._pump_outbox()
