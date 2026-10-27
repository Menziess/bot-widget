"""The bubble text as a real text document: selectable, with clickable http(s) links.

The panel lines come from bubble_layout, so the text breaks exactly where the measured
layout says and the shapes drawn behind it stay in place.
"""

from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption

from botwidget.bubble import line_height, panel_gap, panel_pad
from botwidget.markdown import anchor_url, command_href
from botwidget.theme import (
    BUBBLE_CODE_FONT,
    PAD_PANEL_X,
    SAND_ACCENT,
    SAND_CHIP,
    SAND_CHIP_USER,
    SAND_INK,
    SAND_INK_SOFT,
    SAND_MONO,
    SAND_ON_USER,
    SAND_ON_USER_SOFT,
    SAND_SANS,
)


def color(name: str) -> QColor:
    """A theme token as a colour. The tokens are CSS hex, #rrggbbaa, not Qt's #aarrggbb."""
    if len(name) == 9 and name.startswith("#"):
        r, g, b, a = (int(name[i:i + 2], 16) for i in (1, 3, 5, 7))
        return QColor(r, g, b, a)
    return QColor(name)


def char_format(style: str, user: bool, size: int, grey: bool, head: bool) -> QTextCharFormat:
    """Font and colour of one piece of a line; the style names come from markdown."""
    fmt = QTextCharFormat()
    mono = style in ("code", "mono")
    font = QFont(SAND_MONO if mono else SAND_SANS)
    font.setPixelSize(BUBBLE_CODE_FONT if style == "code" else size)
    font.setBold(style == "b" or head)
    font.setItalic(style == "i")
    fmt.setFont(font)
    ink = SAND_ON_USER if user else SAND_INK
    if style == "code":
        fmt.setBackground(color(SAND_CHIP_USER if user else SAND_CHIP))
        fmt.setForeground(color(ink))
    elif style.startswith(("link:", "cmd:")):
        # Accent blue is unreadable on the dark user panel; it stays white there.
        fmt.setForeground(color(SAND_ON_USER if user else SAND_ACCENT))
    elif style == "dim":
        fmt.setForeground(color(SAND_ON_USER_SOFT if user else SAND_INK_SOFT))
    else:
        fmt.setForeground(color(SAND_ON_USER_SOFT if user and grey else ink))
    return fmt


def line_pieces(line: dict) -> list:
    """The pieces of one laid line as (text, style), spaces included."""
    pieces = []
    if line["prefix"]:
        pieces.append((line["prefix"], ""))
    for i, (word, style, lead) in enumerate(line.get("words") or []):
        if i and lead:
            pieces.append((" ", ""))
        pieces.append((word, style))
    return pieces


def fill_document(doc, panels: list, box_w: int):
    """Rewrite the document from the panels: the same lines, with anchors on links.

    Only a top margin on the first line of each next panel: Qt drops a first block's top
    margin and collapses touching margins, so the spacing it really uses stays predictable.
    The first line of the whole document gets none; the text widget itself sits one panel
    padding lower, which is where the bubble draws it.
    """
    # Without this the new text is inserted above the old text, which then sits below the new
    # panels: white words (made for the dark user panel) on the white bubble.
    doc.clear()
    doc.setUndoRedoEnabled(False)  # no history to keep: it made every piece of text cost more
    doc.setDocumentMargin(0)
    doc.setTextWidth(box_w)
    cursor = QTextCursor(doc)
    cursor.beginEditBlock()  # the document lays out once, not after every piece
    first = True
    for pi, panel in enumerate(panels):
        user = panel["role"] == "user"
        lines = panel["lines"]
        for li, line in enumerate(lines):
            block = QTextBlockFormat()
            block.setTopMargin(panel_pad(panels[pi - 1]) + panel_gap(panels[pi - 1], panel) + panel_pad(panel)
                               if li == 0 and pi > 0 else 0)
            block.setLeftMargin(PAD_PANEL_X + line["indent"])
            block.setLineHeight(float(line_height(line)),
                                QTextBlockFormat.LineHeightTypes.FixedHeight.value)
            if line.get("tabs"):
                block.setTabPositions([QTextOption.Tab(PAD_PANEL_X + line["indent"] + x, QTextOption.LeftTab)
                                       for x in line["tabs"]])
            if first:
                cursor.setBlockFormat(block)
                first = False
            else:
                cursor.insertBlock(block)
            # A line that only continues the one above: copied text joins them with a space.
            cursor.block().setUserState(1 if line.get("cont") else 0)
            for text, style in line_pieces(line):
                fmt = char_format(style, user, line["size"], line["grey"], line.get("head", False))
                url = anchor_url(style) or command_href(style)
                if url:
                    fmt.setAnchor(True)
                    fmt.setAnchorHref(url)
                cursor.insertText(text, fmt)
    cursor.endEditBlock()
    return doc


def selected_text(doc, start: int, end: int) -> str:
    """The words between two positions; lines that are one paragraph wrapped become one line again."""
    parts, block = [], doc.findBlock(start)
    while block.isValid() and block.position() < end:
        first, last = max(start, block.position()), min(end, block.position() + block.length() - 1)
        if last > first or not parts:
            text = block.text()[first - block.position():last - block.position()]
            parts.append((" " if block.userState() == 1 else "\n", text))
        block = block.next()
    return "".join((sep if i else "") + text for i, (sep, text) in enumerate(parts))
