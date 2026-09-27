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

Every client opens **two** WebSocket connections. Whether they share one `session_id`
**depends on the client** — measured 2026-09-01, and the docs previously claimed all three
shared, which is false:

| Client | Queue id | Audio id |
|---|---|---|
| Mobile app (`enhanced_websocket_service.dart:740-741`) | `_sessionId` | the **same** `_sessionId` |
| Web multiplexer (`multiplexer/boot.ts:623-624`) | `sessionId` | the **same** `sessionId` |
| Web app (`static/js/notifications.js:2441-2442`) | `notifications_queue_session_id` | **a different id** — its own `/api/get-session-id` fetch under `notifications_audio_session_id` |

The split in `notifications.js` is deliberate, not drift: TTS requests from that client
carry `audioSessionId` explicitly (`notifications.js:4308`, `4316`, `4368`, `4376`), so its
audio channel is addressed by its own id. Expect to see a user holding two ids — e.g.
`foolish goat` on the queue socket and `slow zebra` on the audio socket. `emit_to_user`
fans out to both, and the audio socket then correctly DECLINES queue events; those
"not subscribed" lines are the design working, not a subscription bug (row `88347f65`
cost three seats six hours reading 749 of them as breakage).


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
| `session_client_types` | `Dict[str, str]` | F-S6-1 side map: `session_id` → `"mobile"` \| `"web"`. Recorded from the queue-WS `auth_request` `client_type` field (exactly `"mobile"` marks mobile; any other EXPLICIT value ⇒ `"web"`; an ABSENT marker writes `"web"` only for an unmapped session and never downgrades an established `"mobile"` — **the mobile app's** audio-WS connect reuses the queue-WS session id without a marker; the web app's audio socket carries its own id and so gets its own entry). Read by `has_live_mobile_session(user_id)` — the FCM `ws_wake` trigger input (a wake fires only when the user has no live mobile queue-WS; web sessions never suppress it) |
| `available_events` | `set` | Valid event names loaded from `lupin-app.ini` |
| `session_is_admin` | `Dict[str, bool]` | Maps `session_id` → whether the authenticating user carried the `admin` role. Set in `connect()` from its `roles` argument. **This map is a gate, not a display hint** — it is the WS-side half of the console's admin check, the REST half being `require_admin`. *(Existing attribute; it was absent from this table until 2026.09.27.)* |
| `cc_transcript_watchers` | `Dict[str, Set[str]]` | **Phase 1, console tee.** Maps `cc_session_id` (a seat's `stable_session_id`) → the set of browser `session_id`s watching it. The **watcher set is the filter, and deliberately the only one**: `emit_to_session` applies no subscription check, so there is no second place a frame can be dropped. Swept by `disconnect()` — see the warning below |
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
| `connect` | `(websocket, session_id, user_id=None, subscribed_events=None, email=None, roles=None, client_type=None) -> None` | Registers a WebSocket. Enforces single-session policy if configured. Validates and stores event subscriptions; defaults to `["*"]`. `roles` sets the admin flag; `client_type` is the F-S6-1 platform marker — see `session_client_types` above for the no-downgrade rule |
| `disconnect` | `(session_id) -> None` | Removes connection and cleans all associated data: timestamps, subscriptions, admin flag, client-type marker, user maps — **and, from phase 1, the CC-transcript watcher registry**. ⚠️ **This sweep is hand-maintained**: it deletes from each map in its own statement, so every new per-session map is a new statement someone has to remember to add. See the warning under § CC Transcript Console Channel |
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
| `emit_to_user_and_admins_sync(user_id, event, data)` | No | Yes | **The canonical dual-emit — reach for this first for any queue or job state change** (`job_created`, `job_removed`, `job_paused`, `job_resumed`, `job_state_transition`). Delivers to the owning user AND every admin session, deduplicated so an owner who is also an admin is not sent it twice. Using `emit_to_user_sync` alone for these is what stranded 14 stale job cards in an admin browser (Session `248e740e`) |
| `emit_to_admins_sync(event, data, exclude_user_id=None)` | No | Yes | Admin-only half of the dual-emit. Note it takes **no** `user_id` — `exclude_user_id` suppresses the copy to one user (that is how the dual-emit avoids sending twice to an owner who is also an admin). Prefer `emit_to_user_and_admins_sync` over calling this and `emit_to_user_sync` separately — forgetting the second call is the `248e740e` defect |
| `emit_to_session_sync(session_id, event, data)` | No | Yes | Thread-safe wrapper for `emit_to_session`; schedules onto the stored main loop |
| `emit_to_user_or_listener_sync(user_id, job_id, event, data)` | No | Yes → returns `dict` | **The `or` is misleading — this is a DUAL emit, not a fallback.** Both emits fire independently: the user emit always runs, and `cc-listener-{job_id}` also receives it when that session is live. CC listeners authenticate as a shared service-account user, so `emit_to_user_sync` alone never reaches them. Returns `{"user_delivered": bool, "listener_delivered": bool, ...}` |

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

## CC Transcript Console Channel

> **Status**: contract documented at phase 0; the server side lands at **phase 1**. Payload schemas: [`websocket-events.md`](websocket-events.md) § "CC Transcript Console Events". REST companion: [`rest-api-reference.md`](rest-api-reference.md) § 27. Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`.

A read-only live window onto a Claude Code seat's transcript, carried on the **existing** `/ws/queue/{session_id}` socket (ruling Q4). No new socket and no new auth path — but **"no new socket" is not "no server work"**, for three reasons set out below.

### 1. The receive loop grows two verbs

`routers/websocket.py` `websocket_queue_endpoint` handles exactly **two** client verbs today — `sys_ping` and `update_subscriptions`. `cc_transcript_watch` and `cc_transcript_unwatch` are **new branches beside them**.

**`update_subscriptions` cannot absorb them.** It is type-level only: it takes a list of event *names* and has no per-target argument, so it cannot express "watch *this* seat". A watch is parameterised by `cc_session_id`; a subscription is not parameterised at all.

### 2. The two fan-out calls do not behave the same, and only one of them is right here

| Call | Subscription check? |
|---|---|
| `emit_to_user` | **Yes** — filters each frame against `session_subscriptions.get( session_id, ["*"] )` |
| `emit_to_session` | **No** — sends unconditionally |

Append frames go out over **`emit_to_session`, to the watching browser session only**. The watcher set is therefore the single filter, which is the point: one place to look when a frame goes missing.

### 3. The `websocket available events` key change

The four names — `cc_transcript_watch`, `cc_transcript_unwatch`, `cc_transcript_append`, `cc_transcript_state` — are added to `websocket available events` in `src/conf/lupin-app.ini` at phase 1, and to both client subscription lists, **even though `emit_to_session` never consults the list**.

Two reasons, and neither is tidiness:

1. A client's subscription list should not silently lie about what it asked for. **A name absent from the registry is dropped at subscribe time, silently**, and a client whose whole list validates to `[]` has every frame dropped while auth still reports success — the failure the in-place comment beside the validation in `websocket_manager.py` describes.
2. Anyone who later switches the carrier from `emit_to_session` to `emit_to_user` would otherwise ship a stream that delivers nothing while reporting success.

> ⚠️ **Append with `", "` exactly — a comma alone silently mangles the name.** The reader is `ConfigurationManager.get( ..., return_type="list-string" )`, and that branch is a bare `value.split( ", " )` with **no per-token strip**. So `…speakerphone_changed,cc_transcript_watch` yields one token spelled `speakerphone_changed,cc_transcript_watch`, which matches nothing: the *previous* event silently stops validating and the new one never starts. Nothing raises — the list is still non-empty, so the `ValueError` guard in `__init__` does not fire either.

**Derive the list through the real reader, never quote a count.** Three documents have carried three different figures for the size of this list, and a count is the weakest possible assertion — it passes just as happily if a name is misspelled. Read it the way the server does and compare **set equality** against a committed literal:

```python
from cosa.config.configuration_manager import ConfigurationManager
names = ConfigurationManager().get( "websocket available events", return_type="list-string" )
```

Verified 2026.09.27: 25 entries, 25 unique, no malformed token.

### The tailer resolves the seat, and opens its path verbatim

The tailer resolves a seat's transcript from the **session bridge** — `session_bridge.find_session_by_id( cc_session_id )`, the per-seat read; `get_session_metadata()` resolves only the *calling* process and cannot answer for another seat. Offsets are advanced with `events_tail.tail_session_file( path, offset )`, which is partial-line safe and returns `( records, new_offset )` landing at the last **complete** line — exactly the `next_offset` rule.

> 🔴 **Open `transcript_path` exactly as the bridge wrote it. Never rejoin it against `LUPIN_ROOT` or any other root.** The container binds the host sessions directory to the **same absolute path inside the container** (`docker-compose.yml`, the `${LUPIN_HOST_SESSIONS_DIR:-/home/rruiz/.claude/sessions}` bind, target `/home/rruiz/.claude/sessions`), which is precisely why a verbatim open works. A path rewritten relative to a project root points at nothing, and `tail_session_file` **never raises** — a missing file returns `( [], offset )` — so the failure is not an error. It is an empty stream: a pane that stays blank while every status says live.

### The leak the watcher registry invites

> 🔴 **`cc_transcript_unwatch` is the polite path, not the reliable one.** A closed tab or a dropped socket never sends it. So `disconnect()` must sweep `cc_transcript_watchers` — and that sweep is **hand-maintained**, deleting from `active_connections`, `session_timestamps`, `session_subscriptions`, `session_is_admin`, `session_client_types` and the user association one statement at a time. The watcher map is a **sixth entry that has to be added there explicitly**.
>
> Miss it and there is **no error anywhere**: the tailer polls forever, and `emit_to_session` early-returns into a session already gone from `active_connections`. A silent burn. The test that catches it drops the socket *without* sending the unwatch verb; a test that only exercises the explicit unwatch stays green while the leak ships.

### Admin gating: two surfaces, two different gates

| Surface | Gate |
|---|---|
| WS verbs (`cc_transcript_watch`) | `session_is_admin[ session_id ]` — a lookup on state `connect()` already stores |
| REST backlog + roster | `require_admin` (`require_roles( ["admin"] )`) |

They are **different mechanisms**, so a test that exercises one proves nothing about the other, and a criterion naming only one is satisfiable by a gate that refuses everybody. Both arms — a non-admin refused **and** an admin accepted — or neither is proved.

---

## Related Documentation

- [WebSocket Events](websocket-events.md) — Complete event catalog with payload schemas
- [WebSocket Configuration](websocket-configuration.md) — All config keys and tuning
- [WebSocket Troubleshooting](websocket-troubleshooting.md) — Diagnostic procedures
