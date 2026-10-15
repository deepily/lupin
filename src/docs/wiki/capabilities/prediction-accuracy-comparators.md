---
capability: prediction-accuracy-comparators
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.prediction_engine.accuracy_comparators.compare_yes_no@1241d5a0c1
  - cosa.agents.prediction_engine.accuracy_comparators.compare_multiple_choice_single@0871984ffc
  - cosa.agents.prediction_engine.accuracy_comparators.compare_multiple_choice_multi@673ca6906e
  - cosa.agents.prediction_engine.accuracy_comparators.compare_open_ended@9c59cecd1f
  - cosa.agents.prediction_engine.accuracy_comparators.compare_open_ended_batch@aad20932e3
---
# Prediction accuracy comparators

One comparator exists for each question type the prediction engine ([[prediction-engine]]) scores. Each takes the predicted and actual response and returns `(match, detail)`.

## What it does
- Every comparator returns `(None, {})` when either side is `None`. No match is claimed for a missing answer.
- `compare_yes_no` matches on the base yes or no value. A trailing comment in the value is kept as qualifier detail, not compared.
- `compare_multiple_choice_single` matches only when every header maps to the same option label on both sides.
- `compare_multiple_choice_multi` scores each header by Jaccard similarity of the chosen options. The overall match needs a score of at least 0.5.
- `compare_open_ended` uses embedding similarity when the actual response carries one, and matches at 0.85 or more. Otherwise it compares the strings, ignoring case and outer whitespace.
- `compare_open_ended_batch` does the same per header. The match is the average similarity across headers meeting the threshold.

## Invariants
- The embedding similarity is a transient field on the actual response, added by an earlier step. The comparators never compute it.
