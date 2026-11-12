---
capability: prediction-engine
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine@3a66666946
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.predict@399fd38a6c
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.record_outcome@c1eaa235d9
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.record_hint_vote@384d7e7edb
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.get_accuracy_summary@c357538e8b
  - cosa.agents.prediction_engine.prediction_engine.get_prediction_engine@17a1a42f8d
  - cosa.agents.prediction_engine.prediction_result.PredictionResult@8f3b490185
  - cosa.agents.prediction_engine.prediction_result.PredictionResult.to_hint_dict@74e10b5df2
  - cosa.agents.prediction_engine.notification_category_classifier.NotificationCategoryClassifier@c07615726c
  - cosa.agents.prediction_engine.accuracy_comparators.get_comparator@f9857181fc
  - cosa.agents.prediction_engine.xml_models.OpenEndedSynthesisResponse@a970522250
---
# Prediction engine

A process-wide singleton that guesses how the user will answer a notification before they do. The guess becomes a hint on the card, and the real answer is logged to measure accuracy and to feed later guesses.

## What it does
- `predict` classifies the message into one of six keyword categories or `uncategorized`, embeds it, and dispatches on the response type. It never raises; any failure returns a cold-start result.
- `yes_no` and `multiple_choice` retrieve the top similar past cases and take a weighted vote. A blank shadow or deferred case casts no vote. Confidence is the best similarity times the vote's consistency.
- A `yes_no` vote says `no` only when the no tally beats the yes tally by `prediction engine yes no no margin`. That default is 1.35, the log-odds of the 79% yes prior. Otherwise it says `yes`. With five unit votes, `no` needs a lead of 2 or more. `open_ended` and `open_ended_batch` try an exact question match first, then an LLM synthesis over the similar cases. If synthesis fails they fall back to retrieval.
- A multiple-choice case's answers are re-keyed onto the new question's own headers before the vote, because a neighbour's headers seldom match. A header with no usable answer is dropped.
- `record_outcome` decodes a multiple-choice or batch answer sent as a JSON string. It compares the prediction with the real answer and writes the `prediction_log` row. The engine reads `prediction engine open ended match threshold` when it is built, and `record_outcome` passes it to `get_comparator` as `open_ended_threshold` (see [[prediction-accuracy-comparators]]). It also stores the answer as a new case.
- `record_hint_vote` stores a thumbs up or down as a case keyed `hintvote-<notification id>`, so a second vote flips the state in place.

## Invariants
- Cold start is a result, not an error. It covers a disabled engine, no embedding, no store, no similar case and an unsupported type.
- An approved case votes `+approved_weight`, a rejected case votes negative, and any other case votes `+1`. A rejected case is never the answer in the open-ended retrieval tiers.
- Consistency is the winner's tally over the positive mass, clamped to 0 to 1. With no positive mass it is 0.
- A multi-select option is kept when its weighted votes reach half the positive case mass.
- `to_hint_dict` returns `None` for a cold start, so the card shows no hint. Batch cases are keyed by the question's content, not the count preamble, so unrelated batches do not collide.

## How it is used
- `lupin_app.main` builds the singleton with the config at startup. The notify route calls `predict` off the event loop and shows the hint only when confidence reaches `prediction engine confidence threshold`.
- The same route stamps the vote gate and the auto-submit keys into the hint, so the client reads them from the server. Auto-submit is off unless `expeditor prediction auto submit enabled` is true.
- The response route calls `record_outcome`. The vote route calls `record_hint_vote`.
- Thresholds, `top k`, the LanceDB table and the open-ended LLM key are `prediction engine ...` INI keys, with code defaults in `config.py`. A hot reload drops the singleton through `PredictionEngine.reset`.
