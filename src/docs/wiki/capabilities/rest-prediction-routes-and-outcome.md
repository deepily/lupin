---
capability: rest-prediction-routes-and-outcome
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.db.repositories.prediction_log_repository.OutcomeAlreadyRecorded@65d086c981
  - cosa.rest.routers.notifications.PredictionSeenRequest@62eb44ade4
  - cosa.rest.routers.notifications.record_prediction_seen@60b22542dd
  - cosa.rest.routers.system.prediction_engine_accuracy@19b1e41095
---
# Prediction routes and the one-outcome rule

Two routes and one error around the forecast log ([[rest-data-repos-proxy-predictions]]).

## What it does
- `OutcomeAlreadyRecorded`, a `ValueError`, is raised when an outcome is attached to a forecast row that already holds one. The stored outcome stays as it was.
- `POST /api/notify/prediction-seen/{notification_id}` takes `PredictionSeenRequest` (`rendered`, `fold_opened`, both default false, and an optional `draft_at_reveal` object) and needs an API key or a Bearer JWT. The first call that reports a time or a draft stores it, and a later call never overwrites it. The reply carries `draft_recorded`. It answers 422 for a non-UUID id and 404 when no forecast row exists.
- `GET /api/prediction-engine/accuracy` (`prediction_engine_accuracy`) needs the admin role: 401 without a token, 403 without the role. It takes `window_days` (default 30), `category`, `response_type` and `sender_id` and returns `get_accuracy_summary`.
- Accuracy counts scored rows only. With none scored the rate is `None` and the status reads `insufficient data`. `test_override` rows are left out. A database failure answers 500, never a zero.
