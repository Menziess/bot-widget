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


def _matrix(pitch: float, yaw: float, roll: float = 0.0) -> tuple:
    """Grok Bot's turn as a matrix: yaw (right is positive), then pitch (up is negative), then roll
    (anticlockwise is positive), the order of its engine, for x right, y down, z to the viewer."""
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    yawed = ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy))
    pitched = ((1.0, 0.0, 0.0), (0.0, cp, sp), (0.0, -sp, cp))
    rolled = ((cr, sr, 0.0), (-sr, cr, 0.0), (0.0, 0.0, 1.0))
    return _mul(rolled, _mul(pitched, yawed))


def _mul(a: tuple, b: tuple) -> tuple:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply(m: tuple):
    (a, b, c), (d, e, f), (g, h, i) = m

    def apply(x: float, y: float, z: float) -> tuple[float, float, float]:
        return a * x + b * y + c * z, d * x + e * y + f * z, g * x + h * y + i * z
    return apply


def turn(pitch: float, yaw: float, roll: float = 0.0):
    """A function that turns a point the way Grok Bot turns its avatars."""
    return _apply(_matrix(pitch, yaw, roll))


def turn_from(rest: tuple, pitch: float, yaw: float, roll: float = 0.0):
    """Turn a body seen in the rest turn (pitch, yaw[, roll]) on to pitch, yaw and roll."""
    back = tuple(zip(*_matrix(*rest)))  # a turn's inverse is its transpose
    return _apply(_mul(_matrix(pitch, yaw, roll), back))


def angles_for(dx: float, dy: float, radius: float) -> tuple[float, float]:
    """The pitch and yaw that move the front of the head by dx, dy px on a head of this radius."""
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, dx / radius))))
    across = radius * math.cos(math.radians(yaw))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, dy / across)))) if across > 1e-9 else 0.0
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
    if (pitch, yaw) == tuple(rest[:2]):
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


def eye_on_surface(centre: tuple, shape: list, rot, normal: tuple | None = None) -> list | None:
    """Lay a flat eye shape (u right, v down, head radii) on the surface at centre, turned by rot.

    The eye bends over a ball of radius 1 that touches the body at centre, with the surface's normal
    there: a ball's own surface for a round head (the default, the unit sphere Grok Bot lays its eye
    capsules on), the flat front or the wrap of the body Grok Bot seats them on otherwise. None when
    the eye has turned away.
    """
    cx, cy, cz = centre
    nx, ny, nz = normal or centre
    k = 1.0 / (math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0)
    nx, ny, nz = nx * k, ny * k, nz * k
    h = math.hypot(nx, nz) or 1.0
    rx, ry, rz = nz / h, 0.0, -nx / h                                    # right: level, along the surface
    dx, dy, dz = ny * rz - nz * ry, nz * rx - nx * rz, nx * ry - ny * rx  # down: normal x right
    ox, oy, oz = cx - nx, cy - ny, cz - nz
    out = []
    for u, v in shape:
        x, y, z = nx + u * rx + v * dx, ny + u * ry + v * dy, nz + u * rz + v * dz
        k = 1.0 / (math.sqrt(x * x + y * y + z * z) or 1.0)
        px, py, _pz = rot(ox + x * k, oy + y * k, (oz + z * k) * EYE_DEPTH)
        out.append((px, py))
    facing = rot(nx, ny, nz)[2]
    return out if facing > -0.05 else None


def eye_draped(centre: tuple, shape: list, rot, normal: tuple, height) -> list | None:
    """Lay a flat eye shape on a body whose front is height(x, y): every point of the eye is put on
    the surface itself, so the eye never stands off the body, however the body curves."""
    nx, ny, nz = normal
    k = 1.0 / (math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0)
    nx, ny, nz = nx * k, ny * k, nz * k
    h = math.hypot(nx, nz) or 1.0
    rx, rz = nz / h, -nx / h
    dx, dy = ny * rz, nz * rx - nx * rz
    cx, cy, _cz = centre
    out = []
    for u, v in shape:
        x, y = cx + u * rx + v * dx, cy + v * dy
        out.append(rot(x, y, height(x, y))[:2])
    return out if rot(nx, ny, nz)[2] > -0.05 else None


# ── Grok Bot's bodies ───────────────────────────────────────────────
# Its engine builds each avatar shape in its own way (grok_bodies.py); the outline of the turned body
# is what it draws. RAYS directions are cast from the middle, as the engine does.
RAYS = 360
AROUND = 32


def _hull(points: list) -> list:
    """The convex hull of 2D points, anticlockwise (monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out
    return half(pts)[:-1] + half(reversed(pts))[:-1]


def _cast(segments: list, rays: int = RAYS) -> list:
    """The outermost point of the segments' union along every ray from the middle."""
    far = [0.0] * rays
    step = math.tau / rays
    for (ax, ay), (bx, by) in segments:
        a0 = math.atan2(ay, ax) % math.tau
        span = (math.atan2(by, bx) - math.atan2(ay, ax) + math.pi) % math.tau - math.pi
        lo, hi = (a0, a0 + span) if span >= 0 else (a0 + span, a0)
        ex, ey = bx - ax, by - ay
        for k in range(math.floor(lo / step) - 1, math.ceil(hi / step) + 2):
            angle = k * step
            dx, dy = math.cos(angle), math.sin(angle)
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = (ax * ey - ay * ex) / den
            u = (ax * dy - ay * dx) / den
            if t > 0 and -1e-9 <= u <= 1 + 1e-9:
                i = k % rays
                far[i] = max(far[i], t)
    return [(math.cos(i * step) * r, math.sin(i * step) * r) for i, r in enumerate(far) if r > 0]


