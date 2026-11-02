---
capability: needset-report-rollup
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.report_rollup.share@341fd51a8b
  - lupin_mcp.reuse_needset.report_rollup.table@380119a51f
  - lupin_mcp.reuse_needset.report_rollup.split@e036ea5d2a
  - lupin_mcp.reuse_needset.report_rollup.load@e90a99b57d
  - lupin_mcp.reuse_needset.report_rollup.counts_table@b0b2b297a6
  - lupin_mcp.reuse_needset.report_rollup.skipped_seeds@e802358fa5
  - lupin_mcp.reuse_needset.report_rollup.yield_section@3861b0011a
  - lupin_mcp.reuse_needset.report_rollup.judge_rows@3f3f656d91
  - lupin_mcp.reuse_needset.report_rollup.forced_section@cf2714e716
  - lupin_mcp.reuse_needset.report_rollup.expansion_section@6237d3ab25
  - lupin_mcp.reuse_needset.report_rollup.discordant@f5f4314402
  - lupin_mcp.reuse_needset.report_rollup.control_pairs_from_report@eade7131c1
  - lupin_mcp.reuse_needset.report_rollup.control_section@cd2153434b
  - lupin_mcp.reuse_needset.report_rollup.render@14a69d195d
  - lupin_mcp.reuse_needset.report_rollup.parse_args@5012ccf80a
  - lupin_mcp.reuse_needset.report_rollup.main@fd8374792d
  - lupin_mcp.reuse_needset.report_rollup.control_report_of@82bff48097
  - lupin_mcp.reuse_needset.report_rollup.legacy_control@493687a942
  - lupin_mcp.reuse_needset.report_rollup.control_sections@1b1513d027
---
# Need set: report roll-up

Reads the JSON that [[needset-forced-judge]], the yield trace, the need expansion and the control print or write. It renders the plan section 10 figures as one markdown table per experiment, and makes no model call, no search and no spend-ledger write.

## Figures
- `share` formats a count as `k/n (p%, lo-hi%)`, with the 95 percent Wilson interval of `reuse_e2e.wilson`.
- `yield_section`, `forced_section` and `expansion_section` each take a plan-only result or a finished report.
- A plan-only input shows counts and what a run would do, with its figures marked not run. `judge_rows` counts the forced judge by label and language.
- The expansion results record no language, so its table is per group only. "Enters 128" is fused rank 128 or better, and the table says it reads a little optimistic.

## Control
- `control_report_of` takes the control report from a stage-reports file or a bare report; `control_pairs_from_report` keeps its same-job pairs that drafted.
- `discordant` counts a (original retrieved, plant not) and b (plant retrieved, original not). `control_sections` renders each pass with the a - b <= 2 mark, worded "not worse by more than two pairs", beside the report's own mark. `legacy_control` renders the older report with no rows: shares only.

## Running
- `render` joins the sections; `main` reads the named files, including `--control`, and prints or writes to `--out`.
