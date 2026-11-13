---
capability: util-agreement-stats
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.agreement_stats.mcnemar_exact@f383c680a6
  - cosa.utils.agreement_stats.percentile@beba0273a0
---
# Agreement statistics shared by the duplicate check and the reuse tools

`cosa.utils.agreement_stats` holds the two small statistics that both the duplicate check proof and the reuse tools need. It sits under `cosa.utils` because the duplicate check may not import `lupin_mcp`, while `lupin_mcp` may import `cosa`. See [[duplicate-check-proof-ledger-agreement]] and [[reuse-end-to-end-run]].

## Rules
- `mcnemar_exact( only_a, only_b )` is the exact two-sided McNemar p of two discordant counts. It returns 1.0 when both are zero.
- `percentile( values, q )` is the q-th percentile, with q from 0 to 1, by linear interpolation. It sorts its own input and returns None for an empty list.
- Both are pure functions. Import them from here; do not write a third copy.

## Don't
- Don't import `lupin_mcp` from a `duplicate_check` module to reach them. That is the reason they live here.
