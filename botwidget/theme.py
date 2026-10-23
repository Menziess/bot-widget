"""Sizes and colours of the speech bubble (Grok Bot's 'sand' set)."""



# ── Grok Bot design ─────────────────────────────────────────────────
# Tokens from Grok Bot's own "sand" set (/opt/Grok Bot/resources/app.asar,
# dist/renderer/assets/index-DkV65EBE.css): light, ink #1c1c1c, accent #1680f3, bubble radius 18.
# Grok's own fonts (X-VF, XMono-VF) are inside the app and not installed system-wide; we take the
# system fonts Grok falls back to.
SAND_SANS = "Noto Sans"
SAND_MONO = "DejaVu Sans Mono"
SAND_INK = "#1c1c1c"
SAND_INK_SOFT = "#1c1c1c8f"
SAND_ACCENT = "#0b6dd3"
SAND_HAIRLINE = "#1c1c1c1f"
SAND_BUBBLE = "#ffffff"
SAND_PANEL_USER = "#2a2a2a"
SAND_ON_USER = "#ffffff"
SAND_ON_USER_SOFT = "#ffffffa8"
SAND_LINE_USER = "#ffffff33"
SAND_CHIP = "#1c1c1c0f"
SAND_CHIP_USER = "#ffffff1f"
SAND_RADIUS = 18
SAND_RADIUS_PANEL = 12
SAND_RADIUS_CODE = 8
BUBBLE_FONT = 15
BUBBLE_CODE_FONT = 13
BUBBLE_CODE_LINES = 6
BUBBLE_MAX_W = 300
# A long answer gets a wider bubble, in these steps, so it scrolls less; never wider than this share of the screen.
BUBBLE_WIDER = (380, 460, 540)
BUBBLE_MAX_SCREEN_SHARE = 0.45
# Librsvg draws text a few percent wider than Pango measures; this margin keeps the line inside the
# text area.
MEET_SLACK = 1.06
MD_HEAD_SIZE = {1: 18, 2: 16, 3: 15}
CHIP_PAD_X = 4
CHIP_RX = 4
CODE_INDENT = 8
PAD_SVG = 18
PAD_BODY = 12
PAD_PANEL_X = 12
PAD_PANEL_Y = 11
GAP_PANEL = 10
# The arrow that says there are earlier messages: a slim strip that sits close to the message below it.
MORE_PAD = 2
MORE_GAP = -8  # a white message under it can sit closer ...
MORE_GAP_DARK = -1  # ... a dark panel starts right below the arrow
MORE_H = 12
# A form element in the bubble: its row, and what it needs next to its label (switch, or button padding).
CONTROL_H = 30
CONTROL_SWITCH_W = 46
CONTROL_BUTTON_PAD = 28
MORE_HIT_HALF_W = 12  # the arrow answers a click this far left and right of its middle, not across the whole bubble
# Thinking dots in the bubble: three circles with a wave running through them.
DOTS_W = 62
DOTS_R = 4.5
DOTS_GAP = 12.0
# A short tick so the wave moves smoothly instead of in steps; one wave takes this many seconds.
DOTS_MS = 32
DOTS_CYCLE_S = 1.2
# A bubble nobody points at goes away after the time to read it: this many seconds plus a bit per
# word, never longer than the maximum. One that was pointed at closes as soon as the pointer leaves.
BUBBLE_LINGER = 4.0
BUBBLE_PER_WORD = 0.3
BUBBLE_LINGER_MAX = 40.0
# While an answer is awaited the bubble stays; a bot that never answers does not keep it forever.
BUBBLE_WAIT_MAX = 600.0
# Room below (or above) the white area for the tail or the cloud circles.
TAIL_ROOM = 22
SHADOW_GROW = 3
SHADOW_BLUR = 4.0
SHADOW_ALPHA = 0.30
# Line heights in the bubble (bubble.py line_height): gap, rule, dots, and per-line padding.
LINE_GAP_H = 10
LINE_RULE_H = 14
LINE_DOTS_H = 26
LINE_CODE_PAD = 12
LINE_TEXT_PAD = 10
