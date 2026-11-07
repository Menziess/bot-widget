# Standards: what exists and what to support

No single standard covers everything a backend does. Three separate layers each have a convention, and a backend picks one per layer. This page walks the layers from the model upwards.

## Layer 1: talking to a model

Most providers accept the shape OpenAI made popular. A minimal request looks like this.

```json
{
  "model": "some-model",
  "messages": [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Hello"}
  ],
  "stream": true
}
```

Sent to the chat completions path of a provider, this works against OpenAI itself and against many others after changing three values.

- Base URL
- Key
- Model name

The shape is the de facto minimum, not a formal standard. Providers differ on the details that matter for an agent.

- Tool call arguments arrive as streamed fragments that must be joined
- Reasoning text is exposed in different fields, or not at all
- Caching is configured differently, or not through this shape at all

### Anthropic is different where it counts

Anthropic has its own Messages API. The system prompt is a top-level field, and caching is switched on by marking blocks.

```json
{
  "model": "some-model",
  "system": [
    {"type": "text", "text": "Long stable instructions", "cache_control": {"type": "ephemeral"}}
  ],
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 1024
}
```

Here the `cache_control` mark is the part to notice.

- A cache_control mark on a block asks for the prefix up to that block to be cached
- Anthropic documents its OpenAI-compatible layer as a way to evaluate the models, and says prompt caching is not supported there
- Schema strictness for tool calls is also ignored in that layer, according to the same documentation

For an efficient backend this decides one thing. The native Messages API is worth its own adapter when Claude models are used, because the compatibility layer gives up caching.

### Open Responses

In January 2026 OpenAI and partners published Open Responses, an open specification based on the Responses API. Its unit is the item, not the message.

```json
{
  "model": "some-model",
  "input": [
    {"type": "message", "role": "user", "content": "Hello"}
  ],
  "stream": true
}
```

The items are the idea to keep.

- Item types such as message and function call are common to all providers
- Each item has a lifecycle, in progress, incomplete or completed
- Streaming events describe changes to items, so reasoning, tool calls and text arrive in one consistent form
- Provider-specific item types have a defined way to be added without breaking the core

The project is run under a Linux Foundation charter. The project site lists, among others, Hugging Face, Vercel, OpenRouter, LM Studio, Ollama, vLLM, NVIDIA, Databricks, AWS, Red Hat and OpenAI as supporters. Anthropic was not among the logos on the site when it was read. Support is still growing, and Open WebUI calls its own support experimental.

### Gateways

A gateway puts one endpoint in front of many providers. OpenRouter, the Vercel AI Gateway and LiteLLM are the common ones.

- One adapter in the backend reaches many models
- Prices and routing are the gateway's concern
- Provider-specific features, caching above all, may be lost or reshaped on the way

## Layer 2: tools

MCP, the Model Context Protocol, is how an agent reaches tools and data. A server lists its tools and the agent calls them.

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

Here is why it matters for a lean backend.

- A backend that is an MCP client gets every existing MCP server for free
- Tool definitions come from the servers, so the backend carries none of its own
- Only the tools a turn needs have to be shown to the model, which is a context saving (see 04-efficiency.md)

## Layer 3: a UI talking to an agent

The Agent Client Protocol, ACP, standardises how an editor or app talks to an agent. The comparison made in its own documentation is with the Language Server Protocol. Local agents run as subprocesses speaking JSON-RPC over stdio. Remote agents over HTTP or WebSocket are a work in progress.

A turn starts with one request.

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/prompt",
  "params": {
    "sessionId": "sess_abc",
    "prompt": [{"type": "text", "text": "What changed today?"}]
  }
}
```

Meanwhile the agent streams notifications back.

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "sess_abc",
    "update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "Looking at the log"}}
  }
}
```

The update types that matter to the widget.

- Reasoning arrives as agent_thought_chunk, for the thinking cloud
- The answer arrives as agent_message_chunk, for the bubble
- Tool activity arrives as tool_call and tool_call_update, for what the bot is doing
- Context size and cost arrive as usage_update
- A compaction arrives as compaction_update, where an agent reports that it compacted
- A request for the user to allow something arrives as session/request_permission
- Structured questions to the user are called elicitation
- A stop from the client is session/cancel, to end a turn

Agents that speak ACP, according to its own list and to adapter lists in other projects, include these.

| Agent | How it is reached |
| - | - |
| Gemini CLI | Native flag |
| OpenCode | A subcommand |
| Hermes Agent | A subcommand |
| Claude Code | Through an adapter |
| Codex CLI | Through an adapter |
| Pi | Through an adapter |
| Goose, Cline, Copilot CLI, Cursor and more | Listed as supporting it |

The list is an example, and it grows. The ACP Registry exists to find and install agents. A Python SDK exists for both sides of the protocol.

Two proposals in the ACP project bear directly on a lean backend. Both are drafts, so neither can be relied on yet.

- Client-provided system prompt, where the client supplies the instructions of a session, either appended to or replacing the agent's own
- Configurable LLM providers, where the client points an agent at its own proxy or gateway

### Agent to agent

A2A, Agent2Agent, connects agents to each other across vendors. It reached version 1.0 in 2026 and is run under the Linux Foundation. IBM's older Agent Communication Protocol folded into it. The widget talks to one bot at a time, so A2A is not needed now.

## What to support

| Layer | Support | Why |
| - | - | - |
| Model | OpenAI chat completions shape | One adapter reaches most providers and local servers |
| Model | Anthropic Messages, native | Keeps prompt caching |
| Model | Open Responses | Later, when more providers offer it |
| Tools | MCP client | Reuses all existing tools |
| Agent | ACP client in the widget | One adapter, many agents |
| Agent | A2A | Skip for now |

The point to remember is the split. Models need an API adapter, agents need a client protocol, and the widget needs only the second.

## Sources

- Open Responses, specification and overview, https://www.openresponses.org/
- InfoQ on Open Responses, https://www.infoq.com/news/2026/02/openai-open-responses
- Anthropic, OpenAI SDK compatibility, https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk
- Gemini API, OpenAI compatibility, https://ai.google.dev/gemini-api/docs/openai
- Agent Client Protocol, introduction and prompt turn, https://agentclientprotocol.com/overview/introduction and https://agentclientprotocol.com/protocol/prompt-turn
- ACP agents, clients, Python library, https://agentclientprotocol.com/get-started/agents and https://agentclientprotocol.com/libraries/python.md
- ACP RFDs, client system prompt and configurable LLM providers, https://agentclientprotocol.com/rfds/client-system-prompt.md and https://agentclientprotocol.com/rfds/custom-llm-endpoint.md
- OpenHands, list of ACP agent commands, https://docs.openhands.dev/openhands/usage/agent-canvas/acp-agents
- Zuplo and Tyk on MCP, A2A and the old ACP, https://zuplo.com/blog/agent-protocol-stack-mcp-a2a-acp-2026 and https://tyk.io/learning-center/agent-protocols-a-complete-guide-to-mcp-a2a-and-acp
