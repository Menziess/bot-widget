"""Line breaking for the speech bubble; the toolkit only supplies the text measurement."""

import re

from botwidget.markdown import md_blocks, split_panels
from botwidget.theme import (
    BUBBLE_CODE_FONT,
    BUBBLE_MAX_W,
    CODE_INDENT,
    CONTROL_BUTTON_PAD,
    CONTROL_SLIDER_W,
    CONTROL_SWITCH_W,
    DOTS_W,
    MEET_SLACK,
    MIN_CONTENT_W,
    MIN_TEXT_ROOM,
    MIN_TEXT_W,
    MORE_W,
    PAD_BODY,
    PAD_PANEL_X,
    SMALL_FONT,
    TABLE_FONT,
    TABLE_GAP,
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

    laid, widest = [], MIN_TEXT_W

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
        room = max(MIN_TEXT_ROOM, max_w - block["indent"])
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
        size, prefix = block["size"], block["prefix"]
        started = measure(prefix, "", size) if prefix else 0
        space_w = measure(" ", "", size)
        total = started  # the row so far, added up in the order the pieces come, as width() does
        for tok in tokens:
            word, style, lead = tok
            trial = (total + space_w if cur and lead else total) + measure(word, style, size)
            if cur and int(round(trial) * MEET_SLACK) + 1 > room:
                rows.append(cur)
                cur, total = [tok], started + measure(word, style, size)
            else:
                cur.append(tok)
                total = trial
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

    def clipped(pieces: list, size: int, room: float) -> list:
        """The pieces of a cell cut to fit, with an ellipsis where they were cut."""
        if width(pieces, size) <= room:
            return pieces
        out, used = [], 0.0
        ellipsis = measure("…", "", size)
        for text, style in pieces:
            for ch in text:
                w = measure(ch, style, size)
                if used + w + ellipsis > room:
                    return out + [("…", "")]
                out.append((ch, style))
                used += w
        return out

    def lay_table(block: dict):
        """A table as one line per row: the cells are separated by tabs, which the text surface sets to the columns.
        Columns take what their words need; when the table is wider than the bubble, the widest give way and their
        words are cut short."""
        nonlocal widest
        size, gap = TABLE_FONT, TABLE_GAP
        rows = [[[(t, "b" if st == "" and n == 0 else st) for t, st in cell] for cell in row]
                for n, row in enumerate(block["rows"])]
        count = max(len(row) for row in rows)
        rows = [row + [[("", "")]] * (count - len(row)) for row in rows]
        natural = [max(width(row[c], size) for row in rows) for c in range(count)]
        room = max(MIN_TEXT_ROOM, max_w - block["indent"]) - gap * (count - 1)
        cols, left, open_ = [0] * count, room, set(range(count))
        while open_:
            share = left / len(open_)
            small = {c for c in open_ if natural[c] <= share}
            if not small:
                for c in open_:
                    cols[c] = share
                break
            for c in small:
                cols[c] = natural[c]
                left -= natural[c]
            open_ -= small
        xs = [sum(cols[:c]) + gap * c for c in range(count)]
        total = round(sum(cols) + gap * (count - 1))
        widest = max(widest, total + block["indent"])
        for n, row in enumerate(rows):
            words = []
            for c, cell in enumerate(row):
                if c:
                    words.append(("\t", "", False))
                words += [(t, st, False) for t, st in clipped(cell, size, cols[c]) if t]
            laid.append({**block, "kind": "text", "size": size, "words": words, "prefix": "", "width": total,
                         "xs": [], "ws": [], "cont": False, "tabs": [round(x) for x in xs[1:]],
                         "natural": round(sum(natural) + gap * (count - 1))})
            if n == 0:
                laid.append({"kind": "rule", "size": 0, "indent": 0, "prefix": "", "grey": False, "chunks": [],
                             "words": [], "width": 0})

    for block in (md_blocks(text) if isinstance(text, str) else text):
        kind = block.get("kind")
        if kind in ("gap", "rule"):
            laid.append({**block, "words": [], "width": 0})
            continue
        if kind == "dots":
            # Thinking dots: three circles that the widget itself makes pulse.
            laid.append({"kind": "dots", "size": SMALL_FONT, "indent": 0, "prefix": "",
                         "grey": False, "head": False, "words": [], "xs": [], "ws": [],
                         "width": DOTS_W, "phase": 0.0})
            widest = max(widest, DOTS_W)
            continue
        if kind == "control":
            label_w = width([(block["label"], "")], SMALL_FONT)
            extra = {"toggle": CONTROL_SWITCH_W, "slider": CONTROL_SLIDER_W}.get(block["control"], CONTROL_BUTTON_PAD)
            laid.append({**block, "words": [], "xs": [], "ws": [], "head": False, "width": label_w + extra})
            widest = max(widest, laid[-1]["width"] + block.get("indent", 0))
            continue
        if kind == "more":
            laid.append({"kind": "more", "size": SMALL_FONT, "indent": 0, "prefix": "", "grey": False,
                         "head": False, "words": [], "xs": [], "ws": [], "width": MORE_W})
            continue
        if kind == "table":
            lay_table(block)
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
    content_w = max(MIN_CONTENT_W, max_w - 2 * PAD_BODY - 2 * PAD_PANEL_X)
    panels = []
    for panel in split_panels(blocks):
        lines, widest = md_layout(measure, panel["blocks"], content_w)
        if not lines:
            continue
        panels.append({"role": panel["role"], "copy": panel.get("copy", ""), "queued": panel.get("queued", ""),
                       "back": panel.get("back", ""), "lines": lines, "text_w": widest})
    return panels
