"""Maten en kleuren van de spraakwolk (de 'sand'-set van Grok Bot)."""



# ── Grok Bot-vormgeving ────────────────────────────────────────────
# Tokens uit de "sand"-set van Grok Bot zelf (/opt/Grok Bot/resources/app.asar,
# dist/renderer/assets/index-DkV65EBE.css): licht, inkt #1c1c1c, accent #1680f3,
# bellen radius 18. Grok's eigen fonts (X-VF, XMono-VF) zitten in de app en zijn
# niet systeembreed geinstalleerd; we pakken de systeemfonts die Grok dan pakt.
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
# Librsvg zet tekst enkele procenten breder dan Pango meet; deze marge houdt de
# regel binnen het tekstvlak.
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
# Denkpuntjes in de wolk: drie bollen met een golf erdoorheen.
DOTS_W = 62
DOTS_R = 4.5
DOTS_GAP = 12.0
DOTS_MS = 180
# Zolang er niets verandert en de muis niet in de buurt is, blijft de wolk staan
# tot deze seconden na de laatste wijziging.
BUBBLE_LINGER = 8.0
# Ruimte onder (of boven) het witte vlak voor het staartje of de wolkbolletjes.
TAIL_ROOM = 22
SHADOW_GROW = 3
SHADOW_BLUR = 4.0
SHADOW_ALPHA = 0.30
