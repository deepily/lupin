---
capability: v2-eval-metrics-and-guards
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.v2_eval.percentile@4330c1ce7f
  - scripts.v2_eval.route_matches@5bab207ef8
  - scripts.v2_eval.compute_metrics@22f3fc5e68
  - scripts.v2_eval.threshold_table@61e1e23e20
  - scripts.v2_eval.latency_delta@94e0927d3c
  - scripts.v2_eval.EvalIntegrityError@53a46fbfc7
  - scripts.v2_eval.guard_run_integrity@a3ffd0df77
  - scripts.v2_eval.guard_cold_start@bbe8801869
  - scripts.v2_eval.read_jsonl_trace_ids@a35d8f861b
  - scripts.v2_eval.neighbouring_trace_paths@67d9ab4ba5
  - scripts.v2_eval.read_trace_ids_around@47bd8161ec
  - scripts.v2_eval.clean_v2_snapshot_store@ca1be40a2b
---
# CJ Flow v2 eval: metrics and integrity guards
These functions of `src/scripts/v2_eval.py` score a pass and refuse a run that cannot be trusted. Readers of one record are on [[v2-eval-corpus-and-records]]; the run itself is on [[v2-eval-run-and-report]].
- `percentile` is the linear-interpolated percentile, None for an empty list. `route_matches` compares the router's command with the expected one, ignoring case and outer spaces.
- `compute_metrics` returns counts, rates, latency percentiles, routing accuracy, the would-be-wrong count and path counts for one pass. Each rate divides by completed requests, so a failed call never inflates it.
- The cache rates divide by observed requests only, and the error rates by observed answered ones. Each family publishes its measurable, observed and unobserved counts.
- `threshold_table` gives hit rate per similarity floor from the recorded scores. `latency_delta` gives the cold to warm change of p50 and p95.
- `EvalIntegrityError` means the run lied, not that it scored low.
- `guard_run_integrity` raises it unless three things hold. Every request returned 200, every trace id is in the day's trace file, and the router error rate is under its cap.
- `guard_cold_start` raises it when the cold pass shows any cache hit, because a pre-warmed store contaminates the cold to warm delta.
- `read_jsonl_trace_ids` lists the trace ids of one file. `neighbouring_trace_paths` and `read_trace_ids_around` widen that to the day before and after.
- `clean_v2_snapshot_store` truncates v2's snapshot and synonym tables. It runs a config cross-check and a measurement-database check first, and raises before any `TRUNCATE` if either fails.
