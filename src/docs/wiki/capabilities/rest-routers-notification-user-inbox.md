---
capability: rest-routers-notification-user-inbox
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.notifications.get_user_notifications@830e4a6281
  - cosa.rest.routers.notifications.get_next_notification@feb899a9a5
  - cosa.rest.routers.notifications.mark_notification_played@ddd8867c45
  - cosa.rest.routers.notifications.delete_notification@66801a9897
  - cosa.rest.routers.notifications.bulk_delete_notifications@e4b3f23394
  - cosa.rest.routers.notifications.PredictionVoteRequest@3bb4d5ef44
  - cosa.rest.routers.notifications.vote_on_prediction_hint@445670813e
  - cosa.rest.routers.notifications.get_broadcast_acks@b98dc16b15
---
# Notification user inbox, votes and acks

The per-user and per-notification doors of `routers/notifications.py`, under `/api`. All need an API key or a JWT. Routes with `{user_id}` or `{user_email}` in the path also need the caller to be that user. See [[rest-routers-notification-helpers-and-catch-up]].

## What it does
- `get_user_notifications` answers `GET /notifications/{user_id}` from the in-memory queue. `include_played`, `limit` (default 50), `priorities` and `sort` (`queue` or `oldest`) apply. A priority outside urgent, high, medium and low is 400.
- `get_next_notification` answers `GET /notifications/{user_id}/next` with `found` or `none_available`, and does not change the played flag.
- `mark_notification_played` answers `POST /notifications/{id}/played`. `delete_notification` answers `DELETE /notifications/{id}`. Both are 404 for an unknown id.
- `bulk_delete_notifications` answers `DELETE /notifications/bulk/{user_email}`. Another user's email is 403, checked first. `hours` must be above 0 (else 400). `exclude_own_jobs` keeps the user's own job rows and rows with no job id.
- `PredictionVoteRequest` is the vote body: `vote` is `up` or `down`. `predicted_value` is optional in the model, but the route answers 422 without it.
- `vote_on_prediction_hint` answers `POST /notify/prediction-vote/{id}`. It records one case, approved on up and rejected on down, and a second vote flips it. A question it cannot resolve is 422.
- `get_broadcast_acks` answers `GET /notifications/broadcast-acks/{broadcast_id}`. It returns the latest ack per session for the caller's own broadcasts, whatever the delivery state, newest first. `limit` (default 500) caps the rows scanned before that fold.

## Don't
- Don't rely on the played and delete doors to check ownership. They check only that the caller is signed in.
- Don't read an empty `acks` list as an error. It means nobody has acked.

## Invariants
- A database failure on acks is a 500, never an empty list.
