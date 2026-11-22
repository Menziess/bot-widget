# Architecture: three ways to build it

There are three ways to give the widget a backend of its own. They are not exclusive. This page compares them, then designs the lean agent in more detail.

## The three options

```text
A  widget --ACP--> existing agent (Pi, OpenCode, Hermes, Claude Code, ...)
B  widget --ACP--> own lean agent --OpenAI shape / native Anthropic--> models
C  widget ---------------------------------own loop inside the widget--> models
```

How the options compare.

| | A. ACP client only | B. Own agent behind ACP | C. Loop inside the widget |
| - | - | - | - |
| Work | A client adapter | The adapter plus an agent | An agent and a bubble contract of its own |
| Backends reached | Every ACP agent | Every ACP agent plus ours | Ours only |
| Context control | What each agent offers | Complete | Complete |
| Process model | One subprocess per agent | One more subprocess | Same process as the face |
| Risk | Depends on adapters and their quality | The agent is real work | A crash takes the face down, and nothing else can reuse the agent |

Reading the table.

- A is the cheapest way to support many backends, and it proves the adapter
- B adds control over every token, at the cost of writing and maintaining an agent
- C is worse than B in every row except the first, so it is not recommended

The route that follows is A first, then B behind the same adapter.

## Why B is an ACP agent and not a private API

If the lean agent speaks ACP, three things come free.

- The widget needs no second adapter
- Zed, JetBrains and other ACP clients can use the same agent for coding work, which makes it testable outside the widget
- The Python SDK supplies the message plumbing for the agent side as well as the client side

The cost is that ACP is shaped around coding sessions. A chat bot has no working directory, and its tool permissions are different. Both are manageable, because a session accepts a fixed directory and the agent decides which tools it offers.

## Parts of the lean agent

```text
 acp server (stdio)
      |
 session store ---- sqlite file per bot
      |
 turn loop --------- tools (MCP client, plus a few built in)
      |
 context builder --- stable prefix, summary, recent turns
      |
 provider adapter -- chat completions shape | Anthropic Messages | later Responses
```

Each part is small.

- ACP server, the JSON-RPC surface, using the SDK
- Session store, messages, summaries and facts in one sqlite file per bot, so a restart loses nothing
- Turn loop, send to the model, run the tool calls, send the results back, stop at a final answer or a limit
- Context builder, decides what goes into the next request and in which order
- Provider adapters, one class per API shape behind a common interface
- Tools, whatever MCP servers are configured, plus read-only built ins at first

## The turn loop

The core of any agent is one loop. It is short enough to sketch in full.

```python
def run_turn(session, text, model, tools):
    session.add("user", text)
    for step in range(MAX_STEPS):
        request = build_context(session, tools)
        reply = model.complete(request)
        session.add_items(reply.items)
        calls = [item for item in reply.items if item.kind == "tool_call"]
        if not calls:
            return "end_turn"
        for call in calls:
            session.add_result(call, run_tool(call))
    return "max_turn_requests"
```

Here are the points the loop makes.

- The step limit bounds a runaway turn, and it maps to an ACP stop reason
- Items are the internal unit, close to the Open Responses idea, so that every provider adapter converts to and from one shape
- Tool results are items too, so compaction can treat them like any other
- Streaming is a property of the adapter, which yields item events as they arrive

## One internal shape, many adapters

The adapters hide the differences from the first page of this folder.

```python
class Model:
    def complete(self, request):
        """Yield item events: text, reasoning, tool call, usage."""
```

What each adapter owns.

- Chat completions adapter, reaches OpenAI, Gemini, Mistral, DeepSeek and local servers such as Ollama, LM Studio and vLLM
- Anthropic adapter, native Messages API, marks cache breakpoints
- Joining streamed tool call fragments, which differ by provider
- Mapping reasoning text to the item model, where the provider exposes it
- Reporting usage, with cached and uncached input counts when the provider gives them

A gateway can replace many adapters with one, at the price of reshaped provider features. Starting with the chat completions adapter pointed at a local server costs nothing and fits the existing setup with a local model.

## Where the agent runs

Two choices.

- A subprocess started by the widget, speaking ACP over stdio, simplest and closed when the widget quits
- A long-running daemon that the widget connects to, which keeps working when the widget is closed

The widget already keeps no state of its own about a conversation and reads it from the backend. A daemon fits that best, and ACP's HTTP and WebSocket transport is in progress for exactly this case. Start with a subprocess, because it needs no service management, and keep the session store on disk so that the choice can change later.

## Safety

An own agent owns its safety, which OpenBot owns today.

- Start with tools that cannot change anything, and add the rest one at a time
- Every tool that writes or runs something asks through session/request_permission
- Secrets stay in the environment of the agent, never in the session store or in messages
- Tool output is data, never instructions, and the context builder labels it that way

## Open design points

- Whether memory is a feature of the agent or only a tool behind MCP
- Whether one agent process serves several bots or each bot has its own
- How a bot gets a face, name and colour, which the widget takes from its id today
