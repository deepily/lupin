/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 4 — ActionRequiredStore.
//
// One XState v5 actor (tracker pattern per Q5) per active prompt.
// Lifecycle: pending → responded | expired | cancelled (terminal).
//
// Side effects (per Q5 tracker pattern — wrapping class owns):
//   - per-actor setInterval(1000) for smooth 1Hz countdown UX (D-F)
//   - sys_time_update subscription → updates clockOffset (server-authoritative)
//   - connection_state_change subscription → backoff/offline pauses interval
//                                              + emits "offline-frozen"
//   - respond(idHash, response) POSTs `/api/notify/response` via ApiClient
//                                       (optimistic, fire-and-forget; Phase 5 backward-compat)
//   - respondAndAwait(idHash, response) POSTs and awaits server confirmation
//                                       (Phase 6b — non-optimistic path per Pass 2 A1)
//
// Spec drifts vs design doc, recorded in execution log:
//   1. Action-required prompts arrive via `notification_queue_update` (with
//      `notification.response_requested === true`), NOT via a separate
//      `notification_received` event. Same dispatch shape as NotificationStore.
//   2. Cancellation reachability via incoming `notification_responded` event
//      from the server-side fanout (P2 verified at notifications.py:1093).
//
// Auto-expiry on countdown reaching zero is LOCAL-ONLY per Q3 — does NOT
// POST `default` back to the server. Server has its own expiry timer; local
// transition is for UI hiding.

import { setup, createActor, type ActorRefFrom } from "xstate";

import type { EventBus } from "../shared/EventBus";
import type {
  ActionRequiredItem,
  ActionRequiredChangeKind,
  ActionRequiredResponse,
  ConnectionStateChangePayload,
  LupinEvent,
  StoreActionRequiredChangedPayload,
} from "../shared/types";

// ---------------------------------------------------------------------------
// Loose ApiClient surface — store only needs `post`.
// ---------------------------------------------------------------------------

export interface ActionRequiredApiClient {
  post<T>(path: string, body: unknown): Promise<T>;
}

// ---------------------------------------------------------------------------
// Per-prompt XState tracker. Pure state graph; no services, no actions with
// side effects. The wrapping class drives transitions explicitly.
// ---------------------------------------------------------------------------

interface PromptContext {
  // Empty — state is the only thing we track. Per-prompt data is held by the
  // wrapping ActorEntry record (which owns the timer + serverside data too).
}

type PromptMachineEvent =
  | { type: "RESPOND" }
  | { type: "EXPIRE" }
  | { type: "CANCEL" };

const promptMachine = setup({
  types : {
    context : {} as PromptContext,
    events  : {} as PromptMachineEvent,
  },
}).createMachine({
  id      : "actionRequiredPrompt",
  initial : "pending",
  context : {},
  states  : {
    pending   : {
      on : {
        RESPOND : "responded",
        EXPIRE  : "expired",
        CANCEL  : "cancelled",
      },
    },
    responded : { type: "final" },
    expired   : { type: "final" },
    cancelled : { type: "final" },
  },
});

// ---------------------------------------------------------------------------
// Wire payload shape — same notification_queue_update branch as the other
// stores, with the action-required-relevant fields surfaced.
// ---------------------------------------------------------------------------

interface QueueUpdatePayload {
  notification?: ServerNotificationFields;
}

interface ServerNotificationFields {
  id_hash             ?: string;
  id                  ?: string;
  message             ?: string;
  sender_id           ?: string;
  timestamp           ?: string;
  response_requested  ?: boolean;
  response_type       ?: ActionRequiredItem["response_type"];
  response_options    ?: ReadonlyArray<string>;
  response_default    ?: string;
  timeout_seconds     ?: number;
}

