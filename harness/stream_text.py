"""The one stage every answer passes through before the bubble.

Streamed chunks and a final copy of the answer, from the lean agent and from an ACP
backend, both go through `fold_chunk`. It keeps one copy of text that was sent again,
and it drops a trailing internal tool name. A skill nudge whose only tool is
`not_for_me` drops the whole reply of that step (`silent_nudge`).

`BOTWIDGET_REPLAY_LOG` appends the raw events to a file outside this checkout.
`scripts/replay_capture` turns that log into a fixture.
"""

import functools
import json
import os
import re

# A skill ending the model wrote as words. The bubble's italic markdown eats `_for_`, so
# not_for_me twice, glued, reads as notformenotforme. wait_for_user is the same kind of leak.
# A name cut short (not_for) is the same leak.
_LEAK = re.compile(
    r"(?:not_for(?:_me)?|NOT_FOR(?:_ME)?|notforme|wait_for(?:_user)?|WAIT_FOR(?:_USER)?|waitforuser)+$"
)


# A run of leaked names is a few dozen characters at most; only the end of a text is ever looked at.
_WINDOW = 256
_EDGE = 32  # longer than any one leaked name


@functools.lru_cache(maxsize=8)
def _glued(endings: tuple) -> re.Pattern:
    names = "|".join(re.escape(name) for name in sorted(endings, key=len, reverse=True))
    return re.compile(rf"(?<=\S)(?:{names}|{_LEAK.pattern[:-1]})+$")


def _tail_cut(pattern: re.Pattern, text: str) -> str:
    """The text without the run that `pattern` (anchored at the end) finds. Only the end can match, so only the end
    is looked at: the whole text on every piece of a streamed answer made a long answer quadratic."""
    while True:
        start = max(0, len(text) - _WINDOW - 1)  # one character more, for a pattern that looks behind
        found = pattern.search(text[start:])
        if not found:
            return text
        text = text[:start + found.start()] + text[start + found.end():]  # `$` also matches before a final newline
        if found.start() > _EDGE or start == 0:
            return text  # the run began well inside the window; one that began at its edge goes on in the next round


def _strip_leak(text: str, endings) -> str:
    """The names a running skill ends with (done, ...) are plain words, so they only count as a leak glued to the text
    before them, and only while a skill runs."""
    text = _tail_cut(_LEAK, text)
    return _tail_cut(_glued(tuple(sorted(endings))), text) if endings else text


def silent_nudge(tool_names: set[str] | None) -> bool:
    """A skill nudge that only called not_for_me has nothing to show."""
    return tool_names == {"not_for_me"}


def fold_chunk(current: str, chunk: str, tool_names: set[str] | None = None, endings=(),
               new_step: bool = False) -> str:
    """The bubble text after one more piece.

    A piece that already starts with the answer is a longer copy and replaces it.
    A piece equal to the answer was sent again and is ignored.
    A trailing tool-name echo is not part of the answer; `endings` are the tools a running skill ends with.
    `new_step` marks the first piece of another model call, which starts a new paragraph.
    A silent skill nudge (`tool_names` is exactly not_for_me) leaves the answer as it was.
    """
    if silent_nudge(tool_names) or not chunk:
        return current
    if not current or chunk.startswith(current):
        merged = chunk
    else:
        # The first words of another model call are another paragraph: "Ok.Next" is two sentences glued.
        glue = "\n\n" if new_step and not current[-1].isspace() and not chunk[0].isspace() else ""
        merged = current + glue + chunk
    cleaned = _strip_leak(merged, endings)
    # A step that was only a leaked name leaves no paragraph break behind.
    return cleaned.rstrip() if cleaned != merged else cleaned


def play(steps: list, endings=()) -> str:
    """Bubble text for one captured turn. `steps` is the raw events each model call emitted.

    A step that contains a `nudge` event is a skill nudge. Its text is kept only when
    that step called something other than not_for_me. `final` is the whole answer sent
    again after the chunks, and is folded like any other piece.
    """
    shown = ""
    for step in steps:
        names = {event["name"] for event in step if event.get("kind") == "tool" and event.get("name")}
        nudge = any(event.get("kind") == "nudge" for event in step)
        opened = False
        for event in step:
            if event.get("kind") not in ("text", "final"):
                continue
            shown = fold_chunk(shown, event.get("text") or "", names if nudge else None, endings,
                               new_step=not opened and event.get("kind") == "text")
            opened = opened or event.get("kind") == "text"
    return shown


def _checkout() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def outside_checkout(path: str) -> bool:
    """A real transcript is not written inside the checkout, so it cannot be committed by mistake."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    root = _checkout()
    return abs_path != root and not abs_path.startswith(root + os.sep)


def note_raw(event: dict) -> None:
    """Append one raw backend event when BOTWIDGET_REPLAY_LOG points outside the checkout."""
    path = os.environ.get("BOTWIDGET_REPLAY_LOG", "").strip()
    if not path or not outside_checkout(path):
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(os.path.expanduser(path))), exist_ok=True)
        with open(os.path.expanduser(path), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        return  # the answer is worth more than a debug line


def steps_from_log(text: str) -> list:
    """Events from a replay log, a fixture, or a JSON list.

    Lines tagged source=model win when both the agent and the widget wrote the same file.
    A `step` line starts a new model call.
    """
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "{[":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            if isinstance(data.get("steps"), list):
                return data["steps"]
            events = data.get("events")
            return [events] if isinstance(events, list) else []
        if isinstance(data, list):
            return [data]
    rows = []
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    sources = {row.get("source") for row in rows if row.get("source")}
    prefer = "model" if "model" in sources else None
    steps, current = [], []
    for row in rows:
        if prefer and row.get("source") not in (None, prefer):
            continue
        if row.get("kind") == "step":
            if current:
                steps.append(current)
            current = []
            continue
        event = {"kind": row.get("kind")}
        if "text" in row:
            event["text"] = row["text"]
        if "name" in row:
            event["name"] = row["name"]
        current.append(event)
    if current:
        steps.append(current)
    return steps
