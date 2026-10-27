# Efficiency: where context and money go

The point of a backend of our own is a lower cost per useful turn. This page lists where a turn's tokens go in an OpenBot session, what a lean backend would do differently, and how to find out whether it really does.

Every figure for OpenBot below is an estimate read off the text the model receives, not a measurement. The plan at the end replaces the estimates with measurements.

## What a turn carries today

A turn in an OpenBot agent starts from a fixed block before the first word of the user.

```text
developer instructions     ~8,000-10,000 tokens, resent every turn
tool lists and tool guides  a few thousand more, for browser, search, files
user instruction files      the global and project files
saved memories              a short block
conversation so far         grows, until compaction
```

Reading the block.

- The instruction block is written for everything a bot can do, teammates, routines, vault, browser, so a turn that only edits a file still carries it
- Prompt caching makes a repeated prefix cheaper, but only while the prefix stays byte-identical
- Anything that changes early in the prompt, such as a date or a tool list, moves the cache boundary and makes the whole turn full price again
- A long-lived bot cannot start a fresh session the way a person does, so it compacts, and compaction loses detail

## What a lean backend does differently

Five levers, in order of effect.

### A small, stable prefix

The system prompt says who the bot is and how to behave in a few hundred tokens. Everything else is loaded when needed.

```text
[system, fixed]  [pinned facts, rarely change]  [summary, changes at compaction]  [recent turns]  [new message]
```

Rules for the order.

- Parts that change least come first
- Nothing in front of the summary is edited in place, only appended to
- The date and other volatile facts go in the newest message, never in the prefix

### Tools on demand

Tool definitions cost tokens on every turn they are present.

- Show a small core set, and offer the rest through one search tool that returns schemas when asked
- MCP servers are connected lazily, when a turn names them
- A tool the user never uses costs nothing

### Compaction in three steps, cheapest first

```python
def shrink(session):
    trim_old_tool_results(session)    # keep the call, replace the output with one line
    if session.tokens() > LIMIT:
        summarise_oldest(session)     # rolling summary by a small model
    pin_facts(session)                # decisions and preferences survive every summary
```

How the steps differ.

- Trimming old tool output is usually the largest saving and loses almost nothing
- A rolling summary replaces the oldest turns and keeps the newest verbatim
- Pinned facts, decisions and preferences, are stored apart so that no summary can drop them

### Fresh by default

A person starts a new session per task and writes a short handover. A bot can do the same on purpose.

- A session per topic, closed when the topic ends
- A handover note carried into the next session, the way the handover and continue skills work in the terminal
- The widget shows the context meter, from the usage update, so the user sees when a topic is getting heavy

### The right model for the turn

- Routine turns, status, short answers, go to a small model
- Hard turns go to a large one, chosen by the user or by a simple rule
- A local model costs nothing per token, and the chat completions adapter reaches one with only a base URL

## Caching in practice

Providers cache differently, and the adapter has to respect each.

| Provider family | How caching is switched on | What the adapter does |
| - | - | - |
| Anthropic Messages | Explicit marks on blocks | Marks the end of the stable prefix |
| OpenAI | Automatic for a repeated prefix, explicit marks on newer models | Keeps the prefix identical, optionally marks |
| Gemini | Implicit by default, explicit as a separate resource | Keeps the prefix identical |
| Compatibility layers | Often none | Avoid for Claude, use the native adapter |

The table is a summary of public documentation read in October 2026, and these details change. The adapter's tests should assert that two consecutive turns share a prefix, which does not depend on any provider's current rules.

## How to find out

Measure before believing any of this. Every turn writes one line.

```json
{"session": "s1", "turn": 7, "model": "x", "input": 5200, "cached": 4800, "output": 310, "tools": 2}
```

The plan.

- Pick twenty real tasks and the same prompts for each backend
- Run them on OpenBot and on the lean agent, with the same model where possible
- Compare input tokens, cached share, output tokens and cost per finished task
- Count a task as finished only when the result is accepted, so a cheap wrong answer does not win

A result worth acting on is a clear difference in cost per finished task, not in tokens per turn.

## What is not saved

- OpenBot's other features, which have a price of their own and may be worth it
- The cost of writing and keeping up an agent, which is real and recurring
- Quality, where a hosted agent with years of tuning may beat a new one on hard tasks

## Sources

- Provider caching differences, https://hidekazu-konishi.com/entry/llm_api_parameter_compatibility_reference.html
- Anthropic, OpenAI SDK compatibility and caching, https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk
- ACP, usage and compaction updates, https://agentclientprotocol.com/protocol/prompt-turn
