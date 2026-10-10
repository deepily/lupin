> Part 12 of 17 of the [Lupin Notification API Reference](../notification-api.md): receiving notifications.

## 9. Receiving Notifications

### 9.1 WebSocket Delivery

When a notification is pushed into the `NotificationFifoQueue`, the queue's
overridden `push()` method emits a `notification_queue_update` WebSocket event
with the full notification payload.

**Event name**: `notification_queue_update`

**Payload structure**:

```json
{
    "queue_name"    : "notification",
    "value"         : 5,
    "notification"  : {
        "id"                 : "a1b2c3d4-...",
        "id_hash"            : "a1b2c3d4-...",
        "message"            : "Build completed",
        "title"              : null,
        "type"               : "task",
        "priority"           : "medium",
        "source"             : "claude_code",
        "user_id"            : "user-uuid-here",
        "timestamp"          : "2026-02-13T10:30:00-05:00",
        "time_display"       : "10:30 EST",
        "played"             : false,
        "play_count"         : 0,
        "last_played"        : null,
        "response_requested" : false,
        "response_type"      : null,
        "response_default"   : null,
        "response_options"   : null,
        "timeout_seconds"    : null,
        "sender_id"          : "claude.code@lupin.deepily.ai",
        "abstract"           : null,
        "suppress_ding"      : false,
        "job_id"             : null,
        "queue_name"         : null,
        "progress_group_id"  : null
    }
}
```

**Targeting**:

- **User-specific**: When `notification.user_id` is set, the event is emitted
  only to that user's WebSocket sessions via `emit_to_user_sync()`.
- **Broadcast**: When `notification.user_id` is `None`, the event is broadcast
  to all connected clients via `emit()`.

---

### 9.2 Related WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `notification_queue_update` | Server -> Client | New notification pushed to queue. Contains full `notification` dict. |
| `notification_responded` | Server -> Client | User submitted a response. Contains `notification_id`, `response_value`, `timestamp`, `time_display`, `date_display`. |
| `notification_expired` | Server -> Client | Notification timed out. Contains `notification_id`, `default_used`, `timeout` flag, `timestamp`. |
| `notification_play_sound` | Server -> Client | Instructs client to play notification sound. Carries priority for sound selection. |

---

### 9.3 SSE Streams

Response-required notifications use FastAPI's `StreamingResponse` with media type
`text/event-stream` to block the calling client until a response arrives or the
timeout expires.

**SSE format**: Each event is a single line prefixed with `data: ` followed by a
JSON object, terminated by two newlines (`\n\n`):

```
data: {"status": "responded", "response": "yes", "default_used": false}\n\n
```

**Event types emitted by the SSE stream**:

| Status | Meaning | Key Fields |
|--------|---------|------------|
| `responded` | User submitted a response | `response`, `default_used: false` |
| `expired` | Timeout reached, default applied | `response` (the default), `default_used: true`, `timeout: true` |
| `offline` | User not connected, default applied | `response` (the default), `default_used: true` |
| `error` | Unexpected server error | `message` (error description) |

**Lifecycle**: The SSE stream emits exactly **one event** and then closes. The
server creates an `asyncio.Event()` in the `pending_responses` dict, waits on it
with `asyncio.wait_for()` using the configured timeout. And yields the appropriate
event based on the outcome.

**Headers**:

```
Content-Type               : text/event-stream
Cache-Control              : no-cache
X-Accel-Buffering          : no
Connection                 : keep-alive
Access-Control-Allow-Origin : *
```

---

### 9.4 Response Submission

Users submit responses via `POST /api/notify/response`.

**Request body**:

```json
{
    "notification_id" : "a1b2c3d4-...",
    "response_value"  : "yes"
}
```

**Who may answer**: only the addressee. The caller's user (the login, or the user owning the API key) must be the notification's `recipient_id`, or the door answers `403`. A proxy answering for someone must therefore be logged in as that someone.

**Processing flow**:

1. **Validation** -- `notification_id` and `response_value` are required. String
   responses are sanitized (HTML tags stripped) and must be non-empty after stripping whitespace.
2. **PostgreSQL update** -- The notification record is updated via
   `NotificationRepository.update_response()`. The notification must be in
   `delivered` state, or in `expired` state within the grace period.
3. **SSE signal** -- If the notification's SSE stream is still waiting in `pending_responses`, the response data is written and the `asyncio.Event` is set.
   That wakes the stream, which then yields a `responded` event.
4. **WebSocket broadcast** -- A `notification_responded` event is emitted to the
   target user's WebSocket sessions.

**Grace period**: Expired notifications can still accept responses within a
configurable grace period (`notification grace period seconds` in
`lupin-app.ini`, default 300 seconds). This supports the "pause button" feature
where users may step away and return after the timeout.

**Error responses**:

| HTTP Status | Condition |
|-------------|-----------|
| `401` | No credential, or a bad one |
| `404` | Notification not found |
| `403` | The caller's user is not the notification's addressee (`recipient_id`). Checked after the 404 and before the state checks; nothing is written |
| `400` | Already responded, or grace period exceeded |
| `422` | Missing `notification_id` or `response_value` |
| `400` | Response empty (after whitespace strip) |

---
