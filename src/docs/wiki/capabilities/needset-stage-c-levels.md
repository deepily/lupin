---
capability: needset-stage-c-levels
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_c_score.threshold_free_level@b15fd8f37a
  - lupin_mcp.reuse_needset.stage_c_score.line_level@65441b5c8d
  - lupin_mcp.reuse_needset.stage_c_score.repeat_floor@9dc145965d
  - lupin_mcp.reuse_needset.stage_c_score.cap_level@b0bbf6de5c
  - lupin_mcp.reuse_needset.stage_c_score.lowest@8535c9a557
  - lupin_mcp.reuse_needset.stage_c_score.side_a_check@20e5950ef1
  - lupin_mcp.reuse_needset.stage_c_score.valid_run@ee2da414db
  - lupin_mcp.reuse_needset.stage_c_score.refused_row@d85b4945d3
  - lupin_mcp.reuse_needset.stage_c_score.coverage@92f6c43905
  - lupin_mcp.reuse_needset.stage_c_score.score@a00e5c0920
  - lupin_mcp.reuse_needset.stage_c_score.parse_args@ef9d6fb967
  - lupin_mcp.reuse_needset.stage_c_score.render@0ce40d9f22
  - lupin_mcp.reuse_needset.stage_c_score.main@b794d18c60
---
# Need set: scoring the judge-only run, levels and checks

Turns the figures of [[needset-stage-c-figures]] into levels and checks. The mark is `io/write-ups/2026.11.02-stage-c-mark-chloe.md`, and each constant cites its section.

## Levels
- `threshold_free_level` names an AUC level: inverted, none shown, weak, moderate or strong. `line_level` says whether the production line of 0.30 is usable.
- The line is usable when D is at least 0.40, its Newcombe lower bound is above 0, and not-same acceptance is at most 0.50.
- `repeat_floor` measures the judge's noise as the largest minus the smallest of the repeats' figures.
- `cap_level` caps a level by that floor in both directions. `lowest` picks the lowest of several levels in a given order.

## Checks
- `side_a_check` needs 95 percent of side-a ratings at the line or higher, and a median of 0.90.
- `valid_run` needs every post to have its own request hash and report tokens. Every pair needs three repeats, and a stray `shared_with` copy fails the run.
- `refused_row` prints the refused pairs as a fixed row outside the population. `coverage` reports drafting losses beside it. Over 15 percent lost in either class awards no level.

## Running
- `score` joins it all and returns coverage, validity, the side-a check, the populations and a headline. The headline is the lowest level of the populations.
- A run that is not valid, or fails the side-a check, awards none. A report with no `refused` key is not valid.
- `parse_args` reads `--report`, `--out` and `--resamples`. `render` writes the text and `main` prints a summary.
