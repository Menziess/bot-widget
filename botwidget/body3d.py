"""Faces as 3D bodies, the way Grok Bot's avatar engine draws them, without a toolkit.

Grok Bot (the Motion Lab engine behind its avatars on x.ai) builds every avatar as a 3D body, turns
it by the pitch and yaw of its clips and draws the projection: the outline of the turned body and
two eye capsules that lie on its surface, so they bend with it and foreshorten when the head turns.

Here every face is such a body: its 2D outline is lofted into a puffy solid, the way Grok Bot lofts
some of its shapes (slices that shrink by cos^0.72 towards the back and the front), and the eyes lie
on an ellipsoid of the same depth. Coordinates are in head radii, x right, y down, z to the viewer.
"""

import math
from functools import lru_cache

# How deep the body is, in head radii: the front of the loft and of the eye surface.
DEPTH = 0.8
# Slices of the loft and points around its outline; enough for a smooth outline when turned.
SLICES = 11
OUTLINE_POINTS = 384
BINS = 128
# Grok Bot's eye capsules lie on the unit sphere: they bend with it, more than the body's front.
EYE_DEPTH = 1.0
LOFT_POWER = 0.72


def turn(pitch: float, yaw: float):
    """A function that turns a point by pitch (up is negative) and then yaw (right is positive)."""
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))

    def apply(x: float, y: float, z: float) -> tuple[float, float, float]:
        y, z = y * cp + z * sp, z * cp - y * sp
        return x * cy + z * sy, y, z * cy - x * sy
    return apply


def turn_from(rest: tuple, pitch: float, yaw: float):
    """Turn a body seen in the rest turn on to pitch and yaw: undo rest, then turn."""
    back_p, back_y = math.radians(-rest[0]), math.radians(-rest[1])
    cp, sp = math.cos(back_p), math.sin(back_p)
    cy, sy = math.cos(back_y), math.sin(back_y)
    on = turn(pitch, yaw)

    def apply(x: float, y: float, z: float) -> tuple[float, float, float]:
        x, z = x * cy + z * sy, z * cy - x * sy
        y, z = y * cp + z * sp, z * cp - y * sp
        return on(x, y, z)
    return apply


def angles_for(dx: float, dy: float, radius: float) -> tuple[float, float]:
    """The pitch and yaw that move the front of the head by dx, dy px on a head of this radius."""
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, dy / radius))))
    across = radius * math.cos(math.radians(pitch))
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, dx / across))))
    return pitch, yaw


