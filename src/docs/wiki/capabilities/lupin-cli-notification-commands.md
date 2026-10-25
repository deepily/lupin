---
capability: lupin-cli-notification-commands
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.notifications.notify_user.main@997116db53
  - lupin_cli.notifications.notify_user.validate_environment@f16063d649
  - lupin_cli.notifications.notify_user_async.main@0f88a039bc
  - lupin_cli.notifications.notify_user_async.validate_environment@f16063d649
  - lupin_cli.notifications.notify_user_sync.consume_sse_stream@b81ac31040
  - lupin_cli.notifications.notify_user_sync.main@2eb1813a59
  - lupin_cli.notifications.test_notifications.NotificationTestSuite@27b9f5973e
  - lupin_cli.notifications.test_notifications.main@6026f47d3b
---
# CLI notification commands

The command lines behind the three clients, the stream reader of the blocking one and the end-to-end test script. The client functions are in [[lupin-cli-notifications]].

## What it does
- `notify_user.main` takes a message plus `--type`, `--priority`, `--target-user`, `--server`, `--timeout`, `--validate-env` and `--debug`. It exits 0 when the send worked and 1 otherwise.
- `notify_user_async.main` adds `--sender-id`. It builds an `AsyncNotificationRequest`, so a bad value prints each field error and exits 1. Otherwise the exit code follows `response.success`.
- `notify_user_sync.main` adds `--response-type`, `--response-default` and `--title`. The timeout defaults to 120. It prints the answer to stdout so a shell script can capture it, then exits with the response exit code.
- `validate_environment` in the plain and async scripts just returns `validate_server_environment`, and `--validate-env` exits 0 or 1 on it.
- `consume_sse_stream` reads the answer stream and returns the first terminal event. A frame that is not valid JSON, or fails validation, is reported and skipped. It returns `None` on a timeout, a stream error, or a stream that ends with no result.
- It records the notification id from the opening `ack` frame and keeps reading. It skips an unknown status and a frame that fails validation.
- A timer cuts the stream five seconds after the timeout. A stream that sends bytes but never a full line would otherwise never return.
- `NotificationTestSuite` sends real notifications through `notify_user` and records pass or fail with timing. `main` in `test_notifications.py` runs the full or `--quick` suite, or only the environment check with `--validate-only`.

## Don't
- Don't run the test script in a unit test. It sends to a live server.

## Invariants
- No error leaves `consume_sse_stream`. A cut by the timer is flagged so it is not reported as a network death.
- The error scenario tests count as passed when the call does not crash.
