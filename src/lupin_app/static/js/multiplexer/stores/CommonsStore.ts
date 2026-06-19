/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane D (WP3, 2026-06-10) — CommonsStore.
//
// Backs the "Recent Activity" commons panel. Ports the data half of the legacy
// `notifications.js` commons-activity subsystem (`_loadCommonsRecentActivity`,
// `_handleCommonsActivityWS`, `_matchesActivityFilter`, the 3-axis filter +
// window state) into the multiplexer store→renderer→transport architecture.
//
// Consumes:
//   - notification_queue_update : the server delivers commons rows INSIDE a
//                                 queue-update frame whose `notification.type`
//                                 is "commons_activity" and whose
//                                 `notification.payload` is the projected entry
//                                 (legacy `case "commons_activity"` sits inside
//                                 the per-notification-type switch). There is NO
//                                 standalone `commons_activity` WS frame, so we
//                                 subscribe to the same event NotificationStore
//                                 does and discriminate on the sub-type.
// Emits:
//   - store_commons_changed { changeKind, matchesFilter? }
// Persists:
//   - lupin:commons:activity-filter envelope (schemaVersion=1)
//     payload shape: { direction, kind, persona }
//
// Hydration (initial load + window change + manual refresh) is an explicit
// `hydrate(api, window)` call — same lazy-fetch pattern as
// `JobStore.hydrateHistory(api)`. The store owns "fetch + cache + emit"; the
// renderer owns "decide when to fetch".

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type {
  CommonsActivityEntry,
  CommonsActivityFilter,
  CommonsActivityWindow,
  CommonsActivityDirection,
  CommonsActivityKind,
  LupinEvent,
  StoreCommonsChangedPayload,
} from "../shared/types";

// ---------------------------------------------------------------------------
// Storage envelope
// ---------------------------------------------------------------------------

const STORAGE_KEY            = "commons:activity-filter";
const STORAGE_SCHEMA_VERSION = 1;

const DEFAULT_WINDOW : CommonsActivityWindow = "today";
const HISTORY_LIMIT  = 200;

function defaultFilter(): CommonsActivityFilter {
  return { direction: null, kind: "all", persona: null };
}

// ---------------------------------------------------------------------------
// Server payload shapes (the subset the store reads).
// ---------------------------------------------------------------------------

// The `notification` field of a `notification_queue_update` frame, narrowed to
// the two fields the commons path needs. `NotificationItem.to_dict()` carries
// `type` + `payload` for commons rows (server `push_notification(...,
// type="commons_activity", payload=entry)`).
interface CommonsQueueNotification {
  type    ?: string;
  payload ?: CommonsActivityEntry;
}

// `notification_queue_update` payload — same envelope NotificationStore reads
// (`{queue_name, value, notification}`); we only touch `notification`.
interface QueueUpdatePayload {
  notification ?: CommonsQueueNotification;
}

// `/api/commons/broadcast-history` response shape
// (`execute_broadcast_history` + the AC2 disabled kill-switch branch).
interface BroadcastHistoryResponse {
  entries  ?: ReadonlyArray<CommonsActivityEntry>;
  disabled ?: boolean;
}

