---
capability: prediction-accuracy-comparators
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.accuracy_comparators.compare_yes_no@4c818a6d76
  - cosa.agents.prediction_engine.accuracy_comparators.score_field@646437df13
  - cosa.agents.prediction_engine.accuracy_comparators.compare_multiple_choice@851632a17b
  - cosa.agents.prediction_engine.accuracy_comparators.confidence_band@18f122aed8
  - cosa.agents.prediction_engine.accuracy_comparators.get_comparator@a124c310bf
  - cosa.agents.prediction_engine.accuracy_comparators.compare_open_ended@dfa4cf30bb
  - cosa.agents.prediction_engine.accuracy_comparators.compare_open_ended_batch@62714ea9e6
  - scripts.rescore_empty_answers_mc.classify@35ecc393c3
  - scripts.rescore_empty_answers_mc.select_rows@3a649df5c9
  - scripts.rescore_empty_answers_mc.default_dump_path@f848818d66
  - scripts.rescore_empty_answers_mc.dump_old_values@f1de852e32
  - scripts.rescore_empty_answers_mc.rescore@f5b60dd0c9
  - scripts.rescore_empty_answers_mc.main@d01a8a118d
  - cosa.agents.prediction_engine.accuracy_comparators.offered_labels@d54e9908aa
---
# Prediction accuracy comparators

One comparator exists for each question type the prediction engine ([[prediction-engine]]) scores. Each takes the predicted and actual response and returns `(match, detail)`. A multiple-choice card is scored field by field by the schema stored with the notification.

## What it does
- Every comparator returns `(None, {})` when either side is `None`. No match is claimed for a missing answer. `compare_yes_no` matches on the base yes or no value. A trailing comment in the value is kept as qualifier detail, not compared. `offered_labels` returns the stripped labels one stored field offered, or an empty set.
- `score_field` scores one field by the mode its schema names. A single select is exact on an equal pick. A multi-select is exact on equal sets and carries their Jaccard overlap.
- `compare_multiple_choice` loops `score_field` over the answered fields and matches only when every field is exact. `detail[ "matches" ]` and `detail[ "total" ]` count the exact fields, so a half-right card is 1 of 2. `get_comparator` binds it to the card's stored `response_options`, and with none every field is a single select. With `per_field` true the scoring changes ([[prediction-per-field-multiple-choice]]). A malformed stored schema is scored the same way and adds `schema_reason`.
- `compare_multiple_choice` reads the forecast through `predicted_answers_of`: the `answers` map, plus write-in or re-frame text for typed fields in `fields` that `answers` lacks. An entry in `answers` is never replaced.
- `get_comparator( complete_action=True, judge=... )` returns a `compare_complete_action_*` comparator for every response type. It scores the whole action (stance and condition, or every field) and adds an atom decomposition (`decompose_atoms`). Free text that differs goes to the injected judge; with none the result is `None` with reason `judge_required`. The engine passes `complete_action` only when `prediction engine complete action scoring enabled` is on (code default off); with it off the binding is unchanged.
- `confidence_band` names the forecast band by its lower edge: [0, 0.4), [0.4, 0.6), [0.6, 0.8) and [0.8, 1.0]. No confidence, NaN or a value outside 0 to 1 gives `None`.
- `compare_open_ended` uses embedding similarity when the actual response carries one, and matches at 0.75 or more. The engine passes the cut-off in from the INI key `prediction engine open ended match threshold`. The built-in default is also 0.75. Otherwise it compares the strings, ignoring case and outer whitespace. `compare_open_ended_batch` does the same per header. The match is the average similarity across headers meeting the threshold. Both take an optional `threshold` and record the one applied in `detail[ "threshold" ]`.

## One-off rescore of old multiple-choice rows
- `src/scripts/rescore_empty_answers_mc.py` rescores the old `multiple_choice` rows left unscored with reason `empty_answers`. They were stored before the router kept the answer as a mapping.
- `select_rows` picks those rows; `open_ended_batch` rows are never selected. `classify` decodes each stored answer the way `record_outcome` does and reruns `get_comparator` with the notification's stored schema and the per-field switch. `main` reads that switch from the live setting.
- A row is skipped, and counted under its reason, when it holds no answers mapping or no prediction. It is also skipped when the comparator still cannot score it.
- It is report-only by default. `--write` first dumps every row it will change to a JSON-lines file (`dump_old_values`, `default_dump_path`), and writes nothing if the dump fails. Then it stores the decoded answer and the new score. It never changes `responded_at`. `main` returns 0 after a run. A required import that fails stops the script with exit 3 before `main` runs.

## Invariants
- The embedding similarity is a transient field on the actual response, added by an earlier step. The comparators never compute it.
