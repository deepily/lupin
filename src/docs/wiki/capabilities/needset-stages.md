---
capability: needset-stages
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stages.attribution_report@9f0ed9a947
  - lupin_mcp.reuse_needset.stages.run_yield@7556cdb9c6
  - lupin_mcp.reuse_needset.stages.run_remainder@15df1f6811
  - lupin_mcp.reuse_needset.stages.run_stages@1385d5c24c
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
- A stage that spends its own budget ends as `budget_reached`, and the stages after it still run, because it took nothing from them. The budgets (`STAGE_BUDGETS`, 1 November 2026) are attribution 300, yield 600, control 250 and remainder none. Yield is the sample of about 100 random seeds. Control is two passes of the 20 planted pairs. The other 164 of the 1,314 calls are unallocated, held for Rick.
- The report gives the calls used, the calls by stage and the stages that spent more than their planned allowance (`PLANNED_CALLS`). Only a cap built without stage limits can show that.