interface RespondedPayload {
  id_hash         ?: string;
  notification_id ?: string;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface ActionRequiredStore {
  list(): ReadonlyArray<ActionRequiredItem>;
  getById(idHash: string): ActionRequiredItem | undefined;
  /**
   * Optimistic respond — flips local state to "responded" before the network
   * round-trip. Phase 5 backward-compat path. Network failure is silently
   * swallowed (UI feedback already delivered). No-op on unknown idHash or
   * non-pending state. Phase 6b widened the response param per Pass 2 A2.
   */
  respond(idHash: string, response: ActionRequiredResponse): Promise<void>;
  /**
   * Non-optimistic respond — Phase 6b per Pass 2 A1. Transitions through
   * "submitting" → "responded" | "failed". Throws on unknown idHash or
   * non-retryable state. Network failure leaves entry in "failed" state and
   * re-throws so the caller (renderer) can render an inline error stripe and
   * re-enable the widget for retry.
   */
  respondAndAwait(idHash: string, response: ActionRequiredResponse): Promise<void>;
  /** Test/cleanup helper: stop all per-prompt intervals + actors. */
  disposeForTesting(): void;
}

export interface ActionRequiredStoreOptions {
  bus       : EventBus;
  api       : ActionRequiredApiClient;
  // Test injection.
  setIntervalFn?   : (cb: () => void, ms: number) => unknown;
  clearIntervalFn? : (id: unknown) => void;
  nowFn?           : () => number;
}

// ---------------------------------------------------------------------------
// Per-prompt entry — combines the data, the actor, and the timer handle.
// ---------------------------------------------------------------------------

interface ActorEntry {
  data        : ActionRequiredItem;
  actor       : ActorRefFrom<typeof promptMachine>;
  intervalId  : unknown;
  // True when paused due to offline/backoff; resume on connection_online.
  frozen      : boolean;
  // Last countdown ms emitted; reused on offline-frozen emission so UI shows
  // the value the user last saw.
  lastCountdown: number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class ActionRequiredStoreImpl implements ActionRequiredStore {
  private readonly bus             : EventBus;
  private readonly api             : ActionRequiredApiClient;
  private readonly setIntervalFn   : (cb: () => void, ms: number) => unknown;
  private readonly clearIntervalFn : (id: unknown) => void;
  private readonly nowFn           : () => number;

  private readonly entries = new Map<string, ActorEntry>();
  // Server clock offset (serverTime - localTime); reconciled by sys_time_update.
  private clockOffset = 0;

  private readonly unsubscribers : Array<() => void> = [];

  constructor(opts: ActionRequiredStoreOptions) {
    this.bus             = opts.bus;
    this.api             = opts.api;
    /* c8 ignore next */ // production-default fallback: globalThis.setInterval is the runtime browser timer; tests always inject makeFakeIntervals().setIntervalFn via opts.
    this.setIntervalFn   = opts.setIntervalFn   ?? ((cb, ms) => globalThis.setInterval(cb, ms));
    /* c8 ignore next */ // production-default fallback: globalThis.clearInterval pairs with the setInterval default above; tests always inject the fake.
    this.clearIntervalFn = opts.clearIntervalFn ?? ((id) => globalThis.clearInterval(id as number));
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn           = opts.nowFn           ?? (() => Date.now());
    this.subscribe();
  }

  list(): ReadonlyArray<ActionRequiredItem> {
    return Array.from(this.entries.values()).map(e => e.data);
  }

  getById(idHash: string): ActionRequiredItem | undefined {
    return this.entries.get(idHash)?.data;
  }

  async respond(idHash: string, response: ActionRequiredResponse): Promise<void> {
    const entry = this.entries.get(idHash);
    if (!entry) return;
    if (entry.data.state !== "pending") return;

    // Optimistic local transition — flip to responded immediately so the UI
    // hides the prompt before the network round-trip. The server's
    // notification_responded fanout will arrive later (idempotent —
    // already-responded prompts are no-ops on the server-side path).
    entry.data = { ...entry.data, state: "responded", response };
    this.stopInterval(entry);
    entry.actor.send({ type: "RESPOND" });
    this.emit("responded", idHash);

    try {
      await this.api.post<unknown>("/api/notify/response", {
        notification_id : idHash,
        response_value  : { response },
      });
    } catch (_err) {
      // Network failure: leave the local state as responded (UI feedback already
      // delivered to user); a reconnect + server-side fanout would re-converge.
      // No retry is wired for Phase 4; Phase 6+ may add one.
    }
  }

  // Phase 6b — non-optimistic path (per Pass 2 A1). Lifecycle:
  //   pending|failed → submitting → (POST) → responded (terminal) | failed (re-tryable)
  // Failed entries can be re-driven through respondAndAwait() again. The interval
  // is stopped when state leaves "pending" (existing tick guard); we do NOT restart
  // it on failure (countdown is suspended for the duration of the user's retry).
  async respondAndAwait(idHash: string, response: ActionRequiredResponse): Promise<void> {
    const entry = this.entries.get(idHash);
    if (!entry) throw new Error(`Unknown action_required id: ${idHash}`);
    if (entry.data.state !== "pending" && entry.data.state !== "failed") {
      throw new Error(`Cannot respondAndAwait in state ${entry.data.state}: ${idHash}`);
    }

    entry.data = { ...entry.data, state: "submitting" };
    this.stopInterval(entry);
    this.emitWithDetails("responded-pending", idHash, { response });

    try {
      await this.api.post<unknown>("/api/notify/response", {
        notification_id : idHash,
        response_value  : { response },
      });
    } catch (err) {
      entry.data = { ...entry.data, state: "failed" };
      this.emitWithDetails("failed", idHash, { response, error: err });
      throw err;
    }

    entry.data = { ...entry.data, state: "responded", response };
    entry.actor.send({ type: "RESPOND" });
    this.emitWithDetails("responded", idHash, { response });
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    for (const off of this.unsubscribers) off();
    for (const entry of this.entries.values()) {
      this.stopInterval(entry);
      entry.actor.stop();
    }
    this.entries.clear();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Subscriptions
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<QueueUpdatePayload>("notification_queue_update", (e) => this.onQueueUpdate(e)),
    );
    this.unsubscribers.push(
      this.bus.on<RespondedPayload>("notification_responded", (e) => this.onResponded(e)),
    );
    this.unsubscribers.push(
      this.bus.on<{ ts?: number; serverTime?: number }>("sys_time_update", (e) => this.onSysTimeUpdate(e)),
    );
    this.unsubscribers.push(
      this.bus.on<ConnectionStateChangePayload>("connection_state_change", (e) => this.onConnectionState(e)),
    );
    this.unsubscribers.push(
      this.bus.on<unknown>("connection_offline", () => this.freezeAll()),
    );
    this.unsubscribers.push(
      this.bus.on<unknown>("connection_online", () => this.thawAll()),
    );
  }

