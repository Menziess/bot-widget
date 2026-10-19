"""De spraakwolk als SVG: maten en tekenen op basis van gebroken regels."""

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
    """Regelhoogte in de wolk: tekst, witregel, streep, puntjes of coderegel."""
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
    """Hoogte van het hele wolkvenster, inclusief rand voor schaduw en staart."""
    total = 2 * PAD_BODY + PAD_SVG + TAIL_ROOM + GAP_PANEL * max(0, len(panels) - 1)
    for panel in panels:
        total += 2 * PAD_PANEL_Y
        for line in panel["lines"]:
            total += line_height(line)
    return total


def content_height(panels: list) -> int:
    """Hoogte van de vlakken samen, zonder de rand en het staartje."""
    return bubble_height(panels) - PAD_SVG - TAIL_ROOM - 2 * PAD_BODY


def bubble_width(panels: list) -> int:
    """Breedte van het tekstvlak."""
    return max((panel["text_w"] for panel in panels), default=16) + 2 * PAD_PANEL_X


def panel_svg(panels: list, box_w: int, ox: float = 0, oy: float = 0) -> str:
    """De vlakken en hun tekst, met de linkerbovenhoek van het vlak op (ox, oy).

    Alleen het uservlak krijgt een vulling; bottekst staat op de witte wolk.
    """
    out, y = [], oy
    for panel in panels:
        user = panel["role"] == "user"
        ink = SAND_ON_USER if user else SAND_INK
        soft = SAND_ON_USER_SOFT if user else SAND_INK_SOFT
        hair = SAND_LINE_USER if user else SAND_HAIRLINE
        # Op het donkere uservlak is het accentblauw onleesbaar; daar blijft wit.
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
        while n < len(lines):  # een codeblok in een eigen vlak
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
    """Drie denkpuntjes; phase laat de golf door de bollen lopen."""
    out = []
    for i in range(3):
        wave = (phase - i * 0.18) % 1.0
        lift = 1 - abs(wave * 2 - 1)
        r = DOTS_R * (0.6 + 0.4 * lift)
        out.append(f'<circle cx="{x + i * DOTS_GAP:.2f}" cy="{y - 2.5 * lift:.2f}"'
                   f' r="{r:.2f}" fill="{ink}" opacity="{0.35 + 0.6 * lift:.2f}"/>')
    return "".join(out)


def bubble_text_svg(panels: list, box_w: int) -> str:
    """Wat er scrollt: de vlakken en hun tekst op een doorzichtige achtergrond."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{box_w}"'
        f' height="{content_height(panels)}">' + panel_svg(panels, box_w) + "</svg>"
    )


def _bubble_canvas(body_w: int, body_h: int, inner: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{body_w + 2 * PAD_SVG}"'
            f' height="{body_h + PAD_SVG + TAIL_ROOM}">' + inner + "</svg>")


def _bubble_tail(tip: float, edge: float, up: bool, grow: float) -> str:
    """Het staartje als pad; edge is de rand waar het uit komt, grow de uitstulping."""
    s = -1 if up else 1
    return (f'M {tip - 6} {edge + s * (grow - 1)} C {tip - 4} {edge + s * (grow - 1)}'
            f' {tip - 1.5} {edge + s * (grow + 6)} {tip} {edge + s * (grow + 7)}'
            f' C {tip + 1.5} {edge + s * (grow + 6)} {tip + 4} {edge + s * (grow - 1)}'
            f' {tip + 6} {edge + s * (grow - 1)} Z')


def _bubble_tip(body_w: int, tip_x: float | None) -> float:
    return PAD_SVG + body_w / 2 if tip_x is None else min(max(tip_x, PAD_SVG + 20), PAD_SVG + body_w - 20)


def bubble_shadow_svg(body_w: int, body_h: int, tip_x: float | None = None,
                      tip_up: bool = False) -> str:
    """De schaduw, scherp getekend; de toolkit vervaagt hem zelf (SVG-filters
    worden niet overal ondersteund)."""
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
    """Het witte vlak met hairline en het staartje naar de kop.

    tip_x is de kop in beeldcoordinaten; het staartje komt uit de onderrand op
    die x (bovenrand als tip_up), dus het volgt het hoofd waar het heen gaat.
    """
    x0, y0 = PAD_SVG, PAD_SVG
    edge = y0 if tip_up else y0 + body_h
    tail = _bubble_tail(_bubble_tip(body_w, tip_x), edge, tip_up, 0)
    return _bubble_canvas(body_w, body_h, (
        f'<rect x="{x0}" y="{y0}" width="{body_w}" height="{body_h}"'
        f' rx="{SAND_RADIUS}" fill="{SAND_BUBBLE}" stroke="{SAND_HAIRLINE}"'
        f' stroke-width="1"/>'
        f'<path d="{tail}" fill="{SAND_BUBBLE}"/>'))


# ── Denkwolk ───────────────────────────────────────────────────────
# Een wolk van bolletjes rond het vlak, met drie kleiner wordende bolletjes naar
# de kop toe. Dezelfde canvasmaat als de praatwolk, dus het venster rekent gelijk.
CLOUD_R = 13.0
CLOUD_INSET = 6.0
CLOUD_STEP = 24.0
# (straal, afstand van het middelpunt tot de rand van het vlak)
CLOUD_TRAIL = ((5.0, 10.0), (3.2, 17.0), (2.0, 20.0))


def _cloud_shapes(body_w: int, body_h: int, tip_x: float | None, tip_up: bool, grow: float = 0.0):
    """Cirkels (cx, cy, r) en het binnenvlak (x, y, w, h) van de wolk."""
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
    """De schaduw van de denkwolk, scherp getekend; de toolkit vervaagt hem."""
    circles, (x, y, w, h) = _cloud_shapes(body_w, body_h, tip_x, tip_up, grow=SHADOW_GROW)
    fill = f'fill="#000" opacity="{SHADOW_ALPHA}"'
    return _bubble_canvas(body_w, body_h, (
        f'<g transform="translate(0 2)"><rect x="{x - SHADOW_GROW}" y="{y - SHADOW_GROW}"'
        f' width="{w + 2 * SHADOW_GROW}" height="{h + 2 * SHADOW_GROW}" {fill}/>'
        + _circles_svg(circles, fill) + "</g>"))


def cloud_body_svg(body_w: int, body_h: int, tip_x: float | None = None,
                   tip_up: bool = False) -> str:
    """De witte denkwolk met hairline. Eerst alles met rand, dan alles zonder
    rand eroverheen, zodat alleen de buitenlijn overblijft."""
    circles, (x, y, w, h) = _cloud_shapes(body_w, body_h, tip_x, tip_up)
    rect = f'<rect x="{x}" y="{y}" width="{w}" height="{h}"'
    outline = f'fill="{SAND_BUBBLE}" stroke="{SAND_HAIRLINE}" stroke-width="2"'
    return _bubble_canvas(body_w, body_h, (
        rect + f" {outline}/>" + _circles_svg(circles, outline)
        + rect + f' fill="{SAND_BUBBLE}"/>' + _circles_svg(circles, f'fill="{SAND_BUBBLE}"')))
