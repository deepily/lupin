---
capability: rejoin-done-blocked-rows
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.rejoin-done-blocked-rows.fetch_board@c6db60b232
  - scripts.rejoin-done-blocked-rows.examine@499b997fe5
  - scripts.rejoin-done-blocked-rows.apply_rejoin@fdc82d5de3
  - scripts.rejoin-done-blocked-rows.main@3d54e90e99
---
# Rejoin done-blocked rows

Rejoins blocked rows whose blockers are all done, moving them back to queued. The pure decision lives in the task-store rejoin module. This script is the caller, not a schedule: nothing runs it on a timer.

## Safety
- It is a dry run by default. Only `--apply` writes, because the pass moves rows into the workable set where a seat will pick them up.
- It writes the amend first, then the transition. If the transition fails, the row stays blocked with a stamp that has not come true yet, which is visible, harmless and retried. The other order could leave a queued row that reads as freshly vetted.
- It never touches a row with a dropped blocker, an unresolvable blocker, or a persona or user blocker. A dead edge is not a satisfied precondition.

## Functions
- `fetch_board` pages the entire board, terminal rows included, because the blockers this pass resolves are done by definition. It returns the rows and whether the board was truncated. A non-success reply raises rather than returning an empty board.
- `examine` classifies every blocked row and returns the eligible entries with counts of each verdict. A row whose blocker is missing from the board is unresolved and is not rejoined.
- `apply_rejoin` amends then transitions one row, returning success, the stage and a detail. A failed amend never proceeds to the transition.
- `main` takes `--apply`, `--actor`, `--max-rows` and `--json`.

## Exit codes
- 0 means nothing eligible. 1 means eligible rows were found in a dry run, or rows were rejoined.
- 2 means the store could not be reached or auth failed.
- 3 means the board was truncated, so the result is unknown. 4 means a row failed mid-write.