  // -------------------------------------------------------------------------
  // Reducer: notification_queue_update with response_requested === true
  // -------------------------------------------------------------------------

  private onQueueUpdate(e: LupinEvent<QueueUpdatePayload>): void {
    const n = e.payload.notification;
    if (!n) return;
    if (n.response_requested !== true) return;
    const idHash = n.id_hash ?? n.id;
    if (!idHash) return;
    if (this.entries.has(idHash)) return;       // dedup — server may re-emit on reconnect

    const ts = n.timestamp ? Date.parse(n.timestamp) : this.nowFn();
    if (Number.isNaN(ts)) return;
    const timeout = n.timeout_seconds ?? 30;
    const expiresAt = ts + timeout * 1000;

    const item: ActionRequiredItem = {
      id_hash       : idHash,
      prompt        : n.message ?? "",
      response_type : n.response_type ?? "open_ended",
      options       : n.response_options ?? [],
      expires_at    : expiresAt,
      state         : "pending",
    };
    if (n.response_default !== undefined) item.default = n.response_default;

    const actor = createActor(promptMachine);
    actor.start();

    const entry: ActorEntry = {
      data         : item,
      actor,
      intervalId   : null,
      frozen       : false,
      lastCountdown: Math.max(0, expiresAt - this.nowFn()),
    };
    this.entries.set(idHash, entry);
    this.emit("added", idHash);
    this.startInterval(entry);
  }

  private startInterval(entry: ActorEntry): void {
    /* c8 ignore next */ // defensive: startInterval is only called from onQueueUpdate (after the entry is just-created with intervalId=null) and from thawAll (after freezeAll has stopped+nulled the timer); the truthy "already running" arm is unreachable in practice. Belt-and-suspenders for any future caller that might double-call without going through the lifecycle.
    if (entry.intervalId !== null) return;     // already running
    /* c8 ignore next */ // defensive: startInterval is only called when the entry is freshly created (frozen=false) or when thawAll has just unfrozen it; the "frozen=true" arm is unreachable from the current call sites. Belt-and-suspenders against future misuse.
    if (entry.frozen) return;                  // currently paused for offline
    entry.intervalId = this.setIntervalFn(() => this.tick(entry), 1000);
  }

  private stopInterval(entry: ActorEntry): void {
    if (entry.intervalId !== null) {
      this.clearIntervalFn(entry.intervalId);
      entry.intervalId = null;
    }
  }

