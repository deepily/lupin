---
capability: rest-prediction-routes-and-outcome
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.db.repositories.prediction_log_repository.OutcomeAlreadyRecorded@65d086c981
  - cosa.rest.routers.notifications.PredictionSeenRequest@94dfb61adb
  - cosa.rest.routers.notifications.record_prediction_seen@af2199fb5a
  - cosa.rest.routers.system.prediction_engine_accuracy@19b1e41095
  - cosa.rest.routers.notifications.get_prediction_hint@29844ea45a
---
# Prediction routes and the one-outcome rule

Three routes and one error around the forecast log ([[rest-data-repos-proxy-predictions]]).

## What it does
- `OutcomeAlreadyRecorded`, a `ValueError`, is raised when an outcome is attached to a forecast row that already holds one. The stored outcome stays as it was.
- `POST /api/notify/prediction-seen/{notification_id}` takes `PredictionSeenRequest` (`rendered`, `fold_opened`, both default false, and an optional `draft_at_reveal` object) and needs an API key or a Bearer JWT. The first call that reports a time or a draft stores it, and a later call never overwrites it. The reply carries `draft_recorded`. A draft's `value` is the string the submit button would send; `exposure.compare_draft_to_answer` reads it. It answers 422 for a non-UUID id and 404 when no forecast row exists.
- `GET /api/prediction-engine/accuracy` (`prediction_engine_accuracy`) needs the admin role: 401 without a token, 403 without the role. It takes `window_days` (default 30), `category`, `response_type` and `sender_id` and returns `get_accuracy_summary`.
- Accuracy counts scored rows only. With none scored the rate is `None` and the status reads `insufficient data`. `test_override` rows are left out. A database failure answers 500, never a zero.
- `GET /api/notify/prediction-hint/{notification_id}` (`get_prediction_hint`) needs an API key or a Bearer JWT. It is the late-forecast fetch: a fold opened after the `prediction_hint_updated` event reads the card's current context forecast payload here. The states are forecasting, ready, unavailable and forecast_timed_out. With the display switch off the payload is null. A card with no baseline row reads forecasting, and forecast_timed_out once 30 seconds have passed since the ask. It answers 422 for a non-UUID id, 404 when the notification does not exist and 500 on a read failure.
