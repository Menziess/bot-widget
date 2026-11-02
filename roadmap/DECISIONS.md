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

## Phase 3, tools and permissions

- **Three read-only-by-default built-ins, one write.** `read_file` and `list_dir` never ask;
  `write_file` asks first. Private paths (`~/.ssh`, `~/.gnupg`, `~/.aws`, gcloud and OpenBot
  automation config, `.env`, `.netrc`, `id_rsa`) are refused outright rather than offered.
- **One MCP server, configured with `HARNESS_MCP_SERVER`.** Its tools ask for permission unless
  their names are listed in `HARNESS_MCP_READ_ONLY`, so a read-only server is not a click per
  call and a new server cannot write on its own. More servers can come once one is proven.
- **Tool output enters the prompt with a line that says it is data, never an instruction.** The
  same text the widget's system prompt already promises.
- **The model stream runs in a thread feeding an asyncio queue**, so a cancel, a permission
  request or a second message is seen while the provider is still thinking; a cancel also sets a
  stop flag and closes the response, so the rest of the answer is not paid for.

## Phase 4, context and caching

- **The request is built from a stable prefix, the summary, the pinned facts and the newest
  turns.** `pin_fact` writes a fact to the session store so it survives the summary; the meter
  reports the estimated request size every turn, and the widget says how full the context is at
  70% or when a summary has just landed.
- **Anthropic gets its own adapter (`HARNESS_MODEL_PROVIDER=anthropic`)**, because its cache is
  explicit: the system block and the last content block carry `cache_control: ephemeral`, so the
  unchanged prefix is a cache read on the next turn. Chat Completions stays the default for every
  OpenAI-compatible provider.
- **Both adapters report the same usage shape** (`prompt_tokens`, `completion_tokens`,
  `prompt_tokens_details.cached_tokens`), so one usage log covers either provider.
- **The cache claim is measured against a fake Messages API that models prefix caching**, not a
  paid provider: a 20-turn replay is 0% cached on turn one, over half cached from turn three and
  over 90% by turn twenty. A hosted run is still untried (no paid credit).
