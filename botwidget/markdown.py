"""Markdown to blocks and panels; pure text, no toolkit."""

import re
from urllib.parse import urlparse

from botwidget.theme import BUBBLE_CODE_LINES, BUBBLE_FONT, MD_HEAD_SIZE

MD_INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|__.+?__|`[^`]+?`|\*[^*\s][^*]*?\*|_[^_\s][^_]*?_"
    r"|\[[^\]]+?\]\((?:[^()\s]|\([^()\s]*\))*\)"
    r"|https?://[^\s<>\"'`]+)"
)
_URL_PAIRS = {")": "(", "]": "[", "}": "{"}
_URL_TAIL = ".,;:!?"
MD_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
MD_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
MD_NUM_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
MD_QUOTE_RE = re.compile(r"^>\s?(.*)$")
MD_RULE_RE = re.compile(r"^([-*_]\s*){3,}$")


def url_host(url: str) -> str:
    """Only the host of a link, shown dim after the label."""
    try:
        host = urlparse(url).netloc or url
    except ValueError:
        host = url
    return host.split("@")[-1].split(":")[0] or url


def anchor_url(style: str) -> str:
    """The href of a link piece; empty for anything that is not an http(s) link."""
    if not style.startswith("link:"):
        return ""
    url = style[len("link:"):]
    return url if url.startswith(("http://", "https://")) else ""


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
    for raw in text.split("\n"):
        line = raw.rstrip()
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


def text_block(size: int, indent: int, prefix: str, grey: bool, chunks: list) -> dict:
    return {"kind": "text", "size": size, "indent": indent, "prefix": prefix,
            "grey": grey, "head": False, "chunks": chunks}


def plain_block(kind: str) -> dict:
    return {"kind": kind, "size": 0, "indent": 0, "prefix": "", "grey": False, "chunks": []}


def status_block(text: str) -> dict:
    """A grey line about the link, not an answer from the bot."""
    return text_block(BUBBLE_FONT, 0, "", True, [(text, "i")])


ACTIVITY_CHARS = 42


def activity_line(text: str) -> str:
    """One short line of what the bot is doing; never more than that."""
    line = " ".join((text or "").split("\n", 1)[0].split())
    return line if len(line) <= ACTIVITY_CHARS else line[:ACTIVITY_CHARS - 1].rstrip() + "…"


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
        if block.get("kind") != "text":
            continue
        words = [word for chunk, _style in block.get("chunks") or [] for word in chunk.split()]
        out.append(block.get("prefix", "") + " ".join(words))
    return "\n".join(out)


def role_panel(role: str, copy: str = "") -> dict:
    """Start of a new panel: user is dark, bot sits on the white bubble. copy is the text its button copies."""
    return {"kind": "panel", "role": role, "copy": copy, "size": 0, "indent": 0,
            "prefix": "", "grey": False, "chunks": []}


def conversation_blocks(messages: list, bot_name: str, limit: int = 6,
                        max_chars: int = 800) -> list:
    """The last turns as panels: per turn a small role label and the markdown."""
    turns, total = [], 0
    for msg in reversed(messages or []):
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        user = msg.get("role") == "user"
        turns.append(("user" if user else "bot", "You" if user else bot_name, text))
        total += len(text)
        if len(turns) >= limit or total >= max_chars:
            break
    turns.reverse()
    blocks = []
    for role, label, text in turns:
        blocks.append(role_panel(role, text))
        blocks.append(text_block(11, 0, "", True, [(label, "b")]))
        blocks.extend(md_blocks(text))
    return blocks


def split_panels(blocks: list) -> list:
    """Blocks into panels. Without a panel marker it becomes a bot panel."""
    panels = []
    for block in blocks:
        if block.get("kind") == "panel":
            panels.append({"role": block.get("role", "bot"), "copy": block.get("copy", ""), "blocks": []})
            continue
        if not panels:
            panels.append({"role": "bot", "blocks": []})
        panels[-1]["blocks"].append(block)
    return panels
