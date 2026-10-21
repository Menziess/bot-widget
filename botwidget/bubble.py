"""The speech bubble as SVG: sizes and drawing based on broken lines."""

import math

from botwidget.avatar import SILHOUETTES
from botwidget.theme import (
    BUBBLE_LINGER,
    BUBBLE_LINGER_MAX,
    BUBBLE_PER_WORD,
    DOTS_GAP,
    DOTS_R,
    GAP_PANEL,
    MORE_GAP,
    MORE_GAP_DARK,
    MORE_H,
    MORE_PAD,
    PAD_BODY,
    PAD_PANEL_X,
    PAD_PANEL_Y,
    PAD_SVG,
    SAND_BUBBLE,
    SAND_HAIRLINE,
    SAND_INK,
    SAND_INK_SOFT,
    SAND_LINE_USER,
    SAND_ON_USER,
    SAND_PANEL_USER,
    SAND_RADIUS,
    SAND_RADIUS_PANEL,
    SHADOW_ALPHA,
    SHADOW_GROW,
    TAIL_ROOM,
)


def reading_seconds(text: str) -> float:
    """How long a bubble nobody points at stays: a few seconds, and more for a longer text."""
    return min(BUBBLE_LINGER_MAX, BUBBLE_LINGER + BUBBLE_PER_WORD * len(text.split()))


def panel_pad(panel: dict) -> int:
    return MORE_PAD if panel["role"] == "more" else PAD_PANEL_Y


def panel_gap(panel: dict, following: dict | None = None) -> int:
    """Space between this panel and the one under it."""
    if panel["role"] != "more":
        return GAP_PANEL
    return MORE_GAP_DARK if following and following["role"] == "user" else MORE_GAP


def line_height(block: dict) -> int:
    """Line height in the bubble: text, blank line, rule, dots or code line."""
    if block["kind"] == "more":
        return MORE_H
    if block["kind"] == "gap":
        return 10
    if block["kind"] == "rule":
        return 14
    if block["kind"] == "dots":
        return 26
    if block.get("code"):
        return block["size"] + 12
    return block["size"] + 10


def bubble_height(panels: list) -> int:
    """Height of the whole bubble window, including the margin for shadow and tail."""
    total = 2 * PAD_BODY + PAD_SVG + TAIL_ROOM + sum(panel_gap(panel, nxt) for panel, nxt in zip(panels, panels[1:]))
    for panel in panels:
        total += 2 * panel_pad(panel)
        for line in panel["lines"]:
            total += line_height(line)
    return total


def content_height(panels: list) -> int:
    """Height of the panels together, without the margin and the tail."""
    return bubble_height(panels) - PAD_SVG - TAIL_ROOM - 2 * PAD_BODY


def panel_rects(panels: list) -> list:
    """(top, height) of every panel in the scrolling content, where panel_svg draws it."""
    rects, top = [], 0
    for i, panel in enumerate(panels):
        height = 2 * panel_pad(panel) + sum(line_height(line) for line in panel["lines"])
        rects.append((top, height))
        top += height + panel_gap(panel, panels[i + 1] if i + 1 < len(panels) else None)
    return rects


def bubble_width(panels: list) -> int:
    """Width of the text area."""
    return max((panel["text_w"] for panel in panels), default=16) + 2 * PAD_PANEL_X


def panel_svg(panels: list, box_w: int, ox: float = 0, oy: float = 0) -> str:
    """The shapes behind the text: the dark user panel, rules and the thinking dots.

    The words themselves are not drawn here: a real text surface draws them, so they
    can be selected and their links clicked.
    """
    out, y = [], oy
    for index, panel in enumerate(panels):
        user = panel["role"] == "user"
        ink = SAND_ON_USER if user else SAND_INK
        hair = SAND_LINE_USER if user else SAND_HAIRLINE
        lines = panel["lines"]
        heights = [line_height(line) for line in lines]
        pad = panel_pad(panel)
        panel_h = 2 * pad + sum(heights)
        if user:
            out.append(f'<rect x="{ox}" y="{y}" width="{box_w}" height="{panel_h}"'
                       f' rx="{SAND_RADIUS_PANEL}" fill="{SAND_PANEL_USER}"/>')
        tops, acc = [], y + pad
        for h in heights:
            tops.append(acc)
            acc += h
        for n, line in enumerate(lines):
            if line["kind"] == "dots":
                out.append(dots_svg(ox + PAD_PANEL_X, tops[n] + 16, line.get("phase", 0.0), ink))
            elif line["kind"] == "more":
                out.append(more_svg(ox + box_w / 2, tops[n] + MORE_H / 2))
            elif line["kind"] == "rule":
                out.append(f'<rect x="{ox + PAD_PANEL_X}" y="{tops[n] + 6}"'
                           f' width="{box_w - 2 * PAD_PANEL_X}" height="1" fill="{hair}"/>')
        y += panel_h + panel_gap(panel, panels[index + 1] if index + 1 < len(panels) else None)
    return "".join(out)


