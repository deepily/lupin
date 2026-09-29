# WebSocket Event System Documentation

**Date**: 2026.03.20 · **Revised**: 2026.09.27 (CC transcript console events; stale event count removed)
**Source of truth**: `lupin-app.ini` key `websocket available events`, `src/cosa/rest/routers/websocket.py`
**Status**: Active

## Event Catalog

The allow-list is the `websocket available events` key in `lupin-app.ini` (`src/conf/lupin-app.ini:1729`), and **that key is the only authority** — a name absent from it is dropped at subscribe time while auth still reports success (see `websocket_manager.py` `connect()`, and the in-place comment beside the validation). Clients subscribe to specific events (or `"*"` for all) during the auth handshake or via dynamic subscription updates.

> **Count, and why this sentence no longer states one.** This document used to open "The system defines **22 events**", which was wrong when read on 2026.09.27: the INI key listed **25**. `websocket-configuration.md` carries a third figure, an 18-name copy of the list. Three documents, three counts, and nothing reconciling them — so the count is deliberately not restated here.
>
> Derive the list through the reader the server itself uses, and compare **set equality** against a committed literal — a count is the weakest possible assertion, since it passes just as happily if a name is misspelled:
>
> ```python
> from cosa.config.configuration_manager import ConfigurationManager
> names = ConfigurationManager().get( "websocket available events", return_type="list-string" )
> ```
>
> Verified 2026.09.27: **25 entries, 25 unique**. The four `cc_transcript_*` names below are **added to that key in phase 1** of the console-tee feature and are **not in it yet** — plan `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`. They must be appended with `", "` exactly: the reader is a bare `value.split( ", " )` with no per-token strip, so a comma without a space mangles the new name *and* the one before it, silently. See [`websocket-architecture.md`](websocket-architecture.md) § CC Transcript Console Channel.

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
| `speakerphone_changed` | Notifications (notification_queue_update wrapper, `type="speakerphone_changed"`) | Server → Client | Yes |
| `proxy_decision_new` | Proxy / Ratification | Server → Client | Yes |
| `cc_transcript_watch` | CC transcript console | Client → Server | N/A (admin-gated) |
| `cc_transcript_unwatch` | CC transcript console | Client → Server | N/A (admin-gated) |
| `cc_transcript_append` | CC transcript console | Server → Client | No — per **watching browser session**, via `emit_to_session` |
| `cc_transcript_state` | CC transcript console | Server → Client | No — per **watching browser session**, via `emit_to_session` |
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

### `speakerphone_changed`

**Renamed 2026-05-13** from `conversation_mode_changed` during the Speakerphone solo/chorus refactor (see [`../rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`](../rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/) Phase 3). Broadcast on every speakerphone-mode toggle so all connected UI tabs sync. In solo mode, activating one session displaces any other active session; in chorus mode, multiple sessions can be simultaneously active.

Wrapped in the canonical `notification_queue_update` envelope with `notification.type == "speakerphone_changed"`. Origin: `src/cosa/rest/routers/speakerphone.py` — emits at two sites: (a) the displaced-other-session push (when a different session previously held the slot in solo mode) and (b) the self-state-change push (always fires on POST `/api/cosa-voice/speakerphone/{sid}`). User-scoped — only sent to the authenticated owner's sessions.

**Payload** (under `notification.payload`):
```json
{
  "session_id": "abc123-uuid",
  "on": true,
  "displaced": false,
  "displaced_by": null
}
```

- `session_id` — the session whose speakerphone state just changed
- `on` — `true` if speakerphone is now active, `false` if deactivated
- `displaced` (optional) — `true` when this session was forcibly deactivated because another session activated in solo mode
- `displaced_by` (optional) — the session_id that displaced this one (only present when `displaced: true`)

Client handling:
- Legacy UI: `notifications.js::handleConversationModeChanged()` (line ~5552) — client-side maps `payload.on → conversation_mode_active` for the legacy in-memory state model; the legacy handler kept its original method name for callsite stability.
- Multiplexer UI: `src/lupin_app/static/js/multiplexer/stores/SenderStore.ts` — `STATE_UPDATE_TYPES` Set includes BOTH `"speakerphone_changed"` (current wire) AND `"conversation_mode_changed"` (post-rename target, in case the type is ever re-renamed back). Reducer reads `payload.active ?? payload.on` to accept either field name. **Forward-compat bridge** — implementer can rename either direction without breaking the client. See `2026-05-19 Run 3 cascade Section D` for the Path III bridge ratification rationale.

**INI subscription**: included in `lupin-app.ini` `websocket available events` (line 741). Subscribed by both legacy and multiplexer clients via the WS auth handshake.

