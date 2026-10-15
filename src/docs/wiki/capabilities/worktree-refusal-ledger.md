---
capability: worktree-refusal-ledger
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.shared.worktree_refusal_ledger.refused_set@cba8b7bb5c
  - cosa.agents.shared.worktree_refusal_ledger.load_ledger@dcc251c229
  - cosa.agents.shared.worktree_refusal_ledger.write_ledger@ddce7661e5
  - cosa.agents.shared.worktree_refusal_ledger.compose_notice@e60f7bf3ac
---
# Worktree refusal ledger

The janitor refuses to remove a tree that holds somebody's ignored data. This ledger makes each change in that refused set visible, and sends one notice per change. See [[worktree-lifecycle]].

## What it does
- `refused_set` builds `{ tree path: [ blocking entries ] }` from the result of one reconcile poll.
- A tree the poll skipped keeps its previous entry, so the set does not flap on every file change.
- A tree that is gone, or was removed this poll, drops out of the set.
- `load_ledger` returns the last recorded set, or an empty dictionary when the file is absent or corrupt.
- `write_ledger` replaces the ledger file whole through a temporary file. It holds `updated_at`, `count` and `refused`.
- `compose_notice` returns a one-sentence message with the count and a markdown table of trees with their first blockers.
- The table is capped at 25 rows. Further rows are counted, not dropped silently.
- `report_refusals` writes the ledger and notifies only when the set differs from the recorded one.

## Invariants
- An unchanged set causes no notify and no write.
- The ledger is replaced and never appended to, so it cannot grow into a pile.
- The ledger is replaced only after the notify succeeded, so a failed announcement is tried again on the next poll.
- A failed notify is logged and never swallowed.
