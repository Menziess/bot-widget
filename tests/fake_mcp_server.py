"""A stand-in MCP server for tests: one read-only tool and one that writes, over stdio."""

import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("fake-mcp")


@server.tool()
def echo(text: str) -> str:
    """Say the text back."""
    return "echo: " + text


@server.tool()
def write_note(path: str, text: str) -> str:
    """Write a note to a file."""
    with open(path, "w") as fh:
        fh.write(text)
    return f"wrote {path}"


if __name__ == "__main__":
    server.run(transport="stdio")
    sys.exit(0)
