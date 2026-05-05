// Multiplexer Phase 2 — shared TypeScript interfaces.
// Foundation types consumed by EventBus, StorageService, AuthManager, ApiClient, broadcast.
// Phase 3 appends transport_* / connection_* / lifecycle types.
// Phase 4 appends server frame types consumed by stores + store_* emission types
//        + Notification / Job / SenderRecord / ActionRequiredItem / AudioPlaybackState
//        + BootCompletePayload (per D-C ratification).

// ---------------------------------------------------------------------------
// LupinEventType — string-literal union (hybrid policy per Phase 2 OQ3).
// Phase 2 emissions + BroadcastChannel whitelist references.
// Phase 3+ phases append transport_* / connection_* / lifecycle types.
// Phase 4 appends server frame types (`notification_queue_update`,
// `notification_responded`, `notification_expired`, `job_state_transition`,
// `job_removed`, `sys_time_update`) + store emission types
// (`store_notifications_changed`, `store_jobs_changed`,
// `store_audio_state_change`, `store_audio_chunk_decoded`,
// `store_action_required_changed`, `store_senders_changed`) + boot signal
// (`boot_complete` per D-C ratification).
// Test code may cast: bus.emit({type: "fake_event" as LupinEventType, ...}).
// ---------------------------------------------------------------------------

export type LupinEventType =
  // AuthManager (Phase 2)
  | "auth_state_change"
  | "refresh_started"
  | "refresh_completed"
  | "refresh_failed"
  // StorageService (Phase 2)
  | "storage_corrupt"
  // EventBus (Phase 2)
  | "listener_error"
  // BroadcastChannel whitelist references (Phase 2 — emitted by Phase 3+
  // transport; declared here so the static whitelist set is type-checked).
  // `notification_received` retained as a compile-time literal for the
  // BROADCAST_WHITELIST set even though Phase 4 stores subscribe to the
  // server-canonical `notification_queue_update` instead. See execution log
  // Phase 4 § "Spec drifts re-audited at execute time" for the wire-vs-design
  // mismatch.
  | "notification_received"
  | "voice_persona_assigned"
  | "voice_persona_released"
  | "conversation_mode_change"
  // ConnectionStateMachine (Phase 3)
  | "connection_state_change"
  | "connection_reconnecting"
  | "connection_offline"
  | "connection_online"
  // Transport wrappers (Phase 3)
  | "transport_ready"
  // boot.ts Lifecycle Emission Contract (Phase 3, per design § "boot.ts
  // Lifecycle Event Emission Contract")
  | "page_hidden"
  | "page_visible"
  | "network_online"
  | "network_offline"
  // Server-frame handshake signal (Phase 3 wrappers wait for this on first
  // text frame post socket_open). The wrapper emits this through unchanged
  // when the server sends it.
  | "auth_success"
  // Server frames consumed by Phase 4 stores (Phase 3 QueueTransport
  // pre-subscribes via QUEUE_SUBSCRIBED_EVENTS; Phase 4 stores subscribe via
  // EventBus.on). `notification_queue_update` is the server-canonical event
  // for new-notification arrival + queue-resync; the discriminator is the
  // presence of `payload.notification`.
  | "notification_queue_update"
  | "notification_responded"
  | "notification_expired"
  | "job_state_transition"
  | "job_removed"
  | "sys_time_update"
  // Phase 4 store emissions — each store emits exactly one type per state
  // mutation; renderers subscribe by store. Payloads carry a `changeKind`
  // discriminator so renderers can fast-path-decide what to repaint.
  | "store_notifications_changed"
  | "store_jobs_changed"
  | "store_audio_state_change"
  | "store_audio_chunk_decoded"
  | "store_action_required_changed"
  | "store_senders_changed"
  // boot.ts one-shot signal (Phase 4 per D-C ratification 2026-05-04 PM).
  // Emitted at end of bootMultiplexer() with the resolved binary handler
  // identity so AC9's Playwright check can verify the wiring without the
  // no-globals-violation `window.audioTransport.binaryHandler` access path.
  | "boot_complete";

// ---------------------------------------------------------------------------
// LupinEvent envelope — the canonical pub/sub shape.
// ---------------------------------------------------------------------------

export interface LupinEvent<T = unknown> {
  type    : LupinEventType;
  payload : T;
  source  : string;   // module name emitting the event ("AuthManager", "broadcast", etc.)
  ts      : number;   // ms epoch
}

// ---------------------------------------------------------------------------
// Auth types — token shape + state machine states.
// ---------------------------------------------------------------------------

export interface Token {
  accessToken  : string;
  refreshToken : string;
  expiresAt    : number;   // ms epoch
}

