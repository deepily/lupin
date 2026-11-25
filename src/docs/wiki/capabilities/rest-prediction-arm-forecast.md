---
capability: rest-prediction-arm-forecast
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.postgres_models.PredictionArmForecast@93545840d9
  - cosa.rest.db.repositories.arm_forecast_repository.displayed_arm_for@7f4ce09bae
  - cosa.rest.db.repositories.arm_forecast_repository.displayed_arm_hook@25f1481f23
  - cosa.rest.db.repositories.arm_forecast_repository.notifications_missing_displayed_sibling@d866f73abf
  - cosa.rest.db.repositories.arm_forecast_repository.ForecastAlreadyFrozen@6d70be47b8
  - cosa.rest.db.repositories.arm_forecast_repository.update_arm_forecast@6f15b8715f
---
# Prediction arm forecasts

One forecast per card and arm, kept beside the card's `prediction_log` row ([[rest-data-repos-proxy-predictions]]). The engine that makes the forecasts is in [[prediction-engine]].

## What it does
- `PredictionArmForecast` is one row per `( notification_id, arm )`. `displayed` is true for the arm whose forecast the card showed. `applicability` lists `{ principle_id, rule }` for each principle the applicability checks dropped for the card. It is written only with that switch on, so NULL means the checks did not run and an empty list means they dropped none.
- `evidence_ids` means different things by arm. It holds principle ids for the principles forecast, and neighbour case ids for the case-based arm that showed the card.
- A late forecast is derived from `forecast_ready_at`, never stored. Deleting the notification deletes its rows.
- `displayed_arm_for( forecast_source )` names the arm a source stands for. It raises `KeyError` for an unregistered source, so a new source must be registered there.
- `displayed_arm_hook( arm )` returns the `pre_commit_hook` for `record_forecast`. It adds the displayed row and flushes, and the caller's commit stores it with the log row. An empty arm raises `ValueError`.
- `notifications_missing_displayed_sibling( session, since )` lists, sorted, the cards predicted at or after `since` that have a log row and no displayed sibling. An empty list means the table is reconciled.
- `update_arm_forecast( session, notification_id, arm, **changes )` reads the row under a lock. It returns `None` when no row exists.
- When the row exists it raises `ForecastAlreadyFrozen`, whatever the changes, and the stored row stays as it was.

## Don't
- Don't let a sibling row of another arm stand in for the displayed one. The check ignores it.
