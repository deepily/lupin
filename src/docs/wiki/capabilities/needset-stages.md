---
capability: needset-stages
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stages.attribution_report@9f0ed9a947
  - lupin_mcp.reuse_needset.stages.run_yield@7556cdb9c6
  - lupin_mcp.reuse_needset.stages.run_remainder@15df1f6811
  - lupin_mcp.reuse_needset.stages.run_stages@441b2ae18d
---
# Need set: stage runner

Runs the four stages of the first 1,000 model calls under one cap: attribution, yield, control and remainder. It makes no call of its own. It builds no packet, takes no person's ruling and writes no label file. The cap is on [[needset-call-cap]].

## Stages
- `attribution_report` summarises a member trace. It stops the run when no member was lost at a named stage.
- `run_yield` draws a need and its partners for each seed, one at a time. It then counts the hard rows per language with a 95 percent interval. It stops when a language with 100 seeds has no hard row. A language with fewer seeds is reported as short.
- `run_remainder` runs the synthetic pairs through the run-check and counts the drifted pairs caught and the unsure pairs resolved. It contacts no model.

## Running
- `run_stages` refuses with `CAP_NOT_INSTALLED` unless the cap's `charge` is the transport's hook, so no call goes uncounted.
- It runs the stages in order, each inside its own stage name. A stage report with a stop, a named failure or `CALL_CAP_REACHED` ends the run, and later stages are not run.
- The report gives the calls used, the calls by stage and the stages that spent more than their planned allowance. The plan is a guide, and only the cap stops the run.
