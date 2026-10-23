"""The speech bubble as SVG: sizes and drawing based on broken lines."""

import math

from botwidget.avatar import AVATAR_SIZE
from botwidget.theme import (
    CONTROL_H,
    BUBBLE_LINGER,
    BUBBLE_LINGER_MAX,
    BUBBLE_PER_WORD,
    DOTS_GAP,
    DOTS_R,
    GAP_PANEL,
    LINE_CODE_PAD,
    LINE_DOTS_H,
    LINE_GAP_H,
    LINE_RULE_H,
    LINE_TEXT_PAD,
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
    TAIL_TIP_MARGIN,
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
    if block["kind"] == "control":
        return CONTROL_H
    if block["kind"] == "gap":
        return LINE_GAP_H
    if block["kind"] == "rule":
        return LINE_RULE_H
    if block["kind"] == "dots":
        return LINE_DOTS_H
    if block.get("code"):
        return block["size"] + LINE_CODE_PAD
    return block["size"] + LINE_TEXT_PAD


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


def bubble_height_cap(face_h: int) -> int:
    """Max bubble window height: this face plus one extra face of chat, plus chrome.

    Longer copy and menu pages scroll inside that band. Width can still grow.
    The cap is not a share of the screen, so a bubble cannot dwarf its face.
    """
    band = max(AVATAR_SIZE, int(face_h))
    return PAD_SVG + TAIL_ROOM + 3 * band + 16


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
                # The group is two gaps wide; its middle dot sits in the middle of the cloud.
                out.append(dots_svg(ox + box_w / 2 - DOTS_GAP, tops[n] + line_height(line) / 2,
                                    line.get("phase", 0.0), ink))
            elif line["kind"] == "more":
                if line.get("loading"):
                    # The arrow turns into the dots while the message before is on its way.
                    out.append(dots_svg(ox + box_w / 2 - DOTS_GAP, tops[n] + MORE_H / 2 + 3, line.get("phase", 0.0), ink))
                else:
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
    return PAD_SVG + length / 2 if tip is None else min(max(tip, PAD_SVG + TAIL_TIP_MARGIN), PAD_SVG + length - TAIL_TIP_MARGIN)


def opening_shadow_alpha(progress: float, opening: bool) -> float:
    """The blurred shadow is a black bar while the bubble is still a sliver."""
    if not opening:
        return SHADOW_ALPHA
    return SHADOW_ALPHA * min(1.0, max(0.0, progress) * 2)


def bubble_shadow_svg(body_w: int, body_h: int, tip: float | None = None, side: str = "above",
                      alpha: float | None = None) -> str:
    """The shadow, drawn sharp; the toolkit blurs it itself (SVG filters
    are not supported everywhere).
    """
    x0, y0 = PAD_SVG, PAD_SVG
    edge = _tail_edge(side, body_w, body_h)[0]
    tail = _bubble_tail(_bubble_tip(side, body_w, body_h, tip), edge, side, 3)
    return _bubble_canvas(body_w, body_h, (
        f'<rect x="{x0 - SHADOW_GROW}" y="{y0 - SHADOW_GROW + 2}"'
        f' width="{body_w + 2 * SHADOW_GROW}" height="{body_h + 2 * SHADOW_GROW}"'
        f' rx="{SAND_RADIUS}" fill="#000" opacity="{SHADOW_ALPHA if alpha is None else alpha}"/>'
        f'<path d="{tail}" fill="#000" opacity="{SHADOW_ALPHA if alpha is None else alpha}"/>'))


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
# A rounded rectangle around the text with a round puff on every stretch of its edge: as many
# puffs as the edge has room for, so the cloud grows with any text and never has to stretch.
CLOUD_PUFF_W = 24.0  # about how wide one puff is along the edge
CLOUD_PUFF_ROUND = 0.62  # the puff's radius as a share of its width; 0.5 is a half circle
CLOUD_CORNER = 24.0
# The balls between the cloud and the face lie on an arc: (radius, how far along the arc, 0 to 1). The arc
# leaves the cloud at CLOUD_ARC_FROM, ends CLOUD_ARC_TO out from its edge (the canvas margin is PAD_SVG)
# and bows CLOUD_ARC_BOW sideways halfway.
CLOUD_TRAIL = ((5.2, 0.0), (3.5, 0.5), (2.2, 1.0))
CLOUD_ARC_FROM = 8.0
CLOUD_ARC_TO = 15.0
CLOUD_ARC_BOW = 10.0


def _edge_point(w: float, h: float, corner: float, distance: float) -> tuple:
    """The point `distance` along the rounded rectangle's edge, clockwise from the end of its top-left corner."""
    run_x, run_y, quarter = w - 2 * corner, h - 2 * corner, math.pi * corner / 2
    for part, length in (("top", run_x), ("tr", quarter), ("right", run_y), ("br", quarter),
                         ("bottom", run_x), ("bl", quarter), ("left", run_y), ("tl", quarter)):
        if distance <= length or part == "tl":
            break
        distance -= length
    if part in ("top", "right", "bottom", "left"):
        return {"top": (corner + distance, 0.0), "right": (w, corner + distance),
                "bottom": (w - corner - distance, h), "left": (0.0, h - corner - distance)}[part]
    centre, start = {"tr": ((w - corner, corner), -math.pi / 2), "br": ((w - corner, h - corner), 0.0),
                     "bl": ((corner, h - corner), math.pi / 2), "tl": ((corner, corner), math.pi)}[part]
    angle = start + distance / corner
    return centre[0] + corner * math.cos(angle), centre[1] + corner * math.sin(angle)


def _cloud_parts(body_w: int, body_h: int, tip: float | None, side: str,
                 grow: float = 0.0):
    """The cloud outline and the circles of the trail toward the head."""
    corner = min(CLOUD_CORNER, body_w / 2, body_h / 2)
    perimeter = 2 * (body_w - 2 * corner) + 2 * (body_h - 2 * corner) + 2 * math.pi * corner
    puffs = max(8, round(perimeter / CLOUD_PUFF_W))
    chord = perimeter / puffs
    radius = chord * CLOUD_PUFF_ROUND + grow
    ox, oy = PAD_SVG - grow, PAD_SVG - grow
    scale_x, scale_y = (body_w + 2 * grow) / body_w, (body_h + 2 * grow) / body_h
    points = []
    for i in range(puffs):
        x, y = _edge_point(body_w, body_h, corner, i * perimeter / puffs)
        points.append((ox + x * scale_x, oy + y * scale_y))
    path = f"M{points[0][0]:.2f} {points[0][1]:.2f}" + "".join(
        f"A{radius:.2f} {radius:.2f} 0 0 1 {x:.2f} {y:.2f}" for x, y in points[1:] + points[:1]) + "Z"
    tip = _bubble_tip(side, body_w, body_h, tip)
    edge, sign = _tail_edge(side, body_w, body_h)
    # A quadratic curve whose middle bows sideways by CLOUD_ARC_BOW.
    start, end = edge + sign * CLOUD_ARC_FROM, edge + sign * CLOUD_ARC_TO
    mid_across, mid_along = (start + end) / 2, tip + 2 * CLOUD_ARC_BOW
    trail = []
    for r, t in CLOUD_TRAIL:
        across = (1 - t) ** 2 * start + 2 * (1 - t) * t * mid_across + t ** 2 * end
        along = (1 - t) ** 2 * tip + 2 * (1 - t) * t * mid_along + t ** 2 * tip
        trail.append((*_at(side, along, across), r + grow))
    return path, trail


def _circles_svg(circles: list, extra: str) -> str:
    return "".join(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" {extra}/>' for cx, cy, r in circles)


def cloud_shadow_svg(body_w: int, body_h: int, tip: float | None = None, side: str = "above",
                     alpha: float | None = None) -> str:
    """The shadow of the thinking cloud, drawn sharp; the toolkit blurs it."""
    path, trail = _cloud_parts(body_w, body_h, tip, side, grow=SHADOW_GROW)
    fill = f'fill="#000" opacity="{SHADOW_ALPHA if alpha is None else alpha}"'
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

