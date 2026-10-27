"""Markdown to blocks and panels; pure text, no toolkit."""

import os
import re
from urllib.parse import urlparse

from botwidget.theme import BUBBLE_CODE_LINES, BUBBLE_FONT, MD_HEAD_SIZE

MD_INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|__.+?__|`[^`]+?`|\*[^*\s][^*]*?\*|_[^_\s][^_]*?_"
    r"|\[[^\]]+?\]\((?:[^()\s]|\([^()\s]*\))*\)"
    r"|https?://[^\s<>\"'`]+)"
    r"|(?:[A-Za-z]:\\\\|~/|/home/|/usr/)[^\s<>\"'`]*[.](?:png|jpg|jpeg|gif|webp|bmp|svg|ico|pdf|txt|md|csv|log|py|js|ts|html|css|sh|bat|exe|dll|dylib|so|mp4|avi|mov|mkv|mp3|wav|flac|zip|tar|gz|7z|rar|dmg|deb|rpm|appimage|appx|msi|apk)"
)
_URL_PAIRS = {")": "(", "]": "[", "}": "{"}
_URL_TAIL = ".,;:!?"
MD_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
MD_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
MD_NUM_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
MD_QUOTE_RE = re.compile(r"^>\s?(.*)$")
MD_RULE_RE = re.compile(r"^([-*_]\s*){3,}$")
MD_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def table_cells(line: str) -> list:
    """The cells of one row of a markdown table, as inline pieces."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [md_inline(cell.strip().replace("\\|", "|")) for cell in re.split(r"(?<!\\)\|", inner)]


def _path_to_file_url(path: str) -> str:
    """Convert a local file path to a file:// URL. ~/ is expanded, backslashes on Windows."""
    import pathlib
    expanded = path if not path.startswith("~") else os.path.expanduser(path)
    # Normalise separators.
    norm = os.path.normpath(expanded)
    return pathlib.Path(norm).as_uri()


def url_host(url: str) -> str:
    """Only the host of a link, shown dim after the label."""
    try:
        host = urlparse(url).netloc or url
    except ValueError:
        host = url
    return host.split("@")[-1].split(":")[0] or url


def anchor_url(style: str) -> str:
    """The href of a link piece; empty for anything that is not an http(s) or file link."""
    if not style.startswith("link:"):
        return ""
    url = style[len("link:"):]
    if url.startswith(("http://", "https://")):
        return url
    # File path: turn into a file:// URL.
    if ":\\" in url or url.startswith("~/") or url.startswith("/home/") or url.startswith("/usr/"):
        return _path_to_file_url(url)
    return ""


def command_href(style: str) -> str:
    """The href of a menu row, "bw:<command>"; only the menu pages use the cmd: style."""
    return "bw:" + style[len("cmd:"):] if style.startswith("cmd:") else ""


def trim_url(url: str) -> str:
    """Drop the punctuation that ends the sentence, keep brackets the url balances itself."""
    while url:
        last = url[-1]
        if last in _URL_TAIL:
            url = url[:-1]
        elif last in _URL_PAIRS:
            if url.count(last) > url.count(_URL_PAIRS[last]):
                url = url[:-1]
            else:
                break
        else:
            break
    return url


def md_inline(text: str) -> list:
    """Inline markdown to (piece, style); style is '', 'b', 'i', 'code', 'dim' or 'link:<url>'."""
    out, pos = [], 0
    for m in MD_INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], ""))
        tok = m.group(0)
        if tok.startswith(("http://", "https://")):
            # A bare URL is a link like a markdown one; the url is its own label.
            url = trim_url(tok)
            if url:
                out.append((url, "link:" + url))
                if tok[len(url):]:
                    out.append((tok[len(url):], ""))
            else:
                out.append((tok, ""))
        elif ":\\" in tok or tok.startswith("~/") or tok.startswith("/home/") or tok.startswith("/usr/"):
            # A file path: show it, turn into a file:// link so a click opens the file.
            out.append((tok, "link:" + tok))
        elif tok[:2] in ("**", "__"):
            out.append((tok[2:-2], "b"))
        elif tok[0] == "`":
            out.append((tok[1:-1], "code"))
        elif tok[0] == "[":
            label, url = tok[1:-1].split("](", 1)
            out.append((label, "link:" + url))
            out.append((f" ({url_host(url)})", "dim"))
        else:
            out.append((tok[1:-1], "i"))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], ""))
    return out or [(text, "")]


def md_blocks(text: str) -> list:
    """Markdown to blocks of one logical line."""
    out, code, code_lines = [], False, []
    lines = text.split("\n")
    skip = 0
    for number, raw in enumerate(lines):
        if skip:
            skip -= 1
            continue
        line = raw.rstrip()
        # A table: a row with bars, then the line of dashes under the header, then the rows.
        if (not code and "|" in line and number + 1 < len(lines) and MD_TABLE_SEP_RE.match(lines[number + 1].strip())
                and "|" in lines[number + 1] + line):
            rows, follow = [table_cells(line)], number + 2
            while follow < len(lines) and "|" in lines[follow] and lines[follow].strip():
                rows.append(table_cells(lines[follow]))
                follow += 1
            out.append(table_block(rows))
            skip = follow - number - 1
            continue
        if line.strip().startswith("```"):
            if code:
                if code_lines:
                    out.append(code_block(code_lines))
                code = False
                code_lines = []
            else:
                code = True
                code_lines = []
            continue
        if code:
            if len(code_lines) < BUBBLE_CODE_LINES:
                code_lines.append(line or " ")
            elif code_lines[-1] != "…":
                code_lines.append("…")
            continue
        s = line.strip()
        if not s:
            out.append(plain_block("gap"))
            continue
        if MD_RULE_RE.match(s):
            out.append(plain_block("rule"))
            continue
        head = MD_HEAD_RE.match(s)
        if head:
            blk = text_block(MD_HEAD_SIZE.get(len(head.group(1)), 15), 0, "", False,
                             md_inline(head.group(2)))
            blk["head"] = True
            out.append(blk)
            continue
        bullet = MD_BULLET_RE.match(s)
        if bullet:
            out.append(text_block(BUBBLE_FONT, 12, "• ", False, md_inline(bullet.group(1))))
            continue
        num = MD_NUM_RE.match(s)
        if num:
            out.append(text_block(BUBBLE_FONT, 12, num.group(1) + ". ", False,
                                  md_inline(num.group(2))))
            continue
        quote = MD_QUOTE_RE.match(s)
        if quote:
            out.append(text_block(BUBBLE_FONT, 12, "▏ ", True, md_inline(quote.group(1))))
            continue
        out.append(text_block(BUBBLE_FONT, 0, "", False, md_inline(s)))
    if code and code_lines:
        out.append(code_block(code_lines))
    return out


