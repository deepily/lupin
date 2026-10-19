---
capability: rest-routers-notification-helpers-and-catch-up
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.notifications.get_notification_queue@419a0b0054
  - cosa.rest.routers.notifications.get_websocket_manager@5c65f1b7d1
  - cosa.rest.routers.notifications.get_local_timestamp@41b941186c
  - cosa.rest.routers.notifications.get_formatted_time_display@015516485d
  - cosa.rest.routers.notifications.get_formatted_date_display@7b9acad9ef
  - cosa.rest.routers.notifications.resolve_sender_id@da26ad8ca8
  - cosa.rest.routers.notifications.get_undelivered_notifications@5da1b0c642
  - cosa.rest.routers.notifications.get_awaiting_response_notifications@056633c87d
  - cosa.rest.routers.notifications.get_answers_owed@a0d70b0ffc
  - cosa.rest.routers.notifications.ack_answer_owed@84d1466725
  - cosa.rest.routers.notifications.get_notification_response@56e16f5b7a
  - cosa.rest.routers.notifications.dismiss_undelivered_notifications@defe68dd3e
---
# Notification helpers and catch-up reads

Helpers and the catch-up routes of `routers/notifications.py`, all under `/api`. The routes need an API key or a JWT. See [[notification-delivery]] and [[rest-routers-notification-user-inbox]].

## What it does
- `get_notification_queue` and `get_websocket_manager` fetch the queue and the socket manager from `lupin_app.main`.
- `get_local_timestamp`, `get_formatted_time_display` and `get_formatted_date_display` read the INI key `app timezone` (default `America/New_York`). They give an ISO stamp, `HH:MM TZ` and `YYYY-MM-DD`. A bad zone falls back to the server's local time, without the zone name.
- `resolve_sender_id` picks the explicit sender id, else `claude.code@<prefix>.deepily.ai` from a leading `[PREFIX]` of capital letters in the message, else `claude.code@unknown.deepily.ai`.
- `get_undelivered_notifications` answers `GET /api/notifications/undelivered` with rows in state created or queued, oldest first, within the age cap (INI `notification undelivered max age hours`, default 24). It is 400 if the caller's id is not a UUID. `dismiss_undelivered_notifications` hides them with `POST /notifications/undelivered/dismiss`, keeps their state and returns `dismissed_count`.
- `get_awaiting_response_notifications` answers `GET /notifications/awaiting-response` with unanswered, unexpired cards, each with `voice_persona`, `suppress_ding` true and, when it has an expiry, `timeout_seconds` recomputed from it. Hidden cards are left out. It marks nothing.
- `get_answers_owed` answers `GET /notifications/answers-owed?persona=` with answered asks not yet handed back, oldest answer first. `session_hash8` sets `from_earlier_session` and never filters. `since` must be ISO 8601, else 400.
- `ack_answer_owed` stamps `answer_delivered_at` for a `notification_id` in the body. It is 422 without one and 404 for an unknown id. A `notification_id` that is not a UUID answers 500.
- `get_notification_response` answers `GET /notifications/response/{id}` with `state`, `response_value` and `responded_at`, and does not ack. It is 404 for an unknown id and 500 for one that is not a UUID.

## Don't
- Don't ack on serve. Ack only after the answer was used, or a dropped reply loses it.
- Don't treat `answers-owed` as per-caller. Any valid key can pull any persona's answers.

## Invariants
- Serving an owed answer never marks it delivered. Only the ack does.
