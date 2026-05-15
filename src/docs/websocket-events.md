# WebSocket Event System Documentation

**Date**: 2026.03.20
**Source of truth**: `lupin-app.ini` key `websocket available events`, `src/cosa/rest/routers/websocket.py`
**Status**: Active

## Event Catalog

The system defines **22 events** in `lupin-app.ini`. Clients subscribe to specific events (or `"*"` for all) during the auth handshake or via dynamic subscription updates.

### Event Summary Table

| Event | Category | Direction | User-Scoped |
|-------|----------|-----------|-------------|
| `job_state_transition` | Job lifecycle | Server → Client | Yes |
| `job_paused` | Job lifecycle | Server → Client | Yes |
| `job_resumed` | Job lifecycle | Server → Client | Yes |
| `tts_job_request` | TTS | Server → Client | Yes |
| `audio_streaming_chunk` | Audio | Server → Client | Yes |
| `audio_streaming_status` | Audio | Server → Client | Yes |
| `audio_streaming_complete` | Audio | Server → Client | Yes |
| `notification_queue_update` | Notifications | Server → Client | Yes |
| `notification_play_sound` | Notifications | Server → Client | Yes |
| `notification_expired` | Notifications | Server → Client | Yes |
| `notification_responded` | Notifications | Server → Client | Yes |
| `commons_activity` | Notifications (notification_queue_update wrapper, `type="commons_activity"`) | Server → Client | Yes |
| `proxy_decision_new` | Proxy / Ratification | Server → Client | Yes |
| `sys_time_update` | System | Server → Client | No (broadcast) |
| `status` | System | Server → Client | Varies |
| `error` | System | Server → Client | Varies |
| `sys_ping` | System | Bidirectional | No |
| `sys_pong` | System | Server → Client | No |
| `auth_request` | Auth handshake | Client → Server | N/A |
| `auth_success` | Auth handshake | Server → Client | N/A |
| `auth_error` | Auth handshake | Server → Client | N/A |
| `connect` | Lifecycle | Server → Client | N/A |
| `update_subscriptions` | Subscription mgmt | Client → Server | N/A |

---

## Job Lifecycle Events

### `job_state_transition`

Notifies when a job moves between queues (todo → running → done/dead). Replaces the deprecated `queue_*_update` events. User-scoped — only sent to the job's owner.

**Payload**:
```json
{
  "type": "job_state_transition",
  "job_id": "abc123",
  "from_queue": "run",
  "to_queue": "done",
  "job_metadata": {
    "agent_type": "MathAgent",
    "question": "What is 2+2?"
  },
  "timestamp": "2026-03-20T10:30:00Z"
}
```

**Queue values**: `"todo"`, `"run"`, `"done"`, `"dead"`

### `job_paused`

Emitted when a todo queue job is paused via `PATCH /api/queue/todo/{id}/pause`. User-scoped — sent to the job's owner. The frontend handler updates the card in-place (adds `.job-paused` class, paused badge, swaps button icon to ▶).

**Payload**:
```json
{
  "type": "job_paused",
  "job_id": "mock-abc123::user-uuid",
  "paused": true,
  "timestamp": "2026-03-28T20:00:00"
}
```

**Source**: `src/cosa/rest/routers/queues.py` → `pause_job()` → `emit_to_user_sync()`

### `job_resumed`

Emitted when a paused todo queue job is resumed via `PATCH /api/queue/todo/{id}/resume`. User-scoped — sent to the job's owner. The frontend handler clears the paused state (removes `.job-paused` class, removes badge, swaps button icon back to ⏸).

**Payload**:
```json
{
  "type": "job_resumed",
  "job_id": "mock-abc123::user-uuid",
  "paused": false,
  "timestamp": "2026-03-28T20:01:00"
}
```

**Source**: `src/cosa/rest/routers/queues.py` → `resume_job()` → `emit_to_user_sync()`

---

## Audio / TTS Events

### `tts_job_request`

Job completion notification with TTS audio.

