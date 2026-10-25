---
capability: doc-lint-train-builder
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.train_builder.store_rows@fd33fcac3d
  - cosa.repo.doc_lint.train_builder.persona_of@4d96f16024
  - cosa.repo.doc_lint.train_builder.amendments_of@23cec16c71
  - cosa.repo.doc_lint.train_builder.approval_of@dead0775c8
  - cosa.repo.doc_lint.train_builder.withdrawal_of@a63438ef69
  - cosa.repo.doc_lint.train_builder.claim_of@24eaf99612
  - cosa.repo.doc_lint.train_builder.event_agrees@b7bc8a5f5e
  - cosa.repo.doc_lint.train_builder.overwrite_event@fa0613bea6
  - cosa.repo.doc_lint.train_builder.checks_problem@2ad3d2e204
  - cosa.repo.doc_lint.train_builder.judge_package@c951f899df
  - cosa.repo.doc_lint.train_builder.build_train@1ad057c299
  - cosa.repo.doc_lint.train_builder.main@1ec06931f2
---
# Doc-lint train builder

Picks the approved packages that go in one day's merge train of the docs-rewrite sweep. A package goes only when its `docs sweep: <package>` store row carries an approval. The per-package check is [[doc-lint-package-check]].

## Reading a row
- `store_rows` reads the sweep claim rows and their audit events from the task store, terminal rows included, scoped by project and correlation key.
- `amendments_of` splits a row body into its amendment blocks. `persona_of` reduces an actor to a lowercase name with accents removed and a trailing 8-hex session id dropped.
- `claim_of` reads the first `docs-sweep-claim` line before the first amendment. A line that is not a JSON object with string `package` and `writer` raises `ValueError`.

## Approval
- `approval_of` finds the latest approval line that no later withdrawal voided. `withdrawal_of` finds the withdrawal that voided it, if one did.
- `event_agrees` is true only when an amended event has that actor and a time within two minutes of the body stamp. `overwrite_event` finds the first `patched` event that overwrote the body.
- `checks_problem` says what is wrong with an approval's checks directory. It is under a temp directory, outside the data root, not a directory, or lacks `result.json` or a passing `history-destination.json`. Another package or a differing file sha is a problem too.

## The train
- `judge_package` returns an entry for an approved package, or a reason. A row that is dropped, parked, overwritten, withdrawn, self-approved by its writer or owner, or with a verdict that is not pass is refused.
- `build_train` returns `head`, `packages`, `commits`, `bisect_order`, `deferred`, `refused`, `landed` and `not_claimed`. Packages are in sweep order, cut at `size`. A package with two live claim rows is refused.
- `main` writes `train.json` and returns 0 when the train holds a package, 1 when it holds none and 2 when the run could not start.
