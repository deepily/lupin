---
capability: doc-lint-metrics-dashboard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.doc_metrics.swept_at@70b3c2017a
  - cosa.repo.doc_lint.doc_metrics.dashboard_rows@6272cb6687
  - cosa.repo.doc_lint.doc_metrics.metric_value@22dcdba59a
  - cosa.repo.doc_lint.doc_metrics.has_risen@bb04f3ef6f
  - cosa.repo.doc_lint.doc_metrics.risen@1c8e0a5db6
  - cosa.repo.doc_lint.doc_metrics.sum_metrics@6a70a674ad
  - cosa.repo.doc_lint.doc_metrics.build_dashboard@69467bec77
  - cosa.repo.doc_lint.doc_metrics.shown_rate@b22cc70710
  - cosa.repo.doc_lint.doc_metrics.dashboard_table@69296afa05
  - cosa.repo.doc_lint.doc_metrics.render_dashboard@04f7441633
  - cosa.repo.doc_lint.doc_metrics.rows_block@fa0f46247a
  - cosa.repo.doc_lint.doc_metrics.page_packages@445052e704
  - cosa.repo.doc_lint.doc_metrics.rise_line@bb621149bc
  - cosa.repo.doc_lint.doc_metrics.check_dashboard@4b19226c0e
  - cosa.repo.doc_lint.doc_metrics.dashboard_main@b9114e9ce6
---
# Doc-lint metrics dashboard

The documentation metrics page, `src/docs/doc-metrics-dashboard.md`, has one row per swept directory. The check refuses a row whose compared values rose. It is step two of the doclint gate.

## Building the rows
- `swept_at` lists swept files at a revision or in the working tree. `dashboard_rows` groups them so each file sits in exactly one directory row, and a row is a `package` when its directory holds an `__init__.py`.
- `build_dashboard` measures every row at the base commit and at head, with a total. `sum_metrics` adds measured sides, and its rates come from the summed counts.

## Judging a rise
- `metric_value` returns one compared value exactly, a marker as raw count over tokens and not the rounded rate. `has_risen` is true for a marker only when both its raw count and its exact rate are higher.
- So the same markers in fewer words is no rise. `risen` lists the compared values that rose, and `rise_line` describes one with its raw numbers.

## The page
- `shown_rate` is the one-decimal rate per thousand tokens, or `inf` for a side with the marker and no tokens. `dashboard_table` renders the rows as aligned text, and `render_dashboard` renders the page.
- The page omits the head commit and the changed-file count, so two trees with the same docstrings give the same bytes. `rows_block` returns the fenced rows block, and `page_packages` lists its row names.

## Commands
- `check_dashboard` compares the page with a fresh measurement and prints a verdict that starts `DASHBOARD CHECK PASSED` or `DASHBOARD CHECK FAILED`.
- `dashboard_main` writes the page or checks it, with `--base`, `--head`, `--page` and `--repo-root`.
