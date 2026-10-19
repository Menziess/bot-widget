"""The speech bubble as SVG: sizes and drawing based on broken lines."""

import math

from botwidget.avatar import SILHOUETTES
from botwidget.theme import (
    DOTS_GAP,
    DOTS_R,
    GAP_PANEL,
    PAD_BODY,
    PAD_PANEL_X,
    PAD_PANEL_Y,
    PAD_SVG,
    SAND_BUBBLE,
    SAND_HAIRLINE,
    SAND_INK,
    SAND_LINE_USER,
    SAND_ON_USER,
    SAND_PANEL_USER,
    SAND_RADIUS,
    SAND_RADIUS_PANEL,
    SHADOW_ALPHA,
    SHADOW_GROW,
    TAIL_ROOM,
)


def line_height(block: dict) -> int:
    """Line height in the bubble: text, blank line, rule, dots or code line."""
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
    total = 2 * PAD_BODY + PAD_SVG + TAIL_ROOM + GAP_PANEL * max(0, len(panels) - 1)
    for panel in panels:
        total += 2 * PAD_PANEL_Y
        for line in panel["lines"]:
            total += line_height(line)
    return total


def content_height(panels: list) -> int:
    """Height of the panels together, without the margin and the tail."""
    return bubble_height(panels) - PAD_SVG - TAIL_ROOM - 2 * PAD_BODY


def bubble_width(panels: list) -> int:
    """Width of the text area."""
    return max((panel["text_w"] for panel in panels), default=16) + 2 * PAD_PANEL_X


def panel_svg(panels: list, box_w: int, ox: float = 0, oy: float = 0) -> str:
    """The shapes behind the text: the dark user panel, rules and the thinking dots.

    The words themselves are not drawn here: a real text surface draws them, so they
    can be selected and their links clicked.
    """
    out, y = [], oy
    for panel in panels:
        user = panel["role"] == "user"
        ink = SAND_ON_USER if user else SAND_INK
        hair = SAND_LINE_USER if user else SAND_HAIRLINE
        lines = panel["lines"]
        heights = [line_height(line) for line in lines]
        panel_h = 2 * PAD_PANEL_Y + sum(heights)
        if user:
            out.append(f'<rect x="{ox}" y="{y}" width="{box_w}" height="{panel_h}"'
                       f' rx="{SAND_RADIUS_PANEL}" fill="{SAND_PANEL_USER}"/>')
        tops, acc = [], y + PAD_PANEL_Y
        for h in heights:
            tops.append(acc)
            acc += h
        for n, line in enumerate(lines):
            if line["kind"] == "dots":
                out.append(dots_svg(ox + PAD_PANEL_X, tops[n] + 16, line.get("phase", 0.0), ink))
            elif line["kind"] == "rule":
                out.append(f'<rect x="{ox + PAD_PANEL_X}" y="{tops[n] + 6}"'
                           f' width="{box_w - 2 * PAD_PANEL_X}" height="1" fill="{hair}"/>')
        y += panel_h + GAP_PANEL
    return "".join(out)


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


def _bubble_tail(tip: float, edge: float, up: bool, grow: float) -> str:
    """The tail as a path; edge is the edge it comes out of, grow the bulge."""
    s = -1 if up else 1
    return (f'M {tip - 6} {edge + s * (grow - 1)} C {tip - 4} {edge + s * (grow - 1)}'
            f' {tip - 1.5} {edge + s * (grow + 6)} {tip} {edge + s * (grow + 7)}'
            f' C {tip + 1.5} {edge + s * (grow + 6)} {tip + 4} {edge + s * (grow - 1)}'
            f' {tip + 6} {edge + s * (grow - 1)} Z')


def _bubble_tip(body_w: int, tip_x: float | None) -> float:
    return PAD_SVG + body_w / 2 if tip_x is None else min(max(tip_x, PAD_SVG + 20), PAD_SVG + body_w - 20)


def bubble_shadow_svg(body_w: int, body_h: int, tip_x: float | None = None,
                      tip_up: bool = False) -> str:
    """The shadow, drawn sharp; the toolkit blurs it itself (SVG filters
    are not supported everywhere).
    """
    x0, y0 = PAD_SVG, PAD_SVG
    edge = y0 if tip_up else y0 + body_h
    tail = _bubble_tail(_bubble_tip(body_w, tip_x), edge, tip_up, 3)
    return _bubble_canvas(body_w, body_h, (
        f'<rect x="{x0 - SHADOW_GROW}" y="{y0 - SHADOW_GROW + 2}"'
        f' width="{body_w + 2 * SHADOW_GROW}" height="{body_h + 2 * SHADOW_GROW}"'
        f' rx="{SAND_RADIUS}" fill="#000" opacity="{SHADOW_ALPHA}"/>'
        f'<path d="{tail}" fill="#000" opacity="{SHADOW_ALPHA}"/>'))


def bubble_body_svg(body_w: int, body_h: int, tip_x: float | None = None,
                    tip_up: bool = False) -> str:
    """The white area with hairline and the tail toward the head.

    tip_x is the head in image coordinates; the tail comes out of the bottom edge at
    that x (top edge with tip_up), so it follows the head wherever it goes.
    """
    x0, y0 = PAD_SVG, PAD_SVG
    edge = y0 if tip_up else y0 + body_h
    tail = _bubble_tail(_bubble_tip(body_w, tip_x), edge, tip_up, 0)
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


def _cloud_parts(body_w: int, body_h: int, tip_x: float | None, tip_up: bool,
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
    tip = _bubble_tip(body_w, tip_x)
    edge = PAD_SVG if tip_up else PAD_SVG + body_h
    sign = -1 if tip_up else 1
    trail = [(tip, edge + sign * dist, radius + grow) for radius, dist in CLOUD_TRAIL]
    return _smooth_closed(pts), trail


def _circles_svg(circles: list, extra: str) -> str:
    return "".join(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" {extra}/>' for cx, cy, r in circles)


def cloud_shadow_svg(body_w: int, body_h: int, tip_x: float | None = None,
                     tip_up: bool = False) -> str:
    """The shadow of the thinking cloud, drawn sharp; the toolkit blurs it."""
    path, trail = _cloud_parts(body_w, body_h, tip_x, tip_up, grow=SHADOW_GROW)
    fill = f'fill="#000" opacity="{SHADOW_ALPHA}"'
    return _bubble_canvas(body_w, body_h, (
        f'<g transform="translate(0 2)"><path d="{path}" {fill}/>'
        + _circles_svg(trail, fill) + "</g>"))


def cloud_body_svg(body_w: int, body_h: int, tip_x: float | None = None,
                   tip_up: bool = False) -> str:
    """The white thinking cloud with hairline, shaped like the nuage face."""
    path, trail = _cloud_parts(body_w, body_h, tip_x, tip_up)
    paint = f'fill="{SAND_BUBBLE}" stroke="{SAND_HAIRLINE}" stroke-width="2"'
    return _bubble_canvas(body_w, body_h, (
        f'<path d="{path}" {paint} stroke-linejoin="round"/>'
        + _circles_svg(trail, paint)))

