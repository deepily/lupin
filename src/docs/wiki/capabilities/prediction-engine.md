---
capability: prediction-engine
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine@777c78bde3
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.predict@d8d8445bfa
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.record_outcome@13f97dac54
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.record_hint_vote@6eea5b4fb5
  - cosa.agents.prediction_engine.prediction_engine.PredictionEngine.get_accuracy_summary@6b034cadf8
  - cosa.agents.prediction_engine.prediction_engine.get_prediction_engine@17a1a42f8d
  - cosa.agents.prediction_engine.prediction_result.PredictionResult@a451dc67b0
  - cosa.agents.prediction_engine.prediction_result.PredictionResult.to_hint_dict@258569218c
  - cosa.agents.prediction_engine.notification_category_classifier.NotificationCategoryClassifier@c07615726c
  - cosa.agents.prediction_engine.accuracy_comparators.get_comparator@a124c310bf
  - cosa.agents.prediction_engine.xml_models.OpenEndedSynthesisResponse@b42b81a7b6
---
# Prediction engine

A process-wide singleton that guesses how the user will answer a notification before they do. The guess becomes a hint on the card, and the real answer is logged to measure accuracy and to feed later guesses.

## What it does
- `predict` classifies the message into one of six keyword categories or `uncategorized`, embeds it, and dispatches on the response type. It never raises; any failure returns a cold-start result.
- `yes_no` and `multiple_choice` retrieve the top similar past cases and take a weighted vote. A blank shadow or deferred case casts no vote. Confidence is the best similarity times the vote's consistency.
- A `yes_no` vote says `no` only when the no tally beats the yes tally by `prediction engine yes no no margin`. That default is 1.35, the log-odds of the 79% yes prior. Otherwise it says `yes`. With five unit votes, `no` needs a lead of 2 or more. `open_ended` and `open_ended_batch` try an exact question match first, then an LLM synthesis over the similar cases. If synthesis fails they fall back to retrieval.
- A multiple-choice case's answers are re-keyed onto the new question's own headers before the vote, because a neighbour's headers seldom match. A header with no usable answer is dropped.
- `record_outcome` decodes a multiple-choice or batch answer sent as a JSON string. It compares the prediction with the real answer and writes the `prediction_log` row. The engine reads `prediction engine open ended match threshold` when it is built. `record_outcome` hands that and the stored `response_options` to `get_comparator` (see [[prediction-accuracy-comparators]]). It also stores the answer as a new case.
- `record_forecast` writes the ask-time `prediction_log` row. It takes an optional `pre_commit_hook( session, forecast )`, run before the commit, so what it writes commits with the row. A hook that raises stores neither row. `record_hint_vote` stores a thumbs up or down as a case keyed `hintvote-<notification id>`, so a second vote flips the state in place.
- `record_outcome` and `record_hint_vote` take an optional `answer_source`, the endpoint's label (`human`, `default`, `not_operator`, `unattributed`). The stored case source follows it: `human` stays `human`, `default` becomes `timeout_default`, and anything else (or none) becomes `unknown`. Only a human answer casts a personal vote.
- Two more switches, both off in code, are read when the engine is built. `prediction engine lookup neither forecast enabled` makes a `yes_no` forecast a three-way vote (yes, no or neither) over the owner's live cases. By default the cases are read live, as of now. A caller may set `three_way_case_provider`, a function of the owner that returns the ask time and the cases. The vote then uses those and reads no database. The replay sets it, so its vote sees only what was known at each ask. `prediction engine timeout defaults excluded enabled` (off in code and in the shipped INI) is read here too. The replay uses it to leave out asks and cases whose answer was the timeout default. `prediction engine complete action scoring enabled` makes `record_outcome` score with the complete-action comparators. Three switches add per-field multiple-choice forecasts ([[prediction-per-field-multiple-choice]]), named failure reasons ([[prediction-failure-visibility]]) and a shadow yes, no or neither stance ([[prediction-three-way-stance]]). Their code defaults are off; the shipped INI sets per-field and three-way true, failure visibility false.

## Invariants
- Cold start is a result, not an error. It covers a disabled engine, no embedding, no store, no similar case and an unsupported type.
- An approved case votes `+approved_weight`, a rejected case votes negative, and any other case votes `+1`. A rejected case is never the answer in the open-ended retrieval tiers.
- Consistency is the winner's tally over the positive mass, clamped to 0 to 1. With no positive mass it is 0. A multi-select option is kept when its weighted votes reach half the positive case mass.
- `to_hint_dict` never returns `None`. The payload carries a state: ready, below threshold, insufficient evidence or unavailable. Value and confidence appear only when ready. `PredictionResult.fields` is None except for a per-field forecast, where `to_hint_dict` adds it to a ready hint. Batch cases are keyed by the question's content, not the count preamble, so unrelated batches do not collide.

## How it is used
- `lupin_app.main` builds the singleton with the config at startup. The notify route calls `predict` off the event loop. Confidence under `prediction engine confidence threshold` gives the below-threshold state.
- The same route stamps the vote gate and the auto-submit keys into the hint, so the client reads them from the server. Auto-submit and batch prefill are **Dormant**: `expeditor prediction auto submit enabled` is false and a unit test pins it. The keys and the client code stay. The response route calls `record_outcome`. The vote route calls `record_hint_vote`.
- Thresholds, `top k`, the LanceDB table and the open-ended LLM key are `prediction engine ...` INI keys, with code defaults in `config.py`. A hot reload drops the singleton through `PredictionEngine.reset`.
