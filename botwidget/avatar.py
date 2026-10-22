"""The face: colours, silhouettes, expressions and the SVGs, without a toolkit."""

import colorsys
import math

# The face fits a circle of diameter 58 in a 68 px window; two long vertical eyes sit in the middle.
AVATAR_SIZE = 68
CIRCLE_R = 29.0
# dx, dy, length factor. Only shifts; the shape stays the same, except for a blink.
POSES = {
    "rest": (0, 0, 1.0),
    # Grok Bot looks up and to the right at rest; that is almost standing still.
    "idle": (5, -5, 1.0),
    "look": (0, 2, 1.0),
    "blink": (0, 0, 0.22),
    "read0": (-2, 1, 1.0),
    "read1": (2, 1, 1.0),
    "aside": (-6, 1, 1.0),
    "aside2": (6, 1, 1.0),
    "hop": (0, -3, 1.0),
}
# The hop lifts the whole face for a moment; the eyes look up while it does.
LIFT = {"hop": 4.0}
# pose, duration in ms. Idle stays almost still: a glance up and to the right, an occasional blink.
# The tick is short enough to make a double blink really double.
FACE_STEP_MS = 110
FACE = {
    "idle": (("idle", 5200), ("blink", 130), ("idle", 4200), ("blink", 130), ("idle", 100),
             ("blink", 130), ("idle", 6500)),
    "work": (("read0", 280), ("read1", 280), ("read0", 280), ("blink", 120)),
    "ask": (("look", 800), ("blink", 130), ("rest", 90), ("blink", 130),
            ("look", 700), ("rest", 200)),
}


# Half a body width beyond the edge: only a pointer this close is followed. Over the face itself the
# bot looks at you instead.
GAZE_NEAR = CIRCLE_R * 2
ON_FACE = CIRCLE_R * 1.1


def eye_aim(vx: float, vy: float) -> tuple[float, float, float, float] | None:
    """dx, dy, how close together the eyes are, and the length; None when the pointer is far away.

    On the face itself the eyes look straight out at you; between the face and GAZE_NEAR they
    follow the pointer, and a bit of squint comes in as it gets closer.
    """
    dist = (vx * vx + vy * vy) ** 0.5
    if dist >= GAZE_NEAR:
        return None
    if dist <= ON_FACE:
        return (0.0, 0.0, 0.0, 1.0)
    t = 1 - dist / GAZE_NEAR
    close = t * t * t
    look = t ** 0.5
    dx = max(-8.0, min(8.0, vx / dist * 8 * look))
    dy = max(-8.0, min(8.0, vy / dist * 8 * look))
    return (dx, dy, close * 6, 1 - close * 0.4)


# ── Face from the bot definition ────────────────────────────────────
# OpenBot draws a face from avatarSeed + avatarHue (bundle out/renderer/assets/logo-color-*.js):
# stableIndex picks the silhouette, the expression and the colour. The 64 radius values per
# silhouette come from that generator, as data. Angle 0 is 3 o'clock, 16 is 6 o'clock and 48 is 12
# o'clock.
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
# Grok Bot draws a bot's own face from an avatar shape and colour of its own: its colour names are
# not OpenBot's, and these shapes come from its avatar art instead of a seed.
GROK_HEX = {"black": "#000000", "brown": "#936439", "red": "#ff263c", "orange": "#ff6700",
            "yellow": "#ff9800", "green": "#00c972", "cyan": "#00bca6", "blue": "#1084fe",
            "violet": "#9159fe", "magenta": "#ff309b", "gray": "#777777"}
# The blob, traced from Grok Bot's own blob avatar: a round face, a little fuller at the top.
GROK_BLOB = (1.036, 1.036, 1.037, 1.037, 1.038, 1.039, 1.04, 1.042, 1.043, 1.044, 1.045, 1.045,
             1.043, 1.041, 1.037, 1.032, 1.027, 1.02, 1.014, 1.007, 1.0, 0.994, 0.989, 0.984,
             0.981, 0.978, 0.975, 0.972, 0.97, 0.967, 0.964, 0.961, 0.957, 0.954, 0.95, 0.948,
             0.946, 0.945, 0.946, 0.948, 0.95, 0.955, 0.959, 0.965, 0.97, 0.976, 0.981, 0.985,
             0.99, 0.993, 0.997, 1.0, 1.003, 1.006, 1.01, 1.013, 1.017, 1.02, 1.024, 1.027, 1.029,
             1.032, 1.034, 1.035)
