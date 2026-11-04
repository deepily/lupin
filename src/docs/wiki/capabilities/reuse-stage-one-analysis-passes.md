---
capability: reuse-stage-one-analysis-passes
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1_analysis.pass_one@b6ede74629
  - lupin_mcp.reuse_stage1_analysis.pass_two@8f8f015a91
  - lupin_mcp.reuse_stage1_analysis.pass_three@ee6d4a28e8
  - lupin_mcp.reuse_stage1_analysis.evaluate@4db341eb43
  - lupin_mcp.reuse_stage1_analysis.stop_rules@8a6c3690c3
  - lupin_mcp.reuse_stage1_analysis.check_canary@449b8d1c86
---
# Reuse stage-one analysis: passes and stop rules

Three passes decide which pack size is safe, and the stop rules decide what happens between questions. Arm reading is on [[reuse-stage-one-analysis-arms]].

## The passes
- `pass_one` passes when the 99th percentile of the per-entry difference between a pack arm and single run 1 is within the noise floor. It is `inconclusive` when the floor is `None`.
- `pass_two` counts flips at the threshold on boundary entries. It passes when the pack's flips are at most the noise flips plus one.
- `pass_three` checks that the probe entry stays within the floor of its single value in all six placements. It is `inconclusive` while a probed question lacks a placement, and `invalid` when a probe arm was stopped.
- A placement given twice for a question raises `ValueError`.
- `evaluate` applies the three passes to each pack size. The default size is the largest that passes; pass three gates only the size it was run at.
- A size that would pass reads `inconclusive` while fewer than 90 pooled boundary entries were seen. The decision stops and asks if any size is invalid or none passes.

## Stop rules
- `stop_rules` reads the rules that stop the stage between questions. They cover the stage ceiling, spend after question 1, and a single run 1 that is absent or not clean.
- An invalid arm of any question stops the stage ahead of an unclean single run 1. Fewer than 50 pooled boundary entries after question 2 stops before question 3.
- Spend counts every attempt, a superseded one too. A retry such as the second canary attempt never stands in for a required arm.

## Canary check
- `check_canary` recomputes the canary's stop conditions from the arm's own rows and compares them with the driver's list.
- It trips on output per entry over the stop figure and usage over a row's reserve. It also trips on any refusal, an answered row with no usage, a model mismatch, an unfinished arm and an arm that sent no request.
