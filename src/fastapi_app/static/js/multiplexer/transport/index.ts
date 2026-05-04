// Multiplexer Phase 3 — transport barrel + createTransports factory.
//
// Per Pass 1 finding #11 (post 2026-05-04 PM A-extended ratification):
//   createTransports(authManager, eventBus, baseUrl) → {queue, audio}
//
// Each transport gets its own ConnectionStateMachine instance — a disconnect
// on one socket does NOT reset the others' backoff.
//
// Claude Code transport is intentionally absent from the multiplexer scope.
// User directive 2026-05-04 PM (D1 ratified Option A-extended): the legacy
// `/api/claude-code/ws/{task_id}` endpoint has structural defects (URL
// mismatch, no auth, in-memory state, parallel pre-cj-flow path) and is
// queued for elimination — see bug-fix-queue.md "🔥 Top of Queue —
// IMMEDIATE" entry. A future Claude Code transport will be built only when
// UI surfaces a missing-functionality gap, against a properly authenticated
// endpoint.

import type { AuthManager } from "../auth/AuthManager";
import type { EventBus } from "../shared/EventBus";

import type { Transport } from "./QueueTransport";
import { createQueueTransport } from "./QueueTransport";
import type { AudioTransport } from "./AudioTransport";
import { createAudioTransport } from "./AudioTransport";

export interface TransportSet {
  queue : Transport;
  audio : AudioTransport;
}

export function createTransports(
  authManager : AuthManager,
  eventBus    : EventBus,
  baseUrl     : string,
): TransportSet {
  return {
    queue : createQueueTransport({
      authManager,
      bus     : eventBus,
      baseUrl,
    }),
    audio : createAudioTransport({
      authManager,
      bus     : eventBus,
      baseUrl,
    }),
  };
}

// Re-exports so consumers can import everything from this barrel.
export type { Transport, BaseTransportOptions, QueueTransportOptions } from "./QueueTransport";
export { BaseTransportImpl, QueueTransportImpl, createQueueTransport } from "./QueueTransport";
export type { AudioTransport, AudioTransportOptions } from "./AudioTransport";
export { AudioTransportImpl, createAudioTransport } from "./AudioTransport";
export type { WSChannel, WSChannelOptions, WSChannelState } from "./ws-channel";
export { createWSChannel } from "./ws-channel";
export type {
  ConnectionStateMachine,
  ConnectionStateMachineOptions,
  ConnectionEvent,
  ConnectionEventOnBus,
} from "./ConnectionStateMachine";
export {
  ConnectionStateMachineImpl,
  createConnectionStateMachine,
  backoffDelayMs,
} from "./ConnectionStateMachine";
