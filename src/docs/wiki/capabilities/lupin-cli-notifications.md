---
capability: lupin-cli-notifications
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_cli.notifications.notify_user_sync.notify_user_sync@a525efb30f
  - lupin_cli.notifications.notify_user_sync.HumanAskInTestError@c2a71f5afa
  - lupin_cli.notifications.notify_user_async.notify_user_async@0156c42205
  - lupin_cli.notifications.notify_user_async.calculate_retry_intervals@ab0f5347c1
  - lupin_cli.notifications.notify_user.notify_user@90fc665e59
  - lupin_cli.notifications.human_ask_containment.refusal_for_human_ask@d540ec25ec
  - lupin_cli.notifications.notification_models.NotificationRequest@c139812a32
  - lupin_cli.notifications.notification_models.resolve_target_user@daa309c26d
---
# CLI notification clients

The command-line side of notifications: scripts and functions that call `POST /api/notify` on the Lupin server. The server side is [[notification-delivery]]; the MCP voice tools are [[cosa-voice-mcp-server]].

## What it does
- `notify_user` sends one notification and returns `True` or `False`. `notify_user_async` is fire-and-forget with retries and returns an `AsyncNotificationResponse`. `notify_user_sync` sends a response-required notification and blocks on the server's SSE stream until an answer or a timeout.
- `notify_user_sync` returns a `NotificationResponse` whose exit code is 0 for an answer (or an offline default). It is 2 for a timeout that used a default, a request timeout or a re-attach that timed out. Every other failure is 1, including an expiry with no default (`status` is `expired_no_default`, `is_timeout` is true). It retries on any timeout response with a growing timeout, but only when `retry_on_timeout` is set and `max_attempts` is above 1. The default is one attempt.
- When the SSE stream dies, `_reattach_after_stream_death` polls the answer by notification id inside the time left. A landed answer is returned without an ack, so the next turn's catch-up still delivers it.
- `calculate_retry_intervals` sets the async retry waits: `[1, 1, 2, 2, 3]` for a 10-second budget and `[1, 2, 4, 5, 5, ...]` capped at 5 seconds for a longer one.
- `resolve_target_user` picks the recipient from, in order: the explicit value, `LUPIN_DEV_EMAIL`, the config file's `global_notification_recipient`, and otherwise raises `ValueError`.
- Notification types and priorities are defined twice: `notification_types` (5 types) and `notification_models` (6 types, adding `session_topic`). `notify_user` imports the first. `notify_user_sync` and `notify_user_async` import the types and priorities from `notification_models`, and take only the default server URL and its variable name from `notification_types`.

## Invariants
- A test must not block on a human. Under pytest, `notify_user_sync` raises `HumanAskInTestError` through `refusal_for_human_ask`. The guard reads `PYTEST_CURRENT_TEST`, which pytest sets itself, so a test cannot skip it by forgetting to opt in.
- The only waiver is `LUPIN_ALLOW_HUMAN_ASK_IN_TESTS=1`, and only the exact value `1` works. Outside pytest the guard returns `None` and nothing is raised.
- Network, validation and timeout failures of `notify_user_sync` come back as an exit code, not an exception. The recipient lookup is the exception: when no recipient is given and `resolve_target_user` finds none, its `ValueError` escapes `notify_user_sync`, `notify_user_async` and `notify_user` alike.
- The sync client is the one blocking path. A fire-and-forget `notify_user_async` never waits for the user.

## Known duplicates
- The duplicate report (`symindex dups`, 2026-10-07, tree `b94451536`) lists six members here. `validate_environment` is identical in `notify_user` and `notify_user_async`. Four `NotificationTestSuite.run_*` methods in `test_notifications.py` are exact or near copies of each other.

## How to extend
- Add a new notification type to both enums, or the scripts and the models disagree.
- Test a caller of the blocking ask with an injected fake, as `approval_for_promotion` does with `ask_fn`; do not waive the guard in an ordinary test.