// Loose ApiClient surface for hydrate — CommonsStore only needs `get<T>`.
// Production passes the canonical ApiClient; tests pass a stub.
export interface CommonsHistoryApiClient {
  get<T>(path: string): Promise<T>;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface CommonsStore {
  /** Raw cached entries, newest-first (unfiltered). */
  entries(): ReadonlyArray<CommonsActivityEntry>;
  /** Cached entries passing the active filter, newest-first. */
  visibleEntries(): ReadonlyArray<CommonsActivityEntry>;
  /** Current filter state (defensive copy). */
  getFilter(): CommonsActivityFilter;
  /** Current time-window selection. */
  getWindow(): CommonsActivityWindow;
  /** True when any filter axis is off its default (drives empty-state copy). */
  isFilterActive(): boolean;
  /** True when the server reported the feature flag OFF on the last hydrate. */
  isDisabled(): boolean;
  /** Filter predicate (public so the renderer can decide single-row inserts). */
  matchesFilter(entry: CommonsActivityEntry): boolean;
  /**
   * Fetch `/api/commons/broadcast-history` for `window`, replace the cache, and
   * emit `store_commons_changed{changeKind:"hydrated"}`. Sets the window. On the
   * server kill-switch (`disabled:true`) the cache is cleared and `isDisabled()`
   * flips true. Rejects with the ApiClient error on transport failure (caller
   * floats + .catch like JobsPaneRenderer).
   */
  hydrate(api: CommonsHistoryApiClient, window?: CommonsActivityWindow): Promise<void>;
  setDirection(value: CommonsActivityDirection): void;
  setKind(value: CommonsActivityKind): void;
  setPersona(value: string | null): void;
  /** Test/cleanup helper: detach EventBus listeners. */
  disposeForTesting(): void;
}

export interface CommonsStoreOptions {
  bus     : EventBus;
  storage : StorageService;
  // Test injection — production uses Date.now.
  nowFn?  : () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class CommonsStoreImpl implements CommonsStore {
  private readonly bus     : EventBus;
  private readonly storage : StorageService;
  private readonly nowFn   : () => number;

  private rawEntries : CommonsActivityEntry[] = [];
  private filter     : CommonsActivityFilter;
  private window     : CommonsActivityWindow  = DEFAULT_WINDOW;
  private disabled   : boolean                = false;

  private readonly unsubscribers: Array<() => void> = [];

  constructor(opts: CommonsStoreOptions) {
    this.bus     = opts.bus;
    this.storage = opts.storage;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn   = opts.nowFn ?? (() => Date.now());
    this.filter  = this.hydrateFilter();
    this.subscribe();
  }

  // -------------------------------------------------------------------------
  // Read API
  // -------------------------------------------------------------------------

  entries(): ReadonlyArray<CommonsActivityEntry> {
    return this.rawEntries;
  }

  visibleEntries(): ReadonlyArray<CommonsActivityEntry> {
    return this.rawEntries.filter(e => this.matchesFilter(e));
  }

  getFilter(): CommonsActivityFilter {
    return { ...this.filter };
  }

  getWindow(): CommonsActivityWindow {
    return this.window;
  }

  isFilterActive(): boolean {
    return (
      this.filter.direction !== null ||
      this.filter.kind !== "all" ||
      this.filter.persona !== null
    );
  }

  isDisabled(): boolean {
    return this.disabled;
  }

  // -------------------------------------------------------------------------
  // Filter predicate — Boolean AND across active axes (port of
  // `notifications.js:_matchesActivityFilter`). Any axis at its default
  // contributes no constraint.
  // -------------------------------------------------------------------------

  matchesFilter(entry: CommonsActivityEntry): boolean {
    const topic       = entry.topic || "";
    const meta        = entry.metadata || {};
    const personaName = (entry.persona_name || "").toLowerCase();
    const kind        = this.filter.kind;
    const direction   = this.filter.direction;
    const target      = this.filter.persona;

    // Kind axis
    if (kind === "heartbeats") {
      if (meta["kind"] !== "heartbeat") return false;
    } else if (kind === "personas") {
      if (!topic.startsWith("dm-")) return false;
      if (meta["kind"] === "heartbeat") return false;
    } else if (kind === "broadcasts") {
      if (topic !== "broadcasts" && topic !== "broadcast-acks") return false;
    }
    // kind === "all" → no constraint

    // Direction × Persona — active only when both axes have a value.
    if (direction !== null && target !== null) {
      if (direction === "sender") {
        if (personaName !== target) return false;
      } else {
        // "recipient" — silent no-op when kind === "broadcasts" (broadcasts fan
        // out: no per-recipient topic).
        if (kind !== "broadcasts") {
          const topicSuffix = target.replace(/[^\w-]+/gu, "_");
          if (topic !== "dm-" + topicSuffix) return false;
        }
      }
    }
    return true;
  }

  // -------------------------------------------------------------------------
  // Hydration from REST
  // -------------------------------------------------------------------------

  async hydrate(api: CommonsHistoryApiClient, window?: CommonsActivityWindow): Promise<void> {
    if (window !== undefined) this.window = window;

    const params = new URLSearchParams();
    const hours  = this.windowToHours(this.window);
    if (hours !== null) params.append("hours", String(hours));
    params.append("limit", String(HISTORY_LIMIT));

    const resp = await api.get<BroadcastHistoryResponse>(
      `/api/commons/broadcast-history?${params.toString()}`,
    );

    if (resp.disabled === true) {
      this.disabled   = true;
      this.rawEntries = [];
    } else {
      this.disabled   = false;
      this.rawEntries = [...(resp.entries ?? [])];
    }
    this.emit({ changeKind: "hydrated" });
  }

  // Map window → `hours` query param (port of the legacy dropdown→query shape).
  //   "all"   → null  (no cutoff)
  //   "today" → hours since local midnight (min 1)
  //   "<n>"   → n
  private windowToHours(window: CommonsActivityWindow): number | null {
    if (window === "all") return null;
    if (window === "today") {
      const now      = new Date(this.nowFn());
      const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      return Math.max(1, Math.ceil((now.getTime() - midnight) / 3_600_000));
    }
    return Number(window);
  }

  // -------------------------------------------------------------------------
  // Filter mutators
  // -------------------------------------------------------------------------

  setDirection(value: CommonsActivityDirection): void {
    this.filter.direction = value;
    this.persistFilter();
    this.emit({ changeKind: "filter-changed" });
  }

  setKind(value: CommonsActivityKind): void {
    this.filter.kind = value;
    this.persistFilter();
    this.emit({ changeKind: "filter-changed" });
  }

  setPersona(value: string | null): void {
    this.filter.persona = value ? value.toLowerCase() : null;
    this.persistFilter();
    this.emit({ changeKind: "filter-changed" });
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    for (const off of this.unsubscribers) off();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Subscriptions
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<QueueUpdatePayload>("notification_queue_update", (e) => this.onQueueUpdate(e)),
    );
  }

