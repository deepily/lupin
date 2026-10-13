> Part 1 of 6 of the [WebSocket Event System Documentation](../websocket-events.md): catalog, job and audio events.

# WebSocket Event System Documentation

**Revised**: CC transcript console events added; stale event count removed
**Source of truth**: `lupin-app.ini` key `websocket available events`, `src/cosa/rest/routers/websocket.py`
**Status**: Active

## Event Catalog

The allow-list is the `websocket available events` key in `lupin-app.ini` (`src/conf/lupin-app.ini:1729`). And **that key is the only authority**. A name absent from it is dropped at subscribe time while auth still reports success (see `websocket_manager.py` `connect()`, and the in-place comment beside the validation). Clients subscribe to specific events (or `"*"` for all) during the auth handshake or via dynamic subscription updates.

**Count, and why this sentence no longer states one**. This document used to open "The system defines **22 events**". Which was wrong when last checked: the INI key listed **25**. `websocket-configuration.md` carries a third figure, an 18-name copy of the list. Three documents, three counts, and nothing reconciling them — so the count is not restated here, by choice.

Derive the list through the reader the server itself uses. And compare **set equality** against a committed literal. A count is the weakest possible assertion, since it passes just as happily if a name is misspelled:

```python
from cosa.config.configuration_manager import ConfigurationManager
names = ConfigurationManager().get( "websocket available events", return_type="list-string" )
```

Verified when last checked: **25 entries, 25 unique**. The four `cc_transcript_*` names below are **added to that key in the first build phase** of the console-tee feature, and are **not in it yet**.
The plan is `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`. They must be appended with `", "` exactly: the reader is a bare `value.split( ", " )` with no per-token strip. So a comma without a space mangles the new name *and* the one before it, silently. See [`websocket-architecture.md`](../websocket-architecture.md) § CC Transcript Console Channel.

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
| `task_store_changed` | Task store | Server → Client | No — broadcast to every connected session subscribed to it, via `emit` |
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

### The utterance id on a speech stream

A speech request (`POST /api/get-speech` or `POST /api/get-speech-elevenlabs`) may carry `utterance_id`: a string of 1 to 255 characters that the client picks, encodable as UTF-8. The key may be left out or sent as `null`. Any other value is refused with HTTP 400 and no stream starts.

When the request carried an id, the server echoes it unchanged:

- in the HTTP reply to the request;
- on every JSON frame that stream sends on the audio WebSocket: `audio_streaming_status`, `audio_streaming_complete`, `tts_error` and the stream's `error` frames.

When the request carried no id, none of those has the key, so the frames are what they were before.

Use it to tell which utterance a completion or an error belongs to. A completion from an abandoned stream can arrive after the client has started the next utterance. Two streams on one socket can also finish in either order. Compare the frame's `utterance_id` with the one the client is waiting on and ignore a frame that names another.

**Audio chunks carry no id.** A chunk is a bare binary frame with no envelope. The first `audio_streaming_status` of a stream arrives before its first chunk and names the utterance. That is enough while one stream at a time is open on the socket. If two streams are open at once their chunks interleave on the socket, and nothing in a chunk says which stream sent it.

Both browser clients send an id with every speech request. Each drops a complete or error frame that names another utterance. In the multiplexer the code is `wireTtsPlayback.ts` and `AudioStore.ts`. In `notifications.js` it is `nextUtteranceId` and `namesAnotherUtterance`.

The code is `read_utterance_id` and `stream_frame` in `src/cosa/rest/routers/speech.py`. The test that drives two overlapping streams through the assembled app is `src/tests/unit/test_overlapping_speech_streams_carry_their_own_utterance_id.py`.

### `audio_streaming_chunk`

An audio chunk during TTS streaming. The server sends it over the audio WebSocket (`/ws/audio/{session_id}`) as a **binary frame**: the bytes are the audio (MP3 from `/api/get-speech`, PCM 24000 from `/api/get-speech-elevenlabs`). There is no JSON envelope, so no `type` and no `utterance_id`. The name is a subscription name that clients list; no server code sends a JSON frame of this type.

### `audio_streaming_status`

Audio WebSocket connection and streaming status updates. Also the confirmation message when an audio WebSocket connects; that one frame belongs to no utterance and never has `utterance_id`.

**Payload** (a stream's status frame, for a request that carried `utterance_id`):
```json
{
  "type": "audio_streaming_status",
  "text": "Streaming audio from ElevenLabs...",
  "status": "streaming",
  "provider": "elevenlabs",
  "utterance_id": "utt-41"
}
```

`provider` is present on the ElevenLabs path only. `status` is `loading`, `streaming` or, on the connection confirmation, `success`.

### `audio_streaming_complete`

Signals that the server has sent every chunk of one stream. Client should finalize audio playback of the utterance the frame names.

**Payload**:
```json
{
  "type": "audio_streaming_complete",
  "text": "ElevenLabs streaming complete (12 chunks, 1.4s)",
  "status": "success",
  "provider": "elevenlabs",
  "utterance_id": "utt-41"
}
```

`provider` is present on the ElevenLabs path only. On that path the frame also follows a `tts_error`, so a completion does not by itself mean audio was sent.

### `tts_error`

The ElevenLabs stream failed. Sent on the audio WebSocket by `/api/get-speech-elevenlabs` only. It is not in the `websocket available events` key.

**Payload**:
```json
{
  "type": "tts_error",
  "text": "ElevenLabs quota exceeded. TTS unavailable until reset.",
  "error_code": "quota_exceeded",
  "status": "error",
  "provider": "elevenlabs",
  "details": "quota_exceeded: ...",
  "utterance_id": "utt-41"
}
```

`error_code` is `quota_exceeded`, `rate_limit`, `auth_error` or `unknown`. The simulated error (`debug_simulate_error` in the request) sends no `error_code`.

**Note**: Audio WebSockets have a **fixed subscription set**: `audio_streaming_status`, `audio_streaming_complete`, `sys_ping`. This is hardcoded in the router, not client-configurable.

---
