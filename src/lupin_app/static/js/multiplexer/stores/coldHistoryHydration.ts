/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line.
// Multiplexer cold-load notification-history runner (2026-09-10, P0 5ebd2aff).
//
// Extracted from boot.ts so the cold-load path is testable and HONEST about
// failure. Before this, boot fetched senders-visible on the ApiClient's 10 s
// default and a `.catch(() => {})` swallowed the abort. Measured 2026-09-10:
// the endpoint took 52.8 s for Rick (5,179 senders), so every cold load was
// abandoned and the list pane said "No notifications yet." while the legacy
// client — which sets no timeout on the same call — loaded 308.
//
// Owns: the senders-visible fetch → its three consumers (strip, senders,
// notification history, unchanged from boot's 2026-06-11 fan-out) → the
// NotificationStore's hydration state (loading / done / failed), plus a re-run
// when the list pane's Retry emits HISTORY_RETRY_EVENT, and a reload when the
// history-window picker changes the window (Rick's ruling 1, legacy
// setHistoryWindow → clearSenderGroups → loadConversationHistory).
//
// Design (original fan-out): src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md
// Parity inventory: src/rnd/2026.09.10-mux-cc-notifications-accordion-parity.md §0

import type { EventBus } from "../shared/EventBus";
import type { StoreNotificationsChangedPayload } from "../shared/types";
import type { ServerSenderHydrationRecord } from "./SessionStripStore";
import type { HydrateHistoryOptions, NotificationHistoryApiClient } from "./NotificationStore";

// Long enough to outlast the measured 52.8 s with headroom; short enough that a
// dead server still resolves to an honest "failed" instead of spinning forever.
export const COLD_HYDRATION_TIMEOUT_MS = 120_000;

// Emitted by NotificationsListRenderer's Retry button; this runner re-runs on it.
export const HISTORY_RETRY_EVENT = "notifications_history_retry_requested";

// Narrowed ApiClient surface — production passes the canonical ApiClient.
export interface ColdHydrationApiLike {
  get<T>(path: string, opts?: { timeoutMs?: number }): Promise<T>;
}

export interface ColdHydrationStores {
  sessionStrip  : { hydrate(records: ReadonlyArray<ServerSenderHydrationRecord>): void };
  senders       : { hydrate(records: ReadonlyArray<ServerSenderHydrationRecord>): void };
  notifications : {
    hydrateHistory(api: NotificationHistoryApiClient, opts: HydrateHistoryOptions): Promise<void>;
    isHistoryHydrated(): boolean;
    markHistoryHydrationLoading(): void;
    markHistoryHydrationFailed(reason: string): void;
    resetHistoryHydration(): void;
  };
}

export interface ColdHistoryHydrationOptions {
  bus               : EventBus;
  api               : ColdHydrationApiLike;
  stores            : ColdHydrationStores;
  getEmail          : () => string | null;
  // Read at the start of every run: "Today" moves with the clock and the picker
  // can change the window. null = All time (historyWindow.effectiveHoursForQuery).
  getEffectiveHours : () => number | null;
  timeoutMs?        : number;   // test injection; production uses COLD_HYDRATION_TIMEOUT_MS
}

export interface ColdHistoryHydration {
  /** Run (or re-run after a failure) the cold-load hydration. Never rejects. */
  run(): Promise<void>;
  /**
   * Drop the loaded history and run again for the current window — the
   * picker's reload. Never rejects.
   *
   * Ensures:
   *   - with no run in flight: the store's history is reset, then run()
   *   - with a run in flight: nothing is dropped or fetched now; when that run
   *     finishes, exactly one reload follows, however many were requested
   */
  reload(): Promise<void>;
  /** Detach the retry and window-change listeners. */
  dispose(): void;
}

class ColdHistoryHydrationImpl implements ColdHistoryHydration {
  private readonly api               : ColdHydrationApiLike;
  private readonly stores            : ColdHydrationStores;
  private readonly getEmail          : () => string | null;
  private readonly getEffectiveHours : () => number | null;
  private readonly timeoutMs         : number;
  private readonly unsubscribers     : Array<() => void>;
  private inFlight      = false;
  private reloadPending = false;

  constructor(opts: ColdHistoryHydrationOptions) {
    this.api               = opts.api;
    this.stores            = opts.stores;
    this.getEmail          = opts.getEmail;
    this.getEffectiveHours = opts.getEffectiveHours;
    this.timeoutMs         = opts.timeoutMs ?? COLD_HYDRATION_TIMEOUT_MS;
    this.unsubscribers     = [
      opts.bus.on(HISTORY_RETRY_EVENT, () => { void this.run(); }),
      opts.bus.on<StoreNotificationsChangedPayload>("store_notifications_changed", (e) => {
        if (e.payload.changeKind === "history_window") void this.reload();
      }),
    ];
  }

  /**
   * Fetch senders-visible and fan it out, reporting the outcome to the store.
   *
   * Requires:
   *   - stores are constructed; the list renderer may or may not be mounted
   * Ensures:
   *   - no-op while a run is in flight or once history is hydrated
   *   - no-op (state stays idle) when no user email resolves — nothing honest to say yet
   *   - marks loading before the first request; every request uses `timeoutMs`
   *   - history is fetched for the hours `getEffectiveHours` returns at the start of this run
   *   - a rejected senders-visible fetch marks failed with the error's message
   *   - a reload requested during this run starts once this run has finished
   *   - never rejects
   */
  async run(): Promise<void> {
    if (this.inFlight || this.stores.notifications.isHistoryHydrated()) return;
    const email = this.getEmail();
    if (email === null || email === "") return;

    this.inFlight = true;
    this.stores.notifications.markHistoryHydrationLoading();
    const effectiveHours = this.getEffectiveHours();
    const timed: NotificationHistoryApiClient = {
      get: <T>(path: string): Promise<T> => this.api.get<T>(path, { timeoutMs: this.timeoutMs }),
    };
    try {
      const records = await timed.get<ServerSenderHydrationRecord[]>(
        `/api/notifications/senders-visible/${encodeURIComponent(email)}`,
      );
      this.stores.sessionStrip.hydrate(records);
      this.stores.senders.hydrate(records);
      await this.stores.notifications.hydrateHistory(timed, {
        userEmail : email,
        effectiveHours,
        senders   : records,
      });
    } catch (err) {
      this.stores.notifications.markHistoryHydrationFailed(err instanceof Error ? err.message : String(err));
    } finally {
      this.inFlight = false;
    }
    if (this.reloadPending) {
      this.reloadPending = false;
      void this.reload();
    }
  }

  async reload(): Promise<void> {
    if (this.inFlight) {
      this.reloadPending = true;   // the in-flight run starts it when it finishes
      return;
    }
    this.stores.notifications.resetHistoryHydration();
    await this.run();
  }

  dispose(): void {
    for (const unsubscribe of this.unsubscribers) unsubscribe();
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the factory declaration line.
export function createColdHistoryHydration(opts: ColdHistoryHydrationOptions): ColdHistoryHydration {
  return new ColdHistoryHydrationImpl(opts);
}
