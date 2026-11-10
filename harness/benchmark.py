"""H2 harness benchmark: deterministic, scripted tasks with per-task metrics and a run summary.

Tasks
-----
A  short_answer        – scripted model replies with a known string.
B  tool_read            – scripted tool call reads a file containing a known token.
C  topic_switch_recall  – two user facts in one store, then ask for one back.
D  compact_without_summary – long thread without a summary: the unique fact is in context.
E  compact_with_summary  – same seed but a summary preserves the unique fact.

Run
---
    python -m harness.benchmark --json
    python -m harness.benchmark --out report.json

The default mode is "scripted": no live model, no network, no API keys.
"""

import argparse
import asyncio
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

from harness.agent.agent import LeanAgent
from harness.agent.context import build, estimate
from harness.agent.store import SessionStore
from harness.agent.tools import Tools


# ── Scripted model ─────────────────────────────────────────────────────

class ScriptModel:
    """Yields scripted stream events. A callable script may inspect a stop event itself."""

    def __init__(self, scripts=(), usage=None):
        self.model = "script"
        self.context_size = 4096
        self.scripts = list(scripts)
        self.usage = usage or {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 2},
        }
        self.ready_calls = 0
        self.reply = None

    def ready(self):
        self.ready_calls += 1

    def stream(self, messages, tools=None, stop=None, opened=None):
        step = self.scripts.pop(0)
        if opened is not None and self.reply is not None:
            opened(self.reply)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            yield from step(stop)
            return
        for event in step:
            if stop is not None and stop.is_set():
                return
            yield event

    def complete(self, messages):
        if isinstance(self.scripts[-1], BaseException):
            raise self.scripts.pop()
        return ""


# ── Helpers ────────────────────────────────────────────────────────────

class _Block:
    """A minimal prompt block: LeanAgent reads ``.text`` from each item."""

    def __init__(self, text=""):
        self.text = text


async def _run_turn(agent, session_id, text):
    """Ask the agent one prompt and return (answer_text, path_steps)."""
    result = await agent.prompt(session_id, [_Block(text)])
    store = agent.stores[session_id]
    bot_messages = [m for m in store.messages() if m["role"] == "bot"]
    answer = bot_messages[-1]["text"] if bot_messages else ""
    tool_count = sum(1 for m in store.messages() if m["role"] == "tool")
    path_steps = 1 + tool_count  # one model step + tool rounds
    return answer, path_steps


async def _run_async_task(name, runner):
    """Run an async task and return a metric dict."""
    start = time.monotonic()
    try:
        result = await runner()
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return _make_result(name, ok=False, answer="", path_steps=0,
                            reason=str(exc)[:200], elapsed=elapsed)
    elapsed = (time.monotonic() - start) * 1000
    ok = result.get("ok", False)
    answer = result.get("answer", "")
    path_steps = result.get("path_steps", 0)
    reason = result.get("reason", "") or ("check did not pass" if not ok else "")
    return _make_result(name, ok=ok, answer=answer, path_steps=path_steps,
                        reason=reason, elapsed=elapsed)


def _run_sync_task(name, runner):
    """Run a sync task and return a metric dict."""
    start = time.monotonic()
    try:
        result = runner()
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return _make_result(name, ok=False, answer="", path_steps=0,
                            reason=str(exc)[:200], elapsed=elapsed)
    elapsed = (time.monotonic() - start) * 1000
    ok = result.get("ok", False)
    answer = result.get("answer", "")
    path_steps = result.get("path_steps", 0)
    reason = result.get("reason", "") or ("check did not pass" if not ok else "")
    return _make_result(name, ok=ok, answer=answer, path_steps=path_steps,
                        reason=reason, elapsed=elapsed)


def _make_result(name, ok, answer, path_steps, reason, elapsed):
    """Build one task's metric dict."""
    return {
        "id": name,
        "ok": ok,
        "first_ms": 0,
        "total_ms": round(elapsed),
        "input_tokens": 0,
        "output_tokens": estimate(answer) if answer else 0,
        "cached_tokens": 0,
        "steps": 1 if ok else 0,
        "path_steps": path_steps,
        "reason": reason,
    }


async def _run_task(name, runner, is_async=True):
    """Dispatch to the right runner type."""
    if is_async:
        return await _run_async_task(name, runner)
    else:
        return _run_sync_task(name, runner)


# ── Task runners ───────────────────────────────────────────────────────

async def task_short_answer():
    """A: scripted model returns a known string."""
    folder = tempfile.mkdtemp()
    try:
        model = ScriptModel([
            [("thought", "ok"), ("text", "The capital of France is Paris."),
             ("usage", {"prompt_tokens": 10, "completion_tokens": 8,
                         "prompt_tokens_details": {"cached_tokens": 2}})]
        ])
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        answer, path_steps = await _run_turn(agent, session,
                                              "What is the capital of France?")
        ok = "Paris" in answer
        return {"ok": ok, "answer": answer, "path_steps": path_steps}
    finally:
        shutil.rmtree(folder, True)


