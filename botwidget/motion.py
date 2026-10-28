"""What a face does and when, after Grok Bot's avatar engine (its Motion Lab), without a toolkit.

Idle is calm: the face holds Grok Bot's still pose and only now and then, after a random wait,
blinks or looks around with one of Grok Bot's idle clips. Everything else is an event or a mood
with its own Grok Bot clip and face (EVENTS, MOODS): a reply is Done_A with the happy face, a
message nobody asked for Grok Bot's waking (Idle_B, surprised), sending a nod, a refusal Blocked_B
with the sad face, no route Blocked_A and then the sleepy face, thinking Working_B with the
inspecting face, a question waiting for you Idle_D. Same for every face, OpenBot's and Grok Bot's.
"""

import math
import random

from botwidget.grok_motion import CLIPS

# Grok Bot's still pose: (pitch, yaw, roll) in degrees, up and to the right, rolled anticlockwise.
STILL = (-15.9, 33.3, 25.4)
NORMAL_ZOOM = 0.6
# A blink: the lids shut by 0.117 s and are open again at 0.26 s.
BLINK_SHUT, BLINK_OPEN = 0.117, 0.26
STANDARD_EASE = (0.42, 0.0, 0.58, 1.0)

# The calm idle: a random wait, then a blink or, less often, a look around.
IDLE_GAP_S = (8.0, 30.0)
IDLE_BLINK_SHARE = 0.6
IDLE_LOOKS = ("Idle_B", "Idle_D", "Idle_A")
# No two faces move in step: the first wait is anywhere up to a full gap, every face plays its clips a
# little faster or slower, a looping mood starts anywhere in its clip, and an event starts up to a
# quarter second late.
FIRST_WAIT_S = (1.0, IDLE_GAP_S[1])
RATE_JITTER = 0.06
EVENT_DELAY_S = 0.25
MOOD_REST_S = (3.0, 6.0)  # a mood clip plays once and then the face holds still this long: less to draw

# event: (clip or poke, face held while it plays, face held after it, seconds that face stays)
EVENTS = {
    "reply": ("Done_A", "happy", None, 0.0),             # the answer to what you sent: Grok Bot's finished
    "new_message": ("Idle_B", "surprised", None, 0.0),    # a message nobody asked for: Grok Bot's waking
    "sent": ("nod", None, None, 0.0),                     # your message went out: Grok Bot's nod
    "error": ("Blocked_B", "sad", "sad", 2.0),            # refused: Grok Bot's failed
    "no_route": ("Blocked_A", "confused", None, 0.0),     # nothing to send to: Grok Bot's blocked
    "click": ("bounce", "happy", None, 0.0),              # a click on the face: Grok Bot's bounce
}
# mood: (clip played over and over, face; None holds the still pose)
MOODS = {
    "idle": (None, "neutral"),
    "thinking": ("Working_B", "inspecting"),   # waiting for the answer: Grok Bot's curious
    "ask": ("Idle_D", "neutral"),              # a question waits for you: Grok Bot's listening
    "offline": (None, "sleepy"),               # no route: Grok Bot's drowsy, held still
}
# Grok Bot's pokes, in seconds.
POKES = {"nod": 0.5, "bounce": 0.62}


def _bezier(t: float, a: float, b: float) -> float:
    u = 1 - t
    return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t


def ease(x: float, curve) -> float:
    """Grok Bot's easing: a cubic bezier (x1, y1, x2, y2) at x, solved like its engine (8 Newton steps)."""
    x1, y1, x2, y2 = curve
    t = x
    for _ in range(8):
        err = _bezier(t, x1, x2) - x
        u = 1 - t
        slope = 3 * u * u * x1 + 6 * u * t * (x2 - x1) + 3 * t * t * (1 - x2)
        if abs(err) < 1e-6 or abs(slope) < 1e-6:
            break
        t = min(1.0, max(0.0, t - err / slope))
    return _bezier(t, y1, y2)


def at(keys, t: float):
    """A track's value at t: from each key to the next on that key's ease, held before and after."""
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    i = 0
    while i < len(keys) - 2 and keys[i + 1][0] <= t:
        i += 1
    (t0, v0, curve), (t1, v1, _c) = keys[i], keys[i + 1]
    k = ease((t - t0) / max(t1 - t0, 1e-9), curve)
    return tuple(a + (b - a) * k for a, b in zip(v0, v1))


def blink_at(since: float) -> float:
    """How shut the lids are this long after a blink began: 0 open, 1 shut."""
    if since < 0 or since >= BLINK_OPEN:
        return 0.0
    if since < BLINK_SHUT:
        return ease(since / BLINK_SHUT, STANDARD_EASE)
    return 1 - ease((since - BLINK_SHUT) / (BLINK_OPEN - BLINK_SHUT), STANDARD_EASE)


def _sin2(t: float, a: float, b: float) -> float:
    return 0.0 if t <= a or t >= b else math.sin(math.pi * (t - a) / (b - a)) ** 2


def poke_at(name: str, t: float) -> dict:
    """Grok Bot's pokes, t from 0 to 1: a nod dips the head 16 degrees, a bounce hops and squashes."""
    if name == "nod":
        return {"pitch": 16 * _sin2(t, 0, 1)}
    ends, middle = _sin2(t, 0, 0.18) + _sin2(t, 0.82, 1), _sin2(t, 0.18, 0.82)
    return {"y": 0.3 * math.sin(math.pi * min(1.0, max(0.0, (t - 0.14) / 0.72))),
            "sx": 1 + 0.08 * ends - 0.04 * middle, "sy": 1 - 0.1 * ends + 0.06 * middle}


