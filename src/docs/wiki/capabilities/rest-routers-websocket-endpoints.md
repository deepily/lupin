---
capability: rest-routers-websocket-endpoints
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.websocket.get_websocket_manager@5c65f1b7d1
  - cosa.rest.routers.websocket.get_active_tasks@5d1e6982b5
  - cosa.rest.routers.websocket.get_app_debug@a612f9c35f
  - cosa.rest.routers.websocket.auth_test@6d84714cd3
  - cosa.rest.routers.websocket.websocket_audio_endpoint@26dbdd1f57
  - cosa.rest.routers.websocket.stop_cc_transcript_tailers_for_disconnect@668f039df1
  - cosa.rest.routers.websocket_admin.get_websocket_manager@5c65f1b7d1
  - cosa.rest.routers.websocket_admin.get_websocket_sessions@ed6e50510e
  - cosa.rest.routers.websocket_admin.get_websocket_stats@62dc3f660a
  - cosa.rest.routers.websocket_admin.get_websocket_session@91323fc0f5
  - cosa.rest.routers.websocket_admin.disconnect_websocket_session@1797c948e5
  - cosa.rest.routers.websocket_admin.update_single_session_policy@1d12d415fe
  - cosa.rest.routers.websocket_admin.get_available_events@4259fb8ba0
---
# WebSocket audio endpoint and session admin routes

The `/ws/audio/{session_id}` socket, its dependencies and the `/api` routes that inspect and manage live WebSocket sessions. The wider design is in [[rest-routers]].

## What it does
- `websocket_audio_endpoint` accepts a valid session id, subscribes to audio events, answers `auth_request` with `auth_success` or `auth_error`, and answers `sys_ping` with `sys_pong`. An invalid id closes with code 1008.
- On disconnect it cancels the session's active streaming task.
- `get_websocket_manager`, `get_active_tasks` and `get_app_debug` read the manager, the task table and the debug flags from the main module. `websocket_admin` has its own `get_websocket_manager`.
- `auth_test` (`GET /api/auth-test`) is the version in `websocket.py`. `system.auth_test` has the same path and is included first, so it answers and this one is never reached.
- `stop_cc_transcript_tailers_for_disconnect` stops each tailer a leaving session was the last watcher of.
- `get_websocket_stats` (`/api/websocket-sessions/stats`) returns counts. `get_websocket_session` (`/api/websocket-sessions/{session_id}`) returns one session, or 404.
- `GET /api/websocket-sessions` and `POST /api/websocket-sessions/cleanup` are answered by `system.get_websocket_sessions` and `system.cleanup_stale_sessions`, because `system.router` is included before `websocket_admin.router`. The `websocket_admin.get_websocket_sessions` pinned here and its cleanup twin are unreachable.
- `disconnect_websocket_session` drops one session, and answers 404 when it is not connected.
- `update_single_session_policy` takes `enabled` and applies it to new connections. `get_available_events` returns the sorted event names.

## Don't
- Don't assume the admin routes need the admin role. They take any signed-in user, and so do the `system.py` versions that shadow two of them.

## Invariants
- A replaced connection is not disconnected by the old socket's cleanup.
