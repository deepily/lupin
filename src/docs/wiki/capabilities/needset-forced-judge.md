---
capability: needset-forced-judge
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.forced_judge.missed_ids@66ead3d242
  - lupin_mcp.reuse_needset.forced_judge.resolved_label@eea748b36e
  - lupin_mcp.reuse_needset.forced_judge.pair_labels@dff2fc68ef
  - lupin_mcp.reuse_needset.forced_judge.frozen_needs@2effc7ef2a
  - lupin_mcp.reuse_needset.forced_judge.plant_lines@01b689f427
  - lupin_mcp.reuse_needset.forced_judge.load_pairs_needs_labels@40ea717627
  - lupin_mcp.reuse_needset.forced_judge.build_rows@da73db5463
  - lupin_mcp.reuse_needset.forced_judge.forced_ids@5b9935f831
  - lupin_mcp.reuse_needset.forced_judge.plant_answer@9f6d1f5b45
  - lupin_mcp.reuse_needset.forced_judge.judge_row@9b9a0c6bd9
  - lupin_mcp.reuse_needset.forced_judge.summarize@353b54053b
  - lupin_mcp.reuse_needset.forced_judge.plan_of@0f4bab37b0
  - lupin_mcp.reuse_needset.forced_judge.run_live@c0977643a7
  - lupin_mcp.reuse_needset.forced_judge.parse_args@ef4fafef56
  - lupin_mcp.reuse_needset.forced_judge.collect_rows@84b75b87c8
  - lupin_mcp.reuse_needset.forced_judge.main@598bdd817c
  - lupin_mcp.reuse_needset.forced_judge.run_cli@2b9e55e56d
---
# Need set: forced judge

Asks the judge about each planted rewrite that retrieval missed, with the plant placed in the shortlist of 128. It shows whether the judge would have accepted what the search never showed it. The control it follows is [[needset-positive-control]]. The `in_pack` variant is on [[needset-forced-judge-in-pack]].

## Rows
- `missed_ids` reads the control's missed pairs from a stage report. `frozen_needs` reads each pair's draft from the saved control ledger and never asks a model.
- `resolved_label` and `pair_labels` give each pair its human label: both raters' choice when they agree, the third rater's when they differ, else unresolved.
- `build_rows` keeps the missed pairs that have a draft and lists the rest as undrafted. `load_pairs_needs_labels` is the one loader behind `collect_rows` and the judge probe's `collect_records`. `plant_lines` reads the plants' purpose lines.

## Judging
- `forced_ids` keeps the first 127 places of the real shortlist beside the plant. A plant already in the first 128 was asked in the real run, so nothing is asked for it.
- `judge_row` asks the 127 in the usual packs and the plant in a pack of its own. `plant_answer` reads the plant's overlap against the policy threshold, and calls it accepted at or above it.
- `summarize` counts accepts by human label.

## Running
- `plan_of` counts the pairs by label. It plans four requests per pair, or three per job of the in_pack variant.
- `run_live` runs through `call_cap.run_under_cap`. It charges every request to the `forced_judge` stage and writes `forced-judge-report.json`. A cap or budget stop keeps the finished rows, and the variant supplies the summary.
- `main` without `--live` reads files only and builds no context, so the spend ledger is untouched. A live run needs `--run-name`, a fresh spend run name, and `--ceiling`; it closes its spend run when it ends. `collect_rows` reads the files, `parse_args` reads the line including `--variant`, and `run_cli` prints the result.
