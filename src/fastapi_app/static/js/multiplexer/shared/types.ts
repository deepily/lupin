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
  | "conversation_mode_change";

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
