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
# Thinking dots in the bubble: three circles with a wave running through them.
DOTS_W = 62
DOTS_R = 4.5
DOTS_GAP = 12.0
# A short tick so the wave moves smoothly instead of in steps; one wave takes this many seconds.
DOTS_MS = 32
DOTS_CYCLE_S = 1.2
# A bubble nobody points at goes away this many seconds after it appeared or changed. One that was
# pointed at closes as soon as the pointer leaves.
BUBBLE_LINGER = 4.0
# Room below (or above) the white area for the tail or the cloud circles.
TAIL_ROOM = 22
SHADOW_GROW = 3
SHADOW_BLUR = 4.0
SHADOW_ALPHA = 0.30