**Payload**:
```json
{
  "type": "tts_job_request",
  "text": "Your calculation has been completed successfully.",
  "audioURL": "/static/audio/job_complete_123.mp3",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

### `audio_streaming_chunk`

Individual audio chunk during progressive TTS streaming. Sent over the audio WebSocket (`/ws/audio/{session_id}`).

**Payload**:
```json
{
  "type": "audio_streaming_chunk",
  "chunk_index": 3,
  "data": "<base64-encoded-audio>",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

### `audio_streaming_status`

Audio WebSocket connection/streaming status updates. Also serves as the connection confirmation message for audio WebSocket connections.

**Payload**:
```json
{
  "type": "audio_streaming_status",
  "text": "Audio WebSocket connected for session wise penguin",
  "status": "success",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

### `audio_streaming_complete`

Signals end of an audio stream. Client should finalize audio playback.

**Payload**:
```json
{
  "type": "audio_streaming_complete",
  "session_id": "wise penguin",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

**Note**: Audio WebSockets have a **fixed subscription set**: `audio_streaming_status`, `audio_streaming_complete`, `sys_ping`. This is hardcoded in the router, not client-configurable.

---

## Notification Events

### `notification_queue_update`

Queue-level notification update. Sent when notification state changes (new notification, read status change, dismissal).

**Payload**:
```json
{
  "type": "notification_queue_update",
  "notification_id": "notif-456",
  "action": "new",
  "data": { "..." },
  "timestamp": "2026-03-20T10:30:00Z"
}
```

### `notification_play_sound`

Triggers a sound notification on the client (e.g., chime on job completion).

**Payload**:
```json
{
  "type": "notification_play_sound",
  "sound": "complete",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

### `notification_expired`

Broadcast when a response-required notification times out without user response. The server applies the `response_default` (if set) and closes the SSE stream.

**Payload**:
```json
{
  "type": "notification_expired",
  "notification_id": "7a3d1fd8-...",
  "default_used": null,
  "timeout": true,
  "timestamp": "2026-03-23T16:35:51Z"
}
```

### `notification_responded`

Broadcast when a user submits a response to a response-required notification. Allows other clients to update their UI (e.g., remove pending indicator).

**Payload**:
```json
{
  "type": "notification_responded",
  "notification_id": "7a3d1fd8-...",
  "response_value": "Add new bugs",
  "timestamp": "2026-03-23T16:34:00Z"
}
```

---

### `commons_activity`

**NEW 2026-05-14** — Real-time push of new commons-topic entries to the broadcast-card Recent Activity stream. Powers the admin-oversight surface described in [`../rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md`](../rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md).

Wrapped in the canonical `notification_queue_update` envelope with `notification.type == "commons_activity"`. Fired by `CommonsActivityWatcher` (FastAPI-side daemon in `src/cosa/rest/commons_activity_watcher.py`) on each ~1s tick when new entries land in the commons store on any non-excluded topic. Recipient is resolved best-effort from `metadata.sender_user_id` first, then a bridge-owner lookup keyed by `sender_session_id`; falls back to broadcast-to-all-authenticated-WS in single-user dev.

Gated by two INI keys (both default True per Q9):
- `commons traffic visibility enabled` — master flag (hot-reloadable via the config re-init endpoint)
- `commons traffic visibility ws push enabled` — emergency-throttle to disable the WS push while keeping the section visible

**Payload** (under `notification.payload`):
```json
{
  "ts": "2026-05-14T20:00:00+00:00",
  "topic": "coord-notifications-js",
  "topic_kind": "free-form",
  "sender_session_id": "...",
  "persona_name": "Maria",
  "persona_icon": "🌸",
  "persona_color": "#F06292",
  "body": "...",
  "metadata": { ... }
}
```

`topic_kind` is `"reserved"` for `broadcasts` + `broadcast-acks`; `"free-form"` otherwise. The client uses this to decide whether to render a topic-chip prefix (Q2 ratification — free-form gets a chip; reserved doesn't). Excluded topics (`presence` + `system-events` by default per `commons traffic visibility exclude topics`) never appear in this stream.

Client handling: `notifications.js::_handleCommonsActivityWS()` prepends the new entry to `#commons-recent-activity-entries`, preserving newest-first ordering (Q7 ratification).

---

## Proxy / Ratification Events

### `proxy_decision_new`

Real-time notification when the SWE Team decision proxy logs a new pending ratification decision. Enables the Trust Dashboard to update without polling.

**Payload**:
```json
{
  "type": "proxy_decision_new",
  "decision_id": "dec-789",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

---

## System Events

### `sys_time_update`

Periodic time broadcast. Interval controlled by `app_debug` setting (5s in debug, 60s in production).

**Payload**:
```json
{
  "type": "sys_time_update",
  "time": "10:30:00",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

### `status`

General status update event for system-level state changes.

### `error`

Error event for broadcasting system-level errors to connected clients.

### `sys_ping` / `sys_pong`

Keepalive mechanism. Server sends `sys_ping` during heartbeat checks; clients respond with `sys_pong`. Clients can also send `sys_ping` and receive `sys_pong`.

**Ping payload**: `{"type": "sys_ping", "timestamp": "..."}`
**Pong payload**: `{"type": "sys_pong", "timestamp": "..."}`

---

## Auth Handshake Events

These events are part of the `/ws/queue/` authentication flow and are not subscribable.

### `auth_request` (Client → Server)

First message a client must send after connecting to `/ws/queue/{session_id}`.

```json
{
  "type": "auth_request",
  "token": "Bearer <jwt_token>",
  "subscribed_events": ["job_state_transition", "notification_queue_update"]
}
```

- `subscribed_events` is optional; defaults to `["*"]` (all events)
- `token` can include or omit the `Bearer ` prefix (stripped server-side)

### `auth_success` (Server → Client)

```json
{
  "type": "auth_success",
  "user_id": "user-123",
  "session_id": "wise penguin"
}
```

### `auth_error` (Server → Client)

Sent immediately before the server closes the connection.

```json
{
  "type": "auth_error",
  "message": "Token expired"
}
```

---

## Lifecycle Events

### `connect`

Post-authentication connection confirmation sent immediately after `auth_success`.

```json
{
  "type": "connect",
  "message": "Connected to queue WebSocket",
  "session_id": "wise penguin",
  "timestamp": "2026-03-20T10:30:00Z"
}
```

---

## Subscription Management Events

### `update_subscriptions` (Client → Server)

Sent after authentication to modify event subscriptions dynamically.

```json
{
  "type": "update_subscriptions",
  "events": ["job_state_transition", "notification_queue_update"],
  "action": "replace"
}
```

**Actions**: `replace` (set exact list), `add` (append), `remove` (subtract)

**Server response**:
```json
{
  "type": "subscription_update",
  "success": true,
  "subscriptions": ["job_state_transition", "notification_queue_update"]
}
```

---

## Subscription Patterns

### Subscribe to All Events

```json
{"subscribed_events": ["*"]}
```

### Subscribe to Specific Events

```json
{"subscribed_events": ["job_state_transition", "notification_queue_update", "notification_play_sound"]}
```

### Typical Browser Client Subscription

```json
{
  "subscribed_events": [
    "job_state_transition",
    "notification_queue_update",
    "notification_play_sound",
    "sys_time_update",
    "proxy_decision_new"
  ]
}
```

### Typical Programmatic Listener

```json
{
  "subscribed_events": ["job_state_transition"]
}
```

---

## Deprecated Events

The following events were removed in July 2025 and replaced by `job_state_transition`:

| Deprecated Event | Replacement |
|-----------------|-------------|
| `queue_todo_update` | `job_state_transition` (with `to_queue: "todo"`) |
| `queue_running_update` | `job_state_transition` (with `to_queue: "run"`) |
| `queue_done_update` | `job_state_transition` (with `to_queue: "done"`) |
| `queue_dead_update` | `job_state_transition` (with `to_queue: "dead"`) |

---

## Close Code Semantics

The server uses RFC 6455 application close codes (4000–4999) to signal
auth-failure outcomes that the browser-side state machine
(`src/fastapi_app/static/js/ws-channel.js`) treats as PERMANENT — the
channel goes straight to `OPEN_CIRCUIT` and does NOT auto-retry.

Codes were introduced in Phase 5 of the WS reconnect circuit-breaker
milestone (`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/06-phase-5-server-side-hardening.md`).
Constants live in `src/cosa/rest/routers/websocket.py`.

| Code | Constant | Meaning | Server emits when… | Client behavior |
|------|----------|---------|---------------------|------------------|
| 4001 | `CLOSE_CODE_AUTH_INVALID_TOKEN`       | Invalid / expired / malformed token; bad `auth_request` envelope | Auth flow on `/ws/queue/{session}` rejects the supplied token (any of: malformed JSON, missing `token` field, empty token, signature failure, `TokenExpiredException`) | `notifications.js` attempts a single `refreshAccessToken()` call FIRST. On refresh-success, `manualRetry()` runs on both channels (no banner shown). On refresh-failure, the auth-permanent banner is shown ("Authentication failed — please log in again."). |
| 4002 | `CLOSE_CODE_AUTH_SESSION_CONFLICT`    | Single-session-per-user policy displaced this connection | A second connection arrives for a user already connected, AND `websocket enforce single session per user = True`. The OLD session receives 4002. | Banner: "Another session has taken over. Refresh to reclaim." Channel does NOT auto-retry. |
| 4003 | `CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED` | RBAC reject on one or more `subscribed_events` | RESERVED — no current branch emits 4003. The audio path filters denied events silently today. Reserved for future RBAC enforcement. | Banner: "Permission denied for one or more notification streams." Channel does NOT auto-retry. |

For comparison, the standard close codes the server still uses unchanged:

| Code | Meaning | Client behavior |
|------|---------|------------------|
| 1000 | Normal client-initiated close | No reconnect. State → `DISCONNECTED`. |
| 1001 | Going away (server shutdown) | Reconnect per normal full-jitter backoff. |
| 1006 / no-code | Abnormal closure (transport-level fault) | Reconnect per normal backoff. |
| 1008 | Policy violation (e.g. invalid session ID format at the URL) | Reconnect per normal backoff. |

### Browser-side reaction

The full reaction logic lives in `ws-channel.js` (`PERMANENT_CLOSE_CODES` set + `socket.onclose` handler) and `notifications.js` (`_showCircuitBanner` / `_renderCircuitBanner`):

- queue WS `onclose` with `event.code` in {4001, 4002, 4003} → `openCircuit("auth-permanent", code)` → `ws-circuit-open` event with `detail.reason="auth-permanent"` + `detail.code` → NotificationsUI: 4001 → try token refresh; else → render auth-permanent banner.
- queue WS `onclose` with any other code (1000 / 1001 / 1006 / …) → `handleClose()` → `scheduleReconnect()` (full-jitter backoff, capped at 20 attempts before the breaker trips for transport reasons).

---

## Related Documentation

- [WebSocket Architecture](websocket-architecture.md) — System design and WebSocketManager API
- [WebSocket Configuration](websocket-configuration.md) — Config keys and tuning
- [WebSocket Troubleshooting](websocket-troubleshooting.md) — Diagnostic procedures
