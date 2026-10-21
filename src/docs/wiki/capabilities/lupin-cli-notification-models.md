---
capability: lupin-cli-notification-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.notifications.notification_models.AsyncNotificationRequest@4617accb72
  - lupin_cli.notifications.notification_models.AsyncNotificationResponse@c12e7b3e7f
  - lupin_cli.notifications.notification_models.ErrorEvent@7db65ef6ed
  - lupin_cli.notifications.notification_models.ExpiredEvent@286274ea04
  - lupin_cli.notifications.notification_models.NotificationPriority@de9751b245
  - lupin_cli.notifications.notification_models.NotificationResponse@6d55e81788
  - lupin_cli.notifications.notification_models.NotificationType@c1ee83ce4f
  - lupin_cli.notifications.notification_models.OfflineEvent@c2fa4dc945
  - lupin_cli.notifications.notification_models.RespondedEvent@9c9b282aab
  - lupin_cli.notifications.notification_models.ResponseType@124a834bc2
  - lupin_cli.notifications.notification_models.SSEEventBase@80dcda10aa
  - lupin_cli.notifications.notification_models.extract_sender_from_message@7566a55ce7
  - lupin_cli.notifications.notification_models.parse_sender_id@64d140f2fb
---
# CLI notification models

The typed values the notification clients build and read: enums, the answer events from the server's stream, the two response shapes and the async request. The clients are in [[lupin-cli-notifications]].

## What it does
- `NotificationType` has six values: task, progress, alert, custom, user_initiated_message and session_topic. `NotificationPriority` has low, medium, high and urgent. `ResponseType` has yes_no, open_ended, multiple_choice and open_ended_batch.
- Four events come off the answer stream, all built on `SSEEventBase`. `RespondedEvent` carries the answer and who posted it. `ExpiredEvent` carries the default if one was set. `OfflineEvent` always used the default. `ErrorEvent` carries a message and no answer.
- `NotificationResponse` is what the blocking client returns. Its `success` is true for exit code 0 and `is_error` is true for exit code 1. Exit code 2 is neither.
- It also carries `error_detail`, the server's own sentence for a non-200, and `reattach_state`, which says whether a dead stream was re-attached.
- `AsyncNotificationRequest` is the fire-and-forget request. It has no response type. Its timeout is 1 to 30 seconds and defaults to 5. It strips the message and refuses a blank one.
- Its `to_api_params` makes the query parameters for `/api/notify`. It raises `ValueError` while `target_user` is unset. The API key is not in it.
- `AsyncNotificationResponse` holds `success`, `status`, the target and a connection count. `is_queued` is true for the status queued. `is_error` is true for error, connection_error and timeout.
- `extract_sender_from_message` turns a leading `[LUPIN]` prefix into `claude.code@lupin.deepily.ai`. It returns `None` when there is no prefix.
- `parse_sender_id` splits a sender id into agent, project and session. A malformed id gives `unknown` for agent and project.

## Don't
- Don't add a type to only one enum. See [[lupin-cli-notification-types]] for the second copy.

## Invariants
- A message has no upper length.
- `parse_sender_id` accepts the old form with no `#session` part and gives a `None` session.
