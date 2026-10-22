"""The face: colours, silhouettes, expressions and the SVGs, without a toolkit."""

import colorsys
import math
from functools import lru_cache

from botwidget import body3d
from botwidget.grok_marks import GROK_MARKS

# The face fits a circle of diameter 58 in a 68 px window; two long vertical eyes sit in the middle.
AVATAR_SIZE = 68
CIRCLE_R = 29.0
# ── Motion, after Grok Bot's own avatar engine ─────────────────────
# Grok Bot animates its avatar with clips of head rotations (pitch, yaw, roll in degrees) and blinks
# (x.ai, the "Motion Lab" engine behind the GrokBotMark). Its eyes sit on the front of the head, so
# a turn moves them across the face; GROK_REST is the turn its still art is drawn in: up and right.
GROK_REST = (-15.9, 33.3)
# Its still pose in full: also rolled anticlockwise by 25.4 degrees.
GROK_STILL = (-15.9, 33.3, 25.4)
# A turn moves the front of the head as far as it would go on a ball of the face's size, up to the
# 40 degrees or so that Grok Bot's idle turns reach.
LOOK_MAX = 20.0


def grok_look(pitch: float, yaw: float) -> tuple[float, float]:
    """Where the eyes go, in px from the middle, when the head turns by pitch and yaw degrees."""
    p, y = math.radians(pitch), math.radians(yaw)
    dx, dy = CIRCLE_R * math.sin(y), CIRCLE_R * math.cos(y) * math.sin(p)
    reach = math.hypot(dx, dy)
    if reach > LOOK_MAX:
        dx, dy = dx * LOOK_MAX / reach, dy * LOOK_MAX / reach
    return round(dx, 1), round(dy, 1)


# A few still poses: dx, dy, length factor. A blink (length 0) leaves the eyes where they look: None
# keeps dx and dy. What a face does over time is botwidget.motion's: Grok Bot's clips.
POSES = {
    "rest": (0, 0, 1.0),
    "look": (0, 2, 1.0),
    "blink": (None, None, 0.0),
    "hop": (0, -3, 1.0),
}
# The hop lifts the whole face for a moment; the eyes look up while it does.
LIFT = {"hop": 4.0}


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
GROK_BLOB_R = sum(GROK_BLOB) / len(GROK_BLOB)
# The blob wears Grok Bot's two pill eyes like every other shape: in Grok Bot's art and avatar engine
# the "sphere" body has the same two eye capsules, filled with the background colour (light on black).

def grok_drawn(shape) -> bool:
    """Can the widget draw this Grok Bot avatar shape the way Grok Bot does?"""
    return isinstance(shape, str) and (shape in GROK_SHAPES or shape in GROK_MARKS)


def mark_extent(shape: str) -> tuple:
    """How far a Grok Bot mark reaches above and below the centre, in head radii."""
    ys = [y for _, y in GROK_MARKS[shape][0]]
    return -min(ys), max(ys)


def mark_path(shape: str, radius: float, cx: float, cy: float) -> str:
    """The outline of a Grok Bot mark, as the polygon Grok Bot draws it."""
    return "M" + "L".join(f"{cx + x * radius:.2f} {cy + y * radius:.2f}"
                          for x, y in GROK_MARKS[shape][0]) + "Z"


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
    # OpenBot and Grok Bot share some shape names (squircle, capsule): only a Grok Bot avatar gets
    # Grok Bot's mark.
    grok = isinstance(avatar, dict) and grok_drawn(avatar.get("shape"))
    if grok:
        shape = avatar["shape"]
        tilt = 0.0  # the mark is already drawn the way Grok Bot draws it; a tilt would skew it
    if isinstance(avatar, dict) and avatar.get("color") in GROK_HEX:
        colour = GROK_HEX[avatar["color"]]
    elif hue is None:
        colour = AVATAR_HEX[AUTO_COLORS[stable_index(f"{seed}:color", len(AUTO_COLORS))]]
    else:
        colour = AVATAR_HEX[HUE_COLORS.get(int(hue), "gris")]
    if grok and shape not in GROK_SHAPES:
        top, bottom = mark_extent(shape)
    else:
        radii = silhouette_radii(shape)
        top, bottom = radii[48], radii[16]
    return {"shape": shape, "expression": expression, "hex": colour, "tilt": tilt,
            "top": top, "bottom": bottom, "grok": grok}


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


