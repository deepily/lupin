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
  | "speakerphone_change"
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
  // WP2 (multiplexer parity bridge, 2026-06-10) — SessionStripStore emission.
  // The CC-session strip is a distinct subsystem from SenderStore: it reduces
  // the SAME `notification_queue_update` state-update branch but captures the
  // two fields SenderStore drops (`manager_persona` for the lineage badge,
  // `assigned_at` for chronological icon ordering) plus an `active` flag.
  // Multiple stores over one wire event is the established pattern (see
  // NotificationStore + SenderStore both consuming notification_queue_update).
  // See: src/rnd/v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/02-bridging-work-plan.md (WP2)
  | "store_session_strip_changed"
  // WP4 (multiplexer-parity Reading Pane, 2026-06-10) — ReadingPaneStore emits
  // this on every pane-state mutation (open/close/back/layout-mode/ratio/AR-pane
  // enter+exit/hydrate). ReadingPaneRenderer subscribes and repaints the pane
  // DOM. Ports the legacy `notifications.js` master-detail behavior (commits
  // cd6cc99, 9211e5c, 97bfb8c, e1ed26a, 498e98e) into the store/renderer split.
  | "store_reading_pane_changed"
  // Lane D (commons activity panel — WP3, 2026-06-10): CommonsStore emits this
  // on every mutation (hydrate / live-prepend / filter-change). The renderer
  // subscribes and repaints the filtered entry list. Carries a `changeKind`
  // discriminator. Note there is NO top-level `commons_activity` event: the
  // server delivers commons rows INSIDE `notification_queue_update`
  // (`payload.notification.type === "commons_activity"`), so CommonsStore
  // subscribes to `notification_queue_update` exactly like NotificationStore.
  | "store_commons_changed"
  // boot.ts one-shot signal (Phase 4 per D-C ratification 2026-05-04 PM).
  // Emitted at end of bootMultiplexer() with the resolved binary handler
  // identity so AC9's Playwright check can verify the wiring without the
  // no-globals-violation `window.audioTransport.binaryHandler` access path.
  | "boot_complete"
  // Phase 6a (per design doc 08 § JobsPaneRenderer Pass 1 F3): emitted by a
  // renderer when its async hydrate path rejects. Carries `source` to
  // discriminate (e.g. `source: "jobs"` for JobsPaneRenderer's hydrateHistory
  // failure). Subscribers (deferred to 6b) can paint a "Could not load
  // history" retry affordance.
  | "hydration_failed"
  // Lane E full-parity sprint (2026-06-10) — self-contained quartet store
  // emissions. Each store emits exactly one type per state mutation; its
  // renderer subscribes by store.
  // WP15 (F7): MissedStore emits when the "N missed while away" count changes
  //   (auth_success surfacing OR Reset dismiss).
  | "store_missed_changed"
  // WP14 (F8): PredictionVoteStore emits when a vote is cast / cleared for a
  //   prediction-hint notification.
  | "store_prediction_vote_changed"
  // WP12 (F12): FleetStatusStore emits when a fleet-state poll resolves
  //   (success, unreachable, or error) or the live-only/offline toggle flips.
  | "store_fleet_status_changed"
  // Step 4 (task-list card): TaskListStore emits when a `/api/tasks` poll
  //   resolves (success, unreachable, or 401).
  | "store_task_list_changed";

// ---------------------------------------------------------------------------
// LupinEvent envelope — the canonical pub/sub shape.
// ---------------------------------------------------------------------------

export interface LupinEvent<T = unknown> {
  type    : LupinEventType;
  payload : T;
  source  : string;   // module name emitting the event ("AuthManager", "broadcast", etc.)
  ts      : number;   // ms epoch
}

