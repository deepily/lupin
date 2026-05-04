// Multiplexer Phase 2 — shared TypeScript interfaces.
// Foundation types consumed by EventBus, StorageService, AuthManager, ApiClient, broadcast.

// ---------------------------------------------------------------------------
// LupinEventType — string-literal union (hybrid policy per Phase 2 OQ3).
// Phase 2 emissions + BroadcastChannel whitelist references.
// Phase 3+ phases append transport_* / connection_* types.
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
  // BroadcastChannel whitelist references (emitted by Phase 3+ transport;
  // declared here so the static whitelist set is type-checked).
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
  // boot.ts Lifecycle Emission Contract (Phase 3, per design §"boot.ts Lifecycle
  // Event Emission Contract")
  | "page_hidden"
  | "page_visible"
  | "network_online"
  | "network_offline"
  // Server-frame handshake signal (Phase 3 wrappers wait for this on first
  // text frame post socket_open). The wrapper emits this through unchanged
  // when the server sends it, so the type string must be in this union.
  | "auth_success";

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
