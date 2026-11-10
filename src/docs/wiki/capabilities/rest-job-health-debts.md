---
capability: rest-job-health-debts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.job_health.window_points@b271e0eb96
  - cosa.rest.job_health.scan_grew@318047b2c5
  - cosa.rest.job_health.no_drain@7646ad05fa
  - cosa.rest.job_health.clears_in@056e341aa2
  - cosa.rest.job_health.freshness_of@908c6a8aef
  - cosa.rest.job_health.fix_piling@2c2003de58
  - cosa.rest.job_health.scan_out@48111ce6ba
  - cosa.rest.job_health.fix_out@8a991e95a1
---
# Background job health: scan and fix debts

The debt tests and blocks behind the behind state of a job. The state rules are in [[rest-job-health-rules]]. A scan debt is work a job has not yet got through. A fix debt is the rows it filed that are still open.

## Scan debt
- `window_points` keeps the points no older than the window, oldest first.
- `scan_grew` (test A) returns the earliest and latest counts when the count rose by at least the item minimum and the percent minimum. It returns `None` with fewer than two points.
- `no_drain` (test B) is true only when debts remain and each of the last two points says it drained zero. A missing figure is not a zero.
- `clears_in` says when the debt clears at the rate of the window. It answers not enough runs, zero days when the count is 0 or never at this rate when the debt did not fall. Otherwise it answers the days left.
- `freshness_of` builds the freshness block of a refresh job. The age in hours is worked out at read time and never stored.
- `scan_out` turns a stored scan block into the page block, with its freshness and `clears_in`.

## Fix debt
- `fix_piling` (test C) is true when three things hold. Rows open now exceed zero. More rows opened than closed in the window. The open count is not below the count at the window start. With no store counts it is false, and the page says open rows are not reported.
- `fix_out` builds the fix block. The open and closed counts come from the store only, and are `None` when the store was not asked or failed.
