"""Springs for the face: every property eases softly toward its target.

No toolkit. The face sets targets (where am I looking, how happy am I) and takes a
step every tick; the result goes to face_svg.
"""

import math

# stiffness, damping. Below 1 a property overshoots a little: that gives the wobble.
SPRINGS = {
    "dx": (320, 0.80),
    "dy": (320, 0.80),
    "scale": (900, 0.90),
    "converge": (320, 0.90),
    "happy": (400, 0.90),
    "lift": (500, 0.60),
    "lean": (220, 0.32),
    "sx": (260, 0.30),
    "sy": (260, 0.30),
    # The breath: slow and without a wobble, like Grok Bot's Idle_B swells and settles.
    "zoom": (6, 1.0),
}
REST = {"dx": 0.0, "dy": 0.0, "scale": 1.0, "converge": 0.0, "happy": 0.0, "lift": 0.0,
        "lean": 0.0, "sx": 1.0, "sy": 1.0, "zoom": 1.0}
MAX_STEP = 1 / 30
SUBSTEP = 0.008
# Below this deviation nobody can see the difference any more: px and degrees, or a factor.
SETTLED = {"dx": 0.04, "dy": 0.04, "converge": 0.04, "lift": 0.04, "lean": 0.04,
           "scale": 0.004, "happy": 0.004, "sx": 0.004, "sy": 0.004, "zoom": 0.002}

# Moves so slow that the calm frame rate shows them smoothly: the breath.
SLOW = frozenset({"zoom"})
# A calm 30 frames per second; 60 while the face is moving or the pointer is near it.
IDLE_MS = 33
BUSY_MS = 16


def frame_ms(*, held: bool, moving: bool, pointer_near: bool) -> int:
    """Timer interval: fast while anything on the face can change smoothly."""
    return BUSY_MS if held or moving or pointer_near else IDLE_MS


class FaceAnimator:
    def __init__(self):
        self.value = dict(REST)
        self.velocity = {name: 0.0 for name in REST}
        self.target = dict(REST)
        # Only slow springs (the breath) moved in the last step: the calm frame rate will do.
        self.only_slow = False

    def jump(self, **values):
        """Jump straight to this state, without springing: the initial state."""
        for name, goal in values.items():
            self.aim(**{name: goal})
            self.value[name] = goal
            self.velocity[name] = 0.0

    def aim(self, **targets):
        """New targets; an unknown name is an error, not a silent miss."""
        for name, goal in targets.items():
            if name not in self.target:
                raise KeyError(name)
            self.target[name] = goal

    def kick(self, name: str, speed: float):
        """A push against the spring, for example a landing."""
        self.velocity[name] += speed

    def step(self, dt: float) -> bool:
        """One frame of dt seconds; True while anything is still moving.

        The stiff springs integrate in pieces of SUBSTEP: one big step makes them
        ring numerically for far too long.
        """
        dt = min(dt, MAX_STEP)
        pieces = max(1, math.ceil(dt / SUBSTEP))
        for _ in range(pieces):
            self._integrate(dt / pieces)
        moved = set()
        for name in SPRINGS:
            x, v, goal = self.value[name], self.velocity[name], self.target[name]
            if abs(goal - x) < SETTLED[name] and abs(v) < SETTLED[name] * 10:
                self.value[name], self.velocity[name] = goal, 0.0
            else:
                moved.add(name)
        self.only_slow = bool(moved) and moved <= SLOW
        return bool(moved)

    def _integrate(self, dt: float):
        for name, (stiffness, damping) in SPRINGS.items():
            x, v, goal = self.value[name], self.velocity[name], self.target[name]
            v += (stiffness * (goal - x) - 2 * damping * math.sqrt(stiffness) * v) * dt
            self.value[name] = x + v * dt
            self.velocity[name] = v
