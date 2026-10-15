---
capability: doc-lint-seeder-writer-and-checks
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_seeder.check_sibling_ledgers@5a1205b47c
  - cosa.repo.doc_lint.labelled_set_seeder.check_ledger_identity@8cea459c6f
  - cosa.repo.doc_lint.labelled_set_seeder.writer_ledger_row@b1438be95e
  - cosa.repo.doc_lint.labelled_set_seeder.WriterStopped@194065c1c5
  - cosa.repo.doc_lint.labelled_set_seeder.CanaryFailed@51f1f0c19d
  - cosa.repo.doc_lint.labelled_set_seeder.TooManyFailures@c7439807a4
  - cosa.repo.doc_lint.labelled_set_seeder.run_writer@5a9a994ef8
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_write@8256a1013b
  - cosa.repo.doc_lint.labelled_set_seeder.weak_cues@986ba687fd
  - cosa.repo.doc_lint.labelled_set_seeder.word_regex@565715a012
  - cosa.repo.doc_lint.labelled_set_seeder.token_count@2f2498f0b5
  - cosa.repo.doc_lint.labelled_set_seeder.check_pair@9a5ac444e8
  - cosa.repo.doc_lint.labelled_set_seeder.check_set@d623772383
  - cosa.repo.doc_lint.labelled_set_seeder.rule1_status@9f766cc186
  - cosa.repo.doc_lint.labelled_set_seeder.cmd_check@923b9becc7
---
# Doc-lint seeder writer and checks

The blind writer phase of the labelled-set seeding script, and rule 1, the mechanical check of its output. The plan comes from [[doc-lint-seeder-plan]].

## Writer ledger
- `writer_ledger_row` returns one call's row: task id, model, prompt hash and output sha256, never the text.
- `check_ledger_identity` refuses a ledger whose rows disagree on model or prompt, among themselves or with now. `check_sibling_ledgers` refuses a write whose model or prompt differs from another split's under the same base.

## Writing
- `run_writer` makes one blind call per task lacking a finished row, and checks every row before the first call. The first pending task is a canary with no retry.
- A failed or empty call is retried once, unless the model is unavailable. A task that still fails is recorded as dropped, and a dropped row is called again by a later run.
- `CanaryFailed` is raised when the canary fails, and `TooManyFailures` after the allowed run of dropped tasks. `WriterStopped` is their base, carrying the reason and what the run had done.
- `cmd_write` refuses without a cap, off the shared ledger, or past the approved count. It returns 0 done, 2 refused, 3 call cap, 4 canary, 5 too many failures and 6 when a task was dropped.

## Rule 1
- `check_pair` checks one seeded pair against the writer's output with no model. It returns `SPAN_VERBATIM`, `WEAK_TOKEN_MISSING` or `STRONG_RESTORED`, or an empty list when the pair passes.
- `weak_cues` returns the cue words that show a weakened token in the output. `word_regex` and `token_count` match whole words, with `n't` matched as a suffix.
- `check_set` runs rule 1 over every seeded pair of a written split. A pair with no output is `NO_OUTPUT`, and one that answers other task text is `STALE_OUTPUT`.
- `rule1_status` takes out pairs a reader accepted. Only a pair whose every reason is waivable can be accepted. `cmd_check` lists the failing seeded pairs.