def _rings(spec: dict) -> list:
    """The rings of an extrusion or a loft, in 3D."""
    outline = spec["outline"]
    if spec["kind"] == "extrusion":
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        h = max(1e-4, min((max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2))
        depth, bevel = spec["half_depth"], spec["bevel"]
        steps = [(t, -1) for t in range(4, -1, -1)] + [(t, 1) for t in range(5)]
        rings = []
        for t, side in steps:
            a = t / 4 * math.pi / 2
            z = side * (depth - bevel + bevel * math.sin(a))
            k = 1 - bevel / h * (1 - math.cos(a))
            rings.append([(cx + (x - cx) * k, cy + (y - cy) * k, z) for x, y in outline])
        return rings
    cx, cy = spec["centre"]
    rings = []
    for t in range(17):
        a = -math.pi / 2 + math.pi * t / 16
        k = max(0.0, math.cos(a)) ** LOFT_POWER
        rings.append([(cx + (x - cx) * k, cy + (y - cy) * k, spec["depth"] * math.sin(a)) for x, y in outline])
    return rings


def _solid(spec: dict) -> list:
    """The sample points of a solid whose outline is their convex hull, in 3D."""
    kind = spec["kind"]
    if kind == "revolve":
        pts = []
        for y, r in spec["profile"]:
            if r <= 0:
                pts.append((0.0, y, 0.0))
                continue
            pts += [(r * math.sin(a), y, r * math.cos(a))
                    for a in (i / AROUND * math.tau for i in range(AROUND))]
        return pts
    if kind == "roundedSlab":
        ring, depth, edge = spec["ring"], spec["half_depth"], spec["edge"]
        n, pts = len(ring), []
        for i, (x, y) in enumerate(ring):
            (lx, ly), (ox, oy) = ring[i - 1], ring[(i + 1) % n]
            nx, ny = oy - ly, -(ox - lx)
            length = math.hypot(nx, ny) or 1.0
            nx, ny = nx / length, ny / length
            if nx * x + ny * y < 0:
                nx, ny = -nx, -ny
            for t in range(5):
                a = t / 4 * math.pi / 2
                inset, z = edge * (1 - math.cos(a)), depth - edge + edge * math.sin(a)
                pts += [(x - nx * inset, y - ny * inset, z), (x - nx * inset, y - ny * inset, -z)]
        return pts
    # The crystal: two tips and two rings of six corners, each a ball of 0.12.
    s = spec["scale"]
    corners = [(0.0, -1.04, 0.0), (0.0, 1.04, 0.0)]
    for side in (-1, 1):
        corners += [(0.52 * math.cos(a), -0.51 * side, 0.52 * math.sin(a))
                    for a in (i / 6 * math.tau for i in range(6))]
    pts = []
    for x, y, z in corners:
        for i in range(9):
            a = i / 8 * math.pi
            for j in range(1 if i in (0, 8) else 14):
                b = j / 14 * math.tau
                pts.append(((x + 0.12 * math.sin(a) * math.sin(b)) * s, (y - 0.12 * math.cos(a)) * s,
                            (z + 0.12 * math.sin(a) * math.cos(b)) * s))
    return pts


@lru_cache(maxsize=64)
def _prepared(name: str) -> tuple:
    from botwidget.grok_bodies import GROK_BODIES
    spec = GROK_BODIES[name]
    if spec["kind"] in ("extrusion", "loft"):
        return ("rings", _rings(spec))
    if spec["kind"] == "balls":
        return ("balls", spec["balls"])
    if spec["kind"] == "sphere":
        return ("sphere", None)
    return ("solid", _solid(spec))


def prepared_body(name: str, spec: dict) -> tuple:
    """Prepare a body that is not one of Grok Bot's (an OpenBot face) the same way."""
    if spec["kind"] in ("extrusion", "loft"):
        return ("rings", _rings(spec))
    if spec["kind"] == "balls":
        return ("balls", spec["balls"])
    return ("solid", _solid(spec))


def body_outline(body: tuple, pitch: float, yaw: float) -> tuple:
    """The outline of a prepared body turned by pitch and yaw, as Grok Bot's engine draws it."""
    kind, data = body
    rot = turn(pitch, yaw)
    if kind == "sphere":
        return tuple((math.cos(a), math.sin(a)) for a in (i / 96 * math.tau for i in range(96)))
    if kind == "solid":
        return tuple((round(x, 4), round(y, 4)) for x, y in _hull([rot(*p)[:2] for p in data]))
    if kind == "balls":
        centres = [(rot(x, y, z)[:2], r) for x, y, z, r in data]
        ox = sum(c[0] for c, _ in centres) / len(centres)
        oy = sum(c[1] for c, _ in centres) / len(centres)
        out = []
        for i in range(160):
            a = i / 160 * math.tau
            dx, dy = math.cos(a), math.sin(a)
            best = 0.0
            for (cx, cy), r in centres:
                px, py = cx - ox, cy - oy
                b = dx * px + dy * py
                h = b * b - (px * px + py * py) + r * r
                if h > 0:
                    best = max(best, b + math.sqrt(h))
            if best > 0:
                out.append((round(ox + dx * best, 4), round(oy + dy * best, 4)))
        return tuple(out)
    turned = [[rot(*p)[:2] for p in ring] for ring in data]
    segments = []
    for i, ring in enumerate(turned):
        segments += [(ring[j - 1], ring[j]) for j in range(len(ring))]
        if i:
            segments += list(zip(turned[i - 1], ring))
    return tuple((round(x, 4), round(y, 4)) for x, y in _cast(segments))


@lru_cache(maxsize=2048)
def grok_outline(name: str, pitch: float, yaw: float) -> tuple:
    """The outline of Grok Bot's body for this avatar shape, turned."""
    return body_outline(_prepared(name), pitch, yaw)