def depth_defs(colour: str, shift_x: float = 0.0, shift_y: float = 0.0) -> str:
    """The light from the top left and the shade at the bottom right; shift moves both with the
    front of the turned body, in fractions of the body's size."""
    return (
        f'<defs><radialGradient id="hl" cx="{0.30 + shift_x:.3f}" cy="{0.22 + shift_y:.3f}" r="0.80">'
        f'<stop offset="0" stop-color="#fff" stop-opacity="{HIGHLIGHT}"/>'
        '<stop offset="0.6" stop-color="#fff" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="sh" cx="{0.62 + shift_x:.3f}" cy="{0.68 + shift_y:.3f}" r="0.75">'
        f'<stop offset="0.45" stop-color="{_darker(colour, SHADE_DARKNESS)}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{_darker(colour, SHADE_DARKNESS)}" stop-opacity="{SHADE}"/>'
        '</radialGradient></defs>'
    )


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# Grok Bot's eyes, in eye widths: a blink presses the pill to a lying one of 0.42 its width, and a
# happy eye is an arc as thick as the eye, 1.23 wide, its top 0.58 above the middle.
LID_SHUT = 0.42
HAPPY_SPAN, HAPPY_TOP, HAPPY_FOOT = 0.615, 0.577, 0.04
# Grok Bot's two happy arcs together take 0.93 of the distance between its eyes, so they never touch.
HAPPY_ROOM = 0.93


def eye_length(length: float, width: float, scale: float) -> float:
    """How long an eye is with its lids at scale: 1 open, 0 shut, the way Grok Bot blinks."""
    if scale >= 1:
        return length * scale
    return _lerp(length, LID_SHUT * width, 1 - max(0.0, scale))


MOUTH_SIZE = 3.2  # half the width of the cross
MOUTH_DROP = 0.5  # below the eyes, in head radii, at most


def _mouth(cx: float, cy: float, fill: str, opacity: float) -> str:
    """A cross: the bot is muted."""
    s = MOUTH_SIZE
    return (f'<path d="M{cx - s:.2f} {cy - s:.2f} L{cx + s:.2f} {cy + s:.2f}'
            f' M{cx - s:.2f} {cy + s:.2f} L{cx + s:.2f} {cy - s:.2f}" fill="none" stroke="{fill}"'
            f' stroke-width="2.6" stroke-linecap="round" opacity="{opacity}"/>')


# Grok Bot's neutral eye, in head radii: a capsule 0.26 wide and 0.57 long, the two 0.312 from the
# middle (its engine's two eye capsules, seen from the front).
GROK_EYE = (0.26, 0.57, 0.0, 1.0)
GROK_EYE_X = 0.312
MIN_EYE = 2.0 / CIRCLE_R


