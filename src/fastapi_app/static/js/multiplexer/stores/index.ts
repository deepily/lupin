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

export interface StoreSet {
  notifications  : NotificationStore;
  senders        : SenderStore;
  actionRequired : ActionRequiredStore;
  audio          : AudioStore;
  jobs           : JobStore;
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

  return { notifications, senders, actionRequired, audio, jobs };
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
