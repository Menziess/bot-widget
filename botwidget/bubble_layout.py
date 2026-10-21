"""Line breaking for the speech bubble; the toolkit only supplies the text measurement."""

import re

from botwidget.markdown import md_blocks, split_panels
from botwidget.theme import (
    BUBBLE_CODE_FONT,
    BUBBLE_MAX_W,
    CODE_INDENT,
    DOTS_W,
    MEET_SLACK,
    PAD_BODY,
    PAD_PANEL_X,
)


def md_layout(measure, text, max_w: int = BUBBLE_MAX_W) -> tuple:
    """Markdown to broken lines.

    measure(text, style, px) returns the width in px; style is "", "b", "i",
    "code" or "mono".
    """
    def width(pieces: list, size: int) -> int:
        return round(sum(measure(text, style, size) for text, style in pieces))

    def fit(pieces: list, size: int) -> int:
        """Width used for breaking. Librsvg draws text wider than the measurement,
        so include that margin; otherwise the line runs into the edge of the
        text area. The x per word stays the bare measurement, for the code chips.
        """
        return int(width(pieces, size) * MEET_SLACK) + 1

    def pieces_of(words: list, prefix: str) -> list:
        out = [(prefix, "")] if prefix else []
        for k, (word, style, lead) in enumerate(words):
            if k and lead:
                out.append((" ", ""))
            out.append((word, style))
        return out

    laid, widest = [], 16

    def lay_block(block: dict):
        """A text block to lines; fills laid and widest, with x per word."""
        nonlocal widest
        tokens, space = [], True
        for chunk, style in block["chunks"]:
            for piece in re.split(r"(\s+)", chunk):
                if piece == "":
                    continue
                if piece.isspace():
                    space = True
                    continue
                tokens.append((piece, style, space))
                space = False
        if not tokens:
            return
        room = max(60, max_w - block["indent"])
        broken = []
        for word, style, lead in tokens:
            if fit(pieces_of([(word, style, lead)], ""), block["size"]) > room:
                piece, first = "", True
                for ch in word:
                    if piece and fit(pieces_of([(piece + ch, style, False)], ""), block["size"]) > room:
                        broken.append((piece, style, lead if first else False))
                        first = False
                        piece = ch
                    else:
                        piece += ch
                if piece:
                    broken.append((piece, style, lead if first else False))
            else:
                broken.append((word, style, lead))
        tokens = broken
        rows, cur = [], []
        for tok in tokens:
            trial = cur + [tok]
            if cur and fit(pieces_of(trial, block["prefix"]), block["size"]) > room:
                rows.append(cur)
                cur = [tok]
            else:
                cur = trial
        if cur:
            rows.append(cur)
        for i, row in enumerate(rows):
            prefix = block["prefix"] if i == 0 else ""
            w = fit(pieces_of(row, prefix), block["size"])
            widest = max(widest, min(room, w) + block["indent"])
            xs, ws, acc = [], [], pieces_of([], prefix)
            for j, (word, style, lead) in enumerate(row):
                if j and lead:
                    acc.append((" ", ""))
                xs.append(width(acc, block["size"]))
                piece = [(word, style)]
                ws.append(width(piece, block["size"]))
                acc += piece
            laid.append({**block, "words": row, "prefix": prefix, "width": w,
                         "xs": xs, "ws": ws, "cont": i > 0})

    for block in (md_blocks(text) if isinstance(text, str) else text):
        kind = block.get("kind")
        if kind in ("gap", "rule"):
            laid.append({**block, "words": [], "width": 0})
            continue
        if kind == "dots":
            # Thinking dots: three circles that the widget itself makes pulse.
            laid.append({"kind": "dots", "size": 15, "indent": 0, "prefix": "",
                         "grey": False, "head": False, "words": [], "xs": [], "ws": [],
                         "width": DOTS_W, "phase": 0.0})
            widest = max(widest, DOTS_W)
            continue
        if kind == "more":
            laid.append({"kind": "more", "size": 15, "indent": 0, "prefix": "", "grey": False,
                         "head": False, "words": [], "xs": [], "ws": [], "width": 12})
            continue
        if kind == "code":
            for code_line in block["lines"]:
                lay_block({"kind": "text", "size": BUBBLE_CODE_FONT, "indent": CODE_INDENT,
                           "prefix": "", "grey": False, "head": False, "code": True,
                           "chunks": [(code_line, "mono")]})
            continue
        if kind != "text":
            continue
        lay_block(block)
    return laid, widest


def bubble_panels(measure, blocks: list, max_w: int = BUBBLE_MAX_W) -> list:
    """Panels with broken lines; the widest text comes with them."""
    content_w = max(80, max_w - 2 * PAD_BODY - 2 * PAD_PANEL_X)
    panels = []
    for panel in split_panels(blocks):
        lines, widest = md_layout(measure, panel["blocks"], content_w)
        if not lines:
            continue
        panels.append({"role": panel["role"], "copy": panel.get("copy", ""), "lines": lines, "text_w": widest})
    return panels