def more_svg(x: float, y: float) -> str:
    """A slim chevron pointing up: there is more above."""
    return (f'<path d="M{x - 5:.1f} {y + 2.5:.1f} L{x:.1f} {y - 2.5:.1f} L{x + 5:.1f} {y + 2.5:.1f}"'
            f' fill="none" stroke="{SAND_INK_SOFT}" stroke-width="1.8" stroke-linecap="round"'
            f' stroke-linejoin="round"/>')


def dots_svg(x: float, y: float, phase: float, ink: str) -> str:
    """Three thinking dots; phase runs a smooth wave through the dots."""
    out = []
    for i in range(3):
        wave = (phase - i * 0.18) % 1.0
        lift = (1 - math.cos(math.tau * wave)) / 2
        r = DOTS_R * (0.6 + 0.4 * lift)
        out.append(f'<circle cx="{x + i * DOTS_GAP:.2f}" cy="{y - 2.5 * lift:.2f}"'
                   f' r="{r:.2f}" fill="{ink}" opacity="{0.35 + 0.6 * lift:.2f}"/>')
    return "".join(out)


def bubble_deco_svg(panels: list, box_w: int) -> str:
    """What scrolls: the panel shapes, rules and dots on a transparent background."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{box_w}"'
        f' height="{content_height(panels)}">' + panel_svg(panels, box_w) + "</svg>"
    )


def _bubble_canvas(body_w: int, body_h: int, inner: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{body_w + 2 * PAD_SVG}"'
            f' height="{body_h + PAD_SVG + TAIL_ROOM}">' + inner + "</svg>")


# Where the bubble sits as seen from the face: above it (tail down), below it (tail up), right of it (tail left)
# or left of it (tail right).
SIDES = ("above", "below", "right", "left")
VERTICAL = ("above", "below")


def _tail_edge(side: str, body_w: int, body_h: int) -> tuple[float, int]:
    """The edge of the white area facing the face, and +1 or -1 for which way is out of the bubble."""
    return {"above": (PAD_SVG + body_h, 1), "below": (PAD_SVG, -1),
            "right": (PAD_SVG, -1), "left": (PAD_SVG + body_w, 1)}[side]


def _at(side: str, along: float, across: float) -> tuple[float, float]:
    """A point given along the edge the tail leaves and across it, as (x, y)."""
    return (along, across) if side in VERTICAL else (across, along)


def _bubble_tail(tip: float, edge: float, side: str, grow: float) -> str:
    """The tail as a path; edge is the edge it comes out of, grow the bulge."""
    s = _tail_edge(side, 0, 0)[1]

    def point(along, across):
        x, y = _at(side, along, across)
        return f"{x:g} {y:g}"
    return (f'M {point(tip - 6, edge + s * (grow - 1))} C {point(tip - 4, edge + s * (grow - 1))}'
            f' {point(tip - 1.5, edge + s * (grow + 6))} {point(tip, edge + s * (grow + 7))}'
            f' C {point(tip + 1.5, edge + s * (grow + 6))} {point(tip + 4, edge + s * (grow - 1))}'
            f' {point(tip + 6, edge + s * (grow - 1))} Z')


def _bubble_tip(side: str, body_w: int, body_h: int, tip: float | None) -> float:
    """Where along its edge the tail points: at the face, but never into a corner."""
    length = body_w if side in VERTICAL else body_h
    return PAD_SVG + length / 2 if tip is None else min(max(tip, PAD_SVG + 20), PAD_SVG + length - 20)


def bubble_shadow_svg(body_w: int, body_h: int, tip: float | None = None, side: str = "above") -> str:
    """The shadow, drawn sharp; the toolkit blurs it itself (SVG filters
    are not supported everywhere).
    """
    x0, y0 = PAD_SVG, PAD_SVG
    edge = _tail_edge(side, body_w, body_h)[0]
    tail = _bubble_tail(_bubble_tip(side, body_w, body_h, tip), edge, side, 3)
    return _bubble_canvas(body_w, body_h, (
        f'<rect x="{x0 - SHADOW_GROW}" y="{y0 - SHADOW_GROW + 2}"'
        f' width="{body_w + 2 * SHADOW_GROW}" height="{body_h + 2 * SHADOW_GROW}"'
        f' rx="{SAND_RADIUS}" fill="#000" opacity="{SHADOW_ALPHA}"/>'
        f'<path d="{tail}" fill="#000" opacity="{SHADOW_ALPHA}"/>'))


def bubble_body_svg(body_w: int, body_h: int, tip: float | None = None, side: str = "above") -> str:
    """The white area with hairline and the tail toward the face.

    tip is the face in image coordinates, along the edge the tail comes out of (x above or below the
    face, y beside it), so the tail follows the face wherever it goes.
    """
    x0, y0 = PAD_SVG, PAD_SVG
    edge = _tail_edge(side, body_w, body_h)[0]
    tail = _bubble_tail(_bubble_tip(side, body_w, body_h, tip), edge, side, 0)
    return _bubble_canvas(body_w, body_h, (
        f'<rect x="{x0}" y="{y0}" width="{body_w}" height="{body_h}"'
        f' rx="{SAND_RADIUS}" fill="{SAND_BUBBLE}" stroke="{SAND_HAIRLINE}"'
        f' stroke-width="1"/>'
        f'<path d="{tail}" fill="{SAND_BUBBLE}"/>'))


# ── Thinking cloud ──────────────────────────────────────────────────
# The lobed profile of the avatars' "nuage" face, stretched over the body area, with three
# shrinking circles toward the head. The same canvas size as the speech bubble.
CLOUD_INSET = 6.0
# How far the notches between the lobes cut in, and how far the lobes stick out (at most:
# the canvas margin is PAD_SVG).
CLOUD_DIP = 6.0
CLOUD_LOBE = 0.16
CLOUD_LOBE_MAX = 14.0
# The base under the lobes is a squircle, so the text in the corners stays inside the cloud.
CLOUD_SQUIRCLE = 0.7
# (radius, distance from the centre to the edge of the area)
CLOUD_TRAIL = ((5.0, 10.0), (3.2, 17.0), (2.0, 20.0))


def _smooth_closed(pts: list) -> str:
    """A closed Catmull-Rom path through the points, the same tension as the faces."""
    tension = 1 / 6
    n = len(pts)
    out = [f"M{pts[0][0]:.2f} {pts[0][1]:.2f}"]
    for i in range(n):
        a, o, s, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        ctl1 = (o[0] + (s[0] - a[0]) * tension, o[1] + (s[1] - a[1]) * tension)
        ctl2 = (s[0] - (c[0] - o[0]) * tension, s[1] - (c[1] - o[1]) * tension)
        out.append(f"C{ctl1[0]:.2f} {ctl1[1]:.2f} {ctl2[0]:.2f} {ctl2[1]:.2f} "
                   f"{s[0]:.2f} {s[1]:.2f}")
    return "".join(out) + "Z"


def _cloud_parts(body_w: int, body_h: int, tip: float | None, side: str,
                 grow: float = 0.0):
    """The cloud outline and the circles of the trail toward the head."""
    x0, y0 = PAD_SVG + CLOUD_INSET, PAD_SVG + CLOUD_INSET
    w, h = body_w - 2 * CLOUD_INSET, body_h - 2 * CLOUD_INSET
    cx, cy = x0 + w / 2, y0 + h / 2
    lobes = SILHOUETTES["nuage"]
    low, high = min(lobes), max(lobes)
    depth = min(CLOUD_LOBE_MAX, h * CLOUD_LOBE)
    pts = []
    for i, r in enumerate(lobes):
        angle = i / len(lobes) * math.tau
        # Stretch the profile: the puffs become puffs, the notches stay notches.
        spread = min(1.0, max(0.0, ((r - low) / (high - low) - 0.35) / 0.45))
        radius_x = w / 2 - CLOUD_DIP + grow + spread * depth
        radius_y = h / 2 - CLOUD_DIP + grow + spread * depth
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        pts.append((cx + math.copysign(abs(cos_a) ** CLOUD_SQUIRCLE, cos_a) * radius_x,
                    cy + math.copysign(abs(sin_a) ** CLOUD_SQUIRCLE, sin_a) * radius_y))
    tip = _bubble_tip(side, body_w, body_h, tip)
    edge, sign = _tail_edge(side, body_w, body_h)
    trail = [(*_at(side, tip, edge + sign * dist), radius + grow) for radius, dist in CLOUD_TRAIL]
    return _smooth_closed(pts), trail


def _circles_svg(circles: list, extra: str) -> str:
    return "".join(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" {extra}/>' for cx, cy, r in circles)


def cloud_shadow_svg(body_w: int, body_h: int, tip: float | None = None, side: str = "above") -> str:
    """The shadow of the thinking cloud, drawn sharp; the toolkit blurs it."""
    path, trail = _cloud_parts(body_w, body_h, tip, side, grow=SHADOW_GROW)
    fill = f'fill="#000" opacity="{SHADOW_ALPHA}"'
    return _bubble_canvas(body_w, body_h, (
        f'<g transform="translate(0 2)"><path d="{path}" {fill}/>'
        + _circles_svg(trail, fill) + "</g>"))


def cloud_body_svg(body_w: int, body_h: int, tip: float | None = None, side: str = "above") -> str:
    """The white thinking cloud with hairline, shaped like the nuage face."""
    path, trail = _cloud_parts(body_w, body_h, tip, side)
    paint = f'fill="{SAND_BUBBLE}" stroke="{SAND_HAIRLINE}" stroke-width="2"'
    return _bubble_canvas(body_w, body_h, (
        f'<path d="{path}" {paint} stroke-linejoin="round"/>'
        + _circles_svg(trail, paint)))

