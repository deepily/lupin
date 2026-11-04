---
capability: needset-stage-c-figures
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_c_score.mean_ratings@714e06092c
  - lupin_mcp.reuse_needset.stage_c_score.population_pairs@79b10d7c09
  - lupin_mcp.reuse_needset.stage_c_score.split@1795a456f7
  - lupin_mcp.reuse_needset.stage_c_score.auc_counts@59642d33e0
  - lupin_mcp.reuse_needset.stage_c_score.aucs@926510cb0e
  - lupin_mcp.reuse_needset.stage_c_score.percentile@beba0273a0
  - lupin_mcp.reuse_needset.stage_c_score.bootstrap@52054210dc
  - lupin_mcp.reuse_needset.stage_c_score.newcombe@e330d34c7f
  - lupin_mcp.reuse_needset.stage_c_score.spread@1711fce0f9
  - lupin_mcp.reuse_needset.stage_c_score.acceptance@c43d7667ee
  - lupin_mcp.reuse_needset.stage_c_score.reach_line@08d4afd7be
  - lupin_mcp.reuse_needset.stage_c_score.pearson@fd5c2947b3
  - lupin_mcp.reuse_needset.stage_c_score.pair_sd_median@51745f66f0
  - lupin_mcp.reuse_needset.stage_c_score.figures@87559576ed
---
# Need set: scoring the judge-only run, figures

Scores the judge-only report against the mark written before any call. It reads `stage-c-report.json`, makes no model call and writes nothing to the spend ledger. The levels and checks are on [[needset-stage-c-levels]]; the run is on [[needset-stage-c-command]].

## Ratings and AUC
- `mean_ratings` collects each pair's ratings across its repeats. `population_pairs` picks one of four populations: all drafted, without unsure pairs, two agreeing raters, or without name-cue pairs.
- `split` groups rated pairs by stratum and class. `auc_counts` counts the pairings in which the same-job rating is higher, ties one half.
- `aucs` gives the within-stratum AUC, the stratum-weighted primary and the pooled AUC.
- `percentile` and `bootstrap` give the 95 percent interval of each AUC. They resample within class and stratum with a fixed seed.

## Acceptance
- `acceptance` counts accepts at a line in each class. `reach_line` reads the not-same acceptance at the line where same-job acceptance reaches 0.80.
- `newcombe` gives a difference of two proportions with its 95 percent interval. `spread` summarises a list of numbers.

## Whole population
- `pearson` and `pair_sd_median` serve the side-a check and the repeat noise.
- `figures` computes every figure of sections 2 to 5 of the mark for one population.
