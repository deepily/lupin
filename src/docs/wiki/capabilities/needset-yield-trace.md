---
capability: needset-yield-trace
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.yield_trace.saved_ask@04aac966fd
  - lupin_mcp.reuse_needset.yield_trace.copy_saved@5471ae171c
  - lupin_mcp.reuse_needset.yield_trace.rebuild@166fb1b44a
  - lupin_mcp.reuse_needset.yield_trace.rebuild_head@d632674775
  - lupin_mcp.reuse_needset.yield_trace.found_intervals@beba11123d
  - lupin_mcp.reuse_needset.yield_trace.trace_needs@1eb57dcd18
  - lupin_mcp.reuse_needset.yield_trace.run_traced@0152dfdbf2
  - lupin_mcp.reuse_needset.yield_trace.parse_args@b72e09f5a6
  - lupin_mcp.reuse_needset.yield_trace.live_parts@319a8bfcac
  - lupin_mcp.reuse_needset.yield_trace.main@49423bda4a
  - lupin_mcp.reuse_needset.yield_trace.exit_status@e0995b5ff4
  - lupin_mcp.reuse_needset.yield_trace.run_cli@2b9e55e56d
---
# Need set: yield trace

Runs the yield seeds' needs through the full checker, each seed as its own known answer, and reports where each was lost. The needs come from an earlier run's saved answers, so the drafter and the second model are never asked. It is the command behind the yield replay in [[needset-first-thousand-command]]; the trace is [[needset-loss-trace]].

## Rebuilding the needs
- `copy_saved` copies the draft ledger, the second-check ledger and the seed lists from the earlier run into this run's folder. A file already there is kept, and a file the earlier run lacks raises `SAVED_FILE_MISSING`.
- `saved_ask` stands in for both models and always raises. `rebuild` lists a seed with no saved answer as unsaved and goes on.
- `rebuild_head` returns the needs with the counts: seeds, needs, unsaved seeds, the reasons seeds gave no need, and needs per language.

## Tracing
- `trace_needs` traces the needs and reports the attribution figures plus `found_intervals`, the found share per language with its 95 percent interval. A stage budget that ends the trace keeps the head and marks it unfinished.
- `run_traced` runs the work under the call cap, charges every call to the `yield_trace` stage and writes `yield-trace-report.json`. Its status is done, stopped, budget_reached, cap_reached or failed.

## Command line
- `main` without `--live` rebuilds the needs and prints the plan, with no model call. With `--live` and an unsaved seed it stops before spending anything. `--cli-path` is needed in both modes.
- `live_parts` builds the parts over the copied ledgers, and `exit_status` gives 1 for a failure, 3 for the cap or the budget, else 0. `parse_args` and `run_cli` read the line and print the result.
