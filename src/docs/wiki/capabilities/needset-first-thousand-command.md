---
capability: needset-first-thousand-command
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.first_thousand.run_first_thousand@ad0d064da7
  - lupin_mcp.reuse_needset.first_thousand.control_job@da8024fd0c
  - lupin_mcp.reuse_needset.first_thousand.planted_stage_for@d5537af534
  - lupin_mcp.reuse_needset.first_thousand.control_stage_live@84057b5f0c
  - lupin_mcp.reuse_needset.first_thousand.tracked_files@0eecf6442d
  - lupin_mcp.reuse_needset.first_thousand.write_seed_lists@480a3dd8ba
  - lupin_mcp.reuse_needset.first_thousand.live_parts@6bdad27106
  - lupin_mcp.reuse_needset.first_thousand.stage_factories@6b083e58de
  - lupin_mcp.reuse_needset.first_thousand.parse_args@1a07efcc78
  - lupin_mcp.reuse_needset.first_thousand.plan@6de27be30d
  - lupin_mcp.reuse_needset.first_thousand.load_inputs@68bde7e075
  - lupin_mcp.reuse_needset.first_thousand.exit_status@d42a152d3e
  - lupin_mcp.reuse_needset.first_thousand.run_cli@2b9e55e56d
  - lupin_mcp.reuse_needset.first_thousand.main@c0f97e3113
  - lupin_mcp.reuse_needset.first_thousand.live_control@5a2bebf949
  - lupin_mcp.reuse_needset.first_thousand.live_run@81c25cfae3
---
# Need set: the first-thousand run, the command

The live control, the command line and the capped run. The planted pool and the remainder are on [[needset-first-thousand]].

## The live control
- `control_job` builds the drafter's job for one pair. The seed is the original and the one key is the rewrite, so the leak check keeps the rewrite out of the sentence.
- `planted_stage_for` builds the planted stage from the live one's own folders, client, arm, K and fusion, with no refresher. It loads the live vectors from disk and adds the planted rows in memory. Its query cache is the run folder's `query-cache`, so nothing of the run goes into the live data folder.
- `control_stage_live` drafts the 20 needs first, one at a time. It then plants, asks the checker through `planted_check`, removes the planted records and proves the pool is as it was. The pool is the index's own sendable entries.

## The command
- `parse_args` requires the root, run folder, planted file, answer key, labels folder, seed and source commit. The cap is 1,314 unless `--limit` says otherwise. `--partners` turns the partner search on; without it each seed is its own known answer. `--second-model` and `--probe-model` default to Opus.
- `load_inputs` reads the 20 pairs and their groups for reading only, and the planted file must match its recorded hash. `main` without `--live` prints `plan` and contacts nothing. The plan shows the cap, the calls spent, the groups and the flagged count.
- `main` with `--live` first needs `--cli-path` (without it: `NO_CLI_PATH`) and points every Claude Code call at that binary. It then builds the context. A context with no candidate stage raises `NO_CANDIDATE_STAGE`, naming the three variables that build it.
- `live_run` exports the source commit, then draws and writes the seed lists, builds the live parts ([[needset-stage-parts]]) and runs the four stages. A second run over other seed lists raises `PLAN_ALREADY_WRITTEN`. `write_seed_lists` draws 50 attribution and 100 yield seeds from the index.
- `live_parts` builds the parts with their own ledgers in the run folder. `stage_factories` hands the lists file and the parts to the two stages and adds the counts of seeds that gave no final need. A stage whose every seed was skipped fails with `ALL_SEEDS_UNREADABLE`. So does a stage with no need and a skipped seed, as `NO_NEEDS_WITH_SKIPS`.
- `main` closes the Jev spend-ledger run when the stages end, by any ending after the context is built (`reuse_tools.close_run`). It returns `closed_run`. A close that raises during another error never replaces that error. After a clean finish it is returned as `close_error` and the exit status is 1.
- `exit_status` gives 1 when any stage failed, 3 when the cap or a stage's own budget ended a stage and none failed, else 0. The argument parser keeps 2 for a usage error. A stop on a finding exits 0. `run_cli` prints the report as JSON first.
- The control runs `CONTROL_PASSES` (two) times. `live_control` gives each later pass its own drafting ledger and query-cache folder, so the second pass asks again. The report is the first pass's plus `passes` and `consistent`, true when every pass missed the same pairs. The stage stops if any pass missed a pair. A pass ended by the stage budget leaves the finished passes in `passes`, with `budget_reached`.
- `run_first_thousand` installs the cap over `call-ledger.jsonl` in the run folder, with each stage's budget, runs the four stages and writes `stage-reports.json`. A resumed run keeps the calls already spent.
