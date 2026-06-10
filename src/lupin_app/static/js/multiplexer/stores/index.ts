/* c8 ignore start */
// Re-exports + factory barrel — coverage of this file is measured indirectly
// via the modules it constructs (NotificationStore.ts, SenderStore.ts,
// ActionRequiredStore.ts, AudioStore.ts, JobStore.ts), each of which has its
// own dedicated test suite at 100% per the global mandate. The createStores
// factory is exercised by integration tests at boot. Direct branch coverage
// of a barrel is meaningless. See project CLAUDE.md "100% COVERAGE MANDATE"
// for the c8-ignore exception clause.
// Multiplexer Phase 4 — stores barrel.
//
// `createStores(opts)` returns the canonical 5-store set. Boot.ts wires its
// resolved dependencies through this factory.
//
// Per Pass 1 F12 — CANONICAL SUBSCRIPTION ORDER PINNED:
//   notifications → senders → actionRequired → audio → jobs
// Order matters because EventBus listener invocation is registration-order
// (per the `EventTarget` contract). NotificationStore mutates first (canonical
// record of the notification arrival); SenderStore second (looks up sender +
// bumps last_active); ActionRequiredStore third (only fires for prompts with
// `response_requested === true`); AudioStore + JobStore last (no inter-store
// dependencies). Order is preserved by the construction sequence below + the
// integration test asserts deterministic microtask-boundary ordering.
//
// Per D-D ratification 2026-05-04 PM: `audioTransport` is NOT a parameter.
// AudioStore exposes `.binaryHandler` (named `audioStoreBinaryHandler` for
// AC9). boot.ts calls `transports.audio.start(sessionId, stores.audio.binaryHandler)`
// directly — the transport's existing `start(sessionId, binaryHandler?)`
// contract.

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";

import type { NotificationStore } from "./NotificationStore";
import { createNotificationStore } from "./NotificationStore";
import type { JobStore } from "./JobStore";
import { createJobStore } from "./JobStore";
import type { SenderStore } from "./SenderStore";
import { createSenderStore } from "./SenderStore";
import type { ActionRequiredStore, ActionRequiredApiClient } from "./ActionRequiredStore";
import { createActionRequiredStore } from "./ActionRequiredStore";
import type { AudioStore, AudioStoreOptions } from "./AudioStore";
import { createAudioStore } from "./AudioStore";
import type { SessionStripStore } from "./SessionStripStore";
import { createSessionStripStore } from "./SessionStripStore";

export interface StoreSet {
  notifications  : NotificationStore;
  senders        : SenderStore;
  actionRequired : ActionRequiredStore;
  audio          : AudioStore;
  jobs           : JobStore;
  // WP2 (parity bridge) — CC-session strip model. Constructed LAST so its
  // notification_queue_update listener registers after the canonical five,
  // preserving the pinned cross-store fanout order the integration test
  // asserts (sessionStrip emits its own store_session_strip_changed, which is
  // not in that watched set).
  sessionStrip   : SessionStripStore;
}

export interface CreateStoresOptions {
  eventBus            : EventBus;
  storage             : StorageService;
  api                 : ActionRequiredApiClient;
  // Forward AudioStore options so boot.ts can pass production-side
  // `audioContextFactory`. Tests usually omit (default factory is browser-only).
  audioContextFactory?: AudioStoreOptions["audioContextFactory"];
}

/**
 * Construct the canonical 5-store set. Subscription order is pinned at
 * construction time — see file-header comment.
 *
 * Requires:
 *   - opts.eventBus is the production EventBus (or a test instance)
 *   - opts.storage is a configured StorageService
 *   - opts.api is an ApiClient (or stub satisfying ActionRequiredApiClient)
 *
 * Ensures:
 *   - Returns the 5-store set with subscriptions wired in canonical order
 *   - Each store's constructor is fully synchronous; the StoreSet is
 *     immediately usable on return
 */
export function createStores(opts: CreateStoresOptions): StoreSet {
  // ORDER MATTERS — see file header. Do not reorder without also updating
  // the integration test assertion.
  const notifications  = createNotificationStore({ bus: opts.eventBus, storage: opts.storage });
  const senders        = createSenderStore       ({ bus: opts.eventBus });
  const actionRequired = createActionRequiredStore({ bus: opts.eventBus, api: opts.api });
  const audio          = createAudioStore        ({
    bus                 : opts.eventBus,
    audioContextFactory : opts.audioContextFactory,
  });
  const jobs           = createJobStore          ({ bus: opts.eventBus });
  // WP2 — LAST (see StoreSet comment): registers after the canonical five so
  // the integration test's pinned fanout order is preserved.
  const sessionStrip   = createSessionStripStore  ({ bus: opts.eventBus });

  return { notifications, senders, actionRequired, audio, jobs, sessionStrip };
}

// Re-exports so consumers can import everything from the barrel.
export type { NotificationStore, NotificationStoreOptions } from "./NotificationStore";
export { createNotificationStore } from "./NotificationStore";
export type { JobStore, JobStoreOptions, JobHistoryApiClient } from "./JobStore";
export { createJobStore } from "./JobStore";
export type { SenderStore, SenderStoreOptions } from "./SenderStore";
export { createSenderStore } from "./SenderStore";
export type {
  ActionRequiredStore,
  ActionRequiredStoreOptions,
  ActionRequiredApiClient,
} from "./ActionRequiredStore";
export { createActionRequiredStore } from "./ActionRequiredStore";
export type { AudioStore, AudioStoreOptions } from "./AudioStore";
export { createAudioStore } from "./AudioStore";
// WP2 (parity bridge) — SessionStripStore is re-exported for direct import but
// is deliberately NOT folded into createStores() here. Wiring it into the
// canonical store set is part of the deferred boot-integration step (against
// Lane A's mount-slot convention), kept out of this lane's held commit.
export type { SessionStripStore, SessionStripStoreOptions } from "./SessionStripStore";
export { createSessionStripStore } from "./SessionStripStore";
/* c8 ignore stop */