  private onQueueUpdate(e: LupinEvent<QueueUpdatePayload>): void {
    const notification = e.payload.notification;
    if (!notification || notification.type !== "commons_activity") return;
    const entry = notification.payload;
    if (!entry) return;

    // Always seed the cache so a later filter-clear re-render includes this row.
    this.rawEntries.unshift(entry);
    this.emit({ changeKind: "prepended", matchesFilter: this.matchesFilter(entry) });
  }

  // -------------------------------------------------------------------------
  // Persistence
  // -------------------------------------------------------------------------

  private hydrateFilter(): CommonsActivityFilter {
    const env = this.storage.getJSON<CommonsActivityFilter>(STORAGE_KEY, STORAGE_SCHEMA_VERSION);
    if (env === null) return defaultFilter();
    // Coerce each axis defensively — a corrupt/partial envelope must not poison
    // the predicate (storage layer already rejects malformed schema versions).
    return {
      direction : env.direction === "sender" || env.direction === "recipient" ? env.direction : null,
      kind      : env.kind === "heartbeats" || env.kind === "personas" || env.kind === "broadcasts" ? env.kind : "all",
      persona   : typeof env.persona === "string" && env.persona.length > 0 ? env.persona.toLowerCase() : null,
    };
  }

  private persistFilter(): void {
    this.storage.setJSON<CommonsActivityFilter>(STORAGE_KEY, this.filter, STORAGE_SCHEMA_VERSION);
  }

  // -------------------------------------------------------------------------
  // Emission helper
  // -------------------------------------------------------------------------

  private emit(payload: StoreCommonsChangedPayload): void {
    this.bus.emit<StoreCommonsChangedPayload>({
      type    : "store_commons_changed",
      payload,
      source  : "CommonsStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createCommonsStore(opts: CommonsStoreOptions): CommonsStore {
  return new CommonsStoreImpl(opts);
}
