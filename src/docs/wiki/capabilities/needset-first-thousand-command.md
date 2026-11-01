---
capability: needset-first-thousand-command
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.first_thousand.run_first_thousand@77407ae439
  - lupin_mcp.reuse_needset.first_thousand.control_job@da8024fd0c
  - lupin_mcp.reuse_needset.first_thousand.planted_stage_for@d5537af534
  - lupin_mcp.reuse_needset.first_thousand.control_stage_live@2553ab4a6f
  - lupin_mcp.reuse_needset.first_thousand.tracked_files@0eecf6442d
  - lupin_mcp.reuse_needset.first_thousand.write_seed_lists@7e9eadb068
  - lupin_mcp.reuse_needset.first_thousand.live_parts@22adc07ae5
  - lupin_mcp.reuse_needset.first_thousand.stage_factories@4a1c93709b
  - lupin_mcp.reuse_needset.first_thousand.parse_args@f520014819
  - lupin_mcp.reuse_needset.first_thousand.plan@6de27be30d
  - lupin_mcp.reuse_needset.first_thousand.load_inputs@68bde7e075
  - lupin_mcp.reuse_needset.first_thousand.main@d64156ab31
---
# Need set: the first 1,000 calls, the command

The live control, the command line and the capped run. The planted pool and the remainder are on [[needset-first-thousand]].

## The live control
- `control_job` builds the drafter's job for one pair. The seed is the original and the one key is the rewrite, so the leak check keeps the rewrite out of the sentence.
- `planted_stage_for` builds the planted stage from the live one's own folders, client, arm, K and fusion, with no refresher. It loads the live vectors from disk and adds the planted rows in memory. Its query cache is the run folder's `query-cache`, so nothing of the run goes into the live data folder.
- `control_stage_live` drafts the 20 needs first, one at a time. It then plants, asks the checker through `planted_check`, removes the planted records and proves the pool is as it was. The pool is the index's own sendable entries.

## The command
- `parse_args` requires the root, run folder, planted file, answer key, labels folder, seed and source commit. The cap is 1,000 unless `--limit` says otherwise.
- `load_inputs` reads the 20 pairs and their groups for reading only. The planted file must match its recorded hash.
- `main` without `--live` prints `plan` and contacts nothing. The plan shows the cap, the calls already spent, the groups and the flagged count.
- `main` with `--live` gets the attribution and yield parts, builds the context, writes the seed lists, and runs the four stages. Parts that are not built raise `STAGE_NOT_WIRED` before a context is built or a list is written.
- `write_seed_lists` draws the 50 attribution and 100 yield seeds from the tree's index and tracked files, and writes them once to the run folder. `tracked_files` is the set git lists.
- `stage_factories` hands that file and the parts to the attribution and yield stages. `live_parts` is the part that is not built: it names `make_need`, `trace_fn` and `prepare_fn`.

## The run
- `run_first_thousand` installs the cap over `call-ledger.jsonl` in the run folder, runs the four stages and writes `stage-reports.json`. A resumed run keeps the calls already spent.
