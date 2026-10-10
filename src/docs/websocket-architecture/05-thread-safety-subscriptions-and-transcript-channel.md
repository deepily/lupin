> Part 5 of 5 of the [WebSocket Architecture Overview](../websocket-architecture.md): thread safety, subscriptions, transcript channel.

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

> **Status**: the contract is documented, and the server side lands in the first build phase. Payload schemas: [`websocket-events.md`](../websocket-events.md) § "CC Transcript Console Events". REST companion: [`rest-api-reference.md`](../rest-api-reference.md) § 27. Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`.

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

> Warning: **Append with `", "` exactly — a comma alone silently mangles the name**. The reader is `ConfigurationManager.get( ..., return_type="list-string" )`, and that branch is a bare `value.split( ", " )` with **no per-token strip**. So `…speakerphone_changed,cc_transcript_watch` yields one token spelled `speakerphone_changed,cc_transcript_watch`, which matches nothing: the *previous* event silently stops validating and the new one never starts. Nothing raises — the list is still non-empty, so the `ValueError` guard in `__init__` does not fire either.

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

Warning: **Open `transcript_path` exactly as the bridge wrote it, and never rejoin it against `LUPIN_ROOT` or any other root**.
The container binds the host sessions directory to the **same absolute path inside the container**.
That is the `${LUPIN_HOST_SESSIONS_DIR:-/home/rruiz/.claude/sessions}` bind in `docker-compose.yml`, with target `/home/rruiz/.claude/sessions`.
That is why a verbatim open works.
A path rewritten relative to a project root points at nothing.
`tail_session_file` **never raises**: a missing file returns `( [], offset )`.
So the failure is not an error. It is an empty stream, a pane that stays blank while every status says live.

### The leak the watcher registry invites

Warning: **`cc_transcript_unwatch` is the polite path, not the reliable one**.
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

- [WebSocket Events](../websocket-events.md) — Complete event catalog with payload schemas
- [WebSocket Configuration](../websocket-configuration.md) — All config keys and tuning
- [WebSocket Troubleshooting](../websocket-troubleshooting.md) — Diagnostic procedures
