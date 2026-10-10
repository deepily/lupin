> Part 4 of 5 of the [WebSocket Architecture Overview](../websocket-architecture.md): the CC transcript watcher registry, event emission, user routing, subscriptions, session policy, background tasks, the authentication flow and session id validation.

### 2b. CC Transcript Console Watcher Registry

The registry owns the **watcher count**. And therefore the tailer's lifecycle: a tailer starts when a seat gains its first watcher and stops when it loses its last. The tailer itself has no concept of a watcher — it exposes `start()`/`stop()` and something must call them. So "starts on the first, stops after the last" lives *here*, not there.

Signatures below were read from the source with `ast`, not inferred from the names. `test_websocket_manager_doc_signature_parity.py` records that two of four methods added were guessed wrong that way.

| Method | Signature | Description |
|--------|-----------|-------------|
| `add_cc_transcript_watcher` | `(cc_session_id, session_id) -> bool` | Registers a browser session as a watcher of a seat, **idempotently** — a re-watch does not double-count. So a reconnect cannot make a seat look busier than it is. Returns `True` iff this was the seat's **first** watcher, which is the signal to start its tailer |
| `remove_cc_transcript_watcher` | `(cc_session_id, session_id) -> bool` | Deregisters one watcher. Removing an absent one is a no-op, because an unwatch can race a disconnect that already swept it. An emptied seat's **key is deleted** rather than left as an empty set. Returns `True` iff the seat now has no watchers — the signal to stop its tailer |
| `drop_all_cc_transcript_watches` | `(session_id) -> List[str]` | Removes one browser session from **every** seat it watched — the disconnect path. And the only reliable end of a watch. Returns the seats that are now unwatched, so the caller can stop their tailers |
| `cc_transcript_watchers_of` | `(cc_session_id) -> set` | The browser sessions watching one seat, **as a copy** — the fan-out iterates it while a watch or disconnect may mutate the live set. And returning the live one would raise mid-broadcast and drop a frame for every watcher after the mutation point |
| `is_watching_cc_transcript` | `(cc_session_id, session_id) -> bool` | Whether one browser session is watching one seat |

Warning: **Two id spaces, never interchangeable**: the registry's **key** is a Claude Code seat's `stable_session_id`; its **values** are browser session ids. A registry that confused them would let a browser "watch" another browser, and the symptom would be an empty pane rather than a type error.


### 3. Event Emission

| Method | Async? | Thread-Safe? | Description |
|--------|--------|--------------|-------------|
| `emit(event, data)` | No | Yes | **Primary interface for COSA queue threads**. Wraps `async_emit` via `asyncio.run_coroutine_threadsafe`. Fire-and-forget |
| `emit_to_user_sync(user_id, event, data)` | No | Yes | Like `emit` but targets a single user's sessions. Called by COSA queues when user routing is needed |
| `async_emit(event, data)` | Yes | N/A | Broadcasts to all active connections subscribed to the event. Adds `type` and `timestamp` to the message. Auto-disconnects dead sockets |
| `emit_to_user(user_id, event, data)` | Yes | N/A | Sends to all sessions for a user, respecting subscriptions. Returns `True` if at least one send succeeded |
| `emit_to_session(session_id, event, data)` | Yes | N/A | Sends to one specific session only. No-ops if session absent |
| `emit_to_all(event, data)` | Yes | N/A | Alias for `async_emit` |
| `emit_to_user_and_admins_sync(user_id, event, data)` | No | Yes | **The canonical dual-emit. Reach for this first for any queue or job state change** (`job_created`, `job_removed`, `job_paused`, `job_resumed`, `job_state_transition`). Delivers to the owning user and every admin session, deduplicated so an owner who is also an admin is not sent it twice. Using `emit_to_user_sync` alone for these is what stranded 14 stale job cards in an admin browser (Session ``) |
| `emit_to_admins_sync(event, data, exclude_user_id=None)` | No | Yes | Admin-only half of the dual-emit. Note it takes **no** `user_id` — `exclude_user_id` suppresses the copy to one user (that is how the dual-emit avoids sending twice to an owner who is also an admin). Prefer `emit_to_user_and_admins_sync` over calling this and `emit_to_user_sync` separately — forgetting the second call is the `` defect |
| `emit_to_session_sync(session_id, event, data)` | No | Yes | Thread-safe wrapper for `emit_to_session`; schedules onto the stored main loop |
| `emit_to_user_or_listener_sync(user_id, job_id, event, data)` | No | Yes → returns `dict` | **The `or` is misleading — this is a dual emit, not a fallback**. Both emits fire independently: the user emit always runs, and `cc-listener-{job_id}` also receives it when that session is live. CC listeners authenticate as a shared service-account user, so `emit_to_user_sync` alone never reaches them. Returns `{"user_delivered": bool, "listener_delivered": bool, ...}` |

**Message envelope** (all emit paths):
```json
{
  "type": "<event_name>",
  "timestamp": "<ISO-8601>",
  "...data fields"
}
```

### 4. User Routing / Session Queries

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `is_connected` | `(session_id)` | `bool` | Whether session has an active WebSocket |
| `is_user_connected` | `(user_id)` | `bool` | Whether user has at least one active session |
| `get_connection_count` | `()` | `int` | Total active WebSocket connections |
| `get_user_connection_count` | `(user_id)` | `int` | Active connections for a specific user |
| `get_session_info` | `(session_id)` | `Optional[dict]` | Returns `session_id`, `connected`, `user_id`, `connected_at`, `duration_seconds` |
| `get_all_sessions_info` | `()` | `list` | Session info dicts for all active connections |

