# Browser choice for a local-model bot

Compared for a bot that runs on this PC, next to a local model, with no cloud account.

- browser-use is a Python agent loop over Chrome. It is robust and already used as an operator tool. It pulls a large stack and a planner, which is slower to start than a single CDP call and fights a small local model for the driver's decisions.
- Playwright MCP speaks Playwright through a Node server. It is robust and widely tested. The extra process and the MCP hop cost more than talking to the browser the model already asked to open.
- Chrome DevTools MCP is the same idea as direct CDP, with a server in between. Direct CDP skips that server: one WebSocket, the commands the browser already documents. That is the fastest robust path when Chrome is running with remote debugging.
- Stagehand plans actions in a hosted or local model on top of Playwright. The planner is a second model call per step, which is the wrong cost for a local model that is already the planner.
- Newer: Lightpanda and other headless CDP browsers speak the same protocol with a smaller footprint. They are not on this machine yet. They stay a later swap behind the same CDP calls.

Pick: direct CDP. It is the fastest robust option because the local model issues a few browser commands and Chrome runs them, with no second agent and no Node server. Until Chrome is attached, the harness reads a fixture page offline so a test and a model with no display still get a title. The live socket is the upgrade when a debugging port is present.