**Server-side whitelist**: `src/cosa/rest/routers/notifications.py:359-364` `valid_types` list. The deprecated `conversation_mode_changed` is NOT in the list — pushing that type would return HTTP 400.

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

## CC Transcript Console Events

> **Status**: contract documented at **phase 0**; the server side lands at **phase 1**. Plan and acceptance criteria: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2–§3. Names are per ruling **OSQ-6** and supersede the earlier `transcript_*` spelling in that plan's ruling Q4b.

A read-only live window onto what a Claude Code seat is printing. The source is the seat's **transcript JSONL file** (ruling Q1) — not a terminal tee — tailed by byte offset on `:7999` and pushed to the watching browser over the **existing** `/ws/queue/{session_id}` socket (ruling Q4). No new socket, no new auth path.

**Four rules that are easy to get wrong, so they are stated before the payloads:**

1. **`cc_session_id` is the seat's `stable_session_id`** — the full id that survives a `/clear`. Never the post-clear id, and never the 8-character form the fleet uses elsewhere (`sender_id`'s `#<8hex>` suffix, a DM's `recipient_session_hash8`). Three id widths circulate in this fleet; a silent mismatch shows up as a roster row that cannot be watched.
2. **`offset` is the sequence number.** It is a byte offset into the source file. There is no separate `seq`, and `next_offset` always lands at the end of a **complete** line.
3. **`file_epoch` scopes every offset.** It names the transcript file. A `/clear` **swaps the path** rather than shrinking the file, so the epoch — not a shrink — is what tells a client its offset is void.
4. **Admin only** (ruling Q5), enforced on **both** surfaces: the WS verb checks `websocket_manager.session_is_admin[ session_id ]`, and the REST backlog uses `require_admin`. Two different gates; both are load-bearing. No redaction in v1 — the stream carries whatever the seat read, including file contents.

### `cc_transcript_watch` (Client → Server)

Start receiving append frames for one seat. Sent on the already-authenticated `/ws/queue` socket.

```json
{
  "type"        : "cc_transcript_watch",
  "cc_session_id": "449359bc-c735-4970-8fc0-e83b635c8548",
  "from_offset" : 0,
  "file_epoch"  : null
}
```

- `from_offset` — **the server starts where the client asked.** It never silently starts at the current end of the file; doing so would open a gap between the REST backlog fetch and the live watch.
- `file_epoch` — **nullable.** `null` means "whatever file is current", and the server answers with the epoch it chose, so a first watch needs no prior REST call. A **stale non-null** epoch is **refused, never silently rebased**: the server replies `cc_transcript_state {state: "epoch_mismatch"}` and sends no blocks. Rebasing would hand the client a whole new file labelled as its own continuation.
- A watch from a non-admin session is **refused**.

### `cc_transcript_unwatch` (Client → Server)

```json
{ "type": "cc_transcript_unwatch", "cc_session_id": "449359bc-..." }
```

Stops the frames. The tailer stops after the **last** watcher leaves, plus a grace period.

> ⚠️ **Unwatch is the polite path, not the reliable one.** A closed tab or a dropped socket never sends it, so `WebSocketManager.disconnect()` sweeps the watcher registry as well. That sweep is hand-maintained — it already deletes from `active_connections`, `session_timestamps`, `session_subscriptions`, `session_is_admin`, `session_client_types` and the user association one statement at a time — so the watcher map is a **sixth entry that has to be added there explicitly**. Miss it and the tailer polls forever while `emit_to_session` early-returns into a session already gone: a silent burn with no error anywhere.

### `cc_transcript_append` (Server → Client)

Coalesced roughly every 300 ms per seat (ruling Q7), delivered by `emit_to_session` to watchers only.

```json
{
  "type"        : "cc_transcript_append",
  "cc_session_id": "449359bc-...",
  "file_epoch"  : "449359bc-c735-4970-8fc0-e83b635c8548",
  "offset"      : 20480,
  "next_offset" : 24576,
  "blocks"      : [
    { "ts": "2026-09-27T18:04:03Z", "role": "assistant", "kind": "text",
      "text": "Reading the spec now.", "truncated": false },
    { "ts": "2026-09-27T18:04:05Z", "role": "assistant", "kind": "tool_call",
      "text": "Bash( sha256sum … )", "truncated": false },
    { "ts": "2026-09-27T18:04:06Z", "role": "user", "kind": "tool_result",
      "text": "41661313b706…", "truncated": true }
  ],
  "ts"          : "2026-09-27T18:04:06Z"
}
```

**Gap rule**: if `offset != last_next_offset`, the client **drops the frame** and repairs over REST from `last_next_offset`.

**A block's `kind` comes from the content block's type, never from the record's role.** In a census of 8,115 records across four recent lupin transcripts, **760 of the 1,026 `user` records carried tool results** — a role-based mapping would render three quarters of them as fake human turns.

