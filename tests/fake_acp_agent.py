#!/usr/bin/env python3
"""A stand-in ACP agent for tests: real protocol on stdio, no model, no network.

Written by hand against the wire format rather than with the same SDK the client uses, so
that a client bug cannot cancel out an agent bug.

Scenarios are picked from the prompt text.

    hello            a thought, then an answer in two chunks
    ask              asks permission first; answers "allow" or "deny" by what came back
    slow             streams a chunk a second until it is cancelled
    fail             ends the turn with stopReason "refusal"
    grow             streams 40 chunks, to watch a long answer arrive
    replay           answers "restored" for session/load, to prove a session survives a restart

Every request and answer is appended to the file named by FAKE_ACP_LOG, one JSON object per
line, so a test can prove what crossed the wire.
"""

import json
import os
import sys
import time

LOG = os.environ.get("FAKE_ACP_LOG", "")
CANCEL = set()


def log(direction: str, message: dict) -> None:
    if LOG:
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"t": round(time.time(), 6), "dir": direction, **message}) + "\n")


def send(message: dict) -> None:
    log("out", message)
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def answer(request_id, result: dict) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def notify(method: str, params: dict) -> None:
    send({"jsonrpc": "2.0", "method": method, "params": params})


def chunk(session_id: str, kind: str, text: str) -> None:
    notify("session/update", {"sessionId": session_id,
                              "update": {"sessionUpdate": kind, "content": {"type": "text", "text": text}}})


def ask_permission(request_id, session_id: str, title: str) -> str:
    """Ask the client, then hand back the option kind it chose."""
    notification = {"jsonrpc": "2.0", "id": f"perm-{request_id}",
                    "method": "session/request_permission",
                    "params": {"sessionId": session_id,
                               "toolCall": {"toolCallId": "t1", "title": title,
                                            "status": "pending", "kind": "edit"},
                               "options": [{"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                                           {"optionId": "no", "name": "Decline", "kind": "reject_once"}]}}
    send(notification)
    while True:
        line = sys.stdin.readline()
        if not line:
            return "cancelled"
        message = json.loads(line)
        log("in", message)
        if message.get("id") == f"perm-{request_id}":
            return message.get("result", {}).get("outcome", {}).get("optionId", "no")


def read_while_busy(seconds: float) -> list[dict]:
    """Read whatever arrived on stdin during a wait, so a cancel is seen mid-turn."""
    import select
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if not ready:
        return []
    line = sys.stdin.readline()
    if not line.strip():
        return []
    message = json.loads(line)
    log("in", message)
    return [message]


def run_prompt(request_id, params: dict) -> None:
    session_id = params["sessionId"]
    text = "".join(part.get("text", "") for part in params.get("prompt", []))
    wanted = text.strip().lower().split()[-1] if text.strip() else ""
    if "ask" in text.lower():
        choice = ask_permission(request_id, session_id, "Write /tmp/out.txt")
        chunk(session_id, "agent_message_chunk", f"chose {choice}")
        answer(request_id, {"stopReason": "end_turn"})
        return
    if "slow" in text.lower():
        for step in range(60):
            for message in read_while_busy(0.05):
                if message.get("method") == "session/cancel":
                    CANCEL.add(message.get("params", {}).get("sessionId"))
            if session_id in CANCEL:
                answer(request_id, {"stopReason": "cancelled"})
                return
            chunk(session_id, "agent_thought_chunk", f"step {step}")
            chunk(session_id, "agent_message_chunk", f"part {step} ")
        answer(request_id, {"stopReason": "end_turn"})
        return
    if "fail" in text.lower():
        answer(request_id, {"stopReason": "refusal"})
        return
    chunk(session_id, "agent_thought_chunk", "Reading the question")
    count = 40 if "grow" in text.lower() else 2
    for step in range(count):
        chunk(session_id, "agent_message_chunk", f"Answer {wanted or 'nothing'} part {step}. ")
    answer(request_id, {"stopReason": "end_turn"})


def main() -> None:
    sessions = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        log("in", message)
        method, request_id = message.get("method"), message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            answer(request_id, {"protocolVersion": 1,
                                "agentCapabilities": {"loadSession": True, "promptCapabilities": {"image": False}},
                                "agentInfo": {"name": "fake-acp-agent", "version": "0"}})
        elif method == "session/new":
            session_id = f"s{len(sessions) + 1}"
            sessions[session_id] = params.get("cwd", "")
            answer(request_id, {"sessionId": session_id})
        elif method == "session/load":
            answer(request_id, {"sessionId": params.get("sessionId", "s1"), "modes": None})
            chunk(params.get("sessionId", "s1"), "agent_message_chunk", "restored")
        elif method == "session/prompt":
            run_prompt(request_id, params)
        elif method == "session/cancel":
            CANCEL.add(params.get("sessionId"))
        elif request_id is not None:
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32601, "message": f"no method {method}"}})


if __name__ == "__main__":
    main()
