---
capability: needset-first-thousand-command
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.first_thousand.run_first_thousand@77407ae439
  - lupin_mcp.reuse_needset.first_thousand.control_job@da8024fd0c
  - lupin_mcp.reuse_needset.first_thousand.planted_stage_for@777d970ee1
  - lupin_mcp.reuse_needset.first_thousand.control_stage_live@9c3c0050ae
  - lupin_mcp.reuse_needset.first_thousand.load_stage_factories@4a6def5ac3
  - lupin_mcp.reuse_needset.first_thousand.parse_args@f520014819
  - lupin_mcp.reuse_needset.first_thousand.plan@6de27be30d
  - lupin_mcp.reuse_needset.first_thousand.load_inputs@68bde7e075
  - lupin_mcp.reuse_needset.first_thousand.main@2b55299310
---
# Need set: the first 1,000 calls, the command

The live control, the command line and the capped run. The planted pool and the remainder are on [[needset-first-thousand]].

## The live control
- `control_job` builds the drafter's job for one pair. The seed is the original and the one key is the rewrite, so the leak check keeps the rewrite out of the sentence.
- `planted_stage_for` builds the planted stage from the live one's own folders, client, arm, K and fusion, with no refresher. It loads the live vectors from disk and adds the planted rows in memory.
- `control_stage_live` drafts the 20 needs first, one at a time. It then plants, asks the checker through `planted_check`, removes the planted records and proves the pool is as it was. The pool is the index's own sendable entries.

## The command
- `parse_args` requires the root, run folder, planted file, answer key, labels folder, seed and source commit. The cap is 1,000 unless `--limit` says otherwise.
- `load_inputs` reads the 20 pairs and their groups for reading only. The planted file must match its recorded hash.
- `main` without `--live` prints `plan` and contacts nothing. The plan shows the cap, the calls already spent, the groups and the flagged count.
- `main` with `--live` loads the stage factories, builds the context from the environment, and runs the four stages. A missing stage module raises `STAGE_NOT_WIRED` before any context is built.
- `load_stage_factories` imports `attribution_stage( env )` and `yield_stage( env )` from the stage module by name, at run time.

## The run
- `run_first_thousand` installs the cap over `call-ledger.jsonl` in the run folder, runs the four stages and writes `stage-reports.json`. A resumed run keeps the calls already spent.