def _densify(points: tuple, count: int) -> list:
    """count points evenly along a closed outline."""
    edges = [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    lengths = [math.dist(a, b) for a, b in edges]
    total = sum(lengths) or 1.0
    out, at, k = [], 0.0, 0
    for i in range(count):
        want = total * i / count
        while k < len(edges) - 1 and at + lengths[k] < want:
            at += lengths[k]
            k += 1
        (ax, ay), (bx, by) = edges[k]
        t = (want - at) / lengths[k] if lengths[k] else 0.0
        out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return out


@lru_cache(maxsize=4096)
def outline(points: tuple, pitch: float, yaw: float, rest: tuple = (0.0, 0.0)) -> tuple:
    """The outline of the lofted body, turned: the outermost turned point in each direction.

    points is the body's 2D outline (head radii, around the centre). Unturned this is the outline
    itself; turned, the slices behind and in front of it push it out on one side. rest is the turn
    the outline was drawn in: Grok Bot's still art shows its bodies turned.
    """
    dense = _densify(points, OUTLINE_POINTS)
    if (pitch, yaw) == rest:
        return tuple(points)
    rot = turn_from(rest, pitch, yaw)
    best = [None] * BINS
    for s in range(SLICES):
        a = -math.pi / 2 + math.pi * s / (SLICES - 1)
        scale = max(0.0, math.cos(a)) ** LOFT_POWER
        z = DEPTH * math.sin(a)
        for x, y in dense:
            px, py, _pz = rot(x * scale, y * scale, z)
            r = math.hypot(px, py)
            k = int((math.atan2(py, px) % math.tau) / math.tau * BINS) % BINS
            if best[k] is None or r > best[k][0]:
                best[k] = (r, px, py)
    filled = [b for b in best if b is not None]
    # The outermost point of each direction, its radius softened with its neighbours: no ripple.
    n = len(filled)
    out = []
    for i, (r, px, py) in enumerate(filled):
        soft = sum(w * filled[(i + d) % n][0] for d, w in ((-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1))) / 9
        k = soft / r if r else 1.0
        out.append((round(px * k, 4), round(py * k, 4)))
    return tuple(out)


def radii_points(radii: tuple) -> tuple:
    """A radii outline (angle 0 at 3 o'clock, going down) as points."""
    n = len(radii)
    return tuple((math.cos(i / n * math.tau) * r, math.sin(i / n * math.tau) * r) for i, r in enumerate(radii))


def radii_of(points: tuple, count: int = 64) -> tuple:
    """Back to radii at count even angles, read off a star-shaped outline."""
    polar = sorted((math.atan2(y, x) % math.tau, math.hypot(x, y)) for x, y in points)
    polar = [(a - math.tau, r) for a, r in polar[-1:]] + polar + [(a + math.tau, r) for a, r in polar[:1]]
    out, j = [], 0
    for i in range(count):
        want = i / count * math.tau
        while j < len(polar) - 2 and polar[j + 1][0] < want:
            j += 1
        (a0, r0), (a1, r1) = polar[j], polar[j + 1]
        t = (want - a0) / (a1 - a0) if a1 > a0 else 0.0
        out.append(r0 + (r1 - r0) * t)
    return tuple(out)


# ── Eyes on the surface ─────────────────────────────────────────────
def _stroke(line: list, half: float, caps: int = 7) -> list:
    """The outline of a thick line with round ends, around a polyline."""
    if len(line) < 2 or math.dist(line[0], line[-1]) < 1e-6 and len(line) <= 3:
        cx, cy = line[0]
        return [(cx + math.cos(a) * half, cy + math.sin(a) * half)
                for a in (i / (4 * caps) * math.tau for i in range(4 * caps))]
    normals = []
    for i, (x, y) in enumerate(line):
        ax, ay = line[max(0, i - 1)]
        bx, by = line[min(len(line) - 1, i + 1)]
        tx, ty = bx - ax, by - ay
        n = math.hypot(tx, ty) or 1.0
        normals.append((-ty / n, tx / n))
    left = [(x + nx * half, y + ny * half) for (x, y), (nx, ny) in zip(line, normals)]
    right = [(x - nx * half, y - ny * half) for (x, y), (nx, ny) in zip(line, normals)]

    def cap(centre, normal, sign):
        cx, cy = centre
        base = math.atan2(normal[1], normal[0])
        return [(cx + math.cos(base - sign * math.pi * k / caps) * half,
                 cy + math.sin(base - sign * math.pi * k / caps) * half) for k in range(1, caps)]
    return left + cap(line[-1], normals[-1], 1) + right[::-1] + cap(line[0], (-normals[0][0], -normals[0][1]), 1)


def eye_on_surface(centre: tuple, shape: list, rot) -> list | None:
    """Lay a flat eye shape (u right, v down, head radii) on the surface at centre, turned by rot.

    centre is the eye's direction on the unit sphere, the surface Grok Bot lays its eye capsules
    on. None when the eye has turned away.
    """
    cx, cy, cz = centre
    n = math.hypot(cx, cz) or 1.0
    right = (cz / n, 0.0, -cx / n)
    out, front = [], 0.0
    for u, v in shape:
        x, y, z = cx + u * right[0], cy + v, cz + u * right[2]
        k = 1.0 / (math.sqrt(x * x + y * y + z * z) or 1.0)
        px, py, pz = rot(x * k, y * k, z * k * EYE_DEPTH)
        front += pz
        out.append((px, py))
    return out if front > 0 else None