// Wire shape of a server WebSocket frame on /ws/queue (and /ws/audio). The
// server (websocket_manager.py broadcast_event / emit_to_session) builds frames
// FLAT — `{ type, timestamp, ...data }` — spreading the event's `data` dict at
// the TOP level; there is NO nested `data` key. auth_success is likewise flat
// (`{ type, user_id, session_id, undelivered_count }`, no `timestamp`).
// QueueTransport.onMessage maps this to a LupinEvent by lifting `type` and
// dropping the envelope keys (`type` + `timestamp`); the remaining keys become
// the event `payload` (i.e. the server's `data` dict), which is what every store
// reads. This is the single client-side frame-shape contract (WP0 flat-frame
// fix) — no per-event server `data`-mirroring.
export interface ServerFrameEnvelope {
  type       : string;
  timestamp? : string;            // present on broadcast frames, absent on auth_success
  [dataKey: string]: unknown;     // spread `**data` — becomes the LupinEvent payload
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
  // Present ONLY on a transition into `failed` via a permanent-auth close
  // (server close code 4001/4002/4003). `reason` is "auth-permanent" and
  // `code` is the WebSocket close code, so the cutover consumer can route
  // 4001 → token-refresh, 4002 → session-displaced, 4003 → permission-denied
  // (parity with legacy ws-channel.js CIRCUIT_OPEN_EVENT.detail). Absent on
  // every other transition (incl. budget-exhausted `failed`).
  reason?   : string;
  code?     : number;
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
// `action_required` (boolean). Server fields `priority`, `notification_type`,
// and `job_id` remain preserved-on-the-raw-envelope-only (renderer reaches
// back if needed).
//
// Phase 5 D-B (2026-05-05) extension: five additional optional fields below
// — `voice_persona`, `abstract`, `progress_group_id`, `was_expired`,
// `time_display` — promoted from raw-envelope to typed surface so the
// renderer can consume them through the store API rather than reaching into
// raw payload (per `92-phase5-review-findings.md` D-B). NotificationStore
// `normalize()` copies each through when present.
// ---------------------------------------------------------------------------

// WP14 (F8) — prediction-hint payload riding on a notification. The server
// stamps a hint (CBR/LLM prediction of how the user will answer) onto the
// notification frame; NotificationStore.normalize() copies it through, and the
// notification-item render path mounts the thumbs-vote controls when the hint's
// confidence clears PREDICTION_VOTE_MIN_PCT. `response_type` (the kind of
// answer predicted) already rides on Notification above. `predicted_value` is
// echoed back verbatim at vote-POST time (the server does not persist the hint,
// so the client supplies what was voted on — parity with legacy notifications.js
// `_predictionVoteContext`).
export interface PredictionHint {
  confidence      : number;     // 0.0–1.0; ×100 → percent for the gate + display
  predicted_value : unknown;    // echoed back on vote (opaque to the renderer)
  category        : string;     // training-signal bucket (echoed back on vote)
}

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
  prediction_hint?: PredictionHint;  // WP14 (F8) — thumbs-vote training-signal source
  // Phase 5 D-B (2026-05-05) — renderer-surfaced fields.
  voice_persona?    : VoicePersona;   // per-sender persona for --persona-color CSS var
  abstract?         : string;         // detailed description; surfaced via 📋 indicator
  progress_group_id?: string;         // groups messages with history accordion (Q-G)
  was_expired?      : boolean;        // true → renders EXPIRED badge on sender-message
  time_display?     : string;         // backend-provided "HH:MM TZ" override
  // WS2 / C2-d (D3 — Rick 2026-06-20): chat-bubble direction. Absent/"incoming"
  // → inbound persona message (.sender-message.incoming); "outgoing" → the
  // user's response, rendered .sender-message.outgoing. Set by the responded-
  // split (load-time: NotificationStore.hydrateHistory; harness: toMuxModel),
  // which expands one responded notification into an incoming prompt + a
  // synthetic `{id}-response` outgoing reply (mirrors legacy notifications.js).
  direction?        : "incoming" | "outgoing";
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
//
// Phase 6c Node D (Step D1 — 2026-05-19): added `conversation_mode_active`
// (boolean) per Q-D1 Path A ratification. Drives the conversation-mode pin
// renderer's `data-pinned-conv-mode` attribute on the sender card. The
// `mic_monopoly` field originally proposed alongside this one was DEFERRED
// per Path δ ratification (Rick, 2026-05-19) — see TODO.md "Phase 6c
// follow-on: mic-monopoly indicator" for the system-wide-semantic question
// that resolves before re-scoping.
// ---------------------------------------------------------------------------

export interface SenderRecord {
  sender_id                : string;
  display_name             : string;
  last_active_ts           : number;
  unread_count             : number;
  conversation_mode_active : boolean;
  voice_persona?           : VoicePersona;
}

export type SenderChangeKind = "added" | "updated" | "removed" | "hydrated";

export interface StoreSendersChangedPayload {
  changeKind : SenderChangeKind;
  // Present for added/updated/removed; OMITTED for "hydrated" (cold-load bulk
  // seed emits a single change for the whole snapshot — consumers reconcile
  // from store.list() rather than a single id). Mirrors
  // StoreSessionStripChangedPayload's contract below.
  sender_id? : string;
}

// ---------------------------------------------------------------------------
// WP2 (multiplexer parity bridge, 2026-06-10) — CC-session strip types.
//
// The CC-session strip is the always-on horizontal row of per-session persona
// icons in the legacy `notifications.js` client (the `#cc-session-strip`
// surface). It is NET-NEW to the multiplexer — the existing FocusTrayRenderer
// is a separate, interim focus affordance. WP2 ports the strip as a dedicated
// SessionStripStore + SessionStripRenderer.
//
// `ManagerPersona` — the lineage badge data (WP9 / legacy F11). Stamped on the
// strip icon's top-left corner ("spawned by <manager>"). The renderer derives
// the displayed initial from `name` (one uppercase char), matching how the
// icon derives its own initial from the session persona name.
// ---------------------------------------------------------------------------

export interface ManagerPersona {
  name  : string;   // manager persona name (e.g., "Tiberius") — initial derived from this
  icon  : string;   // emoji or icon id
  color : string;   // hex color for the lineage badge background
}

// One CC-session strip icon's backing model. Keyed by `sender_id` in the
// store map. `voice_persona` is RETAINED after `voice_persona_released`
// (active flips false) so the icon stays visible-but-inactive, exactly like
// the legacy `senderPersonaMap`-membership inactivity model
// (`notifications.js:_isStripIconInactive`). `session_reaped` removes the
// record outright.
export interface StripSession {
  sender_id        : string;
  voice_persona    : VoicePersona;
  manager_persona? : ManagerPersona;
  assigned_at      : number;    // ms epoch — chronological anchor for icon ordering
  active           : boolean;   // false after voice_persona_released; hide-inactive filter targets !active
}

export type SessionStripChangeKind = "added" | "updated" | "removed" | "hydrated";

export interface StoreSessionStripChangedPayload {
  changeKind : SessionStripChangeKind;
  // Present for added/updated/removed; OMITTED for "hydrated" (WP9 cold-reload
  // bulk load emits a single change for a whole snapshot — the renderer
  // reconciles from store.list() rather than a single id).
  sender_id? : string;
}

// Phase 6c Node D Step D3 (per F-Arnold-D3 — sender-level signature, NOT
// entry-level): NotificationsListRenderer accepts an optional sort comparator
// at construction so consumers (boot.ts wires Phase 6c override here) can
// hoist conversation-mode-pinned senders above the activity-based default.
// Default behavior (no opts override): `(a, b) => b.last_active_ts -
// a.last_active_ts` — preserves Phase 5 sort order.
//
// Phase 6c override (injected at boot per Step D5):
//   `(a, b) => Number(b.conversation_mode_active) -
//              Number(a.conversation_mode_active)
//          || b.last_active_ts - a.last_active_ts`
//
// The signature is `(a, b) => number` exactly like `Array.prototype.sort`;
// callers don't need to know about entry-wrapping.
export type SenderSortComparator = ( a: SenderRecord, b: SenderRecord ) => number;

// ---------------------------------------------------------------------------
// Phase 4 — ActionRequiredItem (per design § ActionRequiredStore + Pass 1 F17
// `response_type` field). One actor per active prompt.
// ---------------------------------------------------------------------------

export type ActionRequiredState =
  | "pending"
  | "submitting"     // Phase 6b — non-optimistic respondAndAwait() in flight (per Pass 2 A1)
  | "responded"
  | "failed"         // Phase 6b — respondAndAwait() POST rejected; user may retry (per Pass 2 A1)
  | "expired"
  | "cancelled";

// Phase 6b — widened response shape (per Pass 2 A2). Wire-side:
//   - string                       : single answer (yes_no, single-select multiple_choice, open_ended)
//   - ReadonlyArray<string>        : multi-select multiple_choice (multiSelect: true)
//   - Record<string, string>       : open_ended_batch (per-question header → answer)
// `response_value: { response: <this shape> }` on the wire.
export type ActionRequiredResponse = string | ReadonlyArray<string> | Record<string, string>;

export interface ActionRequiredItem {
  id_hash       : string;
  prompt        : string;
  response_type : "yes_no" | "multiple_choice" | "open_ended" | "open_ended_batch";
  options       : ReadonlyArray<string>;
  default?      : string;
  expires_at    : number;            // ms epoch
  state         : ActionRequiredState;
  response?     : ActionRequiredResponse;   // Phase 6b — widened from string per Pass 2 A2
  multiSelect?  : boolean;                  // Phase 6b — multiple_choice dispatch (radio if false/undefined, checkbox if true). Wire-side population is Phase 0 prereq #2 (verification pending).
}

export type ActionRequiredChangeKind =
  | "added"
  | "tick"                  // countdown tick (1Hz UX update; UI repaints countdown)
  | "responded-pending"     // Phase 6b — respondAndAwait() POST in flight (per Pass 2 A1)
  | "responded"
  | "failed"                // Phase 6b — respondAndAwait() POST rejected (per Pass 2 A1)
  | "expired"
  | "cancelled"
  | "offline-frozen"
  | "offline-resumed";

export interface StoreActionRequiredChangedPayload {
  changeKind   : ActionRequiredChangeKind;
  id_hash      : string;
  countdownMs? : number;                          // remaining ms; present on "tick" + "offline-frozen"
  response?    : ActionRequiredResponse;          // Phase 6b — present on "responded-pending" / "responded" (respondAndAwait path) / "failed"
  error?       : unknown;                         // Phase 6b — present on "failed"
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
    audioBinary            : string;   // Function.name of the bound binary handler
    // Phase 5 RE-16 + F22 extension (2026-05-05): literal string "mounted"
    // emitted after `renderer.mount(mountEl)` completes. NOT a function-name
    // introspection — fixed contract surface for AC9's Playwright check
    // (`payload.handlers.notificationsRenderer === "mounted"`). Optional so
    // intermediate boot states (mount throws, future no-renderer surfaces)
    // remain typed correctly; production wiring populates it unconditionally.
    notificationsRenderer? : string;
    // Phase 6a F11+F12 extension (2026-05-06): literal string "mounted" emitted
    // after `jobsRenderer.mount(mountEl)` completes. Optional in TS interface
    // (forward/backward-compat per F12); runtime-unconditional in current
    // boot.ts (per F11) — if mount throws, `boot_complete` is never emitted.
    jobsRenderer?          : string;
    // Phase 6b F11+F12 extension (2026-05-12): literal string "mounted" emitted
    // after each new renderer's `mount(root)` completes. Optional per F12 +
    // runtime-unconditional per F11 — boot.ts populates both unconditionally
    // once the renderer mounts land in the boot sequence (Pass 2 A7/A8 order:
    // notifications → jobs → actionRequired → ttsChrome, transports LAST).
    // AC9 grep guard asserts the canonical 4-line console-mount order.
    actionRequiredRenderer? : string;
    ttsChromeRenderer?      : string;
    // Phase 6c Node D Step D5 (2026-05-19): literal string "mounted" emitted
    // after `conversationModePinRenderer.mount(root)` completes. Optional per
    // the Phase 6a F12 forward/backward-compat pattern + runtime-unconditional
    // per Phase 6a F11 — boot.ts populates unconditionally once Node D's
    // renderer mount lands in the boot sequence. AC-D11 boot handshake smoke
    // asserts the canonical 5-line console-mount order (with this 5th line
    // appended after ttsChromeRenderer).
    conversationModePinRenderer? : string;
    // Phase 6c Node A Step A5 (2026-05-19): literal string "mounted" emitted
    // after `personaModalRenderer.mount(root)` completes. Seventh line in
    // the canonical boot handshake (...conversationModePin → focusTray →
    // personaModal); AC-A11 boot handshake smoke asserts this position.
    personaModalRenderer?        : string;
    // Phase 6c Node C Step C5 (2026-05-19): literal string "mounted" emitted
    // after `senderCardRecorderRenderer.mount(root)` completes. Eighth line
    // in the canonical boot handshake; AC-C11 boot handshake smoke asserts
    // this position.
    senderCardRecorderRenderer?  : string;
    // WP2 (parity bridge, 2026-06-10): literal string "mounted" emitted after
    // `sessionStripRenderer.mount(root)` completes. Appended at the NEW-LANE
    // MOUNT SLOT (after the Phase 5/6 mounts), so it follows
    // senderCardRecorderRenderer in the console handshake order.
    sessionStripRenderer?        : string;
    // WP4 (Lane C, 2026-06-10): literal "mounted" emitted after
    // `readingPaneRenderer.mount(.content-shell)` completes — appended at the
    // NEW-LANE MOUNT SLOT (after the Phase 5/6 mounts, before transports start).
    readingPaneRenderer?         : string;
    // Lane D (WP3, 2026-06-10): literal "mounted" emitted after the commons
    // activity renderer mounts at the NEW-LANE MOUNT SLOT. Optional per the
    // Phase 6a forward/backward-compat pattern.
    commonsActivityRenderer?     : string;
    // Lane E full-parity quartet (2026-06-10): literal "mounted" per renderer,
    // appended at the NEW-LANE MOUNT SLOT after the Phase 6c mounts. Optional
    // (Phase 6a F12 forward/backward-compat) + runtime-unconditional (F11).
    ttsPreviewSliderRenderer?    : string;
    missedBadgeRenderer?         : string;
    fleetStatusRenderer?         : string;
    // Step 4 (store-canonical task mgmt, 2026-06-16): literal "mounted" emitted
    // after the task-list card mounts. Optional per the same forward/backward-
    // compat pattern + runtime-unconditional in boot.ts.
    taskListRenderer?            : string;
  };
}

