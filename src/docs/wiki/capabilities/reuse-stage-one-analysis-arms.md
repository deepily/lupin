---
capability: reuse-stage-one-analysis-arms
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1_analysis.lost_limit@55da746450
  - lupin_mcp.reuse_stage1_analysis.read_arm@9058123a60
  - lupin_mcp.reuse_stage1_analysis.read_stage@7dd371bf4c
  - lupin_mcp.reuse_stage1_analysis.percentile@1ecd8c0284
  - lupin_mcp.reuse_stage1_analysis.differences@5bf7811827
  - lupin_mcp.reuse_stage1_analysis.boundary_ids@b679505833
  - lupin_mcp.reuse_stage1_analysis.flips@fb5d8a12bd
  - lupin_mcp.reuse_stage1_analysis.noise_floor@08a8a5a60d
---
# Reuse stage-one analysis: reading the arms

The analysis of the live packing measurement is pure functions on the arm records the driver writes. Nothing here calls a model or reads the cache. Every threshold was fixed before any live number existed. The passes are on [[reuse-stage-one-analysis-passes]].

## Arm status
- `read_arm` turns one arm record into the facts the rules use. An arm is clean, inconclusive or invalid, and only a clean arm can contribute to a pass.
- An arm is invalid when the ceiling, the ledger, refusals or another model stopped it. It is also invalid if any row failed as a model mismatch, or it asked an id twice.
- An arm that asked nothing is inconclusive. Otherwise it is judged by its lost entries: clean at or under the limit, inconclusive above it.
- `lost_limit` is the arm's size divided by 200, rounded down. Lost entries are the asked ids with no valid answer, plus every id named failed, unasked or not reached.
- `read_stage` groups the arm records by question and arm name. A completed rerun of an arm whose earlier attempts hit their ceiling takes the plain name, and those attempts are marked superseded.

## Measures
- `percentile` is the nearest-rank percentile, or `None` for no values.
- `differences` gives the absolute overlap difference per entry, over the ids validly answered in both arms.
- `boundary_ids` lists the entries whose overlap lies in the band 0.35 to 0.65, ends included.
- `flips` lists the entries on opposite sides of a cut between two arms. An overlap equal to the cut counts as above it.
- `noise_floor` is the 99th percentile of single run 1 against single run 2, pooled over the questions. The floor is the larger of that and 0.02.
- A question with an invalid single run is left out of the pool. The state is `invalid` if all are left out, and `inconclusive` if a kept question lacks a clean single run.
