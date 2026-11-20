---
capability: question-vector-backfill-plan
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.backfill_missing_question_vectors.RefusedPlan@bcbc3e3b92
  - scripts.backfill_missing_question_vectors.CountMismatch@86c6b91be2
  - scripts.backfill_missing_question_vectors.Plan@905274a781
  - scripts.backfill_missing_question_vectors.Plan.ids@a5cac48ebd
  - scripts.backfill_missing_question_vectors.read_side_file@c9a06d0613
  - scripts.backfill_missing_question_vectors.encoder_version_of@bfe5f21235
  - scripts.backfill_missing_question_vectors.decision_value_of@3e1a4ac1cc
  - scripts.backfill_missing_question_vectors.vector_text@c205e0ecd0
  - scripts.backfill_missing_question_vectors.fetch_asks@5b521d7d90
  - scripts.backfill_missing_question_vectors.fetch_existing@8adba621c7
  - scripts.backfill_missing_question_vectors.build_plan@ab64bf62a4
  - scripts.backfill_missing_question_vectors.format_counts@3eb80e07b9
---
# Question vector backfill: the side file and the plan
`src/scripts/backfill_missing_question_vectors.py` writes every ask's question vector into `prediction_decisions` from a side file. An operator runs it once, never the server. The run itself is in [[question-vector-backfill-run]].

## The side file
- `read_side_file` reads JSON lines. Line 1 is the header: model, revision, count and engines. Each later line is an ask id, model, revision and vector.
- Each record must carry the header's model and revision. Ids must be unique and the count must match. Every vector passes `validate_fresh_vector`.
- Any other case raises `RefusedPlan`. `encoder_version_of` returns `<model>@<revision>` from the header, the value stamped on `prediction_log.encoder_version`.

## The plan
- `fetch_asks` reads each ask's notification and log row. `fetch_existing` returns the stored question of each ask that already has a case row.
- `build_plan` makes a `Plan`. Its inserts are asks with no case row, and its updates are asks with one. `Plan.ids` lists every id it touches.
- A new row takes its question from the stripped message, and its category and response type from the log row. Its owner is the recipient.
- The answer source is human when the notification answered through the UI, otherwise unknown. `decision_value_of` gives the logged answer: the value field, or sorted JSON text.
- `vector_text` writes a vector as `[a,b,...]` in the shortest round-trip form.
- `build_plan` refuses an id with no notification or log row, no recipient or an empty message. It also refuses an encoder version wider than its column.
- `format_counts` prints the insert, update, log and drift counts, with the insert split by answer source.