export type AuthState = "idle" | "ready" | "refreshing" | "expired";

export interface AuthStateChangePayload {
  state : AuthState;
}

export interface RefreshStartedPayload {
  reason : "expired" | "invalidated";
}

export interface RefreshCompletedPayload {
  expiresAt : number;
}

export interface RefreshFailedPayload {
  error     : string;
  willRetry : boolean;
}

// ---------------------------------------------------------------------------
// StorageService — typed JSON envelope.
// ---------------------------------------------------------------------------

export interface StorageEnvelope<T> {
  schemaVersion : number;
  payload       : T;
  ts            : number;   // ms epoch
}

export interface SessionIdEnvelope {
  sessionId   : string;     // server-generated "adjective noun" form per existing convention
  generatedAt : number;     // ms epoch
}

export interface StorageCorruptPayload {
  key   : string;
  error : string;
}

// ---------------------------------------------------------------------------
// EventBus — listener_error payload references the original event opaquely.
// ---------------------------------------------------------------------------

export interface ListenerErrorPayload {
  originalEvent : LupinEvent<unknown>;
  error         : string;
}

// ---------------------------------------------------------------------------
// ConnectionStateMachine (Phase 3) — connection lifecycle states + payloads.
// ---------------------------------------------------------------------------

export type ConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "backoff"
  | "offline"
  | "failed";

export interface ConnectionStateChangePayload {
  state     : ConnectionState;
  prev      : ConnectionState;
  attempts  : number;
  // Per-transport identification — multiple CSMs share the
  // `source: "ConnectionStateMachine"` event source, so consumers filter
  // by `payload.transport` (e.g. "QueueTransport", "AudioTransport").
  transport : string;
}

export interface ConnectionReconnectingPayload {
  attempts  : number;
  transport : string;
}

export interface ConnectionLifecyclePayload {
  ts        : number;
  transport : string;
}

// ---------------------------------------------------------------------------
// Transport wrappers (Phase 3) — emitted after auth_success arrives.
// ---------------------------------------------------------------------------

export interface TransportReadyPayload {
  // Transport name: "QueueTransport" / "AudioTransport".
  // Mirrors the LupinEvent.source field for the same emission so consumers
  // can subscribe to "transport_ready" and dispatch by `payload.transport`.
  transport : string;
}

// ---------------------------------------------------------------------------
// boot.ts Lifecycle Emission Contract payloads (Phase 3 design § contract).
// page_hidden / page_visible / network_online / network_offline all carry
// `{ ts }`. page_visible from a bfcache restore additionally carries
// `bfcache: true`.
// ---------------------------------------------------------------------------

export interface LifecyclePayload {
  ts       : number;
  bfcache? : true;
}

// ---------------------------------------------------------------------------
// Phase 4 — Voice persona shape (per D-E ratification 2026-05-04 PM —
// matches legacy `senderPersonaMap` shape at `notifications.js:128`).
// Phase 6 TTS routing consumes `voice_id` (legacy `getVoiceIdForSender:9000`).
// ---------------------------------------------------------------------------

export interface VoicePersona {
  name     : string;   // human-readable persona name (e.g., "Tiberius")
  voice_id : string;   // ElevenLabs voice_id — Phase 6 TTS routing input
  icon     : string;   // emoji or icon ID for sender card display
  color    : string;   // hex color for sender card badge / mic-monopoly pin
  borrowed : boolean;  // true if persona is borrowed from another sender
}

// ---------------------------------------------------------------------------
// Phase 4 — Notification interface (per design § NotificationStore).
//
// Field source: server-canonical via `notification_queue_update` (Phase 3
// QueueTransport receives, store normalizes). Per execution log spec drift:
// server emits `timestamp` (ISO string) → normalized to `ts` (ms epoch);
// server emits `response_requested` (boolean) → normalized to
// `action_required` (boolean). Server fields not consumed by stores
// (`abstract`, `priority`, `notification_type`, `voice_persona`, `job_id`,
// `progress_group_id`) are preserved on the raw envelope but not surfaced
// here — Phase 5 renderer can reach back into the original payload if needed.
// ---------------------------------------------------------------------------

export interface Notification {
  id_hash         : string;
  ts              : number;          // ms epoch (normalized from server `timestamp` ISO string)
  sender_id       : string;
  message         : string;
  title?          : string;
  action_required : boolean;          // normalized from server `response_requested`
  expires_at?     : number;           // ms epoch — present for action-required prompts only
  responded?      : boolean;
  // Optional fields surfaced for action-required prompts (per Pass 1 F17).
  response_type?  : "yes_no" | "multiple_choice" | "open_ended" | "open_ended_batch";
  options?        : ReadonlyArray<string>;   // valid choices for multiple_choice; ["yes","no"] for yes_no
  default_value?  : string;          // returned on local expiry without POST
}

