> Part 2 of 5 of the [WebSocket Event System Documentation](../websocket-events.md): notification events, proxy and ratification events and task store events.

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

**NEW 2026-05-14** — Real-time push of new commons-topic entries to the broadcast-card Recent Activity stream. Powers the admin-oversight surface described in [`../rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md`](../../rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md).

Wrapped in the canonical `notification_queue_update` envelope with `notification.type == "commons_activity"`. Fired by `CommonsActivityWatcher` (FastAPI-side daemon in `src/cosa/rest/commons_activity_watcher.py`) on each ~1s tick when new entries land in the commons store on any non-excluded topic. Recipient is resolved best-effort from `metadata.sender_user_id` first, then a bridge-owner lookup keyed by `sender_session_id`; falls back to broadcast-to-all-authenticated-WS in single-user dev.

Gated by two INI keys (both default True):
- `commons traffic visibility enabled`. Master flag (hot-reloadable via the config re-init endpoint)
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

`topic_kind` is `"reserved"` for `broadcasts` + `broadcast-acks`; `"free-form"` otherwise. The client uses this to decide whether to render a topic-chip prefix (ratified: free-form gets a chip; reserved doesn't). Excluded topics (`presence` + `system-events` by default per `commons traffic visibility exclude topics`) never appear in this stream.

Client handling: `notifications.js::_handleCommonsActivityWS()` prepends the new entry to `#commons-recent-activity-entries`, preserving newest-first ordering.

---

### `speakerphone_changed`

**Renamed 2026-05-13** from `conversation_mode_changed` during the Speakerphone solo/chorus refactor.
See [`../rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`](../../rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/). Broadcast on every speakerphone-mode toggle so all connected UI tabs sync. In solo mode, activating one session displaces any other active session; in chorus mode, multiple sessions can be simultaneously active.

Wrapped in the canonical `notification_queue_update` envelope with `notification.type == "speakerphone_changed"`. Origin: `src/cosa/rest/routers/speakerphone.py`, which emits at two sites.
Site (a) is the displaced-other-session push, sent when a different session previously held the slot in solo mode.
Site (b) is the self-state-change push, which always fires on POST `/api/cosa-voice/speakerphone/{sid}`. User-scoped — only sent to the authenticated owner's sessions.

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
- `displaced` (optional). `true` when this session was forcibly deactivated because another session activated in solo mode
- `displaced_by` (optional). The session_id that displaced this one (only present when `displaced: true`)

Client handling:
- Legacy UI: `notifications.js::handleConversationModeChanged()` (line ~5552) — client-side maps `payload.on → conversation_mode_active` for the legacy in-memory state model. The legacy handler kept its original method name for callsite stability.
- Multiplexer UI: `src/lupin_app/static/js/multiplexer/stores/SenderStore.ts`. `STATE_UPDATE_TYPES` Set includes both `"speakerphone_changed"` (current wire) `AND` `"conversation_mode_changed"` (post-rename target, in case the type is ever re-renamed back). Reducer reads `payload.active ?? payload.on` to accept either field name. **Forward-compat bridge** — implementer can rename either direction without breaking the client. See `2026-05-19 Run 3 cascade Section D` for the Path iii bridge ratification rationale.

**INI subscription**: included in `lupin-app.ini` `websocket available events` (line 741). Subscribed by both legacy and multiplexer clients via the WS auth handshake.

**Server-side whitelist**: `src/cosa/rest/routers/notifications.py:359-364` `valid_types` list. The deprecated `conversation_mode_changed` is `NOT` in the list — pushing that type would return HTTP 400.

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

## Task Store Events

### `task_store_changed` (Server → Client)

Slices 1 to 3. An **invalidation**, not a delta: it says "the task store committed a change, re-read", and carries just enough to see what moved. Three panes re-read on it: Task List (`TaskListStore`), Holding Area (`HoldingAreaStore`) and Finished Tasks (`FinishedTasksStore`), each by waiting out a read already in flight. The 60-second poll stays as the safety net, so a missed frame costs a late refresh, never a wrong board.

**When**: once per database session that **commits** after appending one or more `TaskEvent` rows through `TaskRepository._append_event`. Three events in one commit are one frame. A rolled-back session emits nothing. Emitter: `src/cosa/rest/task_store_change_notifier.py`, wired in `lupin_app/main.py`.

**Payload** (the commit's **last** event, plus a count):
```json
{
  "type"       : "task_store_changed",
  "event_id"   : 48213,
  "item_id"    : "4288dd53-6779-460a-88bd-a7365fb734b2",
  "transition" : "queued->in_progress",
  "to_status"  : "in_progress",
  "ts"         : "2026-10-03T21:40:00+00:00",
  "count"      : 1
}
```
`to_status` is `null` for a label without `->` (`patched`, `amended`, `chased`).
The frame on the wire also carries a `timestamp` field, added to every event by `WebSocketManager`; the web client strips it.

**What the web client does with it**: each of the three stores waits out any read already in flight and then starts one more. So the read it shows began after the push. A burst of pushes shares that one read. The 60-second poll continues as the fallback.

**What the legacy page does with it** (slice 3): `notifications.js` carries the name in its queue-socket list (`_buildQueueAuthMessage`, never the audio one).
`_handleTaskStoreChanged` re-reads its task list through `_refreshTaskListAfterWrite`.
It re-reads its finished-tasks pane through `refreshFinishedTasks`. A pane whose 60-second poll was never started is left alone, and so is a task list whose poll was stopped. A push that lands during a finished-tasks read in flight is owed one more read when that read ends. A burst of pushes shares that one read.

**Subscribers**: any session subscribed to it (default `"*"`).
The web `QueueTransport` and the legacy `notifications.js` page subscribe.
**Not covered**: writers in a process that does not run the websocket manager emit nothing.
The `:8001` arbiter's straggler-ticket and follow-through writes are such writers. Their rows show up on the next poll. Delivery is to **all** connected sessions, like the unscoped task poll; scoping by role is an open design question.

---
