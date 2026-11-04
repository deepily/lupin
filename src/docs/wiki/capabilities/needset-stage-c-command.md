---
capability: needset-stage-c-command
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_c.parse_args@83266930db
  - lupin_mcp.reuse_needset.stage_c.collect_rows@c00e1cd585
  - lupin_mcp.reuse_needset.stage_c.main@080490a2f6
  - lupin_mcp.reuse_needset.stage_c.in_source_tree@fe94d60df7
  - lupin_mcp.reuse_needset.stage_c.replay_rejects@fa6c982cbb
  - lupin_mcp.reuse_needset.stage_c.redraft_plan@e0e353d0dc
  - lupin_mcp.reuse_needset.stage_c.redraft@323be2fef0
  - lupin_mcp.reuse_needset.stage_c.redraft_in@2104c00a2f
  - lupin_mcp.reuse_needset.stage_c.live@49ccc1b365
  - lupin_mcp.reuse_needset.stage_c.exit_status@61e70b83e2
  - lupin_mcp.reuse_needset.stage_c.run_cli@2b9e55e56d
---
# Need set: the judge-only run, the command

The command line of the judge-only run. Inputs are on [[needset-stage-c-inputs]], drafting and judging on [[needset-stage-c-drafting]], scoring on [[needset-stage-c-levels]].

## Running
- `parse_args` reads the line. `collect_rows` reads the inputs and splits the pairs.
- `main` without `--live` prints the plan and writes nothing. With `--live` it needs a run name, `--from-run` and `--cli-path`.
- A live run drafts, judges and writes `stage-c-report.json`. `live` is that branch, and it closes the spend-ledger run however it ends.
- `in_source_tree` runs a function with the tree at `--source-commit` and unlocks a tree it made.

## Replay and redraft
- `--save-rejects` calls `replay_rejects`. It reads the saved draft ledger with no model call and writes the refused sentences.
- `redraft_plan` counts the extra drafting that `--redraft` would do. With `--live`, `redraft` tries a few more sentences on pairs still without a need.
- `redraft_in` is that work inside the tree. Its calls are counted in `call-ledger-redraft.jsonl` under their own budget.

## Exit
- `exit_status` is 0 for a save-rejects or redraft result, else the expansion run's answer. `run_cli` prints the result as JSON and returns the status.