def _eye_shape(w: float, h: float, tilt: float, happy: float, scale: float, arc: float) -> list:
    """One eye, flat, around its own middle (u right, v down, head radii): a pill that blinks into a
    lying one and smiles into Grok Bot's arc."""
    ew = max(MIN_EYE, w)
    eh = max(MIN_EYE, eye_length(h, ew, scale))
    half = max(0.001, abs(eh - ew) / 2)
    if eh >= ew:
        pill, thick = ((0.0, -half), (0.0, 0.0), (0.0, half)), ew
    else:
        pill, thick = ((-half, 0.0), (0.0, 0.0), (half, 0.0)), eh
    size = ew * arc
    top, foot = -HAPPY_TOP * size, HAPPY_FOOT * size
    caret = ((-HAPPY_SPAN * size, foot), (0.0, 2 * top - foot), (HAPPY_SPAN * size, foot))
    p0, ctrl, p1 = (tuple(_lerp(a, b, happy) for a, b in zip(u, v)) for u, v in zip(pill, caret))
    width = _lerp(thick, size, happy)
    turn_by = math.radians(tilt * (1 - happy))
    c, s_ = math.cos(turn_by), math.sin(turn_by)
    line = []
    for k in range(9):
        t = k / 8
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * ctrl[0] + t * t * p1[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * ctrl[1] + t * t * p1[1]
        line.append((x * c - y * s_, x * s_ + y * c))
    return body3d._stroke(line, width / 2)


# Grok Bot's faces (its engine's expressions), per eye from the left, in head radii for its neutral
# eye: ("pill", out, up, width, length, tilt) where out moves the eye away from the middle, up raises
# it and tilt turns the left eye clockwise (the right one the other way); ("stroke", out, up, half
# the thickness, three control points of a curve with x outwards and y up); ("happy", ...) its arc.
GROK_FACES = {
    "neutral": (("pill", 0.0, 0.0, 0.26, 0.57, 0.0),) * 2,
    "happy": (("happy", 0.0, 0.0),) * 2,
    "surprised": (("pill", 0.03, 0.0, 0.42, 0.86, 0.0),) * 2,
    "inspecting": (("pill", 0.04, 0.0, 0.54, 0.54, 0.0), ("pill", 0.04, 0.0, 0.27, 0.27, 0.0)),
    "sad": (("pill", -0.05, 0.0, 0.26, 0.5, 27.9),) * 2,
    "squinted": (("pill", 0.01, 0.0, 0.26, 0.5, 90.0),) * 2,
    "sleepy": (("stroke", 0.01, 0.0, 0.13, ((-0.11, 0.025), (0.0, -0.05), (0.11, 0.025))),) * 2,
    "confused": (("stroke", -0.1, 0.0, 0.1305, ((0.01, 0.16), (-0.17, 0.0), (0.01, -0.16))),) * 2,
}
# A blink presses a curved eye no flatter than this.
CURVE_SHUT = 0.25


def expressed_eye(face: str, side: int, eye: tuple, happy: float, scale: float, arc: float) -> tuple:
    """One eye with one of Grok Bot's faces: (flat outline, (u, v) to move it by), for this face's own
    neutral eye (width, length, tilt), side 0 the left one. Neutral is the face's own eye; the others
    are Grok Bot's, sized to it."""
    w, length, tilt = eye[:3]
    if face == "neutral":
        return _eye_shape(w, length, tilt, happy, scale, arc), (0.0, 0.0)
    size = math.sqrt(max(MIN_EYE, w) * max(MIN_EYE, length) / (GROK_EYE[0] * GROK_EYE[1]))
    kind, out, up, *rest = GROK_FACES[face][side]
    mirror = -1 if side == 0 else 1
    shift = (mirror * out * size, -up * size)
    if kind == "happy":
        return _eye_shape(w, length, tilt, 1.0, scale, arc), shift
    if kind == "pill":
        pw, plength, ptilt = rest
        return _eye_shape(pw * size, plength * size, -mirror * ptilt, happy, scale, arc), shift
    half, (a, b, c) = rest
    flat = max(CURVE_SHUT, min(1.0, scale))
    points = [(mirror * x * size, -y * size * flat) for x, y in (a, b, c)]
    line = [tuple((1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t * t * p2 for p0, p1, p2 in zip(*points))
            for t in (k / 8 for k in range(9))]
    curve = body3d._stroke(line, half * size)
    if happy > 0:
        arc_eye = _eye_shape(w, length, tilt, 1.0, scale, arc)
        curve = [(_lerp(x, ax, happy), _lerp(y, ay, happy)) for (x, y), (ax, ay) in zip(curve, arc_eye)]
    return curve, shift


def _points_path(points, radius: float, cx: float, cy: float) -> str:
    return "M" + "L".join(f"{cx + x * radius:.2f} {cy + y * radius:.2f}" for x, y in points) + "Z"


# The turn of Grok Bot's still art on the half-degree grid the outlines are kept on.
MARK_REST = (round(GROK_REST[0] * 2) / 2, round(GROK_REST[1] * 2) / 2)


def grok_body_points(shape: str, pitch: float, yaw: float, roll: float = 0.0) -> tuple:
    """The outline of Grok Bot's 3D body for this avatar shape, turned, in head radii."""
    from botwidget.grok_bodies import GROK_BODIES
    fit = GROK_BODIES[shape]["fit"] * (GROK_BLOB_R if shape == "blob" else 1.0)
    outline = body3d.grok_outline(shape, round(pitch * 2) / 2, round(yaw * 2) / 2)
    c, s_ = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    return tuple((fit * (x * c + y * s_), fit * (y * c - x * s_)) for x, y in outline)


def eye_seats(profile: dict) -> list:
    """Both eyes: (centre in 3D, the surface's normal there or None on a ball, (width, length, tilt,
    opening)), seen from the front. A Grok Bot shape's eyes sit where Grok Bot's engine seats them."""
    from botwidget.grok_bodies import GROK_BODIES
    body = GROK_BODIES.get(profile["shape"]) if profile["grok"] else None
    if body and "eyes" in body:
        fit, seats = body["fit"], []
        for x, y, z, w, length in body["eyes"]:
            normal = {"front": (0.0, 0.0, 1.0), "wrap": (x, 0.0, z), "wrapX": (0.0, y, z)}.get(body["seat"], (x, y, z))
            seats.append(((x * fit, y * fit, z * fit), normal, (w * fit, length * fit, 0.0, 1.0)))
        return seats
    if profile["grok"]:
        return [((-GROK_EYE_X if i == 0 else GROK_EYE_X, 0.0, 0.0), None, GROK_EYE) for i in range(2)]
    spec = EXPRESSIONS[profile["expression"]]
    across = math.sin(math.radians(spec[0]))
    return [((-across if i == 0 else across, 0.0, 0.0), None, eye) for i, eye in enumerate(spec[1:])]


def mark_drawn(profile: dict) -> bool:
    """A Grok Bot shape drawn from its still art, which shows it turned by GROK_REST."""
    return profile["grok"] and profile["shape"] in GROK_MARKS and profile["shape"] not in GROK_SHAPES


# OpenBot's shapes built the way Grok Bot builds the nearest of its own: round ones lofted, the
# squircle a rounded slab, the capsule a chain of balls, the ones with corners extruded and bevelled.
OPENBOT_BUILD = {"cercle": "loft", "galet": "loft", "nuage": "loft", "goutte": "loft",
                 "squircle": "roundedSlab", "capsule": "balls", "triangle": "extrusion", "hexagone": "extrusion"}
# Grok Bot's depths for those constructions (its cloud, squircle and extruded shapes), in head radii.
LOFT_DEPTH, SLAB, EXTRUDE = 0.82, (0.278, 0.109), (0.357, 0.218)


@lru_cache(maxsize=16)
def openbot_body(shape: str) -> tuple:
    points = body3d.radii_points(SILHOUETTES[shape])
    kind = OPENBOT_BUILD.get(shape, "loft")
    if kind == "roundedSlab":
        spec = {"kind": kind, "ring": points, "half_depth": SLAB[0], "edge": SLAB[1]}
    elif kind == "extrusion":
        spec = {"kind": kind, "outline": points, "half_depth": EXTRUDE[0], "bevel": EXTRUDE[1]}
    elif kind == "balls":
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        hx, hy = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
        r, reach = min(hx, hy), abs(hx - hy)
        along = [-reach + 2 * reach * i / 32 for i in range(33)]
        spec = {"kind": kind, "balls": tuple((a, 0.0, 0.0, r) if hx >= hy else (0.0, a, 0.0, r) for a in along)}
    else:
        spec = {"kind": "loft", "outline": points, "depth": LOFT_DEPTH, "centre": (0.0, 0.0)}
    return body3d.prepared_body(shape, spec)


@lru_cache(maxsize=2048)
def _openbot_outline(shape: str, pitch: float, yaw: float) -> tuple:
    return body3d.body_outline(openbot_body(shape), pitch, yaw)


def body_points(profile: dict, pitch: float, yaw: float, roll: float = 0.0) -> tuple:
    """The outline of the face's 3D body, turned, in head radii: Grok Bot's own body for a Grok Bot
    avatar, the nearest of its constructions for an OpenBot shape."""
    if profile["grok"] and profile["shape"] in GROK_MARKS:
        return grok_body_points(profile["shape"], pitch, yaw, roll)
    outline = _openbot_outline(profile["shape"], round(pitch * 2) / 2, round(yaw * 2) / 2)
    c, s_ = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    return tuple((x * c + y * s_, y * c - x * s_) for x, y in outline)


def body_path(profile: dict, pitch: float, yaw: float, radius: float, cx: float, cy: float,
              roll: float = 0.0) -> str:
    """The outline of the face's body, turned like a 3D body."""
    return _points_path(body_points(profile, pitch, yaw, roll), radius, cx, cy)


def face_svg(dx: float = 0, dy: float = 0, scale: float = 1.0, converge: float = 0,
             seed: str = "", hue: float | None = None, lift: float = 0.0,
             happy: float = 0.0, lean: float = 0.0, squash: tuple = (1.0, 1.0),
             muted: bool = False, avatar: dict | None = None, zoom: float = 1.0, roll: float = 0.0,
             pitch: float = 0.0, yaw: float = 0.0, shift: float = 0.0,
             expression: tuple = ("neutral", "neutral", 1.0)) -> str:
    """This bot’s own body and colour, with its two eyes, drawn as Grok Bot draws a 3D body.

    dx/dy turn the head: they are where its front goes, in px, so the body's outline and its
    shading turn and the eyes, lying on the surface, move, bend and foreshorten with it; pitch and
    yaw (degrees) turn it further, roll turns it about the view (Grok Bot's roll, anticlockwise).
    lift raises the whole face (px), shift moves it right, lean tilts it, squash stretches or
    flattens it, zoom sizes it. expression is (face, face, t): Grok Bot's faces (GROK_FACES), the
    eyes t of the way from the first to the second. happy 0 is the eye the expression gives, 1 Grok
    Bot's happy arc; scale below 1 closes the lids. A muted bot has a cross for a mouth. Every face,
    OpenBot's and Grok Bot's, has the same eyes: Grok Bot's own for a Grok Bot avatar, the seed's
    sizes and spacing for an OpenBot one.
    """
    profile = avatar_profile(seed, hue, avatar)
    centre = AVATAR_SIZE / 2
    look_pitch, look_yaw = body3d.angles_for(dx, dy, CIRCLE_R)
    pitch, yaw = look_pitch + pitch, look_yaw + yaw
    front = body3d.turn(pitch, yaw)
    rot = body3d.turn(pitch, yaw, roll)
    seats = eye_seats(profile)
    widest = max(max(MIN_EYE, eye[0]) for _c, _n, eye in seats) * (2 * HAPPY_SPAN + 1)
    arc = min(1.0, HAPPY_ROOM * math.dist(seats[1][0][:2], seats[0][0][:2]) / widest)
    start, end, t = expression
    eyes, middles = [], []
    for i, ((x, y, z), normal, (w, h, tilt, open_)) in enumerate(seats):
        eye = (w, h * open_, tilt)
        shape, (du, dv) = expressed_eye(end, i, eye, happy, scale, arc)
        if t < 1:
            before, (bu, bv) = expressed_eye(start, i, eye, happy, scale, arc)
            shape = [(_lerp(a, c, t), _lerp(b, d, t)) for (a, b), (c, d) in zip(before, shape)]
            du, dv = _lerp(bu, du, t), _lerp(bv, dv, t)
        x += du + (converge if i == 0 else -converge) / CIRCLE_R
        y += dv
        if normal is None:  # on the ball
            z = math.sqrt(max(0.0, 1 - x * x - y * y))
        place = (x, y, z)
        laid = body3d.eye_on_surface(place, shape, rot, normal)
        middles.append(rot(*place))
        if laid:
            eyes.append(f'<path d="{_points_path(laid, CIRCLE_R, centre, centre)}" fill="{EYE_FILL}"/>')
    if muted:
        mx = sum(m[0] for m in middles) / 2 * CIRCLE_R
        my = sum(m[1] for m in middles) / 2 * CIRCLE_R
        drop = min(MOUTH_DROP, 0.6 * (profile["bottom"] - my / CIRCLE_R)) * CIRCLE_R
        eyes.append(_mouth(centre + mx, centre + my + drop, EYE_FILL, 1.0))
    body = body_path(profile, pitch, yaw, CIRCLE_R, centre, centre, roll)
    bx, by, _bz = front(0.0, 0.0, body3d.DEPTH)
    head = (f'<path d="{body}" fill="{profile["hex"]}"/>'
            f'<path d="{body}" fill="url(#sh)"/><path d="{body}" fill="url(#hl)"/>')
    sx, sy = squash
    pose = (f'translate({shift:.2f} {-lift:.2f})'
            f' rotate({profile["tilt"] + lean:.2f} {centre} {centre})'
            f' translate({centre} {centre}) scale({sx * zoom:.4f} {sy * zoom:.4f}) translate({-centre} {-centre})')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{AVATAR_SIZE}" height="{AVATAR_SIZE}">'
        + depth_defs(profile["hex"], bx * 0.45, by * 0.45)
        + f'<g transform="{pose}"><clipPath id="body"><path d="{body}"/></clipPath>{head}'
        + f'<g clip-path="url(#body)">{"".join(eyes)}</g></g>'
        + "</svg>"
    )


def avatar_svg(pose: str = "rest", seed: str = "", hue: float | None = None,
               happy: float = 0.0, avatar: dict | None = None) -> str:
    dx, dy, scale = POSES[pose]
    return face_svg(dx, dy, scale, 0, seed, hue, LIFT.get(pose, 0.0), happy, avatar=avatar)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
