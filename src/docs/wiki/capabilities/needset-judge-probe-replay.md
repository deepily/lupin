---
capability: needset-judge-probe-replay
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.judge_probe.cached_key@f700ae33ac
  - lupin_mcp.reuse_needset.judge_probe.read_cached@11dd33157c
  - lupin_mcp.reuse_needset.judge_probe.collect_records@d92a9cfa39
  - lupin_mcp.reuse_needset.judge_probe.pair_records@a06d83b910
  - lupin_mcp.reuse_needset.judge_probe.rating_dump@64ebfd4f61
  - lupin_mcp.reuse_needset.judge_probe.threshold_sweep@768abd7a42
  - lupin_mcp.reuse_needset.judge_probe.forced_agreement@1a8da5e4d9
  - lupin_mcp.reuse_needset.judge_probe.render_table@fba764b2ff
  - lupin_mcp.reuse_needset.judge_probe.replay@c2ee46bf38
---
# Need set: the judge probe, replay

Asks whether the judge's `p_overlap` rating tells a same-job plant from a not-same one, on the 17 control pairs already held. This page is the replay, which calls no model. The asking is on [[needset-judge-probe-arms]], the read on [[needset-judge-probe-figures]].

## What it reads
- In Part 2 the judge read a plant as its id and signature alone. A real entry carries a docstring and a purpose line too.
- `cached_key` names the cache entry the production judge read for a candidate. `read_cached` looks the rating up and never asks the model.
- A pair with no cached rating is named, never asked again.
- `collect_records` reads each drafted pair, its frozen need, label and judged records from files. `pair_records` pairs a control row with the records the judge saw.

## What it writes
- `rating_dump` reads the saved plant and original rating of every pair.
- `threshold_sweep` counts what each threshold from 0.10 to 0.50 would put on the shortlist.
- `forced_agreement` compares the plant ratings with the forced judge's run ([[needset-forced-judge]]).
- `render_table` writes the dump and the sweep as markdown.
- `replay` runs all of that and writes both files. It builds no context and writes nothing to the cache or the spend ledger.
