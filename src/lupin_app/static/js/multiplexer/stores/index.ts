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
// `createStores(opts)` returns the canonical 6-store set. Boot.ts wires its
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
import type { ReadingPaneStore } from "./ReadingPaneStore";
import { createReadingPaneStore } from "./ReadingPaneStore";
import type { CommonsStore } from "./CommonsStore";
import { createCommonsStore } from "./CommonsStore";
// Lane E full-parity quartet stores (2026-06-10).
import type { MissedStore } from "./MissedStore";
import { createMissedStore } from "./MissedStore";
import type { PredictionVoteStore } from "./PredictionVoteStore";
import { createPredictionVoteStore } from "./PredictionVoteStore";
import type { FleetStatusStore, FleetApiClient } from "./FleetStatusStore";
import { createFleetStatusStore } from "./FleetStatusStore";
import type { TaskListStore } from "./TaskListStore";
import { createTaskListStore } from "./TaskListStore";

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
  // WP4 (2026-06-10) — ReadingPaneStore is action-driven (renderer gestures +
  // AR-store changes), NOT a server-frame subscriber, so it sits OUTSIDE the
  // pinned subscription-order chain below; construction order is irrelevant.
  readingPane    : ReadingPaneStore;
  // Lane D (WP3) — commons "Recent Activity" panel store. No inter-store
  // dependency (consumes notification_queue_update independently), so it
  // constructs last; subscription order of the pinned 5 is unaffected.
  commons        : CommonsStore;
  // Lane E quartet — Missed (auth_success surfacing), PredictionVote (vote
  // POST), FleetStatus (60s poll; boot starts polling AFTER mount).
  missed         : MissedStore;
  predictionVote : PredictionVoteStore;
  fleetStatus    : FleetStatusStore;
  taskList       : TaskListStore;
}

export interface CreateStoresOptions {
  eventBus            : EventBus;
  storage             : StorageService;
  // post (ActionRequired / Missed / PredictionVote) + get (FleetStatus). The
  // production ApiClient satisfies both structurally.
  api                 : ActionRequiredApiClient & FleetApiClient;
  // Forward AudioStore options so boot.ts can pass production-side
  // `audioContextFactory`. Tests usually omit (default factory is browser-only).
  audioContextFactory?: AudioStoreOptions["audioContextFactory"];
}

/**
 * Construct the canonical 6-store set. Subscription order is pinned at
 * construction time — see file-header comment.
 *
 * Requires:
 *   - opts.eventBus is the production EventBus (or a test instance)
 *   - opts.storage is a configured StorageService
 *   - opts.api is an ApiClient (or stub satisfying ActionRequiredApiClient)
 *
 * Ensures:
 *   - Returns the 11-store set (the 5 server-frame subscribers in pinned order + sessionStrip/readingPane/commons + the Lane E quartet stores)
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
  // ReadingPaneStore (WP4) — order-independent (no server-frame subscription);
  // hydrates persisted layout mode + split ratio from storage at construction.
  const readingPane    = createReadingPaneStore  ({ bus: opts.eventBus, storage: opts.storage });
  // Lane D (WP3) — commons store, also order-independent of the pinned five.
  const commons        = createCommonsStore      ({ bus: opts.eventBus, storage: opts.storage });

  // Lane E quartet — appended AFTER the canonical 5 (order-neutral: Missed
  // listens only to auth_success; PredictionVote + FleetStatus subscribe to no
  // server frames). FleetStatus does NOT start polling here — boot.ts kicks
  // startPolling() AFTER the renderer mounts (Cheech's rule).
  const missed         = createMissedStore        ({ bus: opts.eventBus, api: opts.api });
  const predictionVote = createPredictionVoteStore({ bus: opts.eventBus, api: opts.api });
  const fleetStatus    = createFleetStatusStore   ({ bus: opts.eventBus, api: opts.api });
  const taskList       = createTaskListStore      ({ bus: opts.eventBus, api: opts.api });

  return { notifications, senders, actionRequired, audio, jobs, sessionStrip, readingPane, commons, missed, predictionVote, fleetStatus, taskList };
}

// Re-exports so consumers can import everything from the barrel.
export type {
  NotificationStore,
  NotificationStoreOptions,
  NotificationHistoryApiClient,
  HydrateHistoryOptions,
} from "./NotificationStore";
export { createNotificationStore, DEFAULT_HISTORY_WINDOW_HOURS } from "./NotificationStore";
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
// WP2 (parity bridge) — SessionStripStore IS part of the canonical store set
// built by createStores() (folded at the boot-integration step per Lane A's
// mount-slot convention); re-exported here for direct consumers/tests too.
export type { SessionStripStore, SessionStripStoreOptions, ServerSenderHydrationRecord } from "./SessionStripStore";
export { createSessionStripStore } from "./SessionStripStore";
// WP4 (2026-06-10) — ReadingPaneStore IS part of the canonical store set built
// by createStores() (Tiberius uniform ruling 2026-06-10: one store registry, no
// boot-direct stragglers). Re-exported here for direct consumers/tests too.
export type { ReadingPaneStore, ReadingPaneStoreOptions } from "./ReadingPaneStore";
export { createReadingPaneStore } from "./ReadingPaneStore";
export type { CommonsStore, CommonsStoreOptions, CommonsHistoryApiClient } from "./CommonsStore";
export { createCommonsStore } from "./CommonsStore";
export type { MissedStore, MissedStoreOptions, MissedApiClient } from "./MissedStore";
export { createMissedStore } from "./MissedStore";
export type {
  PredictionVoteStore,
  PredictionVoteStoreOptions,
  PredictionVoteApiClient,
  PredictionVoteContext,
} from "./PredictionVoteStore";
export { createPredictionVoteStore } from "./PredictionVoteStore";
export type { FleetStatusStore, FleetStatusStoreOptions, FleetApiClient } from "./FleetStatusStore";
export { createFleetStatusStore } from "./FleetStatusStore";
export type { TaskListStore, TaskListStoreOptions, TaskListApiClient } from "./TaskListStore";
export { createTaskListStore } from "./TaskListStore";
/* c8 ignore stop */
