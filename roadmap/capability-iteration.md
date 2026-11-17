# Capability iteration

Take a baseline with `python -m harness.capability --scratch /tmp/botwidget-capability`. That appends one JSONL row to `history.jsonl` with a score for each capability and the commit id.

Change the harness, then rerun the same command. The new row is appended. History is not replaced.

Merge only when there is no regression: a score that was 1 stays 1. A lower score blocks the merge. Log the scores per commit by keeping the JSONL row that names that commit.

## Live Chrome

Run each check against the live Chrome, on the everyday session after Chrome's "Allow remote debugging?" consent once. These checks are separate from the offline scripted H2 benchmark.

- `list_tabs`/`switch_tab` to reuse existing tabs
- never open a new window (a new tab in the existing window only when needed)
- `goto_url` + `wait_for_load`
- read via `document.body.innerText` plus background-tab screenshots
- click via JS `element.click()` on an element found by its text
- `fetch()` inside the page using the logged-in session, and never display or store tokens
