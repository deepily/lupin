---
capability: prediction-three-way-stance
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.three_way_stance.backoff_prior@a5c43f7151
  - cosa.agents.prediction_engine.three_way_stance.levels_of@df1323416b
  - cosa.agents.prediction_engine.three_way_stance.neighbours_of@23dabd8e18
  - cosa.agents.prediction_engine.three_way_stance.predict_qualifier@ea68c4961d
  - cosa.agents.prediction_engine.three_way_stance.three_way_forecast@2283447613
  - cosa.agents.prediction_engine.three_way_stance.usable_cases@c4120456cd
  - cosa.agents.prediction_engine.three_way_shadow.live_cases@3d0ced1059
  - cosa.agents.prediction_engine.three_way_shadow.stance_of@676ea69f81
  - cosa.agents.prediction_engine.three_way_shadow.unavailable@f198e4132c
---
# Prediction three-way stance

A challenger to the engine's fixed `no` margin rule for yes/no asks ([[prediction-engine]]). It forecasts yes, no or neither, and stays in shadow until a paired comparison says otherwise. It reads only what was known at the ask: the ask's vector, its sender and the earlier answered cases.

## What it does
- `usable_cases` keeps the cases that may cast a personal stance vote. `levels_of` gives a row its family and project, the two back-off levels above the overall prior.
- `backoff_prior` estimates the stance prior by backing off from the ask's family to its project to the owner's overall answers.
- `neighbours_of` picks the nearest cases and weights each by cosine, recency and independence. The recency weight is the shared one, with the engine's half-life (`prediction engine recency half life days`, default 14).
- `predict_qualifier` chooses the qualifier apart from the stance, from the neighbours that gave the predicted stance.
- `three_way_forecast` returns the stance with its three probabilities.

## In shadow on live asks
- `live_cases` loads the owner's answered yes/no cases in the shape the challenger reads. `stance_of` reduces a forecast to what the row stores. `unavailable` names why there is no stance, so the row says so instead of staying empty.
- `PredictionEngine.record_three_way_shadow` runs on each live yes/no ask when `prediction engine three way enabled` is true. It runs after the forecast row is written and stores the stance in `prediction_log.three_way_shadow`. It never reaches the card, never changes another column and never raises.