export type NotificationChangeKind =
  | "added"
  | "updated"
  | "expired"
  | "removed"
  | "hydrated";

export interface StoreNotificationsChangedPayload {
  changeKind : NotificationChangeKind;
  id_hash?   : string;                // present except for "hydrated"
  source?    : "local-sweep";          // present when local expiry sweep triggered the change
}

// ---------------------------------------------------------------------------
// Phase 4 — Job interface (per design § JobStore + cj-flow JobState in
// `running_fifo_queue.py:1024, :147`).
// ---------------------------------------------------------------------------

export type JobStatus = "todo" | "running" | "done" | "dead";
export type JobBucket = JobStatus | "history";

export interface Job {
  id_hash      : string;
  job_type     : string;
  status       : JobStatus;
  created_at   : number;
  started_at?  : number;
  completed_at?: number;
  meta         : Record<string, unknown>;
}

export type JobChangeKind = "added" | "transitioned" | "removed" | "hydrated";

export interface StoreJobsChangedPayload {
  changeKind : JobChangeKind;
  id_hash?   : string;
  from?      : JobBucket;     // present on "transitioned"
  to?        : JobBucket;     // present on "transitioned"
  bucket?    : JobBucket;     // present on "hydrated"
}

// ---------------------------------------------------------------------------
// Phase 4 — SenderRecord (per design § SenderStore + D-E ratification full
// 5-field voice_persona shape).
// ---------------------------------------------------------------------------

export interface SenderRecord {
  sender_id      : string;
  display_name   : string;
  last_active_ts : number;
  unread_count   : number;
  voice_persona? : VoicePersona;
}

export type SenderChangeKind = "added" | "updated" | "removed";

export interface StoreSendersChangedPayload {
  changeKind : SenderChangeKind;
  sender_id  : string;
}

// ---------------------------------------------------------------------------
// Phase 4 — ActionRequiredItem (per design § ActionRequiredStore + Pass 1 F17
// `response_type` field). One actor per active prompt.
// ---------------------------------------------------------------------------

export type ActionRequiredState = "pending" | "responded" | "expired" | "cancelled";

export interface ActionRequiredItem {
  id_hash       : string;
  prompt        : string;
  response_type : "yes_no" | "multiple_choice" | "open_ended" | "open_ended_batch";
  options       : ReadonlyArray<string>;
  default?      : string;
  expires_at    : number;            // ms epoch
  state         : ActionRequiredState;
  response?     : string;             // populated on respond
}

export type ActionRequiredChangeKind =
  | "added"
  | "tick"               // countdown tick (1Hz UX update; UI repaints countdown)
  | "responded"
  | "expired"
  | "cancelled"
  | "offline-frozen"
  | "offline-resumed";

export interface StoreActionRequiredChangedPayload {
  changeKind   : ActionRequiredChangeKind;
  id_hash      : string;
  countdownMs? : number;              // remaining ms; present on "tick" + "offline-frozen"
}

// ---------------------------------------------------------------------------
// Phase 4 — Audio playback state (per design § AudioStore XState).
// ---------------------------------------------------------------------------

export type AudioPlaybackState = "idle" | "decoding" | "playing" | "paused" | "ended" | "error";

export interface StoreAudioStateChangePayload {
  state    : AudioPlaybackState;
  prev     : AudioPlaybackState;
  reason?  : string;     // e.g. "audiocontext-blocked" / "decode-failed" / "out-of-frames"
}

export interface StoreAudioChunkDecodedPayload {
  // ms duration of the decoded chunk (informational; renderer may show it).
  durationMs : number;
  // sample rate the buffer was decoded at (24000 in production per D-A).
  sampleRate : number;
  // frame count in the decoded buffer.
  frameCount : number;
}

// ---------------------------------------------------------------------------
// Phase 4 — boot.ts boot_complete payload (D-C ratification 2026-05-04 PM).
//
// Emitted once at end of bootMultiplexer() with the resolved binary handler
// identity. AC9's Playwright check subscribes via `page.on("console", ...)`
// and asserts `payload.handlers.audioBinary === "audioStoreBinaryHandler"`
// (NOT the Phase 3 default-debug-logger name).
//
// `Function.name` source — the AudioStore exposes `binaryHandler` as a
// readonly bound function whose underlying definition is named
// `audioStoreBinaryHandler` per the design doc § AudioStore implementation
// snippet.
// ---------------------------------------------------------------------------

export interface BootCompletePayload {
  handlers : {
    audioBinary : string;   // Function.name of the bound binary handler
  };
}
