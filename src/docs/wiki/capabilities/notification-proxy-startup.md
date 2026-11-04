---
capability: notification-proxy-startup
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.notification_proxy.__main__.main@0cf15f83b3
  - cosa.agents.notification_proxy.__main__.parse_args@5acfa0926f
  - cosa.agents.notification_proxy.listener.WebSocketListener@f9243e7377
  - cosa.agents.notification_proxy.voice_io.notify@1f32442af0
---
# Notification proxy startup

`python -m cosa.agents.notification_proxy` starts the listener and the responder described in [[notification-proxy]]. This page covers the command line, the listener and the status notices.

## What it does
- `parse_args` takes `--host`, `--port`, `--email`, `--password`, `--session-id`, `--profile`, `--strategy`, `--debug`, `--verbose` and `--dry-run`. The strategy is `llm_script`, `rules` or `auto`, and defaults to `llm_script`.
- `main` treats `--verbose` and `--dry-run` as `--debug`. A credential error exits with code 1.
- It prints a banner with the model and cloud availability. It builds the responder and the listener, and gives the responder the listener's token for posting answers.
- It sends a low-priority notice on connect and on disconnect, and stops the listener on interrupt or terminate. On exit it prints the responder's statistics.
- `WebSocketListener` subclasses `BaseWebSocketListener` ([[proxy-agent-base]]) and fixes the subscribed events. It logs in with `/auth/login`, opens `/ws/queue/<session id>` and sends an auth request with the subscribed events: `notification_queue_update`, `job_state_transition` and `sys_ping`.
- It answers `sys_ping` with `sys_pong` and passes every other message to the `on_event` callback. A failing callback is printed, and the loop continues.
- `authorization` is the `Bearer` token from the last login, or `None` before the first one. A reconnect logs in again, so the token is fresh.
- `voice_io.notify` sends a status notice as the proxy's sender id, at low priority by default, with keywords from `build_notify_kwargs`. It returns whether the notice was sent.

## Invariants
- A dropped connection reconnects with growing delays. This listener's delay is plain exponential, capped, with no jitter. After `RECONNECT_MAX_ATTEMPTS` failures in a row, `run` gives up. The count resets when the server confirms the auth request, not at login.
- A failed login or a refused auth ends that connection attempt and counts as a failure.
