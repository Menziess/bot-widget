"""Phase 0 spike: talk ACP to an agent from the shell, without the widget.

    python -m harness.spike --agent "cmd with args" --cwd /tmp "your message"

Prints every thought, message chunk and tool call as it arrives, then the stop reason and the
two numbers that matter for the face: milliseconds to a usable session, and to the first
update. `--ask` allows a permission request; without it every request is declined. `--cancel
AFTER` cancels the turn after that many seconds, to see the cancelled stop reason.
"""

import argparse
import asyncio
import shlex
import sys
import time

from harness.acp_client import AcpClient


async def run(command: str, prompt: str, cwd: str | None, allow: bool, cancel_after: float) -> int:
    client = AcpClient(*shlex.split(command), cwd=cwd, allow=lambda title: allow)
    client.on_update = lambda update: print(f"  {update.kind}: {update.text}", flush=True)
    try:
        async with client:
            info = await client.start()
            print(f"agent {info['name']} {info['version']}, protocol {info['protocol']}, "
                  f"session {info['session']}, startup {client.startup_ms} ms", flush=True)
            started = time.monotonic()
            turn = asyncio.create_task(client.prompt(prompt))
            if cancel_after:
                await asyncio.sleep(cancel_after)
                await client.cancel()
                print(f"cancelled after {cancel_after}s", flush=True)
            result = await turn
            print(f"stop {result.stop_reason} after {result.total_ms} ms "
                  f"(first update {result.first_update_ms} ms, {time.monotonic() - started:.1f}s)",
                  flush=True)
            if result.error:
                print(result.error, file=sys.stderr)
                return 1
            return 0 if result.stop_reason != "error" else 1
    except Exception as error:
        print(f"failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", required=True, help="command that starts the ACP agent on stdio")
    parser.add_argument("--cwd", default=None, help="working directory for the session")
    parser.add_argument("--ask", action="store_true", help="allow permission requests instead of declining")
    parser.add_argument("--cancel", type=float, default=0.0, metavar="SECONDS", help="cancel the turn after N seconds")
    parser.add_argument("prompt", help="the message to send")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.agent, args.prompt, args.cwd, args.ask, args.cancel))


if __name__ == "__main__":
    raise SystemExit(main())
