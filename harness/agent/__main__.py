"""Start the lean agent on stdio, the way an ACP client (the widget, or a coding editor) does.

    HARNESS_BOT=General HARNESS_MODEL_BASE_URL=http://127.0.0.1:11434/v1 \\
        HARNESS_MODEL=qwen2.5:7b python -m harness.agent
"""

import asyncio
import os

from acp.agent import AgentSideConnection
from acp.stdio import stdio_streams

from harness.agent.agent import LeanAgent
from harness.agent.models import from_environment


async def serve() -> None:
    agent = LeanAgent(os.environ.get("HARNESS_BOT") or "bot", from_environment())
    stdin, stdout = await stdio_streams()
    AgentSideConnection(lambda _conn: agent, stdout, stdin)
    await asyncio.Event().wait()  # the connection reads until the client closes the pipe


def main() -> int:
    try:
        asyncio.run(serve())
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