**`kind` decides the renderer, and prose and tool content do not share one.** `text` renders as markdown; `tool_call`, `tool_result` and `thinking` render as **plain text** (`<pre>` / `textContent` on the web), collapsed and truncated per ruling Q2 — `thinking` folded and expandable per ruling OSQ-7. **A kind the client does not recognise renders as plain text — never dropped, never thrown on.** The mapper is deliberately open-ended, so a switch over three literals with no fallback would render nothing in the one surface whose whole job is to show everything, and silently. The risk here is **mangling, not injection**: a markdown renderer turns a raw file dump into markup, so `#` becomes a heading and a diff renders wrong.

**Blocks are budgeted.** A block over its budget arrives with `truncated: true` and the full text is available over REST. Following `routers/tasks.py`, **`budget == 0` means unbounded, not zero** — keep that sense rather than inventing a `cap` that reads the opposite way.

### `cc_transcript_state` (Server → Client)

```json
{
  "type"        : "cc_transcript_state",
  "cc_session_id": "449359bc-...",
  "file_epoch"  : "…",
  "state"       : "live"
}
```

| `state` | Meaning | Client action |
|---|---|---|
| `live` | The tailer is attached and following the file | none |
| `ended` | The **seat** exited — driven by the `SessionEnd` hook, with a staleness fallback for a seat that dies without firing it | stop expecting frames; the pane is final, not merely quiet |
| `rotated` | The `file_epoch` changed: a `/clear` swapped the transcript path, or the file was truncated in place | drop the buffer and offset, re-fetch the backlog over REST |
| `epoch_mismatch` | The watch named an epoch that is no longer current | same as `rotated` — clear and re-fetch; **no blocks accompany this frame** |

> **`ended` needs a producer, and the tailer's stop rule is not it.** The grace period stops the tailer when the last *watcher* leaves, never when the *seat* leaves. Without a producer, a viewer watching a seat that exits sees a pane that merely stops — indistinguishable from a quiet seat.

> **Why a `/clear` is a path swap and not a shrink.** `register_session.py` runs on every SessionStart, `/clear` fires SessionStart, and the hook rewrites the bridge with the **new** `transcript_path` while **preserving** `stable_session_id`. The old JSONL does not shrink; it simply stops growing while a different file appears elsewhere. So the tailer **re-resolves the bridge on every poll, and a changed `transcript_path` is the primary `/clear` detector**. A tailer watching only for a shrink sits on the dead file forever — no epoch bump, no state frame, and the pane silently freezes at the moment of the clear, which is the precise failure `file_epoch` exists to prevent. The shrink path stays as the **secondary** detector, for genuine in-place truncation.

### REST companion

