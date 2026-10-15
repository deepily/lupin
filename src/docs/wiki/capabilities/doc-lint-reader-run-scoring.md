---
capability: doc-lint-reader-run-scoring
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.reader_rig_run.projected_calls@c9fc31bec0
  - cosa.repo.doc_lint.reader_rig_run.take_score_object@308be372a8
  - cosa.repo.doc_lint.reader_rig_run.cut_raw@de8988c939
  - cosa.repo.doc_lint.reader_rig_run.CallTracker@96d82f2cc2
  - cosa.repo.doc_lint.reader_rig_run.ServedLedger@ed63686b5c
  - cosa.repo.doc_lint.reader_rig_run.score_question@99a3273104
  - cosa.repo.doc_lint.reader_rig_run.score_pair@b1fcf07560
  - cosa.repo.doc_lint.reader_rig_run.score_file@45f4531156
  - cosa.repo.doc_lint.reader_rig_run.summarize@2034dd56c8
  - cosa.repo.doc_lint.reader_rig_run.verdict_word@fd3441d23b
  - cosa.repo.doc_lint.reader_rig_run.refuse@bfac4c60fb
  - cosa.repo.doc_lint.reader_rig_run.main@2f68bbeca6
---
# Doc-lint reader run scoring

The scoring half of the reader-test command line. It scores each question on the old and new text for several runs, under call caps. Text and questions come from [[doc-lint-reader-run-text]].

## One question
- `score_question` tries up to three times and returns the score, or the failing step, error and raw replies. A model-unavailable error ends the attempts at once, and a retry is a real call charged to the cap.
- `score_pair` scores a question on both texts. Identical texts are scored once and share the result.
- `take_score_object` takes `{"score": 0}` or `{"score": 1}` out of a grader reply that reasons first and ends with one such object. Any other shape returns `None`.
- `CallTracker` wraps a query function and remembers the last step and raw reply. It salvages a score only from a grader reply, and never changes a reader reply. `cut_raw` cuts a long raw reply to head and tail, with a marker.

## A file and the run
- `score_file` scores every question of a file on both texts for each run. A question and run that fails on either text is dropped from both totals, and `passes` is `None` when any pair was dropped.
- When a cap stops a call, that pair and every later pair are recorded unscored with step `cap`.
- `summarize` sums the per-file figures. `verdict_word` returns `INCOMPLETE` when any pair was dropped, else `PASS` when the new total is at least the old, else `FAIL`.
- `ServedLedger` remembers which grades a wrapped ledger already held and read back. `projected_calls` counts the calls still owed, less what the ledger holds.

## Command
- `main` returns 0 after printing a line per file and an overall line. It returns 2 and makes no model call for a refused input, or when the projected calls pass a cap.
- It returns 3 when a pair could not be scored, and a rerun against a full ledger makes zero calls. `refuse` prints `REFUSED:` and returns 2.
