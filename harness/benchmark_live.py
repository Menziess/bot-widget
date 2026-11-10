"""Live H2 benchmark: the same five tasks, measured against a real model.

Opt-in via ``python -m harness.benchmark --live``. Scripted tests never import
this path in a way that opens a network connection: they call ``run_all_live``
with a injected model, or the CLI is pointed at a test server.

The API key is read from ``HARNESS_MODEL_API_KEY`` or, if set,
``HARNESS_MODEL_KEY_FILE``. It is never written to the report, stdout, or logs.
The default model comes from ``from_environment`` (same as the agent).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
from harness.agent.tools import Tools
from harness.benchmark import _run_turn


def _cleanup(folder, agent=None):
    """Close stores before deleting the temp folder so a background summary cannot race rmtree."""
    if agent is not None:
        for store in list(getattr(agent, "stores", {}).values()):
            try:
                store.close()
            except Exception:
                pass
    shutil.rmtree(folder, True)


def _load_key() -> str:
    """In-memory only. Empty string if no key is configured."""
    key = (os.environ.get("HARNESS_MODEL_API_KEY") or "").strip()
    if key:
        return key
    path = (os.environ.get("HARNESS_MODEL_KEY_FILE") or "").strip()
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text().strip()
    except OSError:
        raise SystemExit("cannot read HARNESS_MODEL_KEY_FILE") from None


def _model_from_env():
    from harness.agent.models import from_environment

    env = dict(os.environ)
    env["HARNESS_MODEL_API_KEY"] = _load_key()
    return from_environment(env)


def _usage_of(folder: str) -> dict:
    path = os.path.join(folder, "usage.jsonl")
    if not os.path.isfile(path):
        return {}
    last = ""
    with open(path) as fh:
        for line in fh:
            if line.strip():
                last = line
    if not last:
        return {}
    try:
        return json.loads(last)
    except json.JSONDecodeError:
        return {}


def _metrics(folder: str, ok: bool, answer: str, path_steps: int, reason: str = "") -> dict:
    usage = _usage_of(folder)
    return {
        "ok": ok,
        "answer": answer,
        "path_steps": path_steps,
        "reason": reason if not ok else "",
        "first_ms": int(usage.get("first_ms") or 0),
        "steps": int(usage.get("steps") or (1 if ok else 0)),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cached_tokens": int(usage.get("cached_tokens") or 0),
    }


def _safe_model_info(model) -> dict:
    """Host and model name only — never a key."""
    base = getattr(model, "base_url", "") or ""
    host = base
    if "://" in base:
        host = base.split("://", 1)[1]
    host = host.split("/")[0]
    return {"model": getattr(model, "model", "") or "", "host": host,
            "context_size": int(getattr(model, "context_size", 0) or 0)}


async def _live_short_answer(model) -> dict:
    folder = tempfile.mkdtemp()
    try:
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        answer, path_steps = await _run_turn(
            agent, session,
            "Reply with exactly the single word PONG and nothing else.")
        ok = "PONG" in (answer or "").upper()
        return _metrics(folder, ok, answer, path_steps,
                        "" if ok else "expected the word PONG")
    finally:
        _cleanup(folder, locals().get("agent"))


async def _live_tool_read(model) -> dict:
    folder = tempfile.mkdtemp()
    try:
        target = os.path.join(folder, "data.txt")
        with open(target, "w") as fh:
            fh.write("CORAL-TREE-19\nSome data.\n")
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        answer, path_steps = await _run_turn(
            agent, session,
            "Use your tools to read data.txt in the workspace and tell me the exact code written there.")
        ok = "CORAL-TREE-19" in (answer or "")
        return _metrics(folder, ok, answer, path_steps,
                        "" if ok else "expected CORAL-TREE-19 in the answer")
    finally:
        _cleanup(folder, locals().get("agent"))


async def _live_topic_switch_recall(model) -> dict:
    folder = tempfile.mkdtemp()
    try:
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        await _run_turn(agent, session, "Please remember: my mascot name is Coral.")
        await _run_turn(agent, session, "Quick cooking question: how many minutes do you boil spaghetti? One sentence.")
        answer, path_steps = await _run_turn(agent, session, "What is my mascot name? Answer with the name only.")
        ok = "Coral" in (answer or "")
        return _metrics(folder, ok, answer, path_steps,
                        "" if ok else "expected Coral in the answer")
    finally:
        _cleanup(folder, locals().get("agent"))


def _seed_long_thread(folder: str, summary: str | None = None) -> SessionStore:
    store = SessionStore(folder)
    store.add("user", "Remember: SILVER-ORCHID-7 is the special token.")
    store.add("bot", "I will remember SILVER-ORCHID-7.")
    for i in range(50):
        store.add("user", f"Filler question {i}?")
        store.add("bot", f"Filler answer {i}.")
    if summary:
        store.set_summary(summary)
    return store


async def _live_compact_without_summary(model) -> dict:
    folder = tempfile.mkdtemp()
    try:
        store = _seed_long_thread(folder)
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        agent.stores[session] = store
        answer, path_steps = await _run_turn(
            agent, session,
            "What is the special token I asked you to remember? Answer with the token only.")
        ok = "SILVER-ORCHID-7" in (answer or "")
        return _metrics(folder, ok, answer, path_steps,
                        "" if ok else "special token missing from the answer")
    finally:
        _cleanup(folder, locals().get("agent"))


async def _live_compact_with_summary(model) -> dict:
    folder = tempfile.mkdtemp()
    try:
        store = _seed_long_thread(
            folder, summary="The user said SILVER-ORCHID-7 is the special token.")
        agent = LeanAgent("Bench", model, folder=folder, tools=Tools("", workspace=folder))
        session = (await agent.new_session(".")).session_id
        agent.stores[session] = store
        answer, path_steps = await _run_turn(
            agent, session,
            "What is the special token I asked you to remember? Answer with the token only.")
        ok = "SILVER-ORCHID-7" in (answer or "")
        return _metrics(folder, ok, answer, path_steps,
                        "" if ok else "special token missing from the answer")
    finally:
        _cleanup(folder, locals().get("agent"))


LIVE_TASKS = [
    ("short_answer", _live_short_answer),
    ("tool_read", _live_tool_read),
    ("topic_switch_recall", _live_topic_switch_recall),
    ("compact_without_summary", _live_compact_without_summary),
    ("compact_with_summary", _live_compact_with_summary),
]


async def run_all_live(model=None):
    """Run the five H2 tasks against *model* (or the env-configured one)."""
    from harness.benchmark import _run_async_task, _summary

    owned = model is None
    if owned:
        model = _model_from_env()
        if hasattr(model, "ready"):
            model.ready()
    results = []
    try:
        for name, runner in LIVE_TASKS:
            results.append(await _run_async_task(name, lambda r=runner: r(model)))
    finally:
        close = getattr(model, "close", None) if owned else None
        if callable(close):
            close()
    info = _safe_model_info(model)
    return {"suite": "h2", "mode": "live", "model": info,
            "tasks": results, "summary": _summary(results)}
