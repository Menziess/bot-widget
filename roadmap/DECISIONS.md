# Decisions

Choices taken while building the harness, newest last. Each one names the alternative the
roadmap leaves open, and why this option won. General (or Stefan) can overrule any line;
the choice closest to the roadmap stands until then.

## Branch and scope

- **Branch `harness`, from `origin/main`.** Stefan overrode the repo's main-only rule for this
  work. Nothing here may be pushed to `main` or tagged.
- **The roadmap travels with the code**, copied from `origin/roadmap` into `roadmap/`.

## Phase 0, the spike

- **Use the ACP Python SDK (`agent-client-protocol`) instead of hand-written JSON-RPC.** The
  wire protocol is small but streaming, permission and cancellation edge cases are not, and
  the roadmap names the SDK as the intended dependency. Installed in `.venv`, added to
  `pyproject.toml` together with the adapter in phase 1.
- **A fake agent for every test.** A small Python process that speaks real ACP over stdio
  (`tests/fake_acp_agent.py`) stands in for a real agent, so the suite needs no model, no
  network and no provider key. Real agents are tried by hand, and what they did is noted in
  `roadmap/AGENTS-TESTED.md`.

## Phase 1, the widget adapter

- **One link object per backend, chosen where the face picks its backend today.** The face keeps
  its existing `send/chat/due/active/request_fetch/note/resume` calls; the ACP adapter answers
  them from a background asyncio loop, the same way the Grok and Hermes links answer from a
  background HTTP thread. The face must not learn which backend it has.
- **A fixed working directory per bot.** ACP sessions need one and a chat has none:
  `~/.local/share/botwidget/harness/<bot>/` is used, created on demand.

## Phase 2, the lean agent

- **One sqlite file per bot**, `~/.local/share/botwidget/harness/<bot>/session.sqlite`, so a
  restart keeps the conversation and one corrupt bot cannot take the others down.
- **Never summarise inside a turn.** The request is a stable prefix (system text, pinned facts,
  the current summary) plus the recent turns, trimmed to a budget; older turns are summarised in
  a background task after the turn has been answered, and the next request picks up the new
  summary. A turn therefore never waits on a model call it does not need.
- **Chat Completions is the first and only adapter in v0**, pointed at any OpenAI-compatible base
  URL (local server or hosted). Anthropic-native caching is phase 4.
- **Usage is appended to `usage.jsonl` next to the session store**, one line per turn: time,
  bot, model, step count, input/output tokens, cached input tokens if the provider reports them,
  milliseconds until the first token and until the answer finished.
