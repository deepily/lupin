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
//
// 360de81b — ONE CARD AT A TIME, and finished cards LEAVE (legacy parity, Rick 2026-09-10):
//   - Arrival order is queue order. The FIRST entry is the active card; the rest wait.
//   - A card's countdown starts when it reaches the slot (activateHead), not on arrival —
//     legacy addActionRequiredNotification :21339 defers expiresAt, activateNextNotification
//     :21467 sets it. A queued card has expires_at === null and no interval.
//   - A finished ACTIVE card stays for a grace period, then leaves and the next card activates:
//     answered here 600 ms, answered elsewhere 1500 ms, expired 600 ms. A finished QUEUED card
//     leaves at once. `failed` stays for retry.
//   - The server's `notification_expired` expires a card whatever its countdown shows: the
//     server's clock runs from arrival, so a queued card can expire before it is ever seen.

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
import { parseResponseQuestions } from "./responseQuestions";

// ---------------------------------------------------------------------------
// Loose ApiClient surface — store only needs `post`.
// ---------------------------------------------------------------------------

export interface ActionRequiredApiClient {
  post<T>(path: string, body: unknown): Promise<T>;
}

// ---------------------------------------------------------------------------
// The answer's wire shape (P0 5ebd2aff; found by Mr. Radio 2026-09-10).
//
// `/api/notify/response` wraps a plain string as {"value": ..., "source": "ui"}
// and stores anything else exactly as sent, and every reader takes .get("value")
// (notifications.py _extract_response_value; notify_user_sync.py). The old
// `{ response }` wrapper was stored with no "value" key, so every answer from
// this client read back as no answer, and a promotion ask answered here was
// refused.
//
// So EVERY answer goes as a string, exactly as legacy sends it:
//   - yes_no / open_ended: the bare answer (submitResponse, notifications.js:24015)
//   - multiple_choice / open_ended_batch: JSON.stringify({ answers: { <header>: value } })
//     (notifications.js:23855, :23451), which the asker parses back
//     (cosa_voice_mcp._parse_multiple_choice_response).
// ---------------------------------------------------------------------------

export function toWireResponseValue(response: ActionRequiredResponse): string {
  return typeof response === "string" ? response : JSON.stringify(response);
}

// 360de81b — how long a finished ACTIVE card stays before it leaves (legacy notifications.js):
export const RESPONDED_GRACE_MS = 600;    // showConfirmation's fallback timer (:24295)
export const CANCELLED_GRACE_MS = 1500;   // handleNotificationResponded, "responded in another session" (:24560)
export const EXPIRED_GRACE_MS   = 600;    // same bound as an answer; legacy animates, or deletes at once (:24462)

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
  response_options    ?: unknown;                  // { questions: [...] } dict — read by parseResponseQuestions
  response_default    ?: string;
  timeout_seconds     ?: number;
}

interface RespondedPayload {
  id_hash         ?: string;
  notification_id ?: string;
}