def clip_at(name: str, t: float) -> dict:
    """Everything a Grok Bot clip does at t seconds; rotation None where the clip leaves the head be."""
    clip = CLIPS[name]
    rotation = at(clip["rotation"], t)
    if rotation is not None and name == "Idle_A" and t >= clip["rotation"][-1][0]:
        rotation = (rotation[0], rotation[1] % 360, rotation[2])
    x, y = at(clip["position"], t) or (0.0, 0.0)
    zoom = at(clip["zoom"], t)
    sx, sy = at(clip["squash"], t) or (1.0, 1.0)
    face, lids = None, 0.0
    for when, what in clip["expression"]:
        if what == "blink":
            lids = max(lids, blink_at(t - when))
        elif when <= t + 1e-9:
            face = what
    return {"rotation": rotation, "x": x, "y": y, "zoom": zoom[0] / NORMAL_ZOOM if zoom else 1.0,
            "sx": sx, "sy": sy, "anchor": clip["anchor"], "lids": lids, "face": face}


def offsets(pose: dict, radius: float) -> tuple:
    """(lift, shift) in px for a pose: Grok Bot's hop and sway, and its squash about the anchor (-1:
    the bottom stays put)."""
    return (pose["y"] + pose["anchor"] * (1 - pose["sy"])) * radius, pose["x"] * radius


class Motion:
    """The face's motion: a calm idle, moods that loop a clip, events that play one."""

    def __init__(self, rng: random.Random | None = None, seed=None):
        self.rng = rng or random.Random(seed)
        self.rate = self.rng.uniform(1 - RATE_JITTER, 1 + RATE_JITTER)
        self.mood = "idle"
        self.playing = None      # (clip or poke name, seconds in, loops, face while it plays)
        self.after = None        # (face, seconds left) held once a clip is over
        self.rest = 0.0          # seconds a mood holds still before its clip plays again
        self.blink = None        # seconds since an idle blink began
        self.wait = self.rng.uniform(*FIRST_WAIT_S)  # seconds to the next idle blink or look
        self.history = []        # what the idle did, for the curious

    def _gap(self) -> float:
        return self.rng.uniform(*IDLE_GAP_S)

    @property
    def active(self) -> bool:
        """True while something plays: the face must draw every frame."""
        return self.playing is not None or self.blink is not None

    def event(self, name: str):
        what, face, after, hold = EVENTS[name]
        self.playing = (what, -self.rng.uniform(0.0, EVENT_DELAY_S), False, face)
        self.after = (after, hold) if after else None
        self.blink = None

    def set_mood(self, mood: str):
        if mood == self.mood:
            return
        self.mood = mood
        self.rest = 0.0
        if self.playing is None or self.playing[2]:
            self.playing = None   # the loop of the mood before ends; an event plays on
            self._loop_mood()
        self.wait = self._gap()

    def _loop_mood(self):
        clip, face = MOODS[self.mood]
        if clip:
            self.playing = (clip, self.rng.uniform(0.0, CLIPS[clip]["duration"]), True, face)

    def _idle(self, dt: float):
        self.wait -= dt
        if self.wait > 0:
            return
        self.wait = self._gap()
        if self.rng.random() < IDLE_BLINK_SHARE:
            self.blink = 0.0
            self.history.append("blink")
        else:
            look = self.rng.choice(IDLE_LOOKS)
            self.playing = (look, 0.0, False, None)
            self.history.append(look)

    def step(self, dt: float) -> dict:
        """Advance dt seconds; the pose to aim at: pitch, yaw, roll, x, y (head radii, up), zoom, sx, sy,
        anchor, lids (0 open, 1 shut) and face."""
        mood_face = MOODS[self.mood][1]
        pose = {"rotation": STILL, "x": 0.0, "y": 0.0, "zoom": 1.0, "sx": 1.0, "sy": 1.0, "anchor": 0,
                "lids": 0.0, "face": mood_face}
        if self.after is not None and self.playing is None:
            face, left = self.after
            pose["face"] = face
            self.after = (face, left - dt) if left - dt > 0 else None
        if self.playing is None and self.rest > 0:
            self.rest -= dt
            if self.rest <= 0:
                self._loop_mood()
        if self.playing is None and self.mood == "idle" and self.after is None:
            self._idle(dt)
        if self.blink is not None:
            pose["lids"] = blink_at(self.blink)
            self.blink = self.blink + dt if self.blink + dt < BLINK_OPEN else None
        if self.playing is not None and self.playing[1] < 0:  # an event about to start
            name, t, loops, face = self.playing
            self.playing = (name, t + dt, loops, face)
        elif self.playing is not None:
            name, t, loops, face = self.playing
            if name in POKES:
                for key, value in poke_at(name, min(1.0, t / POKES[name])).items():
                    if key == "pitch":
                        pose["rotation"] = (STILL[0] + value, STILL[1], STILL[2])
                    else:
                        pose[key] = value
                length = POKES[name]
            else:
                sample = clip_at(name, t)
                pose.update({k: v for k, v in sample.items() if k not in ("rotation", "face")})
                pose["rotation"] = sample["rotation"] or STILL
                pose["face"] = face or sample["face"] or pose["face"]
                length = CLIPS[name]["duration"]
            t += dt * self.rate
            if t >= length and loops:
                self.playing = None
                self.rest = self.rng.uniform(*MOOD_REST_S)
            elif t >= length:
                self.playing = None
                self._loop_mood()
            else:
                self.playing = (name, t, loops, face)
        pitch, yaw, roll = pose.pop("rotation")
        pose.update(pitch=pitch, yaw=yaw, roll=roll)
        return pose
