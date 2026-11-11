"""The log of who answered an approval: one JSON line per decision.

The widget writes it, so a bot can read it but cannot add to it with a tool of its own.
"""

import json
import os
import time

PATH = os.environ.get("HARNESS_APPROVAL_LOG") or os.path.expanduser("~/.local/share/botwidget/harness/approvals.jsonl")


def record(request: str, decision: str, source: str, by: str) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "a") as fh:
        fh.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "request": request, "decision": decision,
                             "source": source, "by": by}) + "\n")


def recent(count: int = 20) -> str:
    try:
        with open(PATH) as fh:
            return "".join(fh.readlines()[-count:]) or "No approvals yet."
    except OSError:
        return "No approvals yet."
