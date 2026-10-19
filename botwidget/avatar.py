"""Het gezicht: kleuren, silhouetten, uitdrukkingen en de SVG's, zonder toolkit."""

import colorsys
import math

# Zwarte cirkel, diameter 58. Twee lange verticale ogen in het midden.
AVATAR_SIZE = 68
CIRCLE_R = 29.0
# dx, dy, lengte-factor. Alleen schuiven; de vorm blijft gelijk, behalve een knipper.
POSES = {
    "rest": (0, 0, 1.0),
    # Grok Bot kijkt in rust schuin omhoog naar rechts; dat is bijna stilstaand.
    "idle": (5, -5, 1.0),
    "look": (0, 2, 1.0),
    "blink": (0, 0, 0.22),
    "read0": (-2, 1, 1.0),
    "read1": (2, 1, 1.0),
    "aside": (-6, 1, 1.0),
    "aside2": (6, 1, 1.0),
    "hop": (0, -3, 1.0),
}
# De hop tilt het hele gezicht even op; de ogen kijken daarbij omhoog.
LIFT = {"hop": 4.0}
# pose, duur in ms. Idle staat bijna stil: schuin omhoog kijken, af en toe knipperen.
# De tik is kort genoeg om een dubbele knipoog echt dubbel te laten zijn.
FACE_STEP_MS = 110
FACE = {
    "idle": (("idle", 5200), ("blink", 130), ("idle", 4200), ("blink", 130), ("idle", 100),
             ("blink", 130), ("idle", 6500)),
    "work": (("read0", 280), ("read1", 280), ("read0", 280), ("blink", 120)),
    "ask": (("look", 800), ("blink", 130), ("rest", 90), ("blink", 130),
            ("look", 700), ("rest", 200)),
}


# Halve lichaamsbreedte voorbij de rand. Dichterbij kijkt hij, op de neus knijpt hij.
GAZE_NEAR = CIRCLE_R * 2


def eye_aim(vx: float, vy: float) -> tuple[float, float, float, float]:
    """dx, dy, hoe dicht de ogen bij elkaar staan, en de lengte. Ver weg is rust."""
    dist = (vx * vx + vy * vy) ** 0.5
    if dist >= GAZE_NEAR or dist == 0:
        wide = (0.0, 0.0, 0.0, 1.0)
        if dist == 0:
            return (0.0, 0.0, 6.0, 0.6)
        return wide
    t = 1 - dist / GAZE_NEAR
    close = t * t * t
    look = t ** 0.5
    dx = max(-8.0, min(8.0, vx / dist * 8 * look))
    dy = max(-8.0, min(8.0, vy / dist * 8 * look))
    return (dx, dy, close * 6, 1 - close * 0.4)


