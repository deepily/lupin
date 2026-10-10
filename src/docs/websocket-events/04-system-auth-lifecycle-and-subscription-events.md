> Part 4 of 5 of the [WebSocket Event System Documentation](../websocket-events.md): system, auth handshake, lifecycle and subscription management events and subscription patterns.

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
  "subscribed_events": ["job_state_transition", "notification_queue_update"],
  "client_type": "mobile"
}
```

- `subscribed_events` is optional; defaults to `["*"]` (all events)
- `token` can include or omit the `Bearer ` prefix (stripped server-side)
- `client_type` is optional (queue WS only): the mobile app sends `"mobile"`. Anything else — including absent (existing web clients send nothing) — is recorded as `"web"`. Drives the FCM `ws_wake` trigger: a wake push fires only when the user has `NO` live session marked `"mobile"`. So a desktop browser never suppresses the phone's wake. The audio WS never records this marker.

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
| `queue_todo_update` | `job_state_transition` (with `to_state: "queued"`) |
| `queue_running_update` | `job_state_transition` (with `to_state: "running"`) |
| `queue_done_update` | `job_state_transition` (with `to_state: "completed"`) |
| `queue_dead_update` | `job_state_transition` (with `to_state: "failed"`) |

Warning: **This table used to say `to_queue: "todo"` / `"run"` / `"done"` / `"dead"`. And that
field does not exist**. `emit_job_state_transition()` (`src/cosa/rest/queue_util.py:65-71`)
emits exactly `job_id`, `from_state`, `to_state`, `timestamp`, and an optional `metadata` —
never `to_queue`. Measured live on `:7999`: a submitted job produces `pending`->`queued`,
`queued`->`running`, `running`->`completed`. Two consumers had been reading the phantom field with a `.get( "to_queue", "?" )` default.
They printed `? -> ?` on every transition since the rename, and that was corrected 2026-08-24.

The following event was renamed during the 2026-05-13 Speakerphone solo/chorus refactor (the solo/chorus refactor, `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`):

| Deprecated Event | Replacement | Rename Date |
|-----------------|-------------|-------------|
| `conversation_mode_changed` | `speakerphone_changed` (semantic payload identical; `payload.on` carries the boolean state) | 2026-05-13 |

The deprecated name is `NOT` in the `valid_types` whitelist; pushing it returns HTTP 400. The multiplexer `SenderStore` accepts both names client-side as a **forward-compat bridge** in case the event is ever re-renamed back. See `speakerphone_changed` entry above for details.

---

## Frame seq, resume, and ack (part 2)

Frames sent to a **device slot holder** (a mobile session that authenticated with a
`device_id`) carry an extra field. And three protocol shapes exist around it. A session
with no slot — every web client — sees none of this and its frames are unchanged.

| field / frame | direction | meaning |
|---|---|---|
| `seq` | server → client | Monotonic **per device slot**, starting at 1. Added to every frame to a slot holder, alongside `type` and `timestamp` |
| `last_seq` | client → server, in `auth_request` | The client's highest received `seq`. Absent or `0` means a fresh client with nothing to resume. A non-integer, a bool or a negative is treated as absent rather than trusted |
| `resume_complete` | server → client | `{ "type": "resume_complete", "replayed": N, "gap": bool, "seq": <server's current seq> }`, sent once after `auth_success` and after any replayed frames. Marks where the backlog ends. `seq` is the **server's** current seq for the slot, not an echo of `last_seq`. The client sets `last_seq = seq` on receipt. Live frames that arrive during the replay are held and sent right after this frame, so the client never sees a live frame overtake the backlog. **It can be sent twice**: the buffer is bounded. So frames emitted while the replay is on the wire can be evicted before they are sent. A hole found during the replay turns `gap` true on the one frame. A hole found only after the first `resume_complete` went out with `gap: false` is followed by a **second** `resume_complete { gap: true }`, sent before the frames past the hole. A client treats any `gap: true` as "refetch in full", and the second is idempotent with the first |
| `ack` | client → server | `{ "type": "ack", "seq": N }` — the client confirms it has processed through `N`, and the server drops those frames |

Warning: **`gap: true` is the server saying it cannot prove continuity**, and the client must
do a full refetch rather than assume it is current. It is set when frames were evicted by the retention cap.
It is also set when the server holds nothing at all for a client claiming a non-zero `last_seq`.
A server restart looks like that from the client's side. A
partial replay that stayed quiet would leave the client believing it was caught up and it
would stop asking. Which is strictly worse than not replaying.

Retention is bounded by `websocket device frame buffer size` (default 200) per slot.
It is also bounded by `websocket device frame buffer max slots` (default 64) overall.
Eviction takes the oldest slot with no connected holder. A connected slot is never evicted. So the total can exceed 64 by at most
the number of connected holders (one warning per crossing) and settles back at the next write.
Without an `ack` the buffer only ever shrinks by eviction — which is the thing that causes a `gap`.

`resume_complete` is deliberately **not** in `websocket available events`: the endpoint
sends it directly, like `auth_success`, and it never passes through the subscription
filter. Listing it would imply a path that does not exist.
