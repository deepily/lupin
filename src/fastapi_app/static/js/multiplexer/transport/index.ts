// Multiplexer Phase 3 — transport barrel + createTransports factory.
//
// Pass 1 finding #11 pinned the factory signature:
//   createTransports(authManager, eventBus, baseUrl) → {queue, audio, claudeCode}
//
// Each transport gets its own ConnectionStateMachine instance — a disconnect
// on one socket does NOT reset the others' backoff. The stub-by-design
// `claudeCode` member returns a ClaudeCodeTransport whose `start(taskId)`
// throws `not implemented` until Phase 4 stores land.

import type { AuthManager } from "../auth/AuthManager";
import type { EventBus } from "../shared/EventBus";

import type { Transport } from "./QueueTransport";
import { createQueueTransport } from "./QueueTransport";
import type { AudioTransport } from "./AudioTransport";
import { createAudioTransport } from "./AudioTransport";
import type { ClaudeCodeTransport } from "./ClaudeCodeTransport";
import { createClaudeCodeTransport } from "./ClaudeCodeTransport";

export interface TransportSet {
  queue      : Transport;
  audio      : AudioTransport;
  claudeCode : ClaudeCodeTransport;
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
    claudeCode : createClaudeCodeTransport({
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
export type { ClaudeCodeTransport, ClaudeCodeTransportOptions } from "./ClaudeCodeTransport";
export { createClaudeCodeTransport } from "./ClaudeCodeTransport";
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
