# Agents tried through the spike

Measured with `python -m harness.spike --agent "<command>" --cwd /tmp "<message>"` on Stefan's
PC, 2026-10-30. Startup is spawn to a session that accepts a prompt; first update is the first
thought or answer chunk, which is a model call and says nothing about the agent's own speed.

| Agent | Command | Startup | First update | Turn | Notes |
| - | - | - | - | - | - |
| hermes-agent 0.22.5 | `hermes-acp` | 7.8 s | 24.0 s | end_turn | Worked first try: thoughts, chunks, usage update, a normal stop. Startup is far too slow to sit in a click, so the adapter starts the process in the background and says "Waking …" while it does. |
| fake agent | `.venv/bin/python tests/fake_acp_agent.py` | ~15 ms | instant | end_turn / cancelled | The test stand-in: thoughts, chunks, a permission request, cancel, refusal. |
| lean agent v0 | `.venv/bin/python -m harness.agent` | 0.2 s | 56.2 s | end_turn | Real end to end against Ollama `qwen3.8-iq3-32k`: started in a fraction of a second, then the model itself took 56 s to the first word. The harness adds no wait of its own. Usage line: 127 input tokens, 61 output, 59.2 s. |
| lean agent + hermes link | `AcpLink("hermes-acp")` | 7.8 s | 24 s | end_turn | The phase 1 adapter against the real agent: `send` returned at once, the bubble showed the thought, and the answer "link ok" arrived after 31 s. |

Only one real ACP agent is installed on this machine (`hermes-acp`). Pi is installed but speaks
its own protocol; OpenCode, Claude Code and Codex are not installed. Trying a second real agent
is still open, and the adapter has to be expected to differ per agent until then.

Numbers from Ollama are model speed on this machine (a large quantised model on CPU), not a
property of the harness. A small model answers in a fraction of a second.
