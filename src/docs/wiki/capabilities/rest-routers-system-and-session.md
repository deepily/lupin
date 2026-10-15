---
capability: rest-routers-system-and-session
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.system.SimilarityConfirmationRequest@0ebcb9efaa
  - cosa.rest.routers.system.SimilarityConfirmationResponse@a7adc21687
  - cosa.rest.routers.system.get_todo_queue@9bc801466a
  - cosa.rest.routers.system.health_check@00848fea5f
  - cosa.rest.routers.system.get_server_info@8f6aeba2d2
  - cosa.rest.routers.system.reset_prediction_engine@439c7000c5
  - cosa.rest.routers.system.get_session_id@ac09280b89
  - cosa.rest.routers.system.auth_test@46733b121c
  - cosa.rest.routers.system.get_websocket_sessions@60271eecbd
  - cosa.rest.routers.system.cleanup_stale_sessions@318f426280
  - cosa.rest.routers.system.get_websocket_state@cfe1ae4f64
  - cosa.rest.routers.system.get_client_config@52256112e4
  - cosa.rest.routers.system.get_similarity_confirmation@38529ebbf0
  - cosa.rest.routers.system.set_similarity_confirmation@7061cab6ed
  - cosa.rest.routers.system.BounceResponse@4bc17608c8
---
# System routes: health, sessions and runtime toggles

The server's own status routes in `routers/system.py`: health, build facts, WebSocket session views, client timing config and two runtime switches.

## What it does
- `health_check` (`GET /`) returns service, timestamp, version and `code_identity`. It takes no credential.
- `get_server_info` returns `config_block_id`, the database URL with its password replaced by `***`, and the `LUPIN_ENV` name. No credential.
- `get_session_id` returns a fresh two-word `session_id` for WebSocket routing, made by the injected id generator. `get_todo_queue` is the dependency that hands out the todo queue.
- `auth_test` echoes the authenticated user, so a caller can prove a token works. With no token it answers 401.
- `get_websocket_sessions` returns session counts, unique users, users with more than one session and the single-session policy flag. `cleanup_stale_sessions` (POST) drops sessions older than `max_age_hours`, default 24, and returns the count.
- `get_websocket_state` dumps the manager's mappings and diagnostics. It has no credential check; it is a debug door.
- `get_client_config` returns the web client's settings, read from the INI. They are token refresh timing, heartbeat, timezone, TTS preview and an `env_label` of `TEST` or `DEVELOPMENT`. It needs a valid token.
- `get_similarity_confirmation` and `set_similarity_confirmation` read and write the live INI value `similarity confirmation enabled` through the todo queue's config manager. The set reply carries `enabled` and `previous`. Bodies are `SimilarityConfirmationRequest` and `SimilarityConfirmationResponse`.
- `reset_prediction_engine` (POST) rebuilds the PredictionEngine singleton. It needs a credential. It clears decision rows only when `drop_table=true`; a failed clear still resets and answers `status: error`.
- `BounceResponse` is the body of `POST /api/system/bounce`: 202 triggered, 409 a bounce is running, 503 the host watcher is silent.

## Don't
- Don't send `get_client_config` without a token and expect defaults. It answers 401.
- Don't treat the `version` field in `health_check` as the running build. Read `code_identity`.