// ---------------------------------------------------------------------------
// Phase 6a — hydration_failed payload (per design doc 08 § JobsPaneRenderer
// hydration error path; emitted by JobsPaneRenderer when hydrateHistory(api)
// rejects).
// ---------------------------------------------------------------------------

export interface HydrationFailedPayload {
  /** Discriminator: which renderer's hydrate path rejected (e.g. "jobs"). */
  source : string;
  /** The Error that caused the rejection. */
  error  : Error;
}

// ---------------------------------------------------------------------------
// WP4 — Master-Detail Reading Pane (multiplexer parity, 2026-06-10).
//
// Ports the legacy `notifications.js` master-detail two-pane layout into the
// multiplexer's store/renderer split. ReadingPaneStore owns the pure logical
// state (layout mode, history stack, split ratio, action-required-in-pane
// flag); ReadingPaneRenderer owns all DOM (iframe embedding, scroll-anchor
// preservation, splitter drag, toolbar centering). Legacy source of truth:
// `notifications.js:10889-11496` + state init `:181-205`, `:295-300`.
// ---------------------------------------------------------------------------

/** Horizontal = master-detail two-pane; vertical = legacy single column. */
export type LayoutMode = "vertical" | "horizontal";

/**
 * A single Reading-Pane history entry.
 *   - "abstract" → `payload` is markdown text (rendered via renderMarkdown)
 *   - "doc"      → `payload` is a `/app/docs?path=…` href (embedded in iframe)
 */
