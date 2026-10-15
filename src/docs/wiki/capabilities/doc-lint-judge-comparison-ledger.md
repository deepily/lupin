---
capability: doc-lint-judge-comparison-ledger
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.judge_comparison.LedgerIncomplete@a7a5f8e518
  - cosa.repo.doc_lint.judge_comparison.ReportMismatch@96b9138bd0
  - cosa.repo.doc_lint.judge_comparison.MissingRowProbe@88bce303c1
  - cosa.repo.doc_lint.judge_comparison.caused_by_missing_row@f70144f05c
  - cosa.repo.doc_lint.judge_comparison.refuse_model_call@4d66955822
  - cosa.repo.doc_lint.judge_comparison.refuse_post@4168d2194c
  - cosa.repo.doc_lint.judge_comparison.pair_hashes@3dedc3e5f7
  - cosa.repo.doc_lint.judge_comparison.distinct_judged_calls@7042230df6
  - cosa.repo.doc_lint.judge_comparison.call_counts@a1bb4fa000
  - cosa.repo.doc_lint.judge_comparison.rebuild@bed54a0213
  - cosa.repo.doc_lint.judge_comparison.check_report_binds@6f41ec46c3
  - cosa.repo.doc_lint.judge_comparison.check_unanswered@1bc452fb5a
---
# Doc-lint judge comparison ledger

Rebuilds one judge's results from a finished ledger with no model call, and refuses a ledger or report that does not belong to the run. The tables built from it are in [[doc-lint-judge-comparison-report]].

## Rebuilding
- `rebuild` returns results, the harness report and the claim count of each missing pass. A missing ledger row raises `LedgerIncomplete` and never calls a model.
- `refuse_model_call` and `refuse_post` stand in for the model and the Jev request, so any call means the ledger lacks a row. `caused_by_missing_row` finds a `LedgerIncomplete` anywhere in an error's chain.
- `MissingRowProbe` stands in for a back-end judge. It carries the real `key_id` and `prompt_version`, counts the passes the ledger lacks, and answers them unanswered.

## Counting calls
- `pair_hashes` reads the old and new hashes from `ledger_key` itself, so the two cannot disagree. `distinct_judged_calls` is lists times runs per judged text pair.
- `call_counts` counts finished calls of one split's pairs by stage and model. A row whose hashes match no pair is not counted.

## Binding checks
- `check_report_binds` raises `ReportMismatch` naming the field when the report's pairs sha, judge prompt version, judge model or harness version differs. It does not see thresholds.
- `check_unanswered` squares the passes a ledger lacks with the report's unanswered count. Every missing pass must hold at least one unanswered claim and no more than its claims.