### 5. Event Subscriptions

| Method | Signature | Description |
|--------|-----------|-------------|
| `update_subscriptions` | `(session_id, events, action="replace")` | Modifies subscriptions post-connection. `action`: `"replace"` / `"add"` / `"remove"`. Validates against `available_events`. Returns `False` if session not found |
| `get_subscription_stats` | `()` | Returns `total_connections`, `wildcard_subscribers`, `filtered_connections`, per-event `subscription_counts` |

### 6. Session Policy

| Method | Signature | Description |
|--------|-----------|-------------|
| `set_single_session_policy` | `(enabled)` | Runtime toggle for single-session-per-user enforcement |

### 7. Background / Maintenance Tasks

| Method | Signature | Description |
|--------|-----------|-------------|
| `heartbeat_check` | `async ()` | Sends `sys_ping` to all connections. Disconnects dead sockets. Returns count removed. Respects `websocket heartbeat enabled` config |
| `auto_cleanup` | `async ()` | Calls `cleanup_stale_sessions` with configured `websocket session max age hours`. Respects `websocket cleanup enabled` config. Returns count cleaned |
| `cleanup_stale_sessions` | `(max_age_hours=24)` | Synchronous age-based sweep. Disconnects sessions older than threshold. Returns count removed |

---

## Authentication Flow

The `/ws/queue/{session_id}` endpoint uses **in-band auth** (not HTTP headers), because WebSocket upgrade requests cannot carry Authorization headers in most browsers.

```
┌──────────┐                           ┌──────────────┐
│  Client   │                           │  WS Router   │
└─────┬─────┘                           └──────┬───────┘
      │  1. Open /ws/queue/{session_id}        │
      │ ──────────────────────────────────────→ │
      │                                        │  2. Accept connection
      │  3. Send auth_request                  │
      │ ──────────────────────────────────────→ │
      │  {                                     │  4. verify_token()
      │    "type": "auth_request",             │
      │    "token": "Bearer <jwt>",            │
      │    "subscribed_events": [...]          │
      │  }                                     │
      │                                        │  5a. Success:
      │  ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │  auth_success + connect
      │                                        │  5b. Failure:
      │  ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │  auth_error + close
```

### Auth Error Conditions

| Condition | Error Message | Close Code |
|-----------|---------------|------------|
| Not valid JSON | `"Authentication message must be valid JSON"` | 4001 |
| Not a dict | `"Authentication message must be a JSON object"` | 4001 |
| `type` != `auth_request` | `"First message must be auth_request"` | 4001 |
| Missing `token` key | `"Authentication message must include token field"` | 4001 |
| Token not a string | `"Token must be a string"` | 4001 |
| Token empty/whitespace | `"Token cannot be empty"` | 4001 |
| Token expired | `"Token expired"` | 4001 |
| Verification exception | Exception message | 4001 |
| Single-session displaced | (no in-band message; displaced session sees 4002 close frame) | 4002 |
| RBAC subscription denied | _(reserved — not currently emitted)_ | 4003 |
| Device-slot superseded | (no in-band message; displaced socket sees a 4004 close frame, reason `superseded`) | 4004 |
| Resume replay failed **after** auth succeeded | (no `auth_error` frame; reason `resume_failed`; the real exception is logged at error level with the session id) | **1011** — deliberately not 4001 |

A 1011 is **not** an auth outcome.
The replay of a device's backlog runs after `auth_success`, outside the auth `try`.
So a send that dies mid-backlog cannot be mistaken for a bad token.
It used to be sent as `auth_error` + 4001, and the mobile client answers 4001 with a token refresh or a sign-out. The client reconnects on 1011 under normal backoff.

All 4001/4002/4003 codes are permanent from the client's perspective —
the browser-side `ws-channel.js` state machine routes them straight to
`OPEN_CIRCUIT` and does not auto-retry. NotificationsUI attempts a single
token refresh on 4001 before showing the auth-permanent banner. See
[WebSocket Events §Close Code Semantics](../websocket-events.md#close-code-semantics)
for the full reaction matrix and design source.

### Audio WebSocket Authentication

The `/ws/audio/{session_id}` endpoint accepts connections **without** upfront auth. User association is handled via `register_session_user()`.
That call happens when a TTS HTTP request, which carries JWT auth, arrives and needs to route audio to the client's audio socket. Audio subscriptions are fixed: `audio_streaming_status`, `audio_streaming_complete`, `sys_ping`.

---

## Session ID Validation

**Function**: `is_valid_session_id(session_id: str) -> bool`

Both endpoints validate the session ID before accepting the WebSocket. Invalid IDs receive close code `1008`.

| Format | Pattern | Examples |
|--------|---------|----------|
| Browser | `^[a-z]+ [a-z]+$` (two lowercase words, single space) | `wise penguin`, `happy cat` |
| Programmatic | `^[a-z][a-z0-9]*-[a-z0-9-]{1,47}$` | `cc-listener-72116632`, `proxy-ratify` |

Security: tab, newline, carriage return, form-feed, vertical-tab characters are rejected. URL-encoded spaces (`%20`) are decoded before validation.

---
