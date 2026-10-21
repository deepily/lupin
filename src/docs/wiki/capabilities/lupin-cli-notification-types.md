---
capability: lupin-cli-notification-types
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.notifications.notification_types.NotificationPriority@caa17c4b71
  - lupin_cli.notifications.notification_types.NotificationType@980fa87225
  - lupin_cli.notifications.notification_types.validate_server_environment@0cd0c83765
---
# CLI notification types

The plain enums and the server check used by the command-line scripts. The pydantic copy of the enums is in [[lupin-cli-notification-models]].

## What it does
- `NotificationType` has five values: task, progress, alert, custom and user_initiated_message. `values` lists them in declaration order.
- `NotificationPriority` has low, medium, high and urgent. `values` lists them from low to urgent.
- `validate_server_environment` reads `LUPIN_APP_SERVER_URL` and falls back to `http://localhost:7999`.
- It reports a URL that does not start with `http://` or `https://`, a URL with no host and any parse error. It prints each issue and returns `False`, or prints the URL and returns `True`.

## Don't
- Don't look for `session_topic` here. Only the models copy has it.

## Invariants
- The function never raises. Every exception becomes an issue line.
- The default type is custom and the default priority is medium.
