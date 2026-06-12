# WebSocket Architecture Overview

**Date**: 2026.03.20
**Source of truth**: `src/cosa/rest/websocket_manager.py`, `src/cosa/rest/routers/websocket.py`
**Status**: Active

## Executive Summary

The Lupin WebSocket architecture provides real-time bidirectional communication between the FastAPI server and client applications. The system employs a dual-session design with user-centric routing, event subscription filtering, and robust connection management.

### Key Architectural Principles

- **User-Centric Routing**: Events route by user ID, not ephemeral WebSocket connection ID
- **Event Subscription Filtering**: Clients only receive events they explicitly subscribe to
- **Dual-Session Architecture**: Separate channels for queue management and audio streaming
- **Thread-Safe Emission**: Background threads emit via `asyncio.run_coroutine_threadsafe`
- **Session Persistence**: localStorage-based session management across page reloads
- **Concurrent `job_state_transition` events** (v0.1.7+): with the agentic pool
  active (`cj flow max concurrent agentic jobs > 1`), multiple agentic jobs
  may emit `RUNNING → COMPLETED/FAILED` transitions **simultaneously** from
  different pool worker threads. Cross-job event order is non-deterministic;
  clients MUST key cards by `job_id` (as they already do). Within a single
  `job_id`, sequence is preserved by the pop-before-transition invariant in
  `RunningFifoQueue._on_agentic_complete`.

---

## System Architecture

### High-Level Data Flow

```
┌─────────────────┐    WebSocket     ┌──────────────────┐    Events     ┌─────────────────┐
│   Client Apps   │ ←─────────────→  │  WebSocket       │ ←──────────   │   Background    │
│                 │                  │  Manager         │               │   Processes     │
│ • queue.js      │                  │                  │               │                 │
│ • hybrid-tts.js │                  │ • User routing   │               │ • Job queue     │
│ • queue-fresh   │                  │ • Event filtering│               │ • TTS streaming │
└─────────────────┘                  │ • Session mgmt   │               │ • Notifications │
                                     └──────────────────┘               └─────────────────┘
```

### Dual-Session Design

Every client opens **two** WebSocket connections sharing the same `session_id`:

| Channel | Endpoint | Purpose | Auth |
|---------|----------|---------|------|
| Queue | `/ws/queue/{session_id}` | Job state, notifications, system events | JWT required (in-band handshake) |
| Audio | `/ws/audio/{session_id}` | TTS streaming, audio events | No mandatory auth; pre-registration supported |

**Session ID formats**:
- Browser sessions: `"adjective noun"` (e.g., `wise penguin`, `happy cat`)
- Programmatic sessions: `"prefix-identifier"` (e.g., `cc-listener-72116632`, `proxy-ratify`)

The `cc-listener-` prefix identifies programmatic listener sessions (e.g., Claude Code agents) vs. browser clients.

---

## WebSocketManager — Complete API

**File**: `src/cosa/rest/websocket_manager.py`

The `WebSocketManager` bridges COSA's synchronous queue system with FastAPI's async WebSocket API. All methods are documented below, grouped by category.

### Class Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `active_connections` | `Dict[str, WebSocket]` | Maps `session_id` → live WebSocket |
| `session_to_user` | `Dict[str, str]` | Maps `session_id` → `user_id` |
| `user_sessions` | `Dict[str, list]` | Maps `user_id` → list of `session_id`s (multi-session support) |
| `user_to_email` | `Dict[str, str]` | Debug cache: `user_id` → email |
| `session_subscriptions` | `Dict[str, List[str]]` | Maps `session_id` → subscribed event names (or `["*"]` for all) |
| `session_timestamps` | `Dict[str, datetime]` | Connection time per session; used by stale-session cleanup |
| `session_client_types` | `Dict[str, str]` | F-S6-1 side map: `session_id` → `"mobile"` \| `"web"`. Recorded from the queue-WS `auth_request` `client_type` field (exactly `"mobile"` marks mobile; absent/anything else ⇒ `"web"`). Read by `has_live_mobile_session(user_id)` — the FCM `ws_wake` trigger input (a wake fires only when the user has no live mobile queue-WS; web sessions never suppress it) |
| `available_events` | `set` | Valid event names loaded from `lupin-app.ini` |
| `main_loop` | `Optional[asyncio.AbstractEventLoop]` | Main event loop reference for thread-safe emission |
| `single_session_per_user` | `bool` | Policy flag; when `True`, new connections close prior sessions for same user |
| `debug` | `bool` | Verbose diagnostic printing |

