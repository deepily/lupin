---
capability: notification-delivery
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.routers.notifications.notify_user@1eb03c0b2c
  - cosa.rest.routers.notifications.submit_notification_response@a3844000f9
  - cosa.rest.notification_fifo_queue.NotificationFifoQueue.push@a403944495
  - cosa.rest.notify_rate_limiter.check_notify_allowed@e189f2ade6
  - cosa.rest.notification_expiry_sweeper.sweep_once@ea08e4dc58
  - cosa.rest.fcm_wake_service.FcmWakeService.maybe_send_wake@a0196dfc7f
  - cosa.rest.fcm_push_pause.PushPauseController.pause@59a7d6b7fe
---
# Notification delivery

How a notification is created, queued, answered, expired and pushed to a phone. The sender side of the voice tools is in [[cosa-voice-mcp-server]]; rows live in `NotificationRepository` and `FcmTokenRepository` ([[db-repositories]]).

## What it does
- `POST /api/notify` (`notify_user`) checks the per-sender rate limit, finds the target user and stores a row unless `persist` is false. If the user has a live connection it pushes a `NotificationItem` onto the `NotificationFifoQueue`, which emits a WebSocket event. If not, and the request carries a `job_id`, it tries that job's `cc-listener` session. Otherwise it answers `user_not_available` and queues nothing.
- A notification can ask for a response; `POST /api/notify/response` records the answer.
- `check_notify_allowed` is a sliding window per `sender_id`: 60 sends per 10 seconds by default, read from `messaging backpressure *` keys and re-read when the INI file changes. Over the cap the route answers 429 with `Retry-After`.
- `notification_expiry_sweeper` closes response-required notifications whose asker walked away. The loop in `lupin_app/main.py` runs `sweep_once` every `notification expiry sweep interval seconds` (300 in the INI) on at most 200 rows.
- When a user-targeted notification is enqueued, before the queue checks whether emission is enabled, it calls `FcmWakeService.maybe_send_wake`. The wake is a content-free `ws_wake` push that tells the mobile app to fetch over the API. Device tokens are registered at `/api/fcm/register-token` and removed at `/api/fcm/unregister-token`.
- `/api/fcm/push-pause` (admin) turns wake pushes off in memory, optionally for a set number of minutes.

## Invariants
- `/api/notify/response` accepts an answer to a `delivered` row with no deadline, and to an `expired` row only until `notification grace period seconds` (300) after `expires_at`. After that it answers 400, and a row already `responded` answers 400.
- The sweeper waits that same grace key past `expires_at` before it marks a row expired. It reads one key and not a second delay, so the two cannot disagree. It never writes `response_default`, because nobody was waiting for it.
- A notification with no `user_id` never wakes a device. The wake policy runs in this order: enabled, paused, a live mobile WebSocket, debounce, at least one registered token, send. A push inside the debounce window (60 seconds in the INI) is deferred to one trailing wake and not dropped, and a device that reconnected meanwhile is not woken.
- A pause lives only in memory. Restarting the server restores the boot value of `fcm wake push enabled`.
- A wake failure never reaches the notification path: the hook catches every exception.

## How to extend
- Put new wake rules in `FcmWakeService.maybe_send_wake` and keep the queue hook a one-liner.
- Tune limits through the INI keys; the code carries only fallback defaults, and the 24-hour cap on a wake pause is fixed.
