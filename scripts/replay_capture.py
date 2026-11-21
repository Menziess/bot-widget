"""Turn a local transcript into a replay fixture, outside the checkout.

The input is a BOTWIDGET_REPLAY_LOG jsonl file, a JSON fixture, or a harness session
folder (its session.sqlite). The written file is under /tmp/botwidget-replay unless
--out names another path that is not inside this repository.

```sh
BOTWIDGET_REPLAY_LOG=/tmp/botwidget-replay/live.jsonl botwidget --dev
.venv/bin/python scripts/replay_capture /tmp/botwidget-replay/live.jsonl
```
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.agent.store import SessionStore
from harness.stream_text import outside_checkout, play, steps_from_log


def steps_from_session(folder: str) -> list:
    """Each stored bot message as one final event. Chunks were not kept, only the answer."""
    store = SessionStore(folder)
    try:
        return [[{"kind": "final", "text": message["text"]}]
                for message in store.messages() if message["role"] == "bot" and message["text"]]
    finally:
        store.close()


def load_steps(path: str) -> list:
    if os.path.isdir(path):
        return steps_from_session(path)
    with open(path, encoding="utf-8") as fh:
        return steps_from_log(fh.read())


def default_out(source: str) -> str:
    stem = os.path.splitext(os.path.basename(os.path.abspath(source)))[0] or "fixture"
    return os.path.join(os.path.abspath(os.path.join(os.sep, "tmp", "botwidget-replay")), stem + ".json")


def write_fixture(steps: list, out: str, bubble: str | None, user: str) -> str:
    if not outside_checkout(out):
        raise SystemExit(f"refusing to write a transcript inside the checkout: {out}")
    text = play(steps) if bubble is None else bubble
    os.makedirs(os.path.dirname(out), exist_ok=True)
    body = {"user": user, "skill": any(event.get("kind") == "nudge" for step in steps for event in step),
            "bubble": text, "steps": steps}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(body, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write a replay fixture from a local transcript.")
    parser.add_argument("source", help="jsonl log, fixture JSON, or a harness session folder")
    parser.add_argument("--out", default="", help="fixture path outside the checkout (default: /tmp/botwidget-replay/)")
    parser.add_argument("--bubble", default=None, help="expected bubble text; omit to record what the stage shows now")
    parser.add_argument("--user", default="replay", help="the user line stored on the fixture")
    args = parser.parse_args(argv)
    out = args.out or default_out(args.source)
    steps = load_steps(args.source)
    text = write_fixture(steps, out, args.bubble, args.user)
    print(out)
    print(text)


if __name__ == "__main__":
    main()
