"""The face: colours, silhouettes, expressions and the SVGs, without a toolkit."""

import colorsys
import math

from botwidget.grok_marks import GROK_MARKS

# The face fits a circle of diameter 58 in a 68 px window; two long vertical eyes sit in the middle.
AVATAR_SIZE = 68
CIRCLE_R = 29.0
# ── Motion, after Grok Bot's own avatar engine ─────────────────────
# Grok Bot animates its avatar with clips of head rotations (pitch, yaw, roll in degrees) and blinks
# (x.ai, the "Motion Lab" engine behind the GrokBotMark). Its eyes sit on the front of the head, so
# a turn moves them across the face; GROK_REST is the turn its still art is drawn in: up and right.
GROK_REST = (-15.9, 33.3)
# A turn moves the eyes as far as they would go on a ball of the face's size, capped at the same
# reach the eyes have when they follow the pointer.
LOOK_MAX = 8.0


def grok_look(pitch: float, yaw: float) -> tuple[float, float]:
    """Where the eyes go, in px from the middle, when the head turns by pitch and yaw degrees."""
    p, y = math.radians(pitch), math.radians(yaw)
    dx, dy = CIRCLE_R * math.sin(y) * math.cos(p), CIRCLE_R * math.sin(p)
    reach = math.hypot(dx, dy)
    if reach > LOOK_MAX:
        dx, dy = dx * LOOK_MAX / reach, dy * LOOK_MAX / reach
    return round(dx, 1), round(dy, 1)


# Grok Bot's idle clips: (seconds, (pitch, yaw)) where a turn is reached, and when the eyes blink.
# Idle_A ends in a full turn of the head, which a flat face cannot show: it turns back to the front.
GROK_IDLE_CLIPS = {
    "Idle_B": (4.0, ((0.9, (0, 0)), (1.62, (0.1, -8.7)), (2.49, (1.0, 5.7)), (3.46, (0, 0))),
               (1.48, 3.46)),
    "Idle_D": (6.0, ((0.0, GROK_REST), (0.59, (-34.3, 16.9)), (1.96, (-6.2, 3.1)), (3.91, (7.6, 40.4)),
                     (5.63, GROK_REST)), (0.59, 2.07, 2.37, 4.25)),
    "Idle_A": (6.0, ((0.49, (0, 0)), (1.38, (-16.1, -32.7)), (1.78, (-13.5, -31.7)), (2.75, (10.4, 13.6)),
                     (2.93, (22.8, 5.3)), (4.08, (-24.9, 31.8)), (5.75, (0, 0))), (1.16, 4.0)),
}
# Grok Bot plays its idle clips from this bag (Idle_B three times); it starts at the still art.
GROK_IDLE_ORDER = ("Idle_D", "Idle_B", "Idle_A", "Idle_B", "Idle_B")
# A Grok Bot blink: shut in about 0.1 s, a moment closed, open again by 0.26 s.
BLINK_MS = 130


def _idle_cycle(poses: dict) -> tuple:
    """The idle clips as (pose, ms) steps: a turn is aimed at from the key before it, blinks in between.

    Every turn gets a pose of its own in poses; a blink keeps the eyes where they look.
    """
    steps, names = [], {}
    for clip in GROK_IDLE_ORDER:
        duration, keys, blinks = GROK_IDLE_CLIPS[clip]
        events = []
        for i, (_t, turn) in enumerate(keys):
            start = keys[i - 1][0] if i else 0.0
            look = grok_look(*turn)
            if look not in names:
                names[look] = ("idle" if turn == GROK_REST else "front" if look == (0.0, 0.0)
                               else f"turn{len(names)}")
                poses[names[look]] = (look[0], look[1], 1.0)
            events.append((start, names[look]))
        events += [(t, "blink") for t in blinks]
        events.sort(key=lambda event: event[0])
        current = events[0][1]
        for i, (t, pose) in enumerate(events):
            end = events[i + 1][0] if i + 1 < len(events) else duration
            if pose == "blink":
                steps.append(("blink", BLINK_MS))
                if end - t > BLINK_MS / 1000:
                    steps.append((current, round((end - t) * 1000) - BLINK_MS))
            else:
                current = pose
                if end > t:
                    steps.append((pose, round((end - t) * 1000)))
    return tuple(steps)