async def task_tool_read():
    """B: model calls read_file on a temp file containing CORAL-TREE-19."""
    folder = tempfile.mkdtemp()
    try:
        target = os.path.join(folder, 'data.txt')
        with open(target, 'w') as fh:
            fh.write('CORAL-TREE-19\nSome data.\n')

        def tool_step(stop):
            """First agent step: request the read_file tool."""
            yield ("tool_calls", [{"id": "t1", "function": {"name": "read_file",
                             "arguments": json.dumps({"path": target})}}])
            yield ("usage", {"prompt_tokens": 20, "completion_tokens": 5,
                              "prompt_tokens_details": {"cached_tokens": 5}})

        def text_step(stop):
            """Second agent step: the answer after the tool returns."""
            yield ("text", "The file says CORAL-TREE-19.")
            yield ("usage", {"prompt_tokens": 25, "completion_tokens": 8,
                              "prompt_tokens_details": {"cached_tokens": 6}})

        model = ScriptModel([tool_step, text_step])
        model.reply = type("Reply", (), {"close": lambda self: None})()
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        answer, path_steps = await _run_turn(agent, session,
                                              "Read data.txt and tell me the code.")
        ok = "CORAL-TREE-19" in answer
        return {"ok": ok, "answer": answer, "path_steps": path_steps}
    finally:
        shutil.rmtree(folder, True)


async def task_topic_switch_recall():
    """C: two user facts, then ask for the first one back.

    The task checks that the mascot name still appears in the built context
    (documenting that short threads keep verbatim turns).
    """
    folder = tempfile.mkdtemp()
    try:
        store = SessionStore(folder)
        store.add("user", "My mascot name is Coral.")
        store.add("user", "How do I make scrambled eggs?")
        model = ScriptModel([
            [("text", "I remember your mascot name is Coral."),
             ("usage", {"prompt_tokens": 15, "completion_tokens": 6,
                         "prompt_tokens_details": {"cached_tokens": 3}})]
        ])
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        agent.stores[session] = store
        answer, path_steps = await _run_turn(agent, session,
                                              "What is my mascot name?")
        context = build(store, "Bench")
        context_text = " ".join(m.get("content", "") for m in context)
        ok = "Coral" in answer and "Coral" in context_text
        return {"ok": ok, "answer": answer, "path_steps": path_steps}
    finally:
        shutil.rmtree(folder, True)


def task_compact_without_summary():
    """D: long thread, no summary, the unique fact should still appear in context.

    H4 fixed this: older turns are now kept as a BACKGROUND extract when no summary
    exists yet, so nothing vanishes between turns.
    """
    folder = tempfile.mkdtemp()
    try:
        store = SessionStore(folder)
        store.add("user", "Remember: SILVER-ORCHID-7 is the special token.")
        for i in range(50):
            store.add("user", f"Filler question {i}?")
            store.add("bot", f"Filler answer {i}.")
        # No summary is set.
        context = build(store, "Bench")
        context_text = " ".join(m.get("content", "") for m in context)
        ok = "SILVER-ORCHID-7" in context_text
        return {"ok": ok, "answer": "", "path_steps": 0,
                "reason": "" if ok else "older turns dropped before summary exists"}
    finally:
        shutil.rmtree(folder, True)


def task_compact_with_summary():
    """E: same seed, but a summary preserves the unique fact.

    ok iff context.build contains the fact (in summary or messages).
    """
    folder = tempfile.mkdtemp()
    try:
        store = SessionStore(folder)
        store.add("user", "Remember: SILVER-ORCHID-7 is the special token.")
        for i in range(50):
            store.add("user", f"Filler question {i}?")
            store.add("bot", f"Filler answer {i}.")
        store.set_summary("The user said SILVER-ORCHID-7 is the special token.")
        context = build(store, "Bench")
        context_text = " ".join(m.get("content", "") for m in context)
        ok = "SILVER-ORCHID-7" in context_text
        return {"ok": ok, "answer": "", "path_steps": 0,
                "reason": "" if ok else "fact dropped even with summary"}
    finally:
        shutil.rmtree(folder, True)


# ── Summary computation ────────────────────────────────────────────────

def _median(values):
    """Return the median of a list of numbers, or 0 when empty."""
    try:
        return round(statistics.median(values))
    except statistics.StatisticsError:
        return 0


def _summary(tasks):
    """Build a run summary from the task results."""
    passed = [t for t in tasks if t["ok"]]
    failed = [t for t in tasks if not t["ok"]]
    return {
        "n": len(tasks),
        "passed": len(passed),
        "failed": len(failed),
        "median_first_ms": _median(t["first_ms"] for t in tasks),
        "median_total_ms": _median(t["total_ms"] for t in tasks),
        "median_input_tokens": _median(t["input_tokens"] for t in tasks),
        "median_output_tokens": _median(t["output_tokens"] for t in tasks),
        "median_path_steps": _median(t["path_steps"] for t in tasks),
        "cost": 0,
    }


# ── Task registry ──────────────────────────────────────────────────────

# Each entry is (name, runner, is_async).
TASKS = [
    ("short_answer", task_short_answer, True),
    ("tool_read", task_tool_read, True),
    ("topic_switch_recall", task_topic_switch_recall, True),
    ("compact_without_summary", task_compact_without_summary, False),
    ("compact_with_summary", task_compact_with_summary, False),
]


async def run_all():
    """Run every task in the suite and return the full report dict."""
    results = []
    for name, runner, is_async in TASKS:
        result = await _run_task(name, runner, is_async)
        results.append(result)
    return {"suite": "h2", "mode": "scripted", "tasks": results, "summary": _summary(results)}


# ── CLI ────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="H2 harness benchmark")
    parser.add_argument("--out", metavar="PATH", help="Write JSON report to file")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    parser.add_argument("--live", action="store_true",
                        help="Stub flag: live benchmark mode is not yet implemented")
    args = parser.parse_args(argv)

    if args.live:
        print("Live benchmark mode is a stub. --live is not implemented yet.",
              file=sys.stderr)

    report = asyncio.run(run_all())

    if args.json:
        print(json.dumps(report, indent=2))

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2)
        print(f"Report written to {args.out}", file=sys.stderr)

    return report


if __name__ == "__main__":
    main()