export interface ContentPaneEntry {
  type    : "abstract" | "doc";
  payload : string;
  title   : string;
}

export type ReadingPaneChangeKind =
  | "opened"        // open(): pushed a new entry; pane now shows it
  | "closed"        // close(): history cleared, pane hidden
  | "back"          // back(): popped one entry, pane shows the prior one
  | "layout-mode"   // toggleLayoutMode(): vertical ⇄ horizontal
  | "ratio"         // setSplitRatio(): divider moved
  | "ar-enter"      // enterActionRequiredPane(): AR widget lifted into pane @50/50
  | "ar-exit";      // exitActionRequiredPane(): AR widget restored to home

export interface StoreReadingPaneChangedPayload {
  changeKind : ReadingPaneChangeKind;
}

// ---------------------------------------------------------------------------
// Lane D — Commons "Recent Activity" panel (WP3, 2026-06-10).
//
// One projected commons entry. The shape is byte-identical between the REST
// aggregator (`execute_broadcast_history` → `_project_history_entry`,
// `src/cosa/rest/routers/commons.py:600`) and the live WS push
// (`_dispatch_activity_event`, `src/cosa/rest/commons_activity_watcher.py:313`),
// so one interface covers both the initial load and the live-prepend path.
//
// `ts` is an ISO-8601 string (UTC) as emitted server-side; the renderer
// formats it to local HH:MM. All persona fields are nullable because reserved
// topics / system rows may omit them.
// ---------------------------------------------------------------------------

