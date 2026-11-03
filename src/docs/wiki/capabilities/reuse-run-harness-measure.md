---
capability: reuse-run-harness-measure
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.measure.working_seconds@0920a5c2e4
  - lupin_mcp.reuse_harness.measure.working_days@1828f6d49d
  - lupin_mcp.reuse_harness.measure.guard_reached@54084c5b22
  - lupin_mcp.reuse_harness.measure.parse_stats@355c2819dc
  - lupin_mcp.reuse_harness.measure.peak_agents@1b51f43e84
  - lupin_mcp.reuse_harness.measure.Meter@fe67d15243
  - lupin_mcp.reuse_harness.measure.Meter.read@af609f1d4d
  - lupin_mcp.reuse_harness.measure.Clock@4517cadd2f
  - lupin_mcp.reuse_harness.measure.Clock.now@a6ca4c8ea5
---
# Reuse run harness: measurements and the pilot guard

The pilot pair sizes the cap and says how many pairs one machine can run (plan 3, section 7.4). Each run therefore records what it costs. The loop is in [[reuse-run-harness]].

## What a verdict records
- `working_days` and `wall_hours` since the first slice began. The clock starts after the arm proof, so set-up is not counted.
- `cpu_seconds` and `peak_rss_bytes` from `Meter.read`. They cover the commands the harness has finished. The memory figure is the largest single process, not a sum of overlapping ones.
- `server_peak_rss_bytes` and `server_peak_cpu_percent`: the largest `Servers.sample` reading so far. A reading that failed leaves the peak as it was. A run with no reading logs `None`.
- `peak_seats`: the largest `seats` any slice reported. It is a lower bound: a background subagent that spans messages is not counted. A slice cut off by its limit counts the calls it printed. The tool names `Agent` and `Task` are an assumption until a live pilot shows them.
- The stop record names `working_zone` and carries `measure.NOTES`, so the log states its own limits.

## Working days
- `working_seconds` counts the seconds that fall on a weekday in the `app timezone` zone. A Saturday or Sunday adds nothing. Nights count, because the harness cannot pause a run and cannot know when the host was off.
- `working_days` divides by 86400. `guard_reached` is true once 10 working days are used.

## The pilot
- `--pilot` makes the spec's cap `None`. The run has no seat-hour cap. It stops at `all_pass`, or at `guard_working_days` after 10 working days, or at `session_ended`.
- Each slice is given the working hours left under the guard. `time_to_all_pass_working_days` is set only when the stop is `all_pass`.
- The cap for scored runs is 1.5 times the slower arm's `time_to_all_pass_working_days`, rounded up to whole days.

## Don't
- Don't read `peak_rss_bytes` as the memory a run needs. Add the server's peak, and note that sampling can miss a spike.
- Don't count the pilot's logs in a scored set.
