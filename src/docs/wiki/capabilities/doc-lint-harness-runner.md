---
capability: doc-lint-harness-runner
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.harness_runner.check_models@efc08374d9
  - cosa.repo.doc_lint.harness_runner.judge_skipped@30059f0557
  - cosa.repo.doc_lint.harness_runner.text_hash@3d09aafc5b
  - cosa.repo.doc_lint.harness_runner.ledger_key@4e08b08065
  - cosa.repo.doc_lint.harness_runner.LedgerBindingError@6d8a2cdeba
  - cosa.repo.doc_lint.harness_runner.Ledger@a0eca379c1
  - cosa.repo.doc_lint.harness_runner.run_pair@92193538b9
  - cosa.repo.doc_lint.harness_runner.run_all@b4e8489024
  - cosa.repo.doc_lint.harness_runner.summarize_calls@28eb8985a7
  - cosa.repo.doc_lint.harness_runner.unquotable_seeds@c077f275e8
  - cosa.repo.doc_lint.harness_schedule.scheduled_at@0c88e49f34
  - cosa.repo.doc_lint.harness_schedule.build_submit_payload@594f11fdcb
  - cosa.repo.doc_lint.harness_schedule.submit@6da597dc3b
  - cosa.repo.doc_lint.harness_cli.parse_args@716527338d
  - cosa.repo.doc_lint.harness_cli.raw_failure_sink@cedfbdc786
  - cosa.repo.doc_lint.harness_cli.main@cd2fd5622a
  - cosa.repo.doc_lint.harness_cli.run_after_checks@d77fb594eb
---
# Doc-lint harness runner

Runs the judge harness over before and after pairs with a resumable ledger. Figures come from [[doc-lint-harness-report]], and the stages from [[doc-lint-claim-extractor]] and [[doc-lint-claim-judge]].

## Ledger and keys
- `Ledger` is an append-only file of finished calls, one JSON object per line. Its first record binds the Claude Code binary, and `LedgerBindingError` refuses a resume under another binary.
- Every put is on disk before it returns, and a torn last line is ignored on load. `ledger_key` hashes the old text, the new text with its design doc, the prompt version and the model id. `text_hash` makes the short hash.

## Running
- `check_models` refuses a judge or escalation model equal to the writer model. The extractor may equal it. `judge_skipped` returns the reason for a pair whose new text is empty.
- `run_pair` skips every call the ledger holds and freezes each extractor list before judging. `run_all` runs pairs in input order, up to `parallel` at once, and raises the earliest failure after the pairs in flight finish.
- `summarize_calls` folds call records into seconds and counts per stage. `unquotable_seeds` lists seeded pairs whose span cannot itself be quoted.

## Scheduling and command line
- `scheduled_at` returns now inside the 10:00 to 13:00 Eastern window, else the next 10:00. `build_submit_payload` builds a bounded job body with `scheduled_at` at top level. `submit` logs in and posts it.
- `parse_args` requires every model id and gives none a default. `raw_failure_sink` files unreadable replies as JSON lines.
- `main` returns 0 after writing the report. It returns 3 for a gate run whose frozen versions or pairs sha differ, and 4 for an unquotable seeded span. `run_after_checks` does the work once the first checks pass.