export interface CommonsActivityEntry {
  ts                ?: string | null;   // ISO-8601 (UTC); may be absent on malformed rows
  topic              : string;
  topic_kind         : "reserved" | "free-form";
  sender_session_id ?: string | null;
  persona_name      ?: string | null;
  persona_icon      ?: string | null;
  persona_color     ?: string | null;
  body              ?: string | null;
  metadata          ?: Record<string, unknown>;
}

// Time-window selector for the panel. "today" resolves client-side to
// hours-since-local-midnight; "all" applies no cutoff; numeric strings ("1",
// "6", "24", …) are passed through as an `hours` query param. Mirrors the
// legacy dropdown semantics (`notifications.js:10685-10697`).
export type CommonsActivityWindow = string;

// 3-axis filter (per `2026.05.21-recent-activity-filter-and-focus-bar-...md`).
// Each axis at its default contributes no constraint.
export type CommonsActivityDirection = "sender" | "recipient" | null;
export type CommonsActivityKind = "all" | "heartbeats" | "personas" | "broadcasts";

export interface CommonsActivityFilter {
  direction : CommonsActivityDirection;
  kind      : CommonsActivityKind;
  persona   : string | null;   // lowercased persona name; null = "any"
}

export type CommonsChangeKind =
  | "hydrated"      // full reload from REST (window change / refresh / initial)
  | "prepended"     // single live WS entry added to the head
  | "filter-changed"; // filter axis mutated — re-render from cache, no fetch