# dx, dy, length factor. Only shifts; the shape stays the same, except for a blink. A blink (length
# 0) leaves the eyes where they look: None keeps dx and dy.
POSES = {
    "rest": (0, 0, 1.0),
    "look": (0, 2, 1.0),
    "blink": (None, None, 0.0),
    "read0": (-2, 1, 1.0),
    "read1": (2, 1, 1.0),
    "aside": (-6, 1, 1.0),
    "aside2": (6, 1, 1.0),
    "hop": (0, -3, 1.0),
}
# The hop lifts the whole face for a moment; the eyes look up while it does.
LIFT = {"hop": 4.0}
# pose, duration in ms. Idle is Grok Bot's own idle: its turns and blinks, idle being its still art.
# The tick is short enough to make a double blink really double.
FACE_STEP_MS = 110
FACE = {
    "idle": _idle_cycle(POSES),
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


def _eye(ex: float, ey: float, ew: float, eh: float, tilt: float, happy: float,
         fill: str, opacity: float, arc: float = 1.0) -> str:
    """One eye as a thick line with round ends: a standing or lying pill that grows into
    Grok Bot's happy arc (^) at happy 1, arc times its size. Everything stays solid; nothing is faded.
    """
    half = max(0.01, abs(eh - ew) / 2)
    if eh >= ew:
        pill, thick = ((ex, ey - half), (ex, ey), (ex, ey + half)), ew
    else:
        pill, thick = ((ex - half, ey), (ex, ey), (ex + half, ey)), eh
    size = ew * arc
    top = ey - HAPPY_TOP * size
    foot = ey + HAPPY_FOOT * size
    caret = ((ex - HAPPY_SPAN * size, foot), (ex, 2 * top - foot), (ex + HAPPY_SPAN * size, foot))
    p0, ctrl, p1 = (tuple(_lerp(a, b, happy) for a, b in zip(u, v)) for u, v in zip(pill, caret))
    width = _lerp(thick, size, happy)
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


def face_svg(dx: float = 0, dy: float = 0, scale: float = 1.0, converge: float = 0,
             seed: str = "", hue: float | None = None, lift: float = 0.0,
             happy: float = 0.0, lean: float = 0.0, squash: tuple = (1.0, 1.0),
             muted: bool = False, avatar: dict | None = None) -> str:
    """This bot’s own silhouette and colour, with its two eyes.

    dx/dy move the eyes fully and the head partly; lift raises the whole face for a
    moment (the hop). lean tilts the head extra, squash stretches or flattens it.
    happy 0 is the normal eye shape, 1 the happy one (^^): the eyes morph into each
    other, so a half value is a real transition. A muted bot has a cross for a mouth.
    A Grok Bot shape, the blob too, has Grok Bot's own eyes where its art puts them.
    """
    profile = avatar_profile(seed, hue, avatar)
    spec = EXPRESSIONS[profile["expression"]]
    centre = AVATAR_SIZE / 2
    apart = math.sin(math.radians(spec[0])) * CIRCLE_R
    mark = GROK_MARKS.get(profile["shape"]) if profile["grok"] else None
    eyes = []
    # A Grok Bot mark keeps Grok Bot's own eyes where it puts them; they move, blink and smile
    # like every other face.
    # Its art is the head turned to GROK_REST, so the eyes move from there.
    rx, ry = POSES["idle"][:2]
    seats = ([(centre + x * CIRCLE_R - rx, centre + y * CIRCLE_R - ry, w, h, tilt, 1)
              for x, y, w, h, tilt in mark[1]] if mark else
             [(centre + (-1 if i == 0 else 1) * apart, centre, w, h, tilt, open_)
              for i, (w, h, tilt, open_) in enumerate(spec[1:])])
    apart_px = math.hypot(seats[1][0] - seats[0][0], seats[1][1] - seats[0][1])
    for i, (sx, sy, w, h, tilt, open_) in enumerate(seats):
        ex = sx + (converge if i == 0 else -converge) + dx
        ey = sy + dy
        ew = max(2.0, w * CIRCLE_R)
        eh = max(2.0, eye_length(h * CIRCLE_R * open_, ew, scale))
        widest = max(2.0, max(seat[2] for seat in seats) * CIRCLE_R) * (2 * HAPPY_SPAN + 1)
        arc = min(1.0, HAPPY_ROOM * apart_px / widest)
        if not mark:  # Grok Bot's eyes are flat on the face, without a shadow
            eyes.append(_eye(ex, ey + 1.3, ew, eh, tilt, happy, "#000", 0.14, arc))
        eyes.append(_eye(ex, ey, ew, eh, tilt, happy, EYE_FILL, 1.0, arc))
    if muted:
        mx = sum(seat[0] for seat in seats) / len(seats) - centre
        my = sum(seat[1] for seat in seats) / len(seats) - centre
        drop = min(MOUTH_DROP, 0.6 * (profile["bottom"] - my / CIRCLE_R)) * CIRCLE_R
        eyes.append(_mouth(centre + mx + dx, centre + my + dy + drop + 1.3, "#000", 0.14))
        eyes.append(_mouth(centre + mx + dx, centre + my + dy + drop, EYE_FILL, 1.0))
    if mark and profile["shape"] not in GROK_SHAPES:
        body = mark_path(profile["shape"], CIRCLE_R, centre, centre)
    else:  # the blob keeps the outline traced from Grok Bot's app art
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
        + f'<g transform="translate({-dx * PARALLAX:.2f} {-dy * PARALLAX:.2f})">{"".join(eyes)}</g>'
        + "</g></svg>"
    )


def avatar_svg(pose: str = "rest", seed: str = "", hue: float | None = None,
               happy: float = 0.0, avatar: dict | None = None) -> str:
    dx, dy, scale = POSES[pose]
    return face_svg(dx, dy, scale, 0, seed, hue, LIFT.get(pose, 0.0), happy, avatar=avatar)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
