"""Veren voor het gezicht: elke eigenschap loopt zacht naar haar doel toe.

Geen toolkit. Het gezicht stelt doelen (waar kijk ik heen, hoe blij ben ik) en
zet elke tik een stap; wat er uitkomt gaat naar face_svg.
"""

import math

# stijfheid, demping. Onder 1 veert een eigenschap even door: dat geeft het wiebelen.
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
}
REST = {"dx": 0.0, "dy": 0.0, "scale": 1.0, "converge": 0.0, "happy": 0.0, "lift": 0.0,
        "lean": 0.0, "sx": 1.0, "sy": 1.0}
MAX_STEP = 1 / 30
SUBSTEP = 0.008
# Onder deze afwijking ziet niemand het verschil meer: px en graden, of een factor.
SETTLED = {"dx": 0.04, "dy": 0.04, "converge": 0.04, "lift": 0.04, "lean": 0.04,
           "scale": 0.004, "happy": 0.004, "sx": 0.004, "sy": 0.004}


class FaceAnimator:
    def __init__(self):
        self.value = dict(REST)
        self.velocity = {name: 0.0 for name in REST}
        self.target = dict(REST)

    def aim(self, **targets):
        """Nieuwe doelen; een onbekende naam is een fout, geen stille misser."""
        for name, goal in targets.items():
            if name not in self.target:
                raise KeyError(name)
            self.target[name] = goal

    def kick(self, name: str, speed: float):
        """Een duw tegen de veer, bijvoorbeeld een landing."""
        self.velocity[name] += speed

    def step(self, dt: float) -> bool:
        """Eén beeld van dt seconden; True zolang er nog iets beweegt.

        De stijve veren rekenen in stukjes van SUBSTEP: een grote stap laat ze
        numeriek veel te lang naijlen.
        """
        dt = min(dt, MAX_STEP)
        pieces = max(1, math.ceil(dt / SUBSTEP))
        for _ in range(pieces):
            self._integrate(dt / pieces)
        moving = False
        for name in SPRINGS:
            x, v, goal = self.value[name], self.velocity[name], self.target[name]
            if abs(goal - x) < SETTLED[name] and abs(v) < SETTLED[name] * 10:
                self.value[name], self.velocity[name] = goal, 0.0
            else:
                moving = True
        return moving

    def _integrate(self, dt: float):
        for name, (stiffness, damping) in SPRINGS.items():
            x, v, goal = self.value[name], self.velocity[name], self.target[name]
            v += (stiffness * (goal - x) - 2 * damping * math.sqrt(stiffness) * v) * dt
            self.value[name] = x + v * dt
            self.velocity[name] = v
