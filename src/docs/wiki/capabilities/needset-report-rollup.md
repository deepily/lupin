---
capability: needset-report-rollup
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.report_rollup.share@341fd51a8b
  - lupin_mcp.reuse_needset.report_rollup.table@380119a51f
  - lupin_mcp.reuse_needset.report_rollup.split@e036ea5d2a
  - lupin_mcp.reuse_needset.report_rollup.load@e90a99b57d
  - lupin_mcp.reuse_needset.report_rollup.counts_table@b0b2b297a6
  - lupin_mcp.reuse_needset.report_rollup.yield_section@1a6e34d896
  - lupin_mcp.reuse_needset.report_rollup.judge_rows@3f3f656d91
  - lupin_mcp.reuse_needset.report_rollup.forced_section@cf2714e716
  - lupin_mcp.reuse_needset.report_rollup.expansion_section@6237d3ab25
  - lupin_mcp.reuse_needset.report_rollup.discordant@fac3f6d59c
  - lupin_mcp.reuse_needset.report_rollup.control_pairs_from_report@1065d9578b
  - lupin_mcp.reuse_needset.report_rollup.control_section@3dd45a77ec
  - lupin_mcp.reuse_needset.report_rollup.render@11163591df
  - lupin_mcp.reuse_needset.report_rollup.parse_args@cf4327c021
  - lupin_mcp.reuse_needset.report_rollup.main@61bc0eeba9
---
# Need set: report roll-up

Reads the JSON that [[needset-forced-judge]], the yield trace and the need expansion print or write.
It renders the plan section 10 figures as one markdown table per experiment. It makes no model call, no search and no spend-ledger write.

## Figures
- `share` formats a count as `k/n (p%, lo-hi%)`, with the 95 percent Wilson interval of `reuse_e2e.wilson`.
- `yield_section`, `forced_section` and `expansion_section` each take a plan-only result or a finished report.
- A plan-only input shows counts and what a run would do. Its figures are marked not run. `judge_rows` counts the forced judge by label and by language.
- The expansion results record no language, so its table is per group only.
- "Enters 128" is fused rank 128 or better. The table says it reads a little optimistic.

## Control
- `discordant` counts a (original in the 128, plant not) and b (plant in, original not).
- `control_section` renders them with the a - b <= 2 mark, worded as "not worse by more than two pairs".
- `control_pairs_from_report` is a stub that raises until John's control report merges.

## Running
- `render` joins the sections; `main` reads the named files and prints the report or writes it to `--out`.
