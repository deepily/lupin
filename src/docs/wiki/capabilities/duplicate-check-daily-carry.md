---
capability: duplicate-check-daily-carry
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.carry_mode@907a727389
  - lupin_mcp.duplicate_check_daily.carry_progress@b96651528d
  - lupin_mcp.duplicate_check_daily.carry_refusal@b78f8f9ac5
---
# Duplicate check daily: carry the progress

The `--carry-progress` command of [[duplicate-check-daily-run]]. It moves the recorded progress to another branch and commit after a squash merge, with no model call.

## What it does
- `carry_mode` takes the run lock, calls `carry_progress`, prints the answer as JSON and returns 0 when the progress moved, else the refused exit. With the lock held by another run it writes nothing and answers `run_in_flight`.
- `carry_progress` refuses with `no_record`, `target_not_on_branch` or `unknown_recorded_commit` whatever the flags. It refuses with `tree_differs` or `baseline_off_lineage` unless `allow_tree_change` is set.
- A carry writes `carried_from` ( branch and commit ) into the record, so the move can be read afterwards. A refusal changes neither file.
- `carry_refusal( reason, **detail )` builds every refusal answer: `{ carried: False, refusal: reason }` with the detail beside it.