def table_block(rows: list) -> dict:
    """A table: rows of cells (inline pieces), the first row the header. The layout makes the columns."""
    return {"kind": "table", "rows": rows, "size": BUBBLE_FONT, "indent": 0, "prefix": "", "grey": False,
            "chunks": []}


def text_block(size: int, indent: int, prefix: str, grey: bool, chunks: list) -> dict:
    return {"kind": "text", "size": size, "indent": indent, "prefix": prefix,
            "grey": grey, "head": False, "chunks": chunks}


def control_block(control: str, label: str, command: str, on: bool | None = None) -> dict:
    """A real form element in the bubble: a "toggle" with a state, a "slider" with a value (0 to 100), or a "button".
    The window draws the widget."""
    return {"kind": "control", "control": control, "label": label, "command": command, "on": on,
            "size": 15, "indent": 0, "prefix": "", "grey": False, "chunks": []}


def plain_block(kind: str) -> dict:
    return {"kind": kind, "size": 0, "indent": 0, "prefix": "", "grey": False, "chunks": []}


def status_block(text: str) -> dict:
    """A grey line about the link, not an answer from the bot."""
    return text_block(BUBBLE_FONT, 0, "", True, [(text, "i")])


def thought_blocks(text: str) -> list:
    """What the bot is thinking: its markdown, in the muted ink of a thought."""
    blocks = md_blocks(text.strip()) if text and text.strip() else []
    for block in blocks:
        block["grey"] = True
    return blocks


def code_block(lines: list) -> dict:
    """A whole code block at once: monospace, in a panel of its own."""
    return {"kind": "code", "lines": lines}


def block_text(blocks: list) -> str:
    """The plain text of blocks, to see whether anything new is in there."""
    out = []
    for block in blocks:
        if block.get("kind") == "code":
            out.append(" ".join(block.get("lines") or []))
            continue
        if block.get("kind") == "control":
            on = block.get("on")
            mark = "" if on is None else (f"{on}% " if block["control"] == "slider" else "☑ " if on else "☐ ")
            out.append(f"{mark}{block['label']}")
            continue
        if block.get("kind") == "table":
            out.append(" | ".join("".join(piece for piece, _style in cell) for row in block["rows"] for cell in row))
            continue
        if block.get("kind") != "text":
            continue
        words = [word for chunk, _style in block.get("chunks") or [] for word in chunk.split()]
        out.append(block.get("prefix", "") + " ".join(words))
    return "\n".join(out)


def plain_text(markdown: str) -> str:
    """The words of a message as you read them, without the markdown marks and without the link hosts."""
    out = []
    for block in md_blocks(markdown):
        kind = block.get("kind")
        if kind == "gap":
            out.append("")
        elif kind == "code":
            out.extend(block["lines"])
        elif kind == "text":
            words = "".join(chunk for chunk, style in block["chunks"] if style != "dim")
            out.append(block.get("prefix", "") + " ".join(words.split()))
    return "\n".join(out).strip("\n")


def role_panel(role: str, copy: str = "", queued: str = "", back: str = "") -> dict:
    """Start of a new panel: user is dark, bot sits on the white bubble. copy is the text its button copies;
    queued is the id of a message that has not been sent yet and can still be edited; back is the command
    an arrow panel runs, where it otherwise loads the message before."""
    return {"kind": "panel", "role": role, "copy": copy, "queued": queued, "back": back, "size": 0,
            "indent": 0, "prefix": "", "grey": False, "chunks": []}


def conversation_blocks(messages: list, bot_name: str, limit: int = 6,
                        max_chars: int = 800) -> list:
    """The last turns as panels. Several turns get a small role label each; a single message needs none."""
    turns, total = [], 0
    for msg in reversed(messages or []):
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        user = msg.get("role") == "user"
        turns.append(("user" if user else "bot", "You" if user else bot_name, text, msg.get("queued", "")))
        total += len(text)
        if len(turns) >= limit or total >= max_chars:
            break
    turns.reverse()
    blocks = []
    for role, label, text, queued in turns:
        blocks.append(role_panel(role, text, queued))
        if len(turns) > 1:
            blocks.append(text_block(11, 0, "", True, [(label, "b")]))
        blocks.extend(md_blocks(text))
    return blocks


def split_panels(blocks: list) -> list:
    """Blocks into panels. Without a panel marker it becomes a bot panel."""
    panels = []
    for block in blocks:
        if block.get("kind") == "panel":
            panels.append({"role": block.get("role", "bot"), "copy": block.get("copy", ""),
                           "queued": block.get("queued", ""), "back": block.get("back", ""), "blocks": []})
            continue
        if not panels:
            panels.append({"role": "bot", "blocks": []})
        panels[-1]["blocks"].append(block)
    return panels