### 1. Lifecycle / Application Startup

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `() -> None` | Initializes all dicts, loads config, validates available events from INI |
| `set_event_loop` | `(loop) -> None` | Stores main-loop reference. **Must be called at startup** before background threads emit |

### 2. Connection Management

| Method | Signature | Description |
|--------|-----------|-------------|
| `connect` | `(websocket, session_id, user_id=None, subscribed_events=None, email=None) -> None` | Registers a WebSocket. Enforces single-session policy if configured. Validates and stores event subscriptions; defaults to `["*"]` |
| `disconnect` | `(session_id) -> None` | Removes connection and cleans all associated data: timestamps, subscriptions, user maps |
| `register_session_user` | `(session_id, user_id) -> None` | Associates a session with a user **before** the WebSocket connects. Used when a TTS HTTP request arrives with auth ahead of the audio WebSocket upgrade |

### 3. Event Emission

| Method | Async? | Thread-Safe? | Description |
|--------|--------|--------------|-------------|
| `emit(event, data)` | No | Yes | **Primary interface for COSA queue threads.** Wraps `async_emit` via `asyncio.run_coroutine_threadsafe`. Fire-and-forget |
| `emit_to_user_sync(user_id, event, data)` | No | Yes | Like `emit` but targets a single user's sessions. Called by COSA queues when user routing is needed |
| `async_emit(event, data)` | Yes | N/A | Broadcasts to all active connections subscribed to the event. Adds `type` and `timestamp` to the message. Auto-disconnects dead sockets |
| `emit_to_user(user_id, event, data)` | Yes | N/A | Sends to all sessions for a user, respecting subscriptions. Returns `True` if at least one send succeeded |
| `emit_to_session(session_id, event, data)` | Yes | N/A | Sends to one specific session only. No-ops if session absent |
| `emit_to_all(event, data)` | Yes | N/A | Alias for `async_emit` |

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
| RBAC subscription denied | _(RESERVED — not currently emitted)_ | 4003 |

All 4001/4002/4003 codes are PERMANENT from the client's perspective —
the browser-side `ws-channel.js` state machine routes them straight to
`OPEN_CIRCUIT` and does NOT auto-retry. NotificationsUI attempts a single
token refresh on 4001 before showing the auth-permanent banner. See
[WebSocket Events §Close Code Semantics](websocket-events.md#close-code-semantics)
for the full reaction matrix and design source.

### Audio WebSocket Authentication

The `/ws/audio/{session_id}` endpoint accepts connections **without** upfront auth. User association is handled via `register_session_user()` when a TTS HTTP request (which carries JWT auth) arrives and needs to route audio to the client's audio socket. Audio subscriptions are fixed: `audio_streaming_status`, `audio_streaming_complete`, `sys_ping`.

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

## Thread-Safety Model

The core problem: COSA queue workers run in **background threads** and call `emit()` synchronously, but WebSocket `send_json()` is an async coroutine that must run on the **main asyncio event loop**.

### Pattern: `asyncio.run_coroutine_threadsafe`

Both `emit()` and `emit_to_user_sync()` schedule the async coroutine onto `self.main_loop` from any thread. The returned `Future` is discarded (fire-and-forget).

```python
asyncio.run_coroutine_threadsafe(
    self._async_emit( event, data ),
    self.main_loop
)
```

**Guard checks** before scheduling:
1. `self.main_loop is not None`
2. `self.main_loop.is_running()` is `True`

If either fails, the emit is silently dropped with an error print.

**No explicit locks**: All dict mutations ultimately execute on the single asyncio event loop thread. Python's GIL combined with single-threaded event loop model provides safety without mutexes. Direct mutation from a background thread (without `run_coroutine_threadsafe`) would be unsafe.

---

## Dynamic Subscription Updates

Clients can modify their subscriptions after authentication:

```json
// Client sends:
{
  "type": "update_subscriptions",
  "events": ["job_state_transition", "notification_queue_update"],
  "action": "replace"
}

// Server responds:
{
  "type": "subscription_update",
  "success": true,
  "subscriptions": ["job_state_transition", "notification_queue_update"]
}
```

Actions: `replace` (set exact list), `add` (append), `remove` (subtract). All events are validated against `available_events` from config.

---

## Related Documentation

- [WebSocket Events](websocket-events.md) — Complete event catalog with payload schemas
- [WebSocket Configuration](websocket-configuration.md) — All config keys and tuning
- [WebSocket Troubleshooting](websocket-troubleshooting.md) — Diagnostic procedures