export interface StoreCommonsChangedPayload {
  changeKind : CommonsChangeKind;
  // Present on "prepended" — true when the live entry passes the active filter
  // (so the renderer can prepend a single row instead of a full re-render).
  matchesFilter? : boolean;
}

// ---------------------------------------------------------------------------
// Lane E full-parity sprint (2026-06-10) — quartet store payloads.
// ---------------------------------------------------------------------------

// WP15 (F7) — MissedStore. Surfaces the "N missed while away" count from
// auth_success.undelivered_count and the Reset (soft-dismiss) round-trip.
export interface StoreMissedChangedPayload {
  count : number;   // non-negative integer; 0 hides the badge + Reset button
}

// WP14 (F8) — PredictionVoteStore. Thumbs up/down training signal on a
// prediction hint (up = reinforce, down = steer away). Emitted after a vote
// is recorded server-side so the controls highlight the cast direction.
export type PredictionVoteDir = "up" | "down";

export interface StorePredictionVoteChangedPayload {
  notificationId : string;
  vote           : PredictionVoteDir;
}

// WP12 (F12) — FleetStatusStore. Emitted when a poll resolves or the
// live-only/offline view toggle flips. `stampUpdated` distinguishes a real
// fetch (re-stamp the "updated HH:MM:SS" label) from a pure view re-render
// (the toggle — must NOT claim fresh data).
export interface StoreFleetStatusChangedPayload {
  stampUpdated : boolean;
}

// Step 4 (task-list card) — TaskListStore. Emitted when a `/api/tasks` poll
// resolves (success / unreachable / 401). `stampUpdated` re-stamps the
// "updated HH:MM:SS" label; always true here (this store has no view-only
// toggle), but the field mirrors the fleet-status payload shape for symmetry.
export interface StoreTaskListChangedPayload {
  stampUpdated : boolean;
}