`GET /api/cc-transcript/{cc_session_id}` serves the backlog and repairs gaps. It is documented in [`rest-api-reference.md`](rest-api-reference.md) § "CC Transcript Console".

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
  "subscribed_events": ["job_state_transition", "notification_queue_update"],
  "client_type": "mobile"
}
```

- `subscribed_events` is optional; defaults to `["*"]` (all events)
- `token` can include or omit the `Bearer ` prefix (stripped server-side)
- `client_type` is optional (F-S6-1, queue WS only): the mobile app sends `"mobile"`; anything else — including absent (existing web clients send nothing) — is recorded as `"web"`. Drives the FCM `ws_wake` trigger: a wake push fires only when the user has NO live session marked `"mobile"`, so a desktop browser never suppresses the phone's wake. The audio WS never records this marker.

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

> ⚠️ **This table used to say `to_queue: "todo"` / `"run"` / `"done"` / `"dead"`, and that
> field does not exist.** `emit_job_state_transition()` (`src/cosa/rest/queue_util.py:65-71`)
> emits exactly `job_id`, `from_state`, `to_state`, `timestamp`, and an optional `metadata` —
> never `to_queue`. Measured live on :7999: a submitted job produces `pending`->`queued`,
> `queued`->`running`, `running`->`completed`. Two consumers had been reading the phantom
> field with a `.get( "to_queue", "?" )` default and printing `? -> ?` on every transition
> since the rename; corrected 2026-08-24 (row e3417974).

The following event was renamed during the 2026-05-13 Speakerphone solo/chorus refactor (Phase 3 of `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`):

| Deprecated Event | Replacement | Rename Date |
|-----------------|-------------|-------------|
| `conversation_mode_changed` | `speakerphone_changed` (semantic payload identical; `payload.on` carries the boolean state) | 2026-05-13 |

The deprecated name is NOT in the `valid_types` whitelist; pushing it returns HTTP 400. The multiplexer `SenderStore` accepts both names client-side as a **forward-compat bridge** in case the event is ever re-renamed back — see `speakerphone_changed` entry above for details.

---

## Frame seq, resume, and ack (row dc446601 part 2)

Frames sent to a **device slot holder** (a mobile session that authenticated with a
`device_id`) carry an extra field, and three protocol shapes exist around it. A session
with no slot — every web client — sees none of this and its frames are unchanged.

| field / frame | direction | meaning |
|---|---|---|
| `seq` | server → client | Monotonic **per device slot**, starting at 1. Added to every frame to a slot holder, alongside `type` and `timestamp` |
| `last_seq` | client → server, in `auth_request` | The client's highest received `seq`. Absent or `0` means a fresh client with nothing to resume. A non-integer, a bool or a negative is treated as absent rather than trusted |
| `resume_complete` | server → client | `{ "type": "resume_complete", "replayed": N, "gap": bool, "seq": <highest> }`, sent once after `auth_success` and after any replayed frames. Marks where the backlog ENDS |
| `ack` | client → server | `{ "type": "ack", "seq": N }` — the client confirms it has processed through `N`, and the server drops those frames |

🔴 **`gap: true` is the server saying it cannot prove continuity**, and the client must
do a full refetch rather than assume it is current. It is set when frames were evicted by
the retention cap, or when the server holds nothing at all for a client claiming a
non-zero `last_seq` — which is what a server restart looks like from the client's side. A
partial replay that stayed quiet would leave the client believing it was caught up and it
would stop asking, which is strictly worse than not replaying.

Retention is bounded by `websocket device frame buffer size` (default 200) per slot and
`websocket device frame buffer max slots` (default 64) overall. Without an `ack` the
buffer only ever shrinks by eviction — which is the thing that causes a `gap`.

`resume_complete` is deliberately **not** in `websocket available events`: the endpoint
sends it directly, like `auth_success`, and it never passes through the subscription
filter. Listing it would imply a path that does not exist.

## Close Code Semantics

The server uses RFC 6455 application close codes (4000–4999) to signal
auth-failure outcomes that the browser-side state machine
(`src/lupin_app/static/js/ws-channel.js`) treats as PERMANENT — the
channel goes straight to `OPEN_CIRCUIT` and does NOT auto-retry.

Codes were introduced in Phase 5 of the WS reconnect circuit-breaker
milestone (`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/06-phase-5-server-side-hardening.md`).
Constants live in `src/cosa/rest/routers/websocket.py`.

| Code | Constant | Meaning | Server emits when… | Client behavior |
|------|----------|---------|---------------------|------------------|
| 4001 | `CLOSE_CODE_AUTH_INVALID_TOKEN`       | Invalid / expired / malformed token; bad `auth_request` envelope | Auth flow on `/ws/queue/{session}` rejects the supplied token (any of: malformed JSON, missing `token` field, empty token, signature failure, `TokenExpiredException`) | `notifications.js` attempts a single `refreshAccessToken()` call FIRST. On refresh-success, `manualRetry()` runs on both channels (no banner shown). On refresh-failure, the auth-permanent banner is shown ("Authentication failed — please log in again."). |
| 4002 | `CLOSE_CODE_AUTH_SESSION_CONFLICT`    | Single-session-per-user policy displaced this connection | A second connection arrives for a user already connected, AND `websocket enforce single session per user = True`. The OLD session receives 4002. | Banner: "Another session has taken over. Refresh to reclaim." Channel does NOT auto-retry. |
| 4003 | `CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED` | RBAC reject on one or more `subscribed_events` | RESERVED — no current branch emits 4003. The audio path filters denied events silently today. Reserved for future RBAC enforcement. | Banner: "Permission denied for one or more notification streams." Channel does NOT auto-retry. |
| 4004 | `CLOSE_CODE_SUPERSEDED` (row dc446601) | **Superseded**, reason `"superseded"` | A NEWER `/ws/queue` connection claimed this socket's `( user_id, device_id )` slot. The old socket is closed AND fully deregistered — a half-dead socket left registered would make the device read as connected and silently suppress its FCM wake. Emitted only for MOBILE sessions, the only ones holding a slot; a mobile client that sent no `device_id` holds none and is never superseded. | Permanent: the client must NOT reconnect this socket. ⚠️ **A NEW code on purpose.** 4001 is auth failure, which the browser answers with a meaningless token refresh; 4003 is reserved server-side but LIVE on the client — `QueueTransport.ts` lists it in `PERMANENT_CLOSE_CODES` and `notifications.js` renders it "Permission denied…". A reserved SERVER code can still be a spoken-for CLIENT one. Browsers do not yet list 4004, so it falls to their default close handling; they cannot receive it today because they hold no slot. |

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
