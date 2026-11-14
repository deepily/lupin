---
capability: duplicate-check-sample-rejudge
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_sample_rejudge.population_pairs@e6236cbcc8
  - lupin_mcp.duplicate_check_sample_rejudge.frame_ids@b8ef9be3ba
  - lupin_mcp.duplicate_check_sample_rejudge.draw@2c82687888
  - lupin_mcp.duplicate_check_sample_rejudge.matched_pairs@437e530571
  - lupin_mcp.duplicate_check_sample_rejudge.estimate@1db36ec234
  - lupin_mcp.duplicate_check_sample_rejudge.render@61a842c74b
  - lupin_mcp.duplicate_check_sample_rejudge.main@e536a15cff
---
# Duplicate check sample re-judge
When the reference model returns, this corrects the interim judge's flag rate. It draws a seeded sample of the definitions the interim model ruled itself. The reference model judges them again on a slot of its own. The average gap between the two models is added to the interim rate. Without `--go` it prints the sample and the plan and makes no call. It runs through the live path of [[duplicate-check-self-consistency]]. The weekly rates it corrects are in [[duplicate-check-drift-report]].

## What it does
- `population_pairs` sums the pair verdicts the interim model made itself. It reads every result file with a `pairs` entry for it ([[duplicate-check-daily-run]]).
- `frame_ids` lists the definitions that model judged itself in those same runs. So every sampled definition belongs to a run whose counts are in the population. `draw` takes the seeded sample.
- `matched_pairs` pairs up what the two models said about the same definition and candidate, as a 0 or 1 flag each, grouped by definition. Pairs only one pass ruled are counted and left out.
- `estimate` returns the interim rate over all its pairs, the gap on the matched pairs, and their sum as the estimated rate. The interval is 95 percent and normal.
- Its variance adds the interim rate's variance to a ratio variance of the gap. That one treats each definition as a unit, because the pairs of one definition are not independent.
- With fewer than two definitions it gives no interval. With no matched pair it gives no rate.
- The reference model's slot must be 2 or more, and `main` refuses a lower one. Slots 0 and 1 hold the interim model's rulings. A saved ruling of any model is reused on its slot before any call.
- `render` prints the plan, or the table with the estimate, the interval, the gap, the unmatched count, the calls made and the definitions left out. `main` returns 0, or 3 with the reason when the slot, the size, a file, the sample, the lock or the day's budget refuses. `--ruled-by`, `--rejudge-with` and `--size` have no default.

## Limits
- The reference model needs its own entry in the INI key `duplicate check daily call budget`. A model with no entry does not run.
- The interim rate's own variance treats pairs as independent, so the interval is a little narrow.
- Runs written before `pairs` existed are outside both the population and the sample.
