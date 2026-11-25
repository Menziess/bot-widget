"""A turn of the agent as data: what one model step produced, and the checks that decide whether the turn may end.

The loop in agent.py only moves messages. What a step means is decided here:

- A step with tool calls is progress. Its text is commentary and never the answer.
- A step without tool calls is the end of the turn, unless a guard sends the model back to work.
- A guard reads the facts of the turn and answers with one nudge or nothing. Each guard speaks at most `limit` times
  per turn, so a check that can never be satisfied cannot hold a turn forever.
- A request or a claim is an obligation, and only a call of the right tool discharges it. One table says which.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import NamedTuple

from harness import RESUME_PROMPT
from harness.agent.tools import TOOL_OUTPUT

# Words that own up to a failure: a closing message with one of them needs no second round.
FAILURE_WORDS = re.compile(r"\b(fail|failed|error|unable|cannot|can't|could not|couldn't|not found|mislukt|"
                           r"niet gelukt|niet gevonden|kon niet|lukt niet|fout|bestaat niet)\b", re.IGNORECASE)
# Closing words that promise work, or claim it was done. One list for every tool.
PROMISE = re.compile(r"\b(ik ga|ik zal|ik probeer|let me|i'll|i will|i'm going to|i am going to)\b")
DONE_CLAIM = re.compile(r"\b(done|klaar|gedaan|geschreven|uitgevoerd|aangemaakt|written|created|executed|ran)\b")
# A claim that something was written needs a tool in this turn that can write; the others need any tool.
WRITE_CLAIM = re.compile(r"\b(wrote|written|saved|created|now contains|geschreven|opgeslagen|aangemaakt|bevat nu)\b")
WRITERS = {"write_file", "edit", "shell", "delete_file"}
# A place on this machine: a home path, a drive path, or an absolute path with at least two parts (`/demo` is a command).
PATH = re.compile(r"(?<![\w/\\.])(?:~|[A-Za-z]:)?(?:[\\/][\w.\-~]+){2,}|(?<![\w/\\.])~(?:[\\/][\w.\-~]+)+")

# The user asking for the desktop's applications, in either phrase, in any order.
ACCESSIBILITY_ASK = re.compile(r"^(?=.*accessibility)(?=.*\btool\b).*|^(?=.*which applications)(?=.*\bopen\b).*",
                               re.IGNORECASE | re.DOTALL)
# The user asking for something to be changed.
CHANGE_ASK = re.compile(r"\b(write|create|change|fix|repair|delete|remove|schrijf|maak|wijzig|verwijder|repareer)\b",
                        re.IGNORECASE)
# A snake_case word is a tool name; `edit` or `search` are also plain words.
TOOL_NAME = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")

A11Y_NUDGE = ("Call the accessibility tool now, before you answer. Leave query empty so the result lists "
              "application names. Do not invent a list.")
FAILED_NUDGE = ("A tool call just failed and your last message does not say so. Either call it again with a fix, or "
                "say plainly that it failed. Do not answer from earlier messages as if it had worked.")
GROUNDING_NUDGE = ("The user named {what} on this machine and this turn has not looked at anything. Look with a tool "
                   "before you answer. Do not answer from memory.")
NAMED_NUDGE = ("The user asked you to use {what}, and this turn did not call it. Call it now, before you answer. "
               "Do not answer from memory.")
CHANGE_NUDGE = ("The user asked you to {what} something, and no tool that can change anything ran in this turn. Do it "
                "now with a tool, or say plainly that you did not.")
CLAIM_NUDGE = ("You ended on a promise, or on a claim of work that this turn has no tool call for. Do it now "
               "with a tool call. If no tool can do it, say so plainly and do not invent a result.")
SKILL_NUDGE = ("That message ended without a tool call. If the skill still has steps, do the next one now with a tool "
               "call. If you are finished call done, if you wait for the user's answer call wait_for_user, and if the "
               "user's message has nothing to do with this skill call not_for_me.")


@dataclass
class Step:
    """One request to the model, read to its end."""

    chunks: list = field(default_factory=list)  # the text as it came, piece by piece
    calls: list = field(default_factory=list)
    finish: str = ""
    thought_chars: int = 0
    cancelled: bool = False

    @property
    def text(self) -> str:
        return "".join(self.chunks)

    @property
    def tool_names(self) -> set[str]:
        return {(call.get("function") or {}).get("name") or "" for call in self.calls}


@dataclass
class Turn:
    """What the guards may look at."""

    user_text: str
    offered: set[str]
    skill_on: bool = False
    called: set[str] = field(default_factory=set)
    tool_failed: bool = False  # the step before this one called tools, and every one failed


def call_key(call: dict) -> str:
    """The same call in the same words: tool name plus sorted arguments."""
    name = (call.get("function") or {}).get("name") or ""
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        return json.dumps({"name": name, "args": json.loads(raw)}, sort_keys=True)
    except json.JSONDecodeError:
        return raw


class Nudge(NamedTuple):
    text: str  # what the model is told
    keeps_text: bool = False  # the message it answers is still a message for the user; otherwise a guess or a claim
    tool: str = ""  # the one tool the next request must call, when a single tool is what the guard asked for


class Guard:
    """A check on a step that would end the turn. review() returns a nudge for the model, or None."""

    name = ""
    limit = 1

    def review(self, turn: Turn, step: Step) -> Nudge | None:
        raise NotImplementedError


class FailedToolGuard(Guard):
    """The last tools all failed and the closing words do not say so."""

    name = "failed_tool"

    def review(self, turn, step):
        said = step.text.strip()
        return Nudge(FAILED_NUDGE) if turn.tool_failed and said and not FAILURE_WORDS.search(said) else None


class Obligation(Guard):
    """Something asked or claimed that only a tool call can back.

    `where` is the text it reads: what the user wrote, or how the step closes. `needs` is the tools that discharge it:
    a set (any of them), None (any tool at all), an empty set (a call right now, a past one does not count), or
    "match" (the tool the pattern matched). Never in a skill, and never on a closing question."""

    def __init__(self, name, where, pattern, needs, nudge):
        self.name, self.where, self.pattern, self.needs, self.nudge = name, where, pattern, needs, nudge

    def review(self, turn, step):
        said = step.text.strip()
        if turn.skill_on or said.endswith("?"):
            return None
        if self.where == "user":
            if turn.user_text.startswith((TOOL_OUTPUT, RESUME_PROMPT)):  # a finished job is not a question
                return None
            text = turn.user_text
        else:
            text = said[-200:].lower()
        hits = [hit.group(0) for hit in self.pattern.finditer(text)]
        if self.needs == "match":
            hits = sorted({hit for hit in hits if hit in turn.offered and hit not in turn.called})
            if not hits:
                return None
            return Nudge(self.nudge.format(what=", ".join(hits)), tool=hits[0] if len(hits) == 1 else "")
        if not hits:
            return None
        if self.needs is None:
            met = bool(turn.called)
        elif self.needs and not self.needs & turn.offered:
            return None  # the tool is not there to ask for
        else:
            met = bool(turn.called & self.needs)
        if met:
            return None
        return Nudge(self.nudge.format(what=hits[0]), tool=next(iter(self.needs)) if self.needs and len(self.needs) == 1 else "")


OBLIGATIONS = (
    Obligation("accessibility", "user", ACCESSIBILITY_ASK, {"accessibility"}, A11Y_NUDGE),
    Obligation("named_tool", "user", TOOL_NAME, "match", NAMED_NUDGE),
    Obligation("grounding", "user", PATH, None, GROUNDING_NUDGE),
    Obligation("change", "user", CHANGE_ASK, WRITERS, CHANGE_NUDGE),
    Obligation("promise", "closing", PROMISE, frozenset(), CLAIM_NUDGE),
    Obligation("done", "closing", DONE_CLAIM, None, CLAIM_NUDGE),
    Obligation("write", "closing", WRITE_CLAIM, WRITERS, CLAIM_NUDGE),
)


class SkillGuard(Guard):
    """A skill is over when it says so with a tool: a message that only talks gets sent back."""

    name = "skill"
    limit = 2

    def review(self, turn, step):
        # It asks whether the skill is over; what was said still counts.
        return Nudge(SKILL_NUDGE, keeps_text=True) if turn.skill_on else None


class Governor:
    """Runs the guards in order, each within its own limit. The first nudge wins."""

    def __init__(self, guards=None):
        self.guards = guards or (FailedToolGuard(), *OBLIGATIONS, SkillGuard())
        self.used = Counter()

    def review(self, turn: Turn, step: Step) -> Nudge | None:
        for guard in self.guards:
            if self.used[guard.name] >= guard.limit:
                continue
            nudge = guard.review(turn, step)
            if nudge:
                self.used[guard.name] += 1
                return nudge
        return None

    @property
    def nudged(self) -> bool:
        return bool(sum(self.used.values()))


class LoopDetector:
    """The same step, tool calls and arguments alike, this many times in a row. 0 turns it off.

    One entry per step: the same call three times inside one answer is one step, not three in a row."""

    def __init__(self, repeats: int):
        self.repeats = repeats
        self.recent: list[str] = []

    def stuck(self, step: Step) -> str:
        """The tool the loop is on, or empty."""
        self.recent.append("|".join(sorted({call_key(call) for call in step.calls})))
        if self.repeats > 1 and len(self.recent) >= self.repeats and len(set(self.recent[-self.repeats:])) == 1:
            return (step.calls[-1].get("function") or {}).get("name") or "a tool"
        return ""
