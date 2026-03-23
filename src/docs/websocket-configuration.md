# WebSocket Configuration Guide

**Date**: 2026.03.20
**Source of truth**: `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`
**Status**: Active

## Configuration Location

All WebSocket configuration lives in `src/conf/lupin-app.ini` under the `[Lupin: Baseline]` section. Keys use space-separated names (not underscores).

---

## Configuration Keys

### `websocket enforce single session per user`

- **Type**: Boolean
- **Default**: `False`
- **Purpose**: When `True`, new connections automatically close any existing sessions for the same user. When `False`, multiple concurrent sessions per user are allowed.

### `websocket heartbeat enabled`

- **Type**: Boolean
- **Default**: `True`
- **Purpose**: When `True`, sends periodic `sys_ping` messages to detect dead connections. Dead connections are automatically disconnected.

### `websocket heartbeat interval seconds`

- **Type**: Integer (seconds)
- **Default**: `30`
- **Purpose**: Seconds between heartbeat ping messages. Lower values detect dead connections faster but increase traffic.

### `websocket cleanup enabled`

- **Type**: Boolean
- **Default**: `True`
- **Purpose**: When `True`, periodically removes sessions older than max age via `auto_cleanup()`.

### `websocket cleanup interval hours`

- **Type**: Integer (hours)
- **Default**: `1`
- **Purpose**: Hours between automatic cleanup runs.

### `websocket session max age hours`

- **Type**: Integer (hours)
- **Default**: `24`
- **Purpose**: Maximum age in hours before a session is considered stale and eligible for cleanup.

### `websocket available events`

- **Type**: Comma-separated string
- **Default**: See [Event Catalog](websocket-events.md)
- **Purpose**: Defines the valid set of event types clients can subscribe to. Subscription requests for events not in this list are rejected. Clients use `"*"` to subscribe to all events.

**Current value** (18 events):
```
job_state_transition, tts_job_request, audio_streaming_chunk,
notification_queue_update, notification_play_sound, sys_time_update,
status, error, sys_ping, sys_pong, auth_request, auth_success,
auth_error, connect, audio_streaming_status, audio_streaming_complete,
update_subscriptions, proxy_decision_new
```

---

## INI File Example

```ini
[Lupin: Baseline]
# ... other keys ...

websocket enforce single session per user = False
websocket heartbeat enabled              = True
websocket heartbeat interval seconds     = 30
websocket cleanup enabled                = True
websocket cleanup interval hours         = 1
websocket session max age hours          = 24
websocket available events               = job_state_transition, tts_job_request, audio_streaming_chunk, notification_queue_update, notification_play_sound, sys_time_update, status, error, sys_ping, sys_pong, auth_request, auth_success, auth_error, connect, audio_streaming_status, audio_streaming_complete, update_subscriptions, proxy_decision_new
```

---

## Configuration Profiles

### Development

```ini
websocket heartbeat interval seconds = 30
websocket session max age hours      = 24
websocket cleanup interval hours     = 1
```

Enable `app debug = true` for faster `sys_time_update` broadcasts (5s vs 60s).

### Production

```ini
websocket heartbeat interval seconds     = 30
websocket session max age hours          = 24
websocket cleanup interval hours         = 1
websocket enforce single session per user = True
```

### High-Performance / Many Clients

```ini
websocket heartbeat interval seconds = 60
websocket cleanup interval hours     = 2
websocket session max age hours      = 12
```

Increase heartbeat interval to reduce traffic. Shorten max age to reclaim resources faster.

---

## Runtime Management

### View Active Sessions

```
GET /api/websocket-sessions
Authorization: Bearer <jwt_token>
```

### View Session Statistics

```
GET /api/websocket-sessions/stats
Authorization: Bearer <jwt_token>
```

### Toggle Single-Session Policy

```
PUT /api/websocket-sessions/single-session-policy
Authorization: Bearer <jwt_token>
Body: {"enabled": true}
```

### Force Cleanup

```
POST /api/websocket-sessions/cleanup
Authorization: Bearer <jwt_token>
```

These endpoints are in the `websocket_admin.py` router and require admin authentication.

---

## Validation Behavior

- **Event subscription validation**: When a client subscribes to an event not in `websocket available events`, the subscription is rejected and the client is notified
- **Session ID validation**: Both WebSocket endpoints validate session ID format before accepting connections. Invalid formats receive close code `1008`
- **Missing config**: If `websocket available events` is missing from the INI, `WebSocketManager.__init__()` raises `ValueError` at startup

---

## Related Documentation

- [WebSocket Architecture](websocket-architecture.md) — System design and WebSocketManager API
- [WebSocket Events](websocket-events.md) — Complete event catalog with payload schemas
- [WebSocket Troubleshooting](websocket-troubleshooting.md) — Diagnostic procedures