GROK_SHAPES = {"blob": GROK_BLOB}
# Grok Bot's blob is a glossy ball, not a face: two highlights and no eyes. Both marks are traced
# from Grok Bot's own blob art (bot-blob-face@2x.png). The big one is a pill in the upper left; the
# small one is a thin crescent that follows the rim, higher and further right. Radii, angles and
# offsets are in head radii, angles in degrees from 3 o'clock going down.
GROK_HIGHLIGHT = (0.11, -0.33, 0.52, 0.20, 54.0)
GROK_CRESCENT = (0.88, 0.74, -62.0, -22.0)


def silhouette_radii(shape: str) -> tuple:
    """The 64 radii of a face shape: Grok Bot's own art when it names one, ours otherwise."""
    return GROK_SHAPES.get(shape) or SILHOUETTES[shape]
# split in degrees; per eye (width, height, tilt, opening)
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
    # OpenBot draws these half closed (opening 0.42); here they stay open, as small dots they hardly look like eyes.
    "somnolent": (16, (0.2, 0.42, 0, 1), (0.2, 0.42, -0, 1)),
}
HUE_COLORS = {0: "rouge", 30: "orange", 55: "ambre", 100: "vert", 150: "vert",
              185: "turquoise", 215: "bleu", 245: "violet", 280: "violet", 320: "rose"}
AUTO_COLORS = ("rouge", "orange", "ambre", "vert", "turquoise", "bleu", "violet", "rose")
# Grok Bot's own colours: bright and saturated, as on x.ai/bot/marketplace.
AVATAR_HEX = {"encre": "#0a0a0c", "brun": "#8b5e3c", "rouge": "#ff3e51", "orange": "#ff781c",
              "ambre": "#ffaf38", "vert": "#00c972", "turquoise": "#1cc3b0", "bleu": "#2a92fe",
              "violet": "#a97efe", "rose": "#ff5eb1", "gris": "#959595", "creme": "#f1efe9"}
EYE_FILL = "#f9f9f9"


def stable_index(value: str, length: int) -> int:
    """FNV-1a over the seed, just like OpenBot; picks silhouette, face and colour."""
    h = 2166136261
    for ch in value:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h % length


def avatar_profile(seed: str, hue: float | None, avatar: dict | None = None) -> dict:
    """Silhouette, expression and colour that OpenBot derives from this seed.

    avatar is the shape and colour Grok Bot draws for the bot, when it has one: that face wins,
    because the widget should show the same face as Grok Bot itself.
    """
    seed = seed or "agent"
    shapes = list(SILHOUETTES)
    shape = shapes[stable_index(f"{seed}:shape", len(shapes))]
    if shape not in SUPPORTED_SHAPES:
        shape = SUPPORTED_SHAPES[stable_index(f"{seed}:shape:replacement", len(SUPPORTED_SHAPES))]
    names = list(EXPRESSIONS)
    expression = names[stable_index(f"{seed}:expression", len(names))]
    tilt = (stable_index(f"{seed}:tilt", 25) - 12) * 0.8
    if isinstance(avatar, dict) and avatar.get("shape") in GROK_SHAPES:
        shape = avatar["shape"]
        tilt = 0.0  # the blob is already drawn the way Grok Bot draws it; a tilt would skew it
    if isinstance(avatar, dict) and avatar.get("color") in GROK_HEX:
        colour = GROK_HEX[avatar["color"]]
    elif hue is None:
        colour = AVATAR_HEX[AUTO_COLORS[stable_index(f"{seed}:color", len(AUTO_COLORS))]]
    else:
        colour = AVATAR_HEX[HUE_COLORS.get(int(hue), "gris")]
    radii = silhouette_radii(shape)
    return {"shape": shape, "expression": expression, "hex": colour, "tilt": tilt,
            "top": radii[48], "bottom": radii[16]}


def silhouette_path(radii, radius: float, cx: float, cy: float) -> str:
    """The smooth closed shape through the 64 radius points, just like OpenBot."""
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


# Light comes from the top left: a soft highlight there and a shadow at the bottom right in a darker
# tint of the bot's own colour. Black turns yellow and orange surfaces a dirty brown.
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


# The head follows the eyes only partly: that difference gives depth.
PARALLAX = 0.35


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _eye(ex: float, ey: float, ew: float, eh: float, tilt: float, happy: float,
         fill: str, opacity: float) -> str:
    """One eye as a thick line with round ends: a standing or lying pill that grows into
    a ^ at happy 1. Everything stays solid; nothing is faded.
    """
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


MOUTH_SIZE = 3.2  # half the width of the cross
MOUTH_DROP = 0.5  # below the eyes, in head radii, at most


