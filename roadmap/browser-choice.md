# Browser choice for a local-model bot

Compared for a bot that runs on this PC, next to a local model, with no cloud account.

- browser-use is a Python agent loop over Chrome. It is robust and already used as an operator tool. It pulls a large stack and a planner, which is slower to start than a single CDP call and fights a small local model for the driver's decisions.
- Playwright MCP speaks Playwright through a Node server. It is robust and widely tested. The extra process and the MCP hop cost more than talking to the browser the model already asked to open.
- Chrome DevTools MCP is the same idea as direct CDP, with a server in between. Direct CDP skips that server: one WebSocket, the commands the browser already documents.
- Stagehand plans actions in a hosted or local model on top of Playwright. The planner is a second model call per step, which is the wrong cost for a local model that is already the planner.
- Newer: Lightpanda and other headless CDP browsers speak the same protocol with a smaller footprint. They are not on this machine yet. They stay a later swap behind the same CDP calls.

Pick: direct CDP, as browser-use-style control of the running everyday Chrome over CDP. Chrome's "Allow remote debugging?" consent once, then attach to the existing session: his own tabs and logins. No extension, no separate profile, and no `--remote-debugging-port` relaunch. The base this builds on is the current direct-CDP reader in `harness/browser_local.py` (a fixture read until that live socket exists), not the browser-use package, Playwright, or an extension.

Requirements:

- `list_tabs`/`switch_tab` to reuse existing tabs
- never open a new window (a new tab in the existing window only when needed)
- `goto_url` + `wait_for_load`
- read via `document.body.innerText` plus background-tab screenshots
- click via JS `element.click()` on an element found by its text
- `fetch()` inside the page using the logged-in session, and never display or store tokens

OpenCode Browse (`anomalyco/browse`) is the fallback only, and it needs an extension.
