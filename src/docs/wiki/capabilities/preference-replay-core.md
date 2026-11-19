---
capability: preference-replay-core
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.cohorts.answer_source_of@834ff74344
  - cosa.research.preference_replay.cohorts.cohort_asks@e662e99fe2
  - cosa.research.preference_replay.cohorts.counted_scored_filter@6797c07c4e
  - cosa.research.preference_replay.cohorts.scored_rows@bcb7278695
  - cosa.research.preference_replay.cohorts.window_of@fc57249447
  - cosa.research.preference_replay.time_sliced_store.TimeSlicedDecisionStore@ad31f5016d
  - cosa.research.preference_replay.replay_loop.always_yes_arm@0a68cf15a6
  - cosa.research.preference_replay.replay_loop.predicted_value_for@ce4a593836
  - cosa.research.preference_replay.replay_loop.prior_majority_arm@e0977a44e3
  - cosa.research.preference_replay.replay_loop.replay@b6cfa520fe
  - cosa.research.preference_replay.replay_loop.rows_as_of@60687ff8cd
  - cosa.research.preference_replay.replay_loop.summarize@0f75e6985d
  - cosa.research.preference_replay.calibration_fit.fit_and_evaluate@4670219359
---
# Preference replay core

Offline tools that replay the live prediction engine over past asks, using only what was knowable at ask time ([[prediction-engine]]).

## Cohorts
- A scored ask is a `prediction_log` row with a non-null `accuracy_match`. `window_of( predicted_at, response_type )` names its audit window by `predicted_at`, because the audit query groups on that column.
- `scored_rows( session, response_type, window )` lists scored forecasts. `cohort_asks` builds the replay's ask dicts. `answer_source_of( response_value, response_options )` names an answer `review_card` when the ask's `response_options` carry `review_card: true`. That test is `is_review_card`, in `cosa.agents.prediction_engine.review_card`. Otherwise the answer is human when its source is `ui` and unknown if not. The backfill script uses it too. `counted_scored_filter()` is the SQL condition for a row the admin report counts and has scored.

## Replay
- `TimeSlicedDecisionStore` stands in for the decision embeddings. A case is visible only when its `responded_at` is at or before the moment the harness advanced to. So a forecast never sees a later answer. Its `add_decision`, `advance_to`, `find_similar` and `visible_ids` follow that rule.
- `replay( asks, engine, snapshot_sha256, baselines, store_factory, target_types )` predicts every replayable ask in time order with the real engine and with each baseline. `rows_as_of( cases, asked_at, excluded_ids )` builds store rows as they stood at that moment.
- `predicted_value_for( result )` wraps a forecast the way the engine does before comparing it with an answer.
- The baselines: `always_yes_arm` forecasts yes. `prior_majority_arm` forecasts the stance most often given before among visible yes/no cases.
- `summarize( run, baseline_arm, operational_floor )` compares the engine with one baseline, paired on the same asks.

## Calibration
- `fit_and_evaluate( tune_rows, final_rows, cohort_sha, fit_time, n_bins )` fits on the tune rows and scores on the final rows. The final window never reaches the fit ([[prediction-calibration]]).
