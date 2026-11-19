---
capability: duplicate-check-baseline-finding
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.is_baseline_finding@405e5a804e
---
# Duplicate check, baseline finding

One test of [[duplicate-check-daily-run]]: did a finding come from a baseline sweep.

## What it does
- `is_baseline_finding( finding )` is true when the finding's window holds no commits, read from `window.commits`.
- Only a baseline window has no commits. A daily window with none adds no definition and so no finding.
