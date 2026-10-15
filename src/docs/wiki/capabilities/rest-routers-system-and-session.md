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
  - cosa.rest.routers.system.get_websocket_state@5b8d9efef0
  - cosa.rest.routers.system.get_client_config@52256112e4
  - cosa.rest.routers.system.get_similarity_confirmation@38529ebbf0
  - cosa.rest.routers.system.set_similarity_confirmation@7061cab6ed
  - cosa.rest.routers.system.BounceResponse@4bc17608c8
---
# System routes: health, sessions and runtime toggles

The server's own status routes in `routers/system.py`: health, build facts, WebSocket session views, client timing config and two runtime switches.

## What it does
- `health_check` (`GET /`) returns service, timestamp, version and `code_identity`. It takes no credential.
- `get_server_info` returns `config_block_id`, the database URL with its password replaced by `***`, and the lowercased `LUPIN_ENV` name, `development` when unset. No credential.
- `get_session_id` returns a fresh two-word `session_id` for WebSocket routing, made by the injected id generator. `get_todo_queue` is the dependency that hands out the todo queue.
- `auth_test` echoes the authenticated user, so a caller can prove a token works. With no token it answers 401.
- `get_websocket_sessions` returns session counts, unique users, users with more than one session and the single-session policy flag. `cleanup_stale_sessions` (POST) drops sessions older than `max_age_hours`, default 24, and returns the count.
- `get_websocket_state` dumps the manager's mappings and diagnostics. It needs the admin role (401 anonymous, 403 otherwise); it is a debug door.
- `get_client_config` (`GET /api/config/client`) returns the web client's settings, read from the INI with defaults. They are token refresh timing, heartbeat, `app_timezone`, TTS preview and mode, and a few feature flags. `env_label` is `TEST` when `LUPIN_ENV` is `test` or `testing`, else `DEVELOPMENT`. It needs a valid token.
- `get_similarity_confirmation` and `set_similarity_confirmation` read and write `similarity confirmation enabled` in the todo queue's live config manager. The write is in memory only, and the INI file is not rewritten. Both need a signed-in user. The set reply carries `enabled` and `previous`. Bodies are `SimilarityConfirmationRequest` and `SimilarityConfirmationResponse`.
- `reset_prediction_engine` (POST) rebuilds the PredictionEngine singleton. It needs a credential. It clears decision rows only when `drop_table=true`; a failed clear still resets and answers `status: error`.
- `BounceResponse` names the fields (`status`, `reason`, `detail`, `timestamp`) of the `POST /api/system/bounce` reply, which needs a signed-in user. It answers 202 triggered, 409 a bounce is running, 503 the host watcher heartbeat is missing or stale. The handler returns a plain `JSONResponse`, not this model.

## Don't
- Don't send `get_client_config` without a token and expect defaults. It answers 401.
- Don't treat the `version` field in `health_check` as the running build. Read `code_identity`.
