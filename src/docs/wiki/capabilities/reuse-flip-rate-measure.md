---
capability: reuse-flip-rate-measure
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_flip.ask_repeat@1d7d83b23a
  - lupin_mcp.reuse_flip.signature@c49ac8b744
  - lupin_mcp.reuse_flip.flip_rate@2c4ab97ee1
  - lupin_mcp.reuse_flip_run.load_flip_needs@138947c321
  - lupin_mcp.reuse_flip_run.repeat_asks@a8ba347dcc
  - lupin_mcp.reuse_flip_run.report_lines@d741c38653
  - lupin_mcp.reuse_flip_run.check_repeats@0b1a8f50fd
  - lupin_mcp.reuse_flip_run.sendable_ids@d7186dd8c2
  - lupin_mcp.reuse_flip_run.stale_excludes@1f226cad2d
  - lupin_mcp.reuse_flip_run.check_excludes@e0e2d169e1
  - lupin_mcp.reuse_flip_run.main@99d4d2ccf5
  - lupin_mcp.reuse_flip_run.cli@fdb2331ed8
---
# Reuse flip-rate measure
The flip-rate test asks the same need again and again and counts the needs whose answer changes. Thirty needs or more are each asked several times, with every repeat keyed apart. A canary of five needs is read by a person before the rest is paid for. See [[reuse-token-ceiling-and-spend-ledger]].

## Measure
- `ask_repeat( ctx, need, member, run_index )` asks one need once as repeat number `run_index`, leaving the member out. The route is `full` (every entry) or `candidates` (the shortlist only). The question is the old `choice` or the new `provides`, which has no candidate stage.
- `signature( result )` is the verdict and the sorted shortlist ids that must agree between repeats.
- `flip_rate( repeats_by_need )` counts a need as flipped when any two repeats differ in signature, once however often it changes. It returns the rate, a 95% Wilson interval and a state, `inconclusive` under the minimum needs.

## Driver
- `load_flip_needs( path, expected_sha )` reads the frozen needs file. The hash must match, there must be enough needs, and no id or text repeats. Each need is `duplicate` or `distinct`, with an optional symbol to exclude.
- `repeat_asks( repeats, route )` makes one ask per repeat, `r1`, `r2` and so on. Each result carries rows with the verdict and shortlist, so the report needs no receipt.
- `check_repeats` refuses a report whose runs were given another number of repeats. `sendable_ids` and `stale_excludes` name the excluded symbols the sweep would not know, and `check_excludes` refuses them before any spend.
- `report_lines` writes the flip rate, the needs it covers and those left out because their repeats were incomplete. It says when the interval's upper bound is above the pass line.
- `main` runs one step of the test and returns 0. `cli` turns a refusal into one line and exit code 2, and lets any other error propagate.