  private tick(entry: ActorEntry): void {
    /* c8 ignore start */ // Defensive guard — stopInterval is called synchronously on every terminal transition, so a tick callback for a non-pending entry should not occur in practice. Belt-and-suspenders for setInterval edge cases (e.g. tick callback queued before clearInterval reaches the timer).
    if (entry.data.state !== "pending") {
      this.stopInterval(entry);
      return;
    }
    /* c8 ignore stop */
    const remaining = Math.max(0, entry.data.expires_at - (this.nowFn() + this.clockOffset));
    entry.lastCountdown = remaining;
    if (remaining === 0) {
      // Auto-expire — local-only, do NOT POST default per Q3.
      this.stopInterval(entry);
      const next: ActionRequiredItem = { ...entry.data, state: "expired" };
      if (entry.data.default !== undefined) next.response = entry.data.default;
      entry.data = next;
      entry.actor.send({ type: "EXPIRE" });
      this.emit("expired", entry.data.id_hash);
      return;
    }
    this.bus.emit<StoreActionRequiredChangedPayload>({
      type    : "store_action_required_changed",
      payload : { changeKind: "tick", id_hash: entry.data.id_hash, countdownMs: remaining },
      source  : "ActionRequiredStore",
      ts      : this.nowFn(),
    });
  }

  // -------------------------------------------------------------------------
  // Reducer: notification_responded → cancellation reachability
  // -------------------------------------------------------------------------

  private onResponded(e: LupinEvent<RespondedPayload>): void {
    const idHash = e.payload.id_hash ?? e.payload.notification_id;
    if (!idHash) return;
    const entry = this.entries.get(idHash);
    if (!entry) return;
    // If we already responded locally, the server is just confirming — no-op.
    if (entry.data.state === "responded") return;
    if (entry.data.state !== "pending") return;
    this.stopInterval(entry);
    entry.data = { ...entry.data, state: "cancelled" };
    entry.actor.send({ type: "CANCEL" });
    this.emit("cancelled", idHash);
  }

  // -------------------------------------------------------------------------
  // Clock reconciliation
  // -------------------------------------------------------------------------

  private onSysTimeUpdate(e: LupinEvent<{ ts?: number; serverTime?: number }>): void {
    const serverTime = e.payload.serverTime ?? e.payload.ts;
    if (typeof serverTime !== "number") return;
    this.clockOffset = serverTime - this.nowFn();
  }

  // -------------------------------------------------------------------------
  // Connection-state freeze/thaw
  // -------------------------------------------------------------------------

  private onConnectionState(e: LupinEvent<ConnectionStateChangePayload>): void {
    const s = e.payload.state;
    if (s === "backoff" || s === "offline" || s === "failed") {
      this.freezeAll();
    } else if (s === "connected") {
      this.thawAll();
    }
  }

  private freezeAll(): void {
    for (const entry of this.entries.values()) {
      if (entry.data.state !== "pending") continue;
      if (entry.frozen) continue;
      entry.frozen = true;
      this.stopInterval(entry);
      this.bus.emit<StoreActionRequiredChangedPayload>({
        type    : "store_action_required_changed",
        payload : {
          changeKind  : "offline-frozen",
          id_hash     : entry.data.id_hash,
          countdownMs : entry.lastCountdown,
        },
        source  : "ActionRequiredStore",
        ts      : this.nowFn(),
      });
    }
  }

  private thawAll(): void {
    for (const entry of this.entries.values()) {
      if (entry.data.state !== "pending") continue;
      if (!entry.frozen) continue;
      entry.frozen = false;
      this.startInterval(entry);
      this.bus.emit<StoreActionRequiredChangedPayload>({
        type    : "store_action_required_changed",
        payload : {
          changeKind  : "offline-resumed",
          id_hash     : entry.data.id_hash,
          countdownMs : entry.lastCountdown,
        },
        source  : "ActionRequiredStore",
        ts      : this.nowFn(),
      });
    }
  }

  // -------------------------------------------------------------------------
  // Emit helper
  // -------------------------------------------------------------------------

  private emit(changeKind: ActionRequiredChangeKind, idHash: string): void {
    this.bus.emit<StoreActionRequiredChangedPayload>({
      type    : "store_action_required_changed",
      payload : { changeKind, id_hash: idHash },
      source  : "ActionRequiredStore",
      ts      : this.nowFn(),
    });
  }

  // Phase 6b — emit helper for change kinds that carry response/error details
  // (responded-pending / responded / failed via respondAndAwait path).
  private emitWithDetails(
    changeKind : ActionRequiredChangeKind,
    idHash     : string,
    details    : { response?: ActionRequiredResponse; error?: unknown },
  ): void {
    const payload: StoreActionRequiredChangedPayload = { changeKind, id_hash: idHash };
    if (details.response !== undefined) payload.response = details.response;
    if (details.error    !== undefined) payload.error    = details.error;
    this.bus.emit<StoreActionRequiredChangedPayload>({
      type    : "store_action_required_changed",
      payload,
      source  : "ActionRequiredStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createActionRequiredStore(opts: ActionRequiredStoreOptions): ActionRequiredStore {
  return new ActionRequiredStoreImpl(opts);
}
