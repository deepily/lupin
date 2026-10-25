---
capability: needset-drafting-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.run.Env@aa76ae98c8
  - lupin_mcp.reuse_needset.run.cell_name@4346c0b38c
  - lupin_mcp.reuse_needset.run.write_or_check_plan@6bb2354b7f
  - lupin_mcp.reuse_needset.run.near_copy_job@77d638cde1
  - lupin_mcp.reuse_needset.run.routed_job@848e2bcbb8
  - lupin_mcp.reuse_needset.run.nothing_job@87a5ce11f8
  - lupin_mcp.reuse_needset.run.route_table@c2294fde60
  - lupin_mcp.reuse_needset.run.job_maker@f2d0b02da6
  - lupin_mcp.reuse_needset.run.to_need@5c68736119
  - lupin_mcp.reuse_needset.run.cell_specs@15214c71c2
  - lupin_mcp.reuse_needset.run.run_needset@ff1643494a
---
# Need set: drafting run

Runs the drafting end to end: plan, draw, one job per seed, parallel cells, needs and a report. Nothing here talks to a model or an index by itself. The caller hands in the pieces, so a test can use fakes. The smoke run that drives it is on [[needset-smoke-run]].

## Environment and jobs
- `Env` holds everything a run reads: records, search context, model calls and run labels. Its `freeze_from` is the index folder and vector folder to freeze, and may be `None` only for a smoke run.
- `cell_name` joins the kind and language with a slash.
- `near_copy_job` builds the job for a seed keyed on its twin group, or `None` without a twin.
- `routed_job` builds the job for a work-alike seed through its route, or `None` without a key.
- `nothing_job` builds the job for a file: the entry line of each eligible symbol in it.
- `route_table` maps seed ids to routes for a work-alike cell, half and half over the draw order.
- `job_maker` returns a cell's job function. It takes a seed id and returns a job, or `None` when the seed has no key. Routes are assigned over the whole order, spares included.

## Plan and run
- `write_or_check_plan` writes the plan record once. A resume with an identical record changes nothing, and a different plan on disk raises `PLAN_ALREADY_WRITTEN`.
- `to_need` turns an accepted draft into a need record. A nothing need has no seed, key or route, and a smoke run marks the need as smoke.
- `cell_specs` builds the specs for the cell drafter, one per cell with a wanted count, in sorted cell order.
- `run_needset` writes the plan first, with the reader the pool used. A real run then freezes the index and vectors ([[needset-freeze]]). It then draws, drafts every cell, and writes the drafts and the report.
- It returns the plan, census, cells, needs, report and the frozen hashes, with the needs in cell order and then draw order. A cell that runs out of seeds raises `QUOTA_UNFILLABLE`. A real run with no `freeze_from` raises `FREEZE_INCOMPLETE`.
- When the quota holds nothing needs, the caller must set the nothing drafter.