// Same shape NotificationStore reads for this event (NotificationStore.ts ExpiredPayload).
interface ExpiredPayload {
  id_hash         ?: string;
  notification_id ?: string;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface ActionRequiredStore {
  /** Arrival order. The first item is the active card; the rest wait in the queue (360de81b). */
  list(): ReadonlyArray<ActionRequiredItem>;
  getById(idHash: string): ActionRequiredItem | undefined;
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
  setTimeoutFn?    : (cb: () => void, ms: number) => unknown;
  clearTimeoutFn?  : (id: unknown) => void;
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
  // 360de81b — the pending removal after a grace period; null until the card finishes.
  removalId   : unknown;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class ActionRequiredStoreImpl implements ActionRequiredStore {
  private readonly bus             : EventBus;
  private readonly api             : ActionRequiredApiClient;
  private readonly setIntervalFn   : (cb: () => void, ms: number) => unknown;
  private readonly clearIntervalFn : (id: unknown) => void;
  private readonly setTimeoutFn    : (cb: () => void, ms: number) => unknown;
  private readonly clearTimeoutFn  : (id: unknown) => void;
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
    /* c8 ignore next */ // production-default fallback: globalThis.setTimeout is the runtime browser timer for the grace period; tests always inject a fake via opts.
    this.setTimeoutFn    = opts.setTimeoutFn    ?? ((cb, ms) => globalThis.setTimeout(cb, ms));
    /* c8 ignore next */ // production-default fallback: globalThis.clearTimeout pairs with the setTimeout default above; tests always inject the fake.
    this.clearTimeoutFn  = opts.clearTimeoutFn  ?? ((id) => globalThis.clearTimeout(id as number));
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

    // 360de81b: the server may expire the card while the POST is in flight. Once the card is no
    // longer this submission's (expired, or already gone), the late result changes nothing —
    // a failure still re-throws to the caller, but no "failed" or "responded" is emitted.
    const stillOurs = (): boolean => this.entries.get(idHash) === entry && entry.data.state === "submitting";
    try {
      await this.api.post<unknown>("/api/notify/response", {
        notification_id : idHash,
        response_value  : toWireResponseValue(response),
      });
    } catch (err) {
      if (stillOurs()) {
        entry.data = { ...entry.data, state: "failed" };
        this.emitWithDetails("failed", idHash, { response, error: err });
      }
      throw err;
    }
    if (!stillOurs()) return;

    entry.data = { ...entry.data, state: "responded", response };
    entry.actor.send({ type: "RESPOND" });
    this.emitWithDetails("responded", idHash, { response });
    this.retire(entry, RESPONDED_GRACE_MS);
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    for (const off of this.unsubscribers) off();
    for (const entry of this.entries.values()) {
      this.stopInterval(entry);
      if (entry.removalId !== null) this.clearTimeoutFn(entry.removalId);
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
      this.bus.on<ExpiredPayload>("notification_expired", (e) => this.onExpired(e)),
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

    // 360de81b: `timestamp` no longer sets the expiry — the countdown starts at activation.
    const timeout = n.timeout_seconds ?? 30;

    const item: ActionRequiredItem = {
      id_hash         : idHash,
      prompt          : n.message ?? "",
      response_type   : n.response_type ?? "open_ended",
      questions       : parseResponseQuestions(n.response_options),
      expires_at      : null,
      timeout_seconds : timeout,
      state           : "pending",
    };
    if (n.response_default !== undefined) item.default = n.response_default;

    const actor = createActor(promptMachine);
    actor.start();

    const entry: ActorEntry = {
      data         : item,
      actor,
      intervalId   : null,
      frozen       : false,
      lastCountdown: timeout * 1000,
      removalId    : null,
    };
    this.entries.set(idHash, entry);
    // A card arriving into an empty slot activates BEFORE "added", so the one "added" carries
    // it — one arrival stays one emission (stores_integration.test.ts pins the fanout).
    this.activateHead(false);
    this.emit("added", idHash);
  }

  // -------------------------------------------------------------------------
  // 360de81b — the queue: activation, grace period, removal
  // -------------------------------------------------------------------------

  /**
   * Start the countdown of the first card, if it is waiting. Legacy activateNextNotification :21428.
   * `announce` emits "activated" — true when a card is PROMOTED after another leaves; false on
   * arrival, where the caller's "added" already describes the activated card.
   */
  private activateHead(announce: boolean): void {
    const head = this.entries.values().next().value;
    if (head === undefined || head.data.expires_at !== null) return;
    const expiresAt = this.nowFn() + this.clockOffset + head.data.timeout_seconds * 1000;
    head.data = { ...head.data, expires_at: expiresAt };
    if (announce) this.emit("activated", head.data.id_hash);
    this.startInterval(head);
  }

  /** A card has finished: the active card leaves after `graceMs`, a queued card leaves at once. */
  private retire(entry: ActorEntry, graceMs: number): void {
    if (entry.data.expires_at === null) {
      this.removeEntry(entry);
      return;
    }
    entry.removalId = this.setTimeoutFn(() => this.removeEntry(entry), graceMs);
  }

  private removeEntry(entry: ActorEntry): void {
    this.stopInterval(entry);
    entry.actor.stop();
    this.entries.delete(entry.data.id_hash);
    this.emit("removed", entry.data.id_hash);
    this.activateHead(true);
  }

  /** Local countdown or server event: mark expired with the default read-back, then retire. */
  private expireEntry(entry: ActorEntry): void {
    this.stopInterval(entry);
    const next: ActionRequiredItem = { ...entry.data, state: "expired" };
    if (entry.data.default !== undefined) next.response = entry.data.default;
    entry.data = next;
    entry.actor.send({ type: "EXPIRE" });
    this.emit("expired", entry.data.id_hash);
    this.retire(entry, EXPIRED_GRACE_MS);
  }

  // Server timeout — legacy handleNotificationExpired :24591. Expires the card whatever its local
  // countdown shows, including a card still waiting in the queue.
  private onExpired(e: LupinEvent<ExpiredPayload>): void {
    const idHash = e.payload.id_hash ?? e.payload.notification_id;
    if (!idHash) return;
    const entry = this.entries.get(idHash);
    if (!entry) return;
    const s = entry.data.state;
    if (s !== "pending" && s !== "failed" && s !== "submitting") return;   // already finishing
    this.expireEntry(entry);
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
    // Only an activated card has an interval, so expires_at is set here.
    const remaining = Math.max(0, entry.data.expires_at! - (this.nowFn() + this.clockOffset));
    entry.lastCountdown = remaining;
    if (remaining === 0) {
      // Auto-expire — local-only, do NOT POST default per Q3.
      this.expireEntry(entry);
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
    // 360de81b: a failed answer answered elsewhere leaves too, or it would sit in the slot forever.
    if (entry.data.state !== "pending" && entry.data.state !== "failed") return;
    this.stopInterval(entry);
    entry.data = { ...entry.data, state: "cancelled" };
    entry.actor.send({ type: "CANCEL" });
    this.emit("cancelled", idHash);
    this.retire(entry, CANCELLED_GRACE_MS);
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

  // 360de81b: a queued card (expires_at === null) has no countdown, so neither freeze nor thaw
  // touches it — a thaw must never start a timer for a card still waiting.
  private freezeAll(): void {
    for (const entry of this.entries.values()) {
      if (entry.data.state !== "pending") continue;
      if (entry.data.expires_at === null) continue;
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
