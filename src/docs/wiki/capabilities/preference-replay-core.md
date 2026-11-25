---
capability: preference-replay-core
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.cohorts.answer_source_of@834ff74344
  - cosa.research.preference_replay.cohorts.cohort_asks@10a89d06ed
  - cosa.research.preference_replay.cohorts.notification_ask_fields@e72b937eeb
  - cosa.research.preference_replay.cohorts.counted_scored_filter@6797c07c4e
  - cosa.research.preference_replay.cohorts.scored_rows@3fa7f9321a
  - cosa.research.preference_replay.cohorts.window_of@fc57249447
  - cosa.research.preference_replay.time_sliced_store.TimeSlicedDecisionStore@e8caae758a
  - cosa.research.preference_replay.replay_loop.always_yes_arm@0a68cf15a6
  - cosa.research.preference_replay.replay_loop.paired_wins@e07f4d13fc
  - cosa.research.preference_replay.replay_loop.predicted_value_for@ce4a593836
  - cosa.research.preference_replay.replay_loop.prior_majority_arm@e0977a44e3
  - cosa.research.preference_replay.replay_loop.replay@9fd3f5b45c
  - cosa.research.preference_replay.replay_loop.rows_as_of@60687ff8cd
  - cosa.research.preference_replay.replay_loop.summarize@0529144a61
  - cosa.research.preference_replay.calibration_fit.fit_and_evaluate@cbe936ed66
---
# Preference replay core

Offline tools that replay the live prediction engine over past asks, using only what was knowable at ask time ([[prediction-engine]]).

## Cohorts
- A scored ask is a `prediction_log` row with a non-null `accuracy_match`. `window_of( predicted_at, response_type )` names its audit window by `predicted_at`, because the audit query groups on that column.
- `scored_rows( session, response_type, window )` lists scored forecasts, leaving out asks whose `response_options` carry the review-card marker. `cohort_asks` builds the replay's ask dicts. `notification_ask_fields( notification )` gives the fields every cohort takes from the notification row: title, message, sender, recipient, response options and `timeout_default`. `timeout_default` is True when `attribution_tier` names the stored answer the timeout default, whatever the answer source says. `answer_source_of( response_value, response_options )` names an answer `review_card` when the ask's `response_options` carry `review_card: true`. That test is `is_review_card`, in `cosa.agents.prediction_engine.review_card`. Otherwise the answer is human when its source is `ui` and unknown if not. The backfill script uses it too. `counted_scored_filter()` is the SQL condition for a row the admin report counts and has scored.

## Replay
- `TimeSlicedDecisionStore` stands in for the decision embeddings. A case is visible only when its `responded_at` is at or before the moment the harness advanced to. So a forecast never sees a later answer. Its `add_decision`, `advance_to`, `find_similar`, `visible_ids` and `visible_cases` follow that rule; `visible_cases` gives whole copies of the visible cases with their `responded_at`.
- `replay( asks, engine, snapshot_sha256, baselines, store_factory, target_types, context_arms, episode_view_provider, principles_provider, target_ids, complete_action )` predicts every replayable ask in time order. It runs the real engine and each baseline. A baseline named in `context_arms` also gets a copy of the ask cut to its known fields. It gets the providers' episode view and principles too. Given `target_ids`, any other ask stays a case and is not predicted. With `complete_action` on, each record's meta also carries `complete_action` and `complete_action_decided`. With the engine's timeout-defaults switch on, a flagged ask is neither predicted nor scored but counted in `timeout_defaults`, and no baseline sees a flagged case. The engine's three-way vote reads the same cases as the arms, and the engine's store and case provider are put back afterwards. A name not in `baselines` raises `ValueError`. `rows_as_of( cases, asked_at, excluded_ids )` builds store rows as they stood at that moment.
- `predicted_value_for( result )` wraps a forecast the way the engine does before comparing it with an answer.
- The baselines: `always_yes_arm` forecasts yes. `prior_majority_arm` forecasts the stance most often given before among visible yes/no cases.
- `summarize( run, baseline_arm, operational_floor, arm )` compares the engine, or another arm named by `arm`, with one baseline, paired on the same asks. `paired_wins( run, arm, baseline, strict )` counts the asks only one of the two got right. With `strict` on, record lists of different length raise `ValueError`; `summarize` passes it off and cuts the longer list.

## Calibration
- `fit_and_evaluate( tune_rows, final_rows, cohort_sha, fit_time, n_bins )` fits on the tune rows and scores on the final rows. The final window never reaches the fit ([[prediction-calibration]]).
