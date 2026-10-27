# Own backend for bot-widget

Research notes on giving bot-widget a backend of its own, next to OpenBot, Grok Bot and Hermes. Nothing is built yet. This folder is ignored by git on purpose (the global ignore has `___*`), so these notes stay local.

The question behind it is whether a lean backend can cost less context and money per turn than OpenBot, and whether one standard exists that all providers share so that everything can be supported.

## The short answer

The widget talks to a backend in a few calls.

```text
face + bubble
     |
 one adapter per backend
     |
 +---+-------------+---------------+
 |                 |               |
OpenBot       Grok Bot / Hermes   ACP agent (new)
```

There is no single standard, but there are three layers, and each has one that wins.

| Layer | What it connects | Standard that wins | Notes |
| - | - | - | - |
| Model | Your code and a model | OpenAI Chat Completions, as the de facto minimum | Open Responses is the new, open spec on top of the Responses API |
| Tools | An agent and its tools | MCP | Widely supported, a backend only has to be an MCP client |
| Agent | A UI and an agent | ACP, the Agent Client Protocol | This is the layer the widget lives on |

Four facts decide the design.

- The widget is a client of an agent, so ACP is the standard that matches it
- ACP has a Python SDK, and the widget is Python
- Many agents already speak ACP, so one client adapter supports many backends at once
- A lean backend of our own can sit behind the same adapter as one more ACP agent

## Advice in one line

Build an ACP client adapter first, then run a lean agent behind it, and let that agent reach models through the OpenAI-compatible API plus a native Anthropic adapter.

## Files

- [01-standards.md](01-standards.md) Which standards exist, who supports them, what to support
- [02-widget-contract.md](02-widget-contract.md) What the widget needs from a backend today, mapped to ACP
- [03-architecture.md](03-architecture.md) Three ways to build it and the design of the lean one
- [04-efficiency.md](04-efficiency.md) Where context and money go, and how a lean backend saves them
- [05-roadmap.md](05-roadmap.md) Phases, acceptance tests, risks and open decisions

## Status of the facts

Facts about protocols and providers come from public documentation read on 2026-10-27, with links at the bottom of each file. Provider details change quickly. Treat numbers, versions and command lines as examples that must be checked again at build time. Token counts for OpenBot are estimates read off the instruction block, not measurements.
