---
capability: prediction-per-field-multiple-choice
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.predict@d8d8445bfa
  - cosa.agents.prediction_engine.prediction_result.PredictionResult.to_hint_dict@258569218c
  - cosa.agents.prediction_engine.accuracy_comparators.offered_labels@d54e9908aa
  - cosa.agents.prediction_engine.accuracy_comparators.score_field@646437df13
  - cosa.agents.prediction_engine.accuracy_comparators.compare_multiple_choice@8c053be4a2
  - cosa.agents.prediction_engine.accuracy_comparators.get_comparator@c59bd8b6a2
---
# Prediction per-field multiple choice

With `prediction engine per field multiple choice enabled` on, a multiple-choice card is forecast and scored one field at a time ([[prediction-engine]], [[prediction-accuracy-comparators]]). The switch is off by default, and off keeps the whole-card forecast and scorer exactly as they were.

## The forecast
- A neighbour speaks to a field only when its own stored card has a field with the same normalised header. Neither card's field may be ambiguous.
- A field forecasts its most-voted offered label. It abstains with a reason: `ambiguous_labels`, `no_aligned_neighbours`, `no_positive_evidence`, `no_option_evidence` or `other_likely`.
- A pick the neighbour's card did not offer is a typed Other, counted apart. When typed Others outweigh the best label, the field abstains as `other_likely`.
- With no answered field the result is a cold start with reason `no_field_candidates`. `PredictionResult.fields` holds each header's answer or reason, and `to_hint_dict` adds it to a ready hint.
- A neighbour-options lookup error is reported as `prediction_error`.

## The scoring
- `get_comparator` binds `per_field` to the multiple-choice comparator only when it is true. `offered_labels` returns the stripped labels one stored field offered.
- With `per_field` true, `score_field` adds an `outcome`: exact, miss, or `other_write_in` when the pick is not an offered label.
- `compare_multiple_choice` then leaves abstained fields and typed Others out of `total`. It adds `other_write_in`, `abstained` and `field_coverage` to the detail.
- A card with nothing left to score returns `None`, so it is not scored at all.
