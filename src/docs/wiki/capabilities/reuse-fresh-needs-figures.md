---
capability: reuse-fresh-needs-figures
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_phase5_stage.agreement@384399e870
  - lupin_mcp.reuse_phase5_stage.false_reuse@e8fbd288b8
  - lupin_mcp.reuse_phase5_stage.tokens_per_need@54a1d46b9b
  - lupin_mcp.reuse_phase5_stage.report_lines@22cc89a90b
  - lupin_mcp.reuse_phase5_stage.report@0ef0c67f1b
---
# Reuse fresh-needs figures

The report of the fresh-needs run, read from the result files. It sends nothing. The run is on [[reuse-fresh-needs-run]].

## Figures
- `agreement` compares the stage's lookups with the full sweep on the sampled needs. It reports how often the final verdicts match, and recall at ten pooled over the sweep's picks.
- A need whose sweep picked nothing counts in the comparison but not in recall. Recall is agreement with the full search, not ground truth.
- `false_reuse` counts how often a lookup calls reuse on a need written to have no match. It reports reuse as the headline and extend beside it, each with a Wilson interval.
- `tokens_per_need` sums the tokens of a need's lookup and every repeat. A need counts only when all of them are complete.

## Report
- `report_lines` starts with the verdict policy line, then the flip lines of the flip driver on the repeats only, then the other figures.
- With no sweep result it says recall and verdict agreement are not measured yet. With no absent needs it says false reuse is not measured.
- `report` reads the canary and run results of the prefix, plus the sweep result when there is one, and prints the lines.
- It raises `DriverRefused` when no stage result exists, a result fails `check_results`, or the sweep carries another sample hash.
