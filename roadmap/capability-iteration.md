# Capability iteration

Take a baseline with `python -m harness.capability --scratch /tmp/botwidget-capability`. That appends one JSONL row to `history.jsonl` with a score for each capability and the commit id.

Change the harness, then rerun the same command. The new row is appended. History is not replaced.

Merge only when there is no regression: a score that was 1 stays 1. A lower score blocks the merge. Log the scores per commit by keeping the JSONL row that names that commit.