# ── Gezicht uit de botdefinitie ────────────────────────────────────
# OpenBot tekent een gezicht uit avatarSeed + avatarHue (bundel
# out/renderer/assets/logo-color-*.js): stableIndex kiest het silhouet, de
# uitdrukking en de kleur. De 64 straalwaarden per silhouet komen uit die
# generator, als data. Hoek 0 is 3 uur, 16 is 6 uur en 48 is 12 uur.
SILHOUETTES = {
    "cercle": (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
    "galet": (0.9765, 0.9614, 0.9462, 0.9319, 0.919, 0.9083, 0.8998, 0.8937, 0.8899, 0.8881, 0.8879, 0.8889, 0.8906, 0.8927, 0.8948, 0.8967, 0.8985, 0.9002, 0.9021, 0.9044, 0.9076, 0.9118, 0.9175, 0.9248, 0.9336, 0.9439, 0.9553, 0.9672, 0.979, 0.99, 0.9992, 1.0059, 1.0095, 1.0092, 1.0048, 0.9963, 0.9837, 0.9675, 0.9486, 0.9278, 0.9064, 0.8856, 0.8666, 0.8506, 0.8386, 0.8315, 0.8297, 0.8333, 0.8422, 0.8559, 0.8736, 0.8942, 0.9164, 0.9391, 0.9608, 0.9804, 0.9967, 1.0091, 1.0169, 1.02, 1.0184, 1.0126, 1.0031, 0.9908),
    "squircle": (0.9591, 0.9637, 0.9776, 1.0007, 1.0321, 1.0696, 1.108, 1.1383, 1.15, 1.1383, 1.108, 1.0696, 1.0321, 1.0007, 0.9776, 0.9637, 0.9591, 0.9637, 0.9776, 1.0007, 1.0321, 1.0696, 1.108, 1.1383, 1.15, 1.1383, 1.108, 1.0696, 1.0321, 1.0007, 0.9776, 0.9637, 0.9591, 0.9637, 0.9776, 1.0007, 1.0321, 1.0696, 1.108, 1.1383, 1.15, 1.1383, 1.108, 1.0696, 1.0321, 1.0007, 0.9776, 0.9637, 0.9591, 0.9637, 0.9776, 1.0007, 1.0321, 1.0696, 1.108, 1.1383, 1.15, 1.1383, 1.108, 1.0696, 1.0321, 1.0007, 0.9776, 0.9637),
    "capsule": (1.04, 1.0363, 1.0265, 1.0095, 0.9868, 0.9576, 0.9235, 0.8842, 0.8409, 0.7945, 0.7457, 0.703, 0.6711, 0.6479, 0.6321, 0.623, 0.62, 0.623, 0.6321, 0.6479, 0.6711, 0.703, 0.7457, 0.7945, 0.8409, 0.8842, 0.9235, 0.9576, 0.9868, 1.0095, 1.0265, 1.0363, 1.04, 1.0363, 1.0265, 1.0095, 0.9868, 0.9576, 0.9235, 0.8842, 0.8409, 0.7945, 0.7457, 0.703, 0.6711, 0.6479, 0.6321, 0.623, 0.62, 0.623, 0.6321, 0.6479, 0.6711, 0.703, 0.7457, 0.7945, 0.8409, 0.8842, 0.9235, 0.9576, 0.9868, 1.0095, 1.0265, 1.0363),
    "triangle": (0.8429, 0.8981, 0.971, 1.0481, 1.0972, 1.1168, 1.1142, 1.0831, 1.025, 0.9444, 0.878, 0.8277, 0.7901, 0.7628, 0.7443, 0.7335, 0.73, 0.7335, 0.7443, 0.7628, 0.7901, 0.8277, 0.878, 0.9444, 1.025, 1.0831, 1.1142, 1.1168, 1.0972, 1.0481, 0.971, 0.8981, 0.8429, 0.8014, 0.7709, 0.7496, 0.7363, 0.7304, 0.7316, 0.7399, 0.7558, 0.78, 0.8139, 0.8596, 0.9201, 0.9991, 1.0679, 1.1057, 1.12, 1.1057, 1.0679, 0.9991, 0.9201, 0.8596, 0.8139, 0.78, 0.7558, 0.7399, 0.7316, 0.7304, 0.7363, 0.7496, 0.7709, 0.8014),
    "hexagone": (1.04, 1.0245, 0.9879, 0.9606, 0.9436, 0.936, 0.9375, 0.9482, 0.9685, 0.9996, 1.0329, 1.0381, 1.0126, 0.9776, 0.9538, 0.94, 0.9355, 0.94, 0.9538, 0.9776, 1.0126, 1.0381, 1.0329, 0.9996, 0.9685, 0.9482, 0.9375, 0.936, 0.9436, 0.9606, 0.9879, 1.0245, 1.04, 1.0245, 0.9879, 0.9606, 0.9436, 0.936, 0.9375, 0.9482, 0.9685, 0.9996, 1.0329, 1.0381, 1.0126, 0.9776, 0.9538, 0.94, 0.9355, 0.94, 0.9538, 0.9776, 1.0126, 1.0381, 1.0329, 0.9996, 0.9685, 0.9482, 0.9375, 0.936, 0.9436, 0.9606, 0.9879, 1.0245),
    "nuage": (0.9157, 0.9505, 0.976, 0.9922, 0.9987, 0.9956, 0.9829, 0.9606, 0.9291, 0.8886, 0.8395, 0.8587, 0.8746, 0.8866, 0.8944, 0.898, 0.8972, 0.8921, 0.8828, 0.8694, 0.8522, 0.8346, 0.8845, 0.9273, 0.9626, 0.9897, 1.0085, 1.0186, 1.02, 1.0126, 0.9964, 0.9718, 0.939, 0.8985, 0.8507, 0.7964, 0.7772, 0.8064, 0.8297, 0.8469, 0.8576, 0.8618, 0.8593, 0.8502, 0.8347, 0.8129, 0.7851, 0.7519, 0.7137, 0.6712, 0.656, 0.6974, 0.7336, 0.7641, 0.7885, 0.8064, 0.8175, 0.8219, 0.8193, 0.8098, 0.7936, 0.7709, 0.8201, 0.8721),
    "goutte": (0.6151, 0.6442, 0.6737, 0.7041, 0.7351, 0.7658, 0.7954, 0.8249, 0.8515, 0.8773, 0.8995, 0.9201, 0.9363, 0.9499, 0.9596, 0.9653, 0.9679, 0.9653, 0.9596, 0.9499, 0.9363, 0.9201, 0.8995, 0.8773, 0.8515, 0.8249, 0.7954, 0.7658, 0.7351, 0.7041, 0.6737, 0.6442, 0.6151, 0.5879, 0.5661, 0.551, 0.5418, 0.5379, 0.5393, 0.5459, 0.5582, 0.5766, 0.6024, 0.637, 0.6827, 0.7433, 0.8244, 0.9354, 1.04, 0.9354, 0.8244, 0.7433, 0.6827, 0.637, 0.6024, 0.5766, 0.5582, 0.5459, 0.5393, 0.5379, 0.5418, 0.551, 0.5661, 0.5879),
}
SUPPORTED_SHAPES = ("cercle", "galet", "squircle", "capsule", "triangle", "hexagone", "nuage")
# split in graden; per oog (breedte, hoogte, kanteling, opening)
EXPRESSIONS = {
    "neutre": (15.46, (0.186, 0.412, 0, 1), (0.186, 0.412, 0, 1)),
    "attentif": (16, (0.21, 0.44, 0, 1), (0.21, 0.44, -0, 1)),
    "surpris": (19, (0.45, 0.47, 0, 1), (0.45, 0.47, -0, 1)),
    "excite": (19.5, (0.4, 0.56, -10, 1), (0.4, 0.56, 10, 1)),
    "heureux": (17, (0.27, 0.17, 14, 1), (0.27, 0.17, -14, 1)),
    "hilare": (18, (0.34, 0.13, 20, 1), (0.34, 0.13, -20, 1)),
    "colere": (17, (0.34, 0.15, 30, 1), (0.34, 0.15, -30, 1)),
    "triste": (16, (0.22, 0.4, -28, 1), (0.22, 0.4, 28, 1)),
    "effraye": (20.5, (0.4, 0.6, 0, 1), (0.4, 0.6, -0, 1)),
    "mefiant": (16, (0.21, 0.4, 0, 1), (0.22, 0.15, 0, 1)),
    "confus": (16.5, (0.2, 0.44, -18, 1), (0.28, 0.17, 14, 1)),
    "curieux": (16.5, (0.24, 0.46, -8, 1), (0.2, 0.38, -8, 1)),
    "fier": (17, (0.3, 0.15, 18, 1), (0.3, 0.15, -18, 1)),
    "timide": (14, (0.17, 0.3, 0, 1), (0.17, 0.3, -0, 1)),
    "blase": (16, (0.3, 0.12, 0, 1), (0.3, 0.12, -0, 1)),
    "somnolent": (16, (0.2, 0.42, 0, 0.42), (0.2, 0.42, -0, 0.42)),
}
HUE_COLORS = {0: "rouge", 30: "orange", 55: "ambre", 100: "vert", 150: "vert",
              185: "turquoise", 215: "bleu", 245: "violet", 280: "violet", 320: "rose"}
AUTO_COLORS = ("rouge", "orange", "ambre", "vert", "turquoise", "bleu", "violet", "rose")
# De kleuren van Grok Bot zelf: helder en verzadigd, zoals op x.ai/bot/marketplace.
AVATAR_HEX = {"encre": "#0a0a0c", "brun": "#8b5e3c", "rouge": "#ff3e51", "orange": "#ff781c",
              "ambre": "#ffaf38", "vert": "#00c972", "turquoise": "#1cc3b0", "bleu": "#2a92fe",
              "violet": "#a97efe", "rose": "#ff5eb1", "gris": "#959595", "creme": "#f1efe9"}
EYE_FILL = "#f9f9f9"


def stable_index(value: str, length: int) -> int:
    """FNV-1a over de seed, net als OpenBot; kiest silhouet, gezicht en kleur."""
    h = 2166136261
    for ch in value:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h % length


def avatar_profile(seed: str, hue: float | None) -> dict:
    """Silhouet, uitdrukking en kleur die OpenBot uit deze seed haalt."""
    seed = seed or "agent"
    shapes = list(SILHOUETTES)
    shape = shapes[stable_index(f"{seed}:shape", len(shapes))]
    if shape not in SUPPORTED_SHAPES:
        shape = SUPPORTED_SHAPES[stable_index(f"{seed}:shape:replacement", len(SUPPORTED_SHAPES))]
    names = list(EXPRESSIONS)
    expression = names[stable_index(f"{seed}:expression", len(names))]
    if hue is None:
        colour = AUTO_COLORS[stable_index(f"{seed}:color", len(AUTO_COLORS))]
    else:
        colour = HUE_COLORS.get(int(hue), "gris")
    radii = SILHOUETTES[shape]
    tilt = (stable_index(f"{seed}:tilt", 25) - 12) * 0.8
    return {"shape": shape, "expression": expression, "hex": AVATAR_HEX[colour], "tilt": tilt,
            "top": radii[48], "bottom": radii[16]}


def silhouette_path(radii, radius: float, cx: float, cy: float) -> str:
    """De gladde gesloten vorm door de 64 straalpunten, net als OpenBot."""
    pts = []
    for i, r in enumerate(radii):
        ang = i / 64 * math.tau
        pts.append((cx + math.cos(ang) * r * radius, cy + math.sin(ang) * r * radius))
    tension = 1 / 6
    n = len(pts)
    out = [f"M{pts[0][0]:.2f} {pts[0][1]:.2f}"]
    for i in range(n):
        a, o, s, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        ctrl1 = (o[0] + (s[0] - a[0]) * tension, o[1] + (s[1] - a[1]) * tension)
        ctrl2 = (s[0] - (c[0] - o[0]) * tension, s[1] - (c[1] - o[1]) * tension)
        out.append(f"C{ctrl1[0]:.2f} {ctrl1[1]:.2f} {ctrl2[0]:.2f} {ctrl2[1]:.2f} "
                   f"{s[0]:.2f} {s[1]:.2f}")
    return "".join(out) + "Z"


# Licht komt linksboven: een zachte glans daar en een schaduw rechtsonder in een
# donkerdere tint van de eigen kleur. Zwart maakt gele en oranje vlakken vies bruin.
HIGHLIGHT = 0.18
SHADE = 0.50
SHADE_DARKNESS = 0.66


def _darker(colour: str, factor: float) -> str:
    red, green, blue = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    red, green, blue = colorsys.hls_to_rgb(hue, light * factor, min(1.0, sat * 1.05))
    return "#{:02x}{:02x}{:02x}".format(round(red * 255), round(green * 255), round(blue * 255))


def depth_defs(colour: str) -> str:
    return (
        '<defs><radialGradient id="hl" cx="0.30" cy="0.22" r="0.80">'
        f'<stop offset="0" stop-color="#fff" stop-opacity="{HIGHLIGHT}"/>'
        '<stop offset="0.6" stop-color="#fff" stop-opacity="0"/></radialGradient>'
        '<radialGradient id="sh" cx="0.62" cy="0.68" r="0.75">'
        f'<stop offset="0.45" stop-color="{_darker(colour, SHADE_DARKNESS)}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{_darker(colour, SHADE_DARKNESS)}" stop-opacity="{SHADE}"/>'
        '</radialGradient></defs>'
    )


# De kop volgt de ogen maar voor een deel: dat verschil geeft diepte.
PARALLAX = 0.35


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _eye(ex: float, ey: float, ew: float, eh: float, tilt: float, happy: float,
         fill: str, opacity: float) -> str:
    """Eén oog als dikke lijn met ronde uiteinden: een staande of liggende pil, die met
    happy 1 uitgroeit tot een ^. Alles blijft massief; er wordt geen vervaagd."""
    half = max(0.01, abs(eh - ew) / 2)
    if eh >= ew:
        pill, thick = ((ex, ey - half), (ex, ey), (ex, ey + half)), ew
    else:
        pill, thick = ((ex - half, ey), (ex, ey), (ex + half, ey)), eh
    caret = ((ex - ew / 2, ey + eh * 0.10), (ex, ey - eh * 1.05), (ex + ew / 2, ey + eh * 0.10))
    p0, ctrl, p1 = (tuple(_lerp(a, b, happy) for a, b in zip(u, v)) for u, v in zip(pill, caret))
    width = _lerp(thick, max(2.2, ew * 0.26), happy)
    turn = f' transform="rotate({tilt * (1 - happy):.1f} {ex:.2f} {ey:.2f})"' if tilt else ""
    return (f'<path d="M{p0[0]:.2f} {p0[1]:.2f} Q{ctrl[0]:.2f} {ctrl[1]:.2f} {p1[0]:.2f} {p1[1]:.2f}"'
            f' fill="none" stroke="{fill}" stroke-width="{width:.2f}" stroke-linecap="round"'
            f' opacity="{opacity}"{turn}/>')


def face_svg(dx: float = 0, dy: float = 0, scale: float = 1.0, converge: float = 0,
             seed: str = "", hue: float | None = None, lift: float = 0.0,
             happy: float = 0.0, lean: float = 0.0, squash: tuple = (1.0, 1.0)) -> str:
    """Het eigen silhouet en de eigen kleur van deze bot, met zijn twee ogen.

    dx/dy verzetten de ogen volledig en de kop voor een deel; lift tilt het hele
    gezicht even op (de hop). lean kantelt de kop extra, squash rekt of drukt hem.
    happy 0 is de gewone oogvorm, 1 de blije (^^): de ogen faden over elkaar,
    zodat een halve stand een echte overgang is.
    """
    profile = avatar_profile(seed, hue)
    spec = EXPRESSIONS[profile["expression"]]
    centre = AVATAR_SIZE / 2
    apart = math.sin(math.radians(spec[0])) * CIRCLE_R
    eyes = []
    for i, (w, h, tilt, open_) in enumerate(spec[1:]):
        side = -1 if i == 0 else 1
        ex = centre + side * apart + (converge if i == 0 else -converge) + dx
        ey = centre + dy
        ew = max(2.0, w * CIRCLE_R)
        eh = max(2.0, h * CIRCLE_R * scale * open_)
        eyes.append(_eye(ex, ey + 1.3, ew, eh, tilt, happy, "#000", 0.14))
        eyes.append(_eye(ex, ey, ew, eh, tilt, happy, EYE_FILL, 1.0))
    body = silhouette_path(SILHOUETTES[profile["shape"]], CIRCLE_R, centre, centre)
    head = (f'<path d="{body}" fill="{profile["hex"]}"/>'
            f'<path d="{body}" fill="url(#sh)"/><path d="{body}" fill="url(#hl)"/>')
    sx, sy = squash
    pose = (f'translate({dx * PARALLAX:.2f} {dy * PARALLAX - lift:.2f})'
            f' rotate({profile["tilt"] + lean:.2f} {centre} {centre})'
            f' translate({centre} {centre}) scale({sx:.4f} {sy:.4f}) translate({-centre} {-centre})')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{AVATAR_SIZE}" height="{AVATAR_SIZE}">'
        + depth_defs(profile["hex"])
        + f'<g transform="{pose}">{head}'
        + f'<g transform="translate({-dx * PARALLAX:.2f} {-dy * PARALLAX:.2f})">{"".join(eyes)}</g></g>'
        + "</svg>"
    )


def avatar_svg(pose: str = "rest", seed: str = "", hue: float | None = None,
               happy: float = 0.0) -> str:
    dx, dy, scale = POSES[pose]
    return face_svg(dx, dy, scale, 0, seed, hue, LIFT.get(pose, 0.0), happy)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
