# WebSocket Architecture Overview

**Date**:
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
- **Concurrent `job_state_transition` events** (v0.1.7+): with the agentic pool active (`cj flow max concurrent agentic jobs > 1`), several agentic jobs may emit transitions at once.
  The transitions are `RUNNING → COMPLETED/FAILED`, and they come from different pool worker threads.
  Cross-job event order is non-deterministic.
  Clients must key cards by `job_id`, as they already do. Within a single
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
**depends on the client** — measured, and the docs previously claimed all three
shared, which is false:

| Client | Queue id | Audio id |
|---|---|---|
| Mobile app (`enhanced_websocket_service.dart:740-741`) | `_sessionId` | the **same** `_sessionId` |
| Web multiplexer (`multiplexer/boot.ts:623-624`) | `sessionId` | the **same** `sessionId` |
| Web app (`static/js/notifications.js:2441-2442`) | `notifications_queue_session_id` | **a different id** — its own `/api/get-session-id` fetch under `notifications_audio_session_id` |

The split in `notifications.js` is deliberate, not drift: TTS requests from that client
carry `audioSessionId` explicitly (`notifications.js:4308`, `4316`, `4368`, `4376`). So its
audio channel is addressed by its own id. Expect to see a user holding two ids — e.g.
`foolish goat` on the queue socket and `slow zebra` on the audio socket. `emit_to_user`
fans out to both, and the audio socket then correctly declines queue events. Those
"not subscribed" lines are the design working, not a subscription bug (cost three seats six hours reading 749 of them as breakage).


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
| `session_client_types` | `Dict[str, str]` | Client-type side map: `session_id` → `"mobile"` \| `"web"`. Recorded from the queue-WS `auth_request` `client_type` field (exactly `"mobile"` marks mobile; any other explicit value so `"web"`; an absent marker writes `"web"` only for an unmapped session and never downgrades an established `"mobile"` — **the mobile app's** audio-WS connect reuses the queue-WS session id without a marker; the web app's audio socket carries its own id and so gets its own entry). Read by `has_live_mobile_session(user_id)` — the FCM `ws_wake` trigger input (a wake fires only when the user has no live mobile queue-WS; web sessions never suppress it) |
| `available_events` | `set` | Valid event names loaded from `lupin-app.ini` |
| `session_is_admin` | `Dict[str, bool]` | Maps `session_id` → whether the authenticating user carried the `admin` role. Set in `connect()` from its `roles` argument. **This map is a gate, not a display hint**. It is the WS-side half of the console's admin check, the REST half being `require_admin`. *(Existing attribute; it was absent from this table until.)* |
| `session_device_slots` | `Dict[str, tuple]` | **The device slot**. Maps `session_id` → the `( user_id, device_key )` slot it holds. One live `/ws/queue` socket per slot: a newer connection displaces the older with `CLOSE_CODE_SUPERSEDED`. **Only mobile queue-WS sessions get a slot** — see the "One socket per device" section below. **Keyed by session, with no reverse index** — a slot→session map is a second place the truth lives. And the failure it invites is the displaced socket's late cleanup evicting its successor. Here a disconnect pops only its own entry, so that is unreachable rather than guarded |
| `device_frame_buffers` | `OrderedDict[tuple, deque]` | Slot → retained stamped frames, least-recently-emitted-to first. Keyed on the slot, not the session, so it survives a reconnect; see the frame sequence, resume and ack section |
| `resuming_sessions` | `set` | Sessions whose live frames are held (stamped and buffered, not sent) between `begin_resume` and the end of `replay_and_resume`. `disconnect()` discards the entry |
| `cc_transcript_watchers` | `Dict[str, Set[str]]` | Maps `cc_session_id` (a seat's `stable_session_id`) → the set of browser `session_id`s watching it. The **watcher set is the filter, and the only one**: `emit_to_session` applies no subscription check. So there is no second place a frame can be dropped. Swept by `disconnect()` — see the warning below |
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
| `connect` | `(websocket, session_id, user_id=None, subscribed_events=None, email=None, roles=None, client_type=None, device_id=None) -> None` | Registers a WebSocket. Enforces single-session policy if configured. Validates and stores event subscriptions; defaults to `["*"]`. `roles` sets the admin flag; `client_type` is the platform marker — see `session_client_types` above for the no-downgrade rule. `device_id` keys the device slot and is consulted **only** for a mobile session |
| `disconnect` | `(session_id, close_code=1000, close_reason="Server disconnect") -> None` | Removes connection and cleans all associated data: timestamps, subscriptions, admin flag, client-type marker, user maps. **And the CC-transcript watcher registry**, and the device slot. The close parameters exist so the supersede path emits one close carrying `CLOSE_CODE_SUPERSEDED` rather than closing the socket itself and then calling in — two closes race, and the wrong code can win. **This sweep is hand-maintained**: it deletes from each map in its own statement. So every new per-session map is a new statement someone has to remember to add. See the warning under the CC Transcript Console Channel section |
| `register_session_user` | `(session_id, user_id) -> None` | Associates a session with a user **before** the WebSocket connects. Used when a TTS HTTP request arrives with auth ahead of the audio WebSocket upgrade |

### 2a. Device Slots — one socket per device

Mobile "live mode" needs exactly one live `/ws/queue` socket per phone.
A reconnect must displace the phone's previous socket rather than sit beside it.
The displaced socket must be **fully deregistered**, because the FCM wake fires only when the device's socket is down. So a
half-dead socket that still reads as connected silently suppresses the wake.

**The slot key** (Mr. Radio's ruling): `( user_id, device_id )` taken from
`auth_request`, falling back to `client_type` when `device_id` is absent, and **no slot at all
for web clients**.

That last clause is the one that matters, and it is a *mechanism* rather than a policy. The
multiplexer, the legacy client and the console page (`/app/console`, a fresh session id per
load) can all be open for one user at once. And a console tab must not kick the multiplexer
off. Because a web session never gets a slot, it never enters the supersession path. There is
no arm that could be reached with the wrong input. A browser that sent a `device_id` anyway
still gets no slot.

**A mobile client that sends no `device_id` also gets no slot** (Tiffany's revision, replacing the `client_type` fallback this first shipped with). Two phones on one account are indistinguishable without a device id, so they would share one slot and displace each other.
The app also **ignores close codes today and reconnects after any close**.
So that is not one displacement but two phones knocking each other off forever, each reconnect re-opening the loop. Holding no slot is strictly better than holding a wrong one: the sockets
simply coexist, the way web tabs do, until the app ships `device_id`.

**The objection to that, and its answer**. With nobody displacing it, a stale mobile socket
stays registered, keeps `has_live_mobile_session` true and silently suppresses that user's
FCM wake. The exact failure this row exists to prevent. What bounds it is uvicorn's own
websocket ping: it pings every `ws_ping_interval` and drops a peer that has not answered
within `ws_ping_timeout`. So a half-open socket is reaped in at most **interval + timeout**.
Measured on uvicorn 0.46.0: 20 s + 20 s = **~40 s**, inside the 60 s `fcm wake debounce
seconds` window. So a suppressed wake is delayed by less than one window, never lost.

**That is an argument, and an argument is not a guard**. It holds only while `main.py`
leaves the ping enabled. A single `ws_ping_interval=None` turns the bound into "forever" with
nothing failing anywhere. `src/tests/unit/test_uvicorn_websocket_ping_bound.py` is what makes
it falsifiable. It asserts two things.
First, `main.py` disables the ping neither by keyword nor through the `reload_kwargs` splat.
Second, the installed defaults are finite and sum to less than the wake window read from the INI. Both halves, because either alone passes vacuously.

| Method | Signature | Description |
|--------|-----------|-------------|
| `resolve_device_slot` | `(user_id, client_type, device_id=None) -> Optional[tuple]` | **Static**. The slot a session claims, or `None`. Returns `None` when `user_id` is falsy or `client_type` is not exactly `"mobile"`. Otherwise `( user_id, device_id or "mobile" )`. `client_type` here is the **normalized** marker out of `session_client_types`, never the raw `auth_request` value — `connect()` reads the marker it just pinned. So the slot and the FCM wake trigger cannot disagree about what counts as mobile |
| `device_slot_of` | `(session_id) -> Optional[tuple]` | The slot this session holds, or `None` |
| `slot_holder` | `(user_id, slot) -> Optional[str]` | The session currently holding `slot`, or `None`. Scans **one user's** sessions rather than a reverse index (see the `session_device_slots` attribute row for why). Only sessions holding a live connection count, so a `register_session_user` pre-registration can neither be displaced nor block a claim |

#### Frame seq, resume, and ack (part 2)

A device's socket can go away and come back without losing frames. Every frame to a
**slot holder** carries a monotonic `seq`; the server retains them. The client reconnects
with `last_seq` in its `auth_request` and gets the backlog after it; its `ack` trims what
it has processed. A session with no slot — every web client — gets none of this, and pays
nothing for it.

| direction | shape |
|---|---|
| `auth_request` | `+ "last_seq": int` — absent or 0 means a fresh client with nothing to resume |
| every frame to a slot holder | `+ "seq": int`, monotonic **per slot**, starting at 1 |
| after the replay | `{ "type": "resume_complete", "replayed": N, "gap": bool, "seq": <server's current seq for the slot> }` |
| client → server | `{ "type": "ack", "seq": N }` |

**The buffer is keyed on the slot, not the session, and `disconnect()` does not sweep
it**. A session id dies with its socket. The slot is what survives a reconnect, so it is
the only key a resume can be built on. It is also what keeps supersession honest — the
successor inherits the buffer and the seq **continues** rather than restarting. So a
reconnecting client is never handed a second frame 1 carrying different contents while
its `last_seq` quietly means two things.

**`gap` is the field that is easy to get silently wrong**. A partial replay that does
not announce itself is worse than no replay: the client believes it is current and stops
asking. `gap` is true when the server cannot **prove** continuity from `last_seq`.
That means frames were evicted by the cap, or nothing is retained at all against a non-zero `last_seq`.
A server restart looks like that from the client's side. It is false for
`last_seq` 0 against an unknown slot, or every device's first-ever connection would
trigger a pointless full refetch.

**A hole between the replay and the held frames is announced**. The per-device
buffer is bounded, and live frames keep arriving while the replay is on the wire. So the
oldest of them can be evicted before they are sent. `replay_and_resume` checks that each
next batch starts at `cursor + 1`. A hole found during the replay proper sets `gap` on the
one `resume_complete`. A hole found after that frame has already gone out with `gap: false` is followed by a **second** `resume_complete { gap: true }`.
That second frame is sent once, however many holes there are.
It goes out before the frames that lie past the hole. So the client refetches instead of trusting them.

**`resume_complete.seq` is the server's current seq, never an echo of the client's
`last_seq`**. After a reset the two differ, and a client that adopted its own stale number
back would discard every new frame as already seen. The client sets `last_seq =
resume_complete.seq` when it arrives.

**Live frames are held until the replay drains**. A live frame sent while the backlog is
still going out would overtake it. And a client deduping on `seq` would then drop the
replayed frames as old. So between `begin_resume` and the end of `replay_and_resume` a
session's frames are stamped and buffered but not sent (`resuming_sessions`). The fan-out
still counts the device as reached, since the frame will arrive. `disconnect()` discards the
hold.

**Bounded at both ends**, because the buffers outlive their sockets and per-slot capping alone would bound nothing.
`websocket device frame buffer size` (default 200) caps frames per slot.
`websocket device frame buffer max slots` (default 64) caps slots.
Eviction takes the least-recently-emitted-to slot **that has no connected holder** first.
The device most likely to come back is the one whose backlog is worth keeping. A slot whose socket is open is never evicted, however quiet.
When every slot past the ceiling is live, the map exceeds `max slots` by at most the number of connected holders.
That logs one `[WS]` warning per crossing, not per frame.
The next write after holders disconnect evicts back down.

`resume_complete` is **not** in `websocket available events`: the endpoint
sends it directly like `auth_success` and it never passes through the subscription filter.
Listing it would imply a path that does not exist.

| Method | Signature | Description |
|--------|-----------|-------------|
| `buffer_frame_for_slot` | `(slot, message) -> dict` | Assigns the slot's next seq, retains a stamped **copy**, returns it. The copy matters: `emit_to_user` builds one message and fans it out. So stamping in place would give every device the last writer's number — invisible with a single device connected. Which is how it would ship |
| `frames_since` | `(slot, last_seq) -> (list, bool)` | The retained frames after `last_seq`, plus whether continuity is proven (see `gap` above). A `last_seq` **beyond** the slot's current seq means the numbering reset under the client (a server restart). So it answers `gap: true` with the whole buffer rather than an empty, falsely-current replay |
| `begin_resume` | `(session_id) -> bool` | Starts **holding** a slot holder's live frames: they are still stamped and buffered, but not sent, until `replay_and_resume` drains. The router calls it right after `connect()` with **no `await` in between**. That adjacency is what leaves no window for a live frame to go out unheld. Returns `False` for a session holding no slot |
| `replay_and_resume` | `async (session_id, last_seq, send) -> Optional[dict]` | Sends the backlog after `last_seq`, then `resume_complete`, then releases everything held since `begin_resume`. All in seq order — and returns the `resume_complete` frame. `None`, sending nothing, for a session holding no slot |
| `ack_frames` | `(session_id, seq) -> int` | Drops that session's slot buffer up to and including `seq`; returns how many went. A session holding no slot is a silent no-op, so an ack cannot reach another device's buffer |

**Close code**. A displaced socket receives `CLOSE_CODE_SUPERSEDED` = **4004**, reason
`"superseded"` (Tiffany's ruling). Permanent: the client must not reconnect it.

**A new code — this shipped as 4001, was cut to 4003, and both were taken**.
4001 is auth failure, which the browser answers with a token refresh that means nothing for a
supersede. 4003 is `CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED`.
It is reserved server-side and never emitted.
But the code is **live on the client**.
`QueueTransport.ts` lists it in `PERMANENT_CLOSE_CODES`.
`notifications.js` renders it "Permission denied for one or more notification streams".
A reserved server code can still be a spoken-for client one, which is worth remembering.
4004 is free in both places.

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

**Two id spaces, never interchangeable**: the registry's **key** is a Claude Code seat's `stable_session_id`; its **values** are browser session ids. A registry that confused them would let a browser "watch" another browser, and the symptom would be an empty pane rather than a type error.


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
| Resume replay failed **after** auth succeeded | (no `auth_error` frame; reason `resume_failed`; the real exception is logged at error level with the session id) | **1011** — not 4001 |

A 1011 is **not** an auth outcome.
The replay of a device's backlog runs after `auth_success`, outside the auth `try`.
So a send that dies mid-backlog cannot be mistaken for a bad token.
It used to be sent as `auth_error` + 4001, and the mobile client answers 4001 with a token refresh or a sign-out. The client reconnects on 1011 under normal backoff.

All 4001/4002/4003 codes are permanent from the client's perspective —
the browser-side `ws-channel.js` state machine routes them straight to
`OPEN_CIRCUIT` and does not auto-retry. NotificationsUI attempts a single
token refresh on 4001 before showing the auth-permanent banner. See
[WebSocket Events §Close Code Semantics](websocket-events.md#close-code-semantics)
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

## Thread-Safety Model

The core problem: COSA queue workers run in **background threads** and call `emit()` synchronously. But WebSocket `send_json()` is an async coroutine that must run on the **main asyncio event loop**.

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

> **Status**: the contract is documented, and the server side lands in the first build phase. Payload schemas: [`websocket-events.md`](websocket-events.md) § "CC Transcript Console Events". REST companion: [`rest-api-reference.md`](rest-api-reference.md) § 27. Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`.

A read-only live window onto a Claude Code seat's transcript, carried on the **existing** `/ws/queue/{session_id}` socket. No new socket and no new auth path — but **"no new socket" is not "no server work"**, for three reasons set out below.

### 1. The receive loop grows two verbs

`routers/websocket.py` `websocket_queue_endpoint` handles exactly **two** client verbs today — `sys_ping` and `update_subscriptions`. `cc_transcript_watch` and `cc_transcript_unwatch` are **new branches beside them**.

**`update_subscriptions` cannot absorb them**. It is type-level only: it takes a list of event *names* and has no per-target argument, so it cannot express "watch *this* seat". A watch is parameterised by `cc_session_id`; a subscription is not parameterised at all.

### 2. The two fan-out calls do not behave the same, and only one of them is right here

| Call | Subscription check? |
|---|---|
| `emit_to_user` | **Yes** — filters each frame against `session_subscriptions.get( session_id, ["*"] )` |
| `emit_to_session` | **No** — sends unconditionally |

Append frames go out over **`emit_to_session`, to the watching browser session only**. The watcher set is therefore the single filter, so there is one place to look when a frame goes missing.

### 3. The `websocket available events` key change

The four names — `cc_transcript_watch`, `cc_transcript_unwatch`, `cc_transcript_append`, `cc_transcript_state` — are added to `websocket available events` in `src/conf/lupin-app.ini` in the first build phase. And to both client subscription lists, **even though `emit_to_session` never consults the list**.

Two reasons, and neither is tidiness:

1. A client's subscription list should not silently lie about what it asked for. **A name absent from the registry is dropped at subscribe time, silently**. And a client whose whole list validates to `[]` has every frame dropped while auth still reports success. The failure the in-place comment beside the validation in `websocket_manager.py` describes.
2. Anyone who later switches the carrier from `emit_to_session` to `emit_to_user` would otherwise ship a stream that delivers nothing while reporting success.

> **Append with `", "` exactly — a comma alone silently mangles the name**. The reader is `ConfigurationManager.get( ..., return_type="list-string" )`, and that branch is a bare `value.split( ", " )` with **no per-token strip**. So `…speakerphone_changed,cc_transcript_watch` yields one token spelled `speakerphone_changed,cc_transcript_watch`, which matches nothing: the *previous* event silently stops validating and the new one never starts. Nothing raises — the list is still non-empty, so the `ValueError` guard in `__init__` does not fire either.

**Derive the list through the real reader, never quote a count**. Three documents have carried three different figures for the size of this list. And a count is the weakest possible assertion — it passes just as happily if a name is misspelled. Read it the way the server does and compare **set equality** against a committed literal:

```python
from cosa.config.configuration_manager import ConfigurationManager
names = ConfigurationManager().get( "websocket available events", return_type="list-string" )
```

Verified: 25 entries, 25 unique, no malformed token.

### The tailer resolves the seat, and opens its path verbatim

The tailer resolves a seat's transcript from the **session bridge** — `session_bridge.find_session_by_id( cc_session_id )`, the per-seat read. `get_session_metadata()` resolves only the *calling* process and cannot answer for another seat.
Offsets are advanced with `events_tail.tail_session_file( path, offset )`.
That call is partial-line safe and returns `( records, new_offset )` landing at the last **complete** line, which is the `next_offset` rule.

**Open `transcript_path` exactly as the bridge wrote it, and never rejoin it against `LUPIN_ROOT` or any other root**.
The container binds the host sessions directory to the **same absolute path inside the container**.
That is the `${LUPIN_HOST_SESSIONS_DIR:-/home/rruiz/.claude/sessions}` bind in `docker-compose.yml`, with target `/home/rruiz/.claude/sessions`.
That is why a verbatim open works.
A path rewritten relative to a project root points at nothing.
`tail_session_file` **never raises**: a missing file returns `( [], offset )`.
So the failure is not an error. It is an empty stream, a pane that stays blank while every status says live.

### The leak the watcher registry invites

**`cc_transcript_unwatch` is the polite path, not the reliable one**.
A closed tab or a dropped socket never sends it.
So `disconnect()` must sweep `cc_transcript_watchers`.
That sweep is **hand-maintained**, deleting from `active_connections`, `session_timestamps`, `session_subscriptions`, `session_is_admin`, `session_client_types` and the user association one statement at a time. The watcher map is a **sixth entry that has to be added there explicitly**.

Miss it and there is **no error anywhere**.
The tailer polls forever, and `emit_to_session` early-returns into a session already gone from `active_connections`.
That is a silent burn. The test that catches it drops the socket *without* sending the unwatch verb. A test that only exercises the explicit unwatch stays green while the leak ships.

### Admin gating: two surfaces, two different gates

| Surface | Gate |
|---|---|
| WS verbs (`cc_transcript_watch`) | `session_is_admin[ session_id ]` — a lookup on state `connect()` already stores |
| REST backlog + roster | `require_admin` (`require_roles( ["admin"] )`) |

They are **different mechanisms**, so a test that exercises one proves nothing about the other. And a criterion naming only one is satisfiable by a gate that refuses everybody. Both arms — a non-admin refused **and** an admin accepted — or neither is proved.

---

## Related Documentation

- [WebSocket Events](websocket-events.md) — Complete event catalog with payload schemas
- [WebSocket Configuration](websocket-configuration.md) — All config keys and tuning
- [WebSocket Troubleshooting](websocket-troubleshooting.md) — Diagnostic procedures
