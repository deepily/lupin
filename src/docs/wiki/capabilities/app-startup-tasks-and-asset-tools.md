---
capability: app-startup-tasks-and-asset-tools
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_app.main.load_stt_model@0d41c8f438
  - lupin_app.main.clock_loop@22b2251fc5
  - lupin_app.main.websocket_heartbeat_loop@93f6feadc0
  - lupin_app.main.websocket_cleanup_loop@c01b7d0403
  - lupin_app.main.notification_expiry_sweep_loop@8e6dd7aa7f
  - lupin_app.asset_tokens.project_static_root@0e02f2112d
  - lupin_app.asset_tokens.static_url_to_path@f71f8f8b97
  - lupin_app.asset_tokens.source_files@3093a3afc7
  - lupin_app.asset_tokens.collect_refs@489e59a812
  - lupin_app.asset_tokens.main@a6aa3d34f8
---
# App startup tasks and asset tools

The model loader and background loops that `lifespan` starts, and the file helpers of `asset_tokens`. [[app-bootstrap-and-static]] describes the app build and the token check itself.

## What it does
- `load_stt_model` builds the speech-to-text pipeline during startup. `lifespan` then runs one warmup transcription when the warmup file exists. It raises `RuntimeError` when the model cannot load, and `KeyError` for a missing config value.
- `clock_loop` is always started. It emits a `sys_time_update` event to every connected WebSocket client each 60 seconds.
- `websocket_heartbeat_loop` runs only when the INI key `websocket heartbeat enabled` is true, and it is true by default. It checks heartbeats at the configured interval, 30 seconds by default, and removes dead connections.
- `websocket_cleanup_loop` runs only when `websocket cleanup enabled` is true, also by default. It removes sessions older than the maximum age, every hour by default.
- `notification_expiry_sweep_loop` closes response-required notifications whose asking client walked away. It runs only when `notification expiry sweep enabled` is true, and an absent key means off.
- The sweep waits `notification grace period seconds` past `expires_at` before marking a row, so a late answer is still honoured. It handles at most `notification expiry sweep batch limit` rows a pass.
- The sweep does its database work off the event loop, logs a database error and retries on the next tick.
- `project_static_root` and `static_url_to_path` map the project root and a `/static/...` URL to paths on disk.
- `source_files` lists every authored `.html` and `.js` under the static tree, sorted, reading the disk so a new file counts before it is committed.
- `collect_refs` returns one `( source, url, token )` tuple per versioned reference in those files. `main` runs verify or stamp and returns 0, 1 on drift, or 2 when stamp cannot converge.

## Don't
- Don't expect the sweep on a fresh install. Its key defaults to off, so a missing key never arms the one loop that can refuse a human answer.
- Don't let a loop exit on an error. Each loop logs it and carries on, and only cancellation at shutdown ends it.

## Invariants
- Every loop runs until the task is cancelled, and a cancellation is the normal way it ends.