def _mouth(cx: float, cy: float, fill: str, opacity: float) -> str:
    """A cross: the bot is muted."""
    s = MOUTH_SIZE
    return (f'<path d="M{cx - s:.2f} {cy - s:.2f} L{cx + s:.2f} {cy + s:.2f}'
            f' M{cx - s:.2f} {cy + s:.2f} L{cx + s:.2f} {cy - s:.2f}" fill="none" stroke="{fill}"'
            f' stroke-width="2.6" stroke-linecap="round" opacity="{opacity}"/>')


def _crescent(cx: float, cy: float, radius: float, shape: tuple, fill: str) -> str:
    """A thin mark along the rim of a ball: an arc of the outer circle, back along the inner one.

    shape is (outer, inner, start, end) in radii and degrees, so the mark narrows to a point at both
    ends the way Grok Bot's own small highlight does.
    """
    outer, inner, start, end = shape

    def at(r: float, deg: float) -> tuple[float, float]:
        a = math.radians(deg)
        return cx + math.cos(a) * r * radius, cy + math.sin(a) * r * radius

    large = 1 if abs(end - start) > 180 else 0
    o0, o1, i1, i0 = at(outer, start), at(outer, end), at(inner, end), at(inner, start)
    return (f'<path d="M{o0[0]:.2f} {o0[1]:.2f} A{outer * radius:.2f} {outer * radius:.2f} 0 {large} 1 '
            f'{o1[0]:.2f} {o1[1]:.2f} L{i1[0]:.2f} {i1[1]:.2f} '
            f'A{inner * radius:.2f} {inner * radius:.2f} 0 {large} 0 {i0[0]:.2f} {i0[1]:.2f} Z" '
            f'fill="{fill}"/>')


def face_svg(dx: float = 0, dy: float = 0, scale: float = 1.0, converge: float = 0,
             seed: str = "", hue: float | None = None, lift: float = 0.0,
             happy: float = 0.0, lean: float = 0.0, squash: tuple = (1.0, 1.0),
             muted: bool = False, avatar: dict | None = None) -> str:
    """This bot’s own silhouette and colour, with its two eyes.

    dx/dy move the eyes fully and the head partly; lift raises the whole face for a
    moment (the hop). lean tilts the head extra, squash stretches or flattens it.
    happy 0 is the normal eye shape, 1 the happy one (^^): the eyes morph into each
    other, so a half value is a real transition. A muted bot has a cross for a mouth.
    A Grok Bot ball has neither: two highlights on the surface, like Grok Bot draws it.
    """
    profile = avatar_profile(seed, hue, avatar)
    spec = EXPRESSIONS[profile["expression"]]
    centre = AVATAR_SIZE / 2
    apart = math.sin(math.radians(spec[0])) * CIRCLE_R
    ball = profile["shape"] in GROK_SHAPES
    eyes = []
    if ball:
        hx, hy, hw, hh, htilt = GROK_HIGHLIGHT
        eyes.append(_eye(centre + hx * CIRCLE_R, centre + hy * CIRCLE_R, hw * CIRCLE_R,
                         hh * CIRCLE_R, htilt, 0.0, EYE_FILL, 1.0))
        eyes.append(_crescent(centre, centre, CIRCLE_R, GROK_CRESCENT, EYE_FILL))
    else:
        for i, (w, h, tilt, open_) in enumerate(spec[1:]):
            side = -1 if i == 0 else 1
            ex = centre + side * apart + (converge if i == 0 else -converge) + dx
            ey = centre + dy
            ew = max(2.0, w * CIRCLE_R)
            eh = max(2.0, h * CIRCLE_R * scale * open_)
            eyes.append(_eye(ex, ey + 1.3, ew, eh, tilt, happy, "#000", 0.14))
            eyes.append(_eye(ex, ey, ew, eh, tilt, happy, EYE_FILL, 1.0))
        if muted:
            drop = min(MOUTH_DROP, 0.6 * profile["bottom"]) * CIRCLE_R
            eyes.append(_mouth(centre + dx, centre + dy + drop + 1.3, "#000", 0.14))
            eyes.append(_mouth(centre + dx, centre + dy + drop, EYE_FILL, 1.0))
    body = silhouette_path(silhouette_radii(profile["shape"]), CIRCLE_R, centre, centre)
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
        + (f'{"".join(eyes)}' if ball else
           f'<g transform="translate({-dx * PARALLAX:.2f} {-dy * PARALLAX:.2f})">{"".join(eyes)}</g>')
        + "</g></svg>"
    )


def avatar_svg(pose: str = "rest", seed: str = "", hue: float | None = None,
               happy: float = 0.0, avatar: dict | None = None) -> str:
    dx, dy, scale = POSES[pose]
    return face_svg(dx, dy, scale, 0, seed, hue, LIFT.get(pose, 0.0), happy, avatar=avatar)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
