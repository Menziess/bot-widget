"""The speech bubble as SVG: sizes and drawing based on broken lines."""

from botwidget.avatar import xml_escape
from botwidget.theme import (
    BUBBLE_CODE_FONT,
    CHIP_PAD_X,
    CHIP_RX,
    DOTS_GAP,
    DOTS_R,
    GAP_PANEL,
    PAD_BODY,
    PAD_PANEL_X,
    PAD_PANEL_Y,
    PAD_SVG,
    SAND_ACCENT,
    SAND_BUBBLE,
    SAND_CHIP,
    SAND_CHIP_USER,
    SAND_HAIRLINE,
    SAND_INK,
    SAND_INK_SOFT,
    SAND_LINE_USER,
    SAND_MONO,
    SAND_ON_USER,
    SAND_ON_USER_SOFT,
    SAND_PANEL_USER,
    SAND_RADIUS,
    SAND_RADIUS_CODE,
    SAND_RADIUS_PANEL,
    SAND_SANS,
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
    """The panels and their text, with the top left corner of the panel at (ox, oy).

    Only the user panel gets a fill; bot text sits on the white bubble.
    """
    out, y = [], oy
    for panel in panels:
        user = panel["role"] == "user"
        ink = SAND_ON_USER if user else SAND_INK
        soft = SAND_ON_USER_SOFT if user else SAND_INK_SOFT
        hair = SAND_LINE_USER if user else SAND_HAIRLINE
        # On the dark user panel the accent blue is unreadable; it stays white there.
        link_ink = SAND_ON_USER if user else SAND_ACCENT
        chip = SAND_CHIP_USER if user else SAND_CHIP
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
        n = 0
        while n < len(lines):  # a code block in a panel of its own
            if not lines[n].get("code"):
                n += 1
                continue
            last = n
            while last + 1 < len(lines) and lines[last + 1].get("code"):
                last += 1
            top = tops[n] - 2
            out.append(f'<rect x="{ox + PAD_PANEL_X}" y="{top}"'
                       f' width="{box_w - 2 * PAD_PANEL_X}"'
                       f' height="{tops[last] + heights[last] - tops[n] + 4}"'
                       f' rx="{SAND_RADIUS_CODE}" fill="{chip}"/>')
            n = last + 1
        for n, line in enumerate(lines):
            if line["kind"] == "gap":
                continue
            if line["kind"] == "dots":
                out.append(dots_svg(ox + PAD_PANEL_X, tops[n] + 16, line.get("phase", 0.0),
                                    ink if not user else SAND_ON_USER))
                continue
            if line["kind"] == "rule":
                out.append(f'<rect x="{ox + PAD_PANEL_X}" y="{tops[n] + 6}"'
                           f' width="{box_w - 2 * PAD_PANEL_X}" height="1" fill="{hair}"/>')
                continue
            inner = tops[n] + line["size"] + 6
            xs = line.get("xs") or []
            ws = line.get("ws") or []
            body = xml_escape(line["prefix"]) if line["prefix"] else ""
            for i, (word, style, lead) in enumerate(line["words"]):
                if i and lead:
                    body += " "
                esc = xml_escape(word)
                if style == "b":
                    body += f'<tspan font-weight="bold">{esc}</tspan>'
                elif style == "i":
                    body += f'<tspan font-style="italic">{esc}</tspan>'
                elif style == "code":
                    if i < len(xs):
                        x = ox + PAD_PANEL_X + line["indent"] + xs[i] - CHIP_PAD_X
                        out.append(f'<rect x="{x:.2f}" y="{inner - line["size"] + 2}"'
                                   f' width="{ws[i] + 2 * CHIP_PAD_X:.2f}"'
                                   f' height="{line["size"] + 2}" rx="{CHIP_RX}"'
                                   f' fill="{chip}"/>')
                    body += (f'<tspan font-family="{SAND_MONO}"'
                             f' font-size="{BUBBLE_CODE_FONT}" fill="{ink}">{esc}</tspan>')
                elif style == "mono":
                    body += f'<tspan font-family="{SAND_MONO}">{esc}</tspan>'
                elif style == "link":
                    body += f'<tspan fill="{link_ink}">{esc}</tspan>'
                elif style == "dim":
                    body += f'<tspan fill="{soft}">{esc}</tspan>'
                else:
                    body += f"<tspan>{esc}</tspan>"
            fill = soft if line["grey"] else ink
            weight = ' font-weight="600"' if line.get("head") else ""
            out.append(
                f'<text x="{ox + PAD_PANEL_X + line["indent"]}" y="{inner}"'
                f' xml:space="preserve" font-family="{SAND_SANS}"'
                f' font-size="{line["size"]}" fill="{fill}"{weight}>{body}</text>'
            )
        y += panel_h + GAP_PANEL
    return "".join(out)


def dots_svg(x: float, y: float, phase: float, ink: str) -> str:
    """Three thinking dots; phase runs the wave through the dots."""
    out = []
    for i in range(3):
        wave = (phase - i * 0.18) % 1.0
        lift = 1 - abs(wave * 2 - 1)
        r = DOTS_R * (0.6 + 0.4 * lift)
        out.append(f'<circle cx="{x + i * DOTS_GAP:.2f}" cy="{y - 2.5 * lift:.2f}"'
                   f' r="{r:.2f}" fill="{ink}" opacity="{0.35 + 0.6 * lift:.2f}"/>')
    return "".join(out)


def bubble_text_svg(panels: list, box_w: int) -> str:
    """What scrolls: the panels and their text on a transparent background."""
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
# A cloud of circles around the area, with three shrinking circles toward the head. The same canvas
# size as the speech bubble, so the window sizes the same.
CLOUD_R = 13.0
CLOUD_INSET = 6.0
CLOUD_STEP = 24.0
# (radius, distance from the centre to the edge of the area)
CLOUD_TRAIL = ((5.0, 10.0), (3.2, 17.0), (2.0, 20.0))


def _cloud_shapes(body_w: int, body_h: int, tip_x: float | None, tip_up: bool, grow: float = 0.0):
    """Circles (cx, cy, r) and the inner area (x, y, w, h) of the cloud."""
    x0, y0 = PAD_SVG + CLOUD_INSET, PAD_SVG + CLOUD_INSET
    w, h = body_w - 2 * CLOUD_INSET, body_h - 2 * CLOUD_INSET
    nx, ny = max(2, round(w / CLOUD_STEP)), max(2, round(h / CLOUD_STEP))
    circles = []
    for i in range(nx + 1):
        for y in (y0, y0 + h):
            circles.append((x0 + w * i / nx, y, CLOUD_R + grow))
    for j in range(1, ny):
        for x in (x0, x0 + w):
            circles.append((x, y0 + h * j / ny, CLOUD_R + grow))
    tip = _bubble_tip(body_w, tip_x)
    edge = PAD_SVG if tip_up else PAD_SVG + body_h
    sign = -1 if tip_up else 1
    for radius, dist in CLOUD_TRAIL:
        circles.append((tip, edge + sign * dist, radius + grow))
    return circles, (x0, y0, w, h)


def _circles_svg(circles: list, extra: str) -> str:
    return "".join(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" {extra}/>' for cx, cy, r in circles)


def cloud_shadow_svg(body_w: int, body_h: int, tip_x: float | None = None,
                     tip_up: bool = False) -> str:
    """The shadow of the thinking cloud, drawn sharp; the toolkit blurs it."""
    circles, (x, y, w, h) = _cloud_shapes(body_w, body_h, tip_x, tip_up, grow=SHADOW_GROW)
    fill = f'fill="#000" opacity="{SHADOW_ALPHA}"'
    return _bubble_canvas(body_w, body_h, (
        f'<g transform="translate(0 2)"><rect x="{x - SHADOW_GROW}" y="{y - SHADOW_GROW}"'
        f' width="{w + 2 * SHADOW_GROW}" height="{h + 2 * SHADOW_GROW}" {fill}/>'
        + _circles_svg(circles, fill) + "</g>"))


def cloud_body_svg(body_w: int, body_h: int, tip_x: float | None = None,
                   tip_up: bool = False) -> str:
    """The white thinking cloud with hairline. First everything with an outline, then
    everything without one over it, so only the outer line remains.
    """
    circles, (x, y, w, h) = _cloud_shapes(body_w, body_h, tip_x, tip_up)
    rect = f'<rect x="{x}" y="{y}" width="{w}" height="{h}"'
    outline = f'fill="{SAND_BUBBLE}" stroke="{SAND_HAIRLINE}" stroke-width="2"'
    return _bubble_canvas(body_w, body_h, (
        rect + f" {outline}/>" + _circles_svg(circles, outline)
        + rect + f' fill="{SAND_BUBBLE}"/>' + _circles_svg(circles, f'fill="{SAND_BUBBLE}"')))
