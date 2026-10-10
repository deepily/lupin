> Part 2 of 5 of the [WebSocket Architecture Overview](../websocket-architecture.md): manager API through device slots.

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
| `session_device_slots` | `Dict[str, tuple]` | **The device slot**. Maps `session_id` → the `( user_id, device_key )` slot it holds. One live `/ws/queue` socket per slot: a newer connection displaces the older with `CLOSE_CODE_SUPERSEDED`. **Only mobile queue-WS sessions get a slot** — see the "One socket per device" section below. Warning: **Keyed by session, with no reverse index: a rule, not a gap** — a slot→session map is a second place the truth lives. And the failure it invites is the displaced socket's late cleanup evicting its successor. Here a disconnect pops only its own entry, so that is unreachable rather than guarded |
| `device_frame_buffers` | `OrderedDict[tuple, deque]` | Slot → retained stamped frames, least-recently-emitted-to first. Keyed on the slot, not the session, so it survives a reconnect; see the frame sequence, resume and ack section |
| `resuming_sessions` | `set` | Sessions whose live frames are held (stamped and buffered, not sent) between `begin_resume` and the end of `replay_and_resume`. `disconnect()` discards the entry |
| `cc_transcript_watchers` | `Dict[str, Set[str]]` | Maps `cc_session_id` (a seat's `stable_session_id`) → the set of browser `session_id`s watching it. The **watcher set is the filter, and the only one, by rule**: `emit_to_session` applies no subscription check. So there is no second place a frame can be dropped. Swept by `disconnect()` — see the warning below |
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
| `disconnect` | `(session_id, close_code=1000, close_reason="Server disconnect") -> None` | Removes connection and cleans all associated data: timestamps, subscriptions, admin flag, client-type marker, user maps. **And the CC-transcript watcher registry**, and the device slot. The close parameters exist so the supersede path emits one close carrying `CLOSE_CODE_SUPERSEDED` rather than closing the socket itself and then calling in — two closes race, and the wrong code can win. Warning: **This sweep is hand-maintained**: it deletes from each map in its own statement. So every new per-session map is a new statement someone has to remember to add. See the warning under the CC Transcript Console Channel section |
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

Warning: **That is an argument, and an argument is not a guard**. It holds only while `main.py`
leaves the ping enabled. A single `ws_ping_interval=None` turns the bound into "forever" with
nothing failing anywhere. `src/tests/unit/test_uvicorn_websocket_ping_bound.py` is what makes
it falsifiable. It asserts two things.
First, `main.py` disables the ping neither by keyword nor through the `reload_kwargs` splat.
Second, the installed defaults are finite and sum to less than the wake window read from the INI. Both halves, because either alone passes vacuously.

| Method | Signature | Description |
|--------|-----------|-------------|
| `resolve_device_slot` | `(user_id, client_type, device_id=None) -> Optional[tuple]` | **Static**. The slot a session claims, or `None`. Returns `None` when `user_id` is falsy or `client_type` is not exactly `"mobile"`. Otherwise `( user_id, device_id or "mobile" )`. Warning: `client_type` here is the **normalized** marker out of `session_client_types`, never the raw `auth_request` value — `connect()` reads the marker it just pinned. So the slot and the FCM wake trigger cannot disagree about what counts as mobile |
| `device_slot_of` | `(session_id) -> Optional[tuple]` | The slot this session holds, or `None` |
| `slot_holder` | `(user_id, slot) -> Optional[str]` | The session currently holding `slot`, or `None`. Scans **one user's** sessions rather than a reverse index (see the `session_device_slots` attribute row for why). Only sessions holding a live connection count, so a `register_session_user` pre-registration can neither be displaced nor block a claim |
