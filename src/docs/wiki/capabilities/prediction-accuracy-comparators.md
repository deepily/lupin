---
capability: prediction-accuracy-comparators
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.prediction_engine.accuracy_comparators.compare_yes_no@1241d5a0c1
  - cosa.agents.prediction_engine.accuracy_comparators.compare_multiple_choice_single@0871984ffc
  - cosa.agents.prediction_engine.accuracy_comparators.compare_multiple_choice_multi@673ca6906e
  - cosa.agents.prediction_engine.accuracy_comparators.compare_open_ended@dfa4cf30bb
  - cosa.agents.prediction_engine.accuracy_comparators.compare_open_ended_batch@62714ea9e6
  - scripts.rescore_empty_answers_mc.classify@f6deb6b1a3
  - scripts.rescore_empty_answers_mc.select_rows@3a649df5c9
  - scripts.rescore_empty_answers_mc.default_dump_path@f848818d66
  - scripts.rescore_empty_answers_mc.dump_old_values@f1de852e32
  - scripts.rescore_empty_answers_mc.rescore@72598b798c
  - scripts.rescore_empty_answers_mc.main@8a17febbaa
---
# Prediction accuracy comparators

One comparator exists for each question type the prediction engine ([[prediction-engine]]) scores. Each takes the predicted and actual response and returns `(match, detail)`.

## What it does
- Every comparator returns `(None, {})` when either side is `None`. No match is claimed for a missing answer.
- `compare_yes_no` matches on the base yes or no value. A trailing comment in the value is kept as qualifier detail, not compared.
- `compare_multiple_choice_single` matches only when every header maps to the same option label on both sides.
- `compare_multiple_choice_multi` scores each header by Jaccard similarity of the chosen options. The overall match needs a score of at least 0.5.
- `compare_open_ended` uses embedding similarity when the actual response carries one, and matches at 0.75 or more. The engine passes the cut-off in from the INI key `prediction engine open ended match threshold`. The built-in default is also 0.75. Otherwise it compares the strings, ignoring case and outer whitespace.
- `compare_open_ended_batch` does the same per header. The match is the average similarity across headers meeting the threshold. Both take an optional `threshold` and record the one applied in `detail[ "threshold" ]`.

## One-off rescore of old multiple-choice rows
- `src/scripts/rescore_empty_answers_mc.py` rescores the old `multiple_choice` rows left unscored with reason `empty_answers`. They were stored before the router kept the answer as a mapping.
- `select_rows` picks those rows; `open_ended_batch` rows are never selected. `classify` decodes each stored answer the way `record_outcome` does and reruns `get_comparator`.
- A row is skipped, and counted under its reason, when it holds no answers mapping or no prediction. It is also skipped when the comparator still cannot score it.
- It is report-only by default. `--write` first dumps every row it will change to a JSON-lines file (`dump_old_values`, `default_dump_path`), and writes nothing if the dump fails. Then it stores the decoded answer and the new score. It never changes `responded_at`.
- `main` returns 0 after a run. A required import that fails stops the script with exit 3 before `main` runs.

## Invariants
- The embedding similarity is a transient field on the actual response, added by an earlier step. The comparators never compute it.
