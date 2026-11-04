---
capability: needset-judge-readings
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.judge_readings.rating_of@b652627ce1
  - lupin_mcp.reuse_needset.judge_readings.entry_key@0b6a19b4f8
  - lupin_mcp.reuse_needset.judge_readings.SweepTap@af7500aacf
  - lupin_mcp.reuse_needset.judge_readings.judge_reading@7a6b1bbf00
  - lupin_mcp.reuse_needset.judge_readings.readings_of@dc376d104a
  - lupin_mcp.reuse_needset.judge_readings.write_readings@4e663d39ca
---
# Need set: judge readings

A control run used to keep only whether a plant was accepted. The rating itself, the `p_overlap` the judge gave, lived only in the Jev cache. This module records each reading as the checker takes it. It writes them beside the stage report in `judge-readings.json`, and changes nothing the checker sees. The control is on [[needset-first-thousand-command]] and its rows on [[needset-control-scoring]].

## What is recorded
- `rating_of` reads one answer's probabilities as `{ p_overlap, confidence, choice }`. `p_overlap` is the reuse plus extend share to 6 places. A malformed answer gives `None`.
- `entry_key` names the cache entry the judge reads for a candidate: the packed candidate key for a packed request. Otherwise it is the hash of the one-request body.
- `SweepTap` wraps a context's sweeper on a copy. Every call returns what the real sweeper returns. The tap keeps the keys, answers, failed ids and ids not reached.
- `judge_reading` turns one entry's taps into `judged`, with its rating, or `not_judged` with a reason. The reasons are `malformed_answer`, `failed`, `not_reached`, `no_answer`, `not_retrieved` and `retrieved_not_sent`.

## Writing
- `readings_of` pulls each pair's plant and original readings out of a stage report, per pass. A report with no control stage gives no rows.
- `write_readings` writes `judge-readings.json` in the run folder, derived from the report's rows so the two cannot disagree. `run_first_thousand` calls it on every write of the report.
