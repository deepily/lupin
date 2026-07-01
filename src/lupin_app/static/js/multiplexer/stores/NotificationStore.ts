/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 4 — NotificationStore.
//
// Plain reducer (no XState per Q6 — append-mostly list with expiry sweep).
// Consumes:
//   - notification_queue_update : new-notification arrival (when payload.notification present)
//                                 OR queue resync (when only payload.unplayed_count present)
//   - notification_responded    : mark responded=true on matching id_hash
//   - notification_expired      : move from active to history (idempotent)
//   - sys_time_update           : local expiry sweep — any active item with
//                                 expires_at < now moves to history with
//                                 source: "local-sweep"
// Emits:
//   - store_notifications_changed { changeKind, id_hash?, source? }
// Persists:
//   - lupin:notifications:unread-count envelope (schemaVersion=1)
//     payload shape: {count: number, lastSeenTs: number}
//     250ms tail debounce on writes (per Pass 1 F5).
//
// Spec drift recorded in execution log § "Spec drifts re-audited at execute
// time": design says subscribe to `notification_received` but server-canonical
// event is `notification_queue_update` with payload `{notification: {...}}`.
// Field normalization: server `timestamp` (ISO string) → client `ts` (ms
// epoch); server `response_requested` → client `action_required`.
//
// Per P1 Option C ratification 2026-05-04 PM: server replay on auth_success
// is NOT implemented; active list starts empty on construct + populates from
// live events from auth_success onward. Reload loses in-flight active list.
// Promotion to server replay or full-list persistence tracked in TODO.md
// § "✅ Q2 OPTION C RATIFIED — P1 server-replay deferred".

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type {
  LupinEvent,
  Notification,
  NotificationChangeKind,
  NotificationFilterMode,
  PredictionHint,
  SessionTopicPayload,
  StoreNotificationsChangedPayload,
  VoicePersona,
} from "../shared/types";
// Cold-load hydration (2026-06-11): type-only import of the ONE canonical
// senders-visible row shape (SessionStripStore owns the definition — WP9
// introduced it; SenderStore + this store consume the SAME records from the
// single boot fetch). No runtime coupling.
import type { ServerSenderHydrationRecord } from "./SessionStripStore";

// Persisted envelope shape (StorageService prepends `lupin:` prefix; key is
// `notifications:unread-count`).
interface UnreadCountEnvelope {
  count       : number;
  lastSeenTs  : number;
}

const STORAGE_KEY            = "notifications:unread-count";
const STORAGE_SCHEMA_VERSION = 1;
const PERSIST_DEBOUNCE_MS    = 250;

// B3 (01-C) — own-only notification filter persistence (mirrors CommonsStore's
// activity-filter envelope). The mode persists across reload via StorageService.
const FILTER_STORAGE_KEY     = "notifications:filter-mode";
const FILTER_SCHEMA_VERSION  = 1;
const DEFAULT_FILTER_MODE: NotificationFilterMode = "own";

interface FilterModeEnvelope {
  mode : NotificationFilterMode;
}

// B3 (01-C) — the filter predicate, keyed on the ONE client-available axis
// (`direction`), per the Mr. Radio 2026-06-29 axis ruling. PURE + exported so
// every mode branch is directly unit-coverable (only "own" is UI-wired today).
//   - own    : inbound persona messages — direction absent/"incoming"
//   - others : the user's own sent replies — direction === "outgoing"
//   - all    : pass everything
// (Single-user mux ⇒ recipient-based own/others is vacuous; `direction` is the
// non-vacuous axis. A future real axis swaps in here with zero plumbing rework.)
export function matchesNotificationFilter( n: Notification, mode: NotificationFilterMode ): boolean {
  if ( mode === "all" )    return true;
  if ( mode === "others" ) return n.direction === "outgoing";
  // mode === "own"
  return n.direction !== "outgoing";
}

// ---------------------------------------------------------------------------
// Cold-load history hydration (2026-06-11) — supporting types + window helper.
// Design: src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md
// ---------------------------------------------------------------------------

// Loose ApiClient surface for hydrateHistory — this store only needs `get<T>`
// (mirrors JobStore's JobHistoryApiClient). Production passes the canonical
// ApiClient; tests pass a stub.
export interface NotificationHistoryApiClient {
  get<T>(path: string): Promise<T>;
}

export interface HydrateHistoryOptions {
  userEmail      : string;
  // Rolling window in hours (DEFAULT_HISTORY_WINDOW_HOURS for the silent
  // classic-parity default).
  effectiveHours : number;
  // The boot-time senders-visible snapshot — the SAME records the strip and
  // SenderStore hydrate from (single fetch, three consumers).
  senders        : ReadonlyArray<ServerSenderHydrationRecord>;
}

// One row from GET /api/notifications/conversation-by-date/{sender}/{email}
// (notifications.py get_sender_conversation_by_date serialization). DB-null
// optionals arrive as null, not undefined — the normalizer copies only
// string values through.
interface ServerHistoryRow {
  id                ?: string;          // DB row UUID — the cross-surface identity key
  sender_id         ?: string;
  message           ?: string;
  title             ?: string | null;
  abstract          ?: string | null;
  timestamp         ?: string;          // ISO, app-timezone
  time_display      ?: string | null;
  progress_group_id ?: string | null;
  [k: string]       : unknown;
}

// Classic-verbatim VIRGIN default for the history window — notifications.js:360
// (`parseInt( storedWindow ) || 48`). Ruling amended 2026-06-11 post-review
// (Tiberius, reviewer Rio): classic's virgin default is a 48h ROLLING window;
// 'today' is only a stored-sentinel option a user can pick later. 48h also
// covers the originally-reported case — a pre-midnight external advisory must
// still card the next morning — and moots the e2e midnight-straddle flake a
// today-anchored window would have had. Silent default per ruling (a): no
// selector, no localStorage key.
export const DEFAULT_HISTORY_WINDOW_HOURS = 48;

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface NotificationStore {
  /** Active notifications (not expired, not in history). */
  list(): ReadonlyArray<Notification>;
  /** Expired or otherwise archived notifications. */
  history(): ReadonlyArray<Notification>;
  /** Count of notifications not yet acknowledged by the user. */
  unreadCount(): number;
  /** Mark a specific notification as read (decrements unread_count). */
  markRead(idHash: string): void;
  /** Mark every active notification as read in one shot (e.g. inbox open). */
  markAllRead(): void;
  /**
   * B3 (01-C) — active notifications passing the current filter mode (the
   * render source for the sender section). `list()` stays the raw total.
   */
  visibleEntries(): ReadonlyArray<Notification>;
  /** B3 (01-C) — the active filter mode. */
  filterMode(): NotificationFilterMode;
  /**
   * B3 (01-C) — set the filter mode, persist it (StorageService), and emit
   * `store_notifications_changed { changeKind: "filtered" }` so the renderer
   * re-renders from `visibleEntries()`. (UI to call this is DEFERRED per Rick's
   * scope — the mechanism is wired, only "own" is reachable today.)
   */
  setFilterMode( mode: NotificationFilterMode ): void;
  /** B3 (01-C) — true when the mode is off its "own" default (drives empty-state copy). */
  isFilterActive(): boolean;
  /**
   * B3 (01-C) — remove the given notifications from the active list (the
   * clear-all primitive). The header renderer deletes each id server-side
   * (DELETE /api/notifications/{id_hash}) over `visibleEntries()` THEN calls
   * this with the SUCCESSFULLY-deleted ids only (partial-failure safe — failed
   * ids stay in the store). Emits one `store_notifications_changed { "removed" }`.
   * Unknown ids are skipped. (Realizes F-Krishna-BC3's clearAll() as the
   * filter-scoped, partial-failure-correct removal Rick's ruling requires.)
   */
  removeByIdHashes( idHashes: ReadonlyArray<string> ): void;
  /**
   * Cold-load history hydration (2026-06-11) — fetch each in-window sender's
   * conversation-by-date history and bulk-seed the active list, then emit a
   * single `store_notifications_changed { changeKind: "hydrated" }`.
   *
   * Contract (per the design note §2/§4):
   *   - senders outside the window (last_activity older than effectiveHours,
   *     or missing/unparseable) are skipped
   *   - per-sender fetch failures are skipped (best-effort; never rejects)
   *   - rows whose id already exists in the store are skipped (live-first
   *     wins; the reverse order — hydrate-first, live re-arrival — is handled
   *     by onQueueUpdate's existing idempotent-re-arrival branch)
   *   - seeded rows NEVER bump unread, NEVER set expires_at, and force
   *     action_required=false (historical rows are conversation history,
   *     never live prompts)
   *   - idempotent: a second call is a no-op (isHistoryHydrated guard)
   */
  hydrateHistory(api: NotificationHistoryApiClient, opts: HydrateHistoryOptions): Promise<void>;
  isHistoryHydrated(): boolean;
  /** Test/cleanup helper: flush any pending persistence write immediately. */
  flushPersistenceForTesting(): void;
  /** Test/cleanup helper: cancel any pending persistence timer. */
  disposeForTesting(): void;
}

export interface NotificationStoreOptions {
  bus     : EventBus;
  storage : StorageService;
  // Test injection — production uses globalThis.setTimeout.
  setTimeoutFn?    : (cb: () => void, ms: number) => unknown;
  clearTimeoutFn?  : (id: unknown) => void;
  // Test injection — production uses Date.now.
  nowFn?           : () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

interface QueueUpdatePayload {
  queue_name      ?: string;
  value           ?: number;
  // Optional `notification` field signals "new notification arrived" path.
  notification    ?: ServerNotificationFields;
  // Optional `unplayed_count` signals queue resync (count-only update).
  unplayed_count  ?: number;
}

// Subset of server NotificationItem.to_dict() fields the store reads.
// Server-side defined in `src/cosa/rest/notification_fifo_queue.py:173`.
interface ServerNotificationFields {
  id_hash             ?: string;
  id                  ?: string;
  message             ?: string;
  title               ?: string;
  sender_id           ?: string;
  // R5 (2026-07-01) — control-notification discriminator + payload. The server
  // sends `notification_type` (legacy reads `type || notification_type`,
  // notifications.js:5855); neither survives normalize(), so the session_topic
  // intercept reads them off the RAW field here, before normalization.
  notification_type   ?: string;
  type                ?: string;
  session_name        ?: string;
  timestamp           ?: string;       // ISO string — normalized to ms epoch
  response_requested  ?: boolean;       // → action_required
  response_type       ?: Notification["response_type"];
  response_options    ?: ReadonlyArray<string>;
  response_default    ?: string;
  timeout_seconds     ?: number;        // when present, sets expires_at
  // Phase 5 D-B (2026-05-05) — server-emitted renderer-surfaced fields.
  voice_persona       ?: VoicePersona;
  abstract            ?: string;
  progress_group_id   ?: string;
  was_expired         ?: boolean;
  time_display        ?: string;
  prediction_hint     ?: PredictionHint;   // WP14 (F8) — thumbs-vote training-signal source
}

interface ResponsePayload {
  id_hash         ?: string;
  notification_id ?: string;            // legacy alt
  response        ?: string;
}

interface ExpiredPayload {
  id_hash         ?: string;
  notification_id ?: string;
}

class NotificationStoreImpl implements NotificationStore {
  private readonly bus            : EventBus;
  private readonly storage        : StorageService;
  private readonly setTimeoutFn   : (cb: () => void, ms: number) => unknown;
  private readonly clearTimeoutFn : (id: unknown) => void;
  private readonly nowFn          : () => number;

  private active   : Notification[]                = [];
  private archived : Notification[]                = [];
  private byId     : Map<string, Notification>     = new Map();
  // Tracks read state per id_hash so unread_count is recomputed deterministically.
  private readSet  : Set<string>                   = new Set();
  private unread   : number                        = 0;
  // B3 (01-C) — active notification-filter mode (StorageService-persisted).
  private filterModeState : NotificationFilterMode = DEFAULT_FILTER_MODE;

  // Debounced persistence state.
  private persistTimer : unknown = null;

  // Cold-load history hydration guard (JobStore.historyHydrated precedent).
  private historyHydrated = false;

  // Subscriptions (kept so dispose can unwire if ever needed; primarily used
  // by the lifetime-of-store assumption).
  private readonly unsubscribers : Array<() => void> = [];

  constructor(opts: NotificationStoreOptions) {
    this.bus            = opts.bus;
    this.storage        = opts.storage;
    /* c8 ignore next */ // production-default fallback: globalThis.setTimeout is the runtime browser timer; tests always inject a fake setTimeoutFn for deterministic debounce control.
    this.setTimeoutFn   = opts.setTimeoutFn   ?? ((cb, ms) => globalThis.setTimeout(cb, ms));
    /* c8 ignore next */ // production-default fallback: globalThis.clearTimeout pairs with the setTimeout default above; tests always inject the fake.
    this.clearTimeoutFn = opts.clearTimeoutFn ?? ((id) => globalThis.clearTimeout(id as number));
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn          = opts.nowFn          ?? (() => Date.now());

    this.filterModeState = this.hydrateFilterMode();
    this.hydrate();
    this.subscribe();
  }

  list(): ReadonlyArray<Notification> {
    return this.active;
  }

  history(): ReadonlyArray<Notification> {
    return this.archived;
  }

  unreadCount(): number {
    return this.unread;
  }

  markRead(idHash: string): void {
    if (this.readSet.has(idHash)) return;
    if (!this.byId.has(idHash))   return;
    this.readSet.add(idHash);
    if (this.unread > 0) this.unread--;
    this.schedulePersist();
    this.emit("updated", idHash);
  }

  markAllRead(): void {
    if (this.unread === 0) return;
    for (const n of this.active) {
      this.readSet.add(n.id_hash);
    }
    this.unread = 0;
    this.schedulePersist();
    // Single emission for the bulk operation; payload omits id_hash.
    this.bus.emit<StoreNotificationsChangedPayload>({
      type    : "store_notifications_changed",
      payload : { changeKind: "updated" },
      source  : "NotificationStore",
      ts      : this.nowFn(),
    });
  }

  // -------------------------------------------------------------------------
  // B3 (01-C) — own-only notification filter + clear-all primitive
  // -------------------------------------------------------------------------

  visibleEntries(): ReadonlyArray<Notification> {
    return this.active.filter(n => matchesNotificationFilter(n, this.filterModeState));
  }

  filterMode(): NotificationFilterMode {
    return this.filterModeState;
  }

  setFilterMode(mode: NotificationFilterMode): void {
    this.filterModeState = mode;
    this.persistFilterMode();
    // Full re-render signal — the renderer's store_notifications_changed
    // subscription re-reads visibleEntries() (F-Sam-BC2: no stale cards).
    this.bus.emit<StoreNotificationsChangedPayload>({
      type    : "store_notifications_changed",
      payload : { changeKind: "filtered" },
      source  : "NotificationStore",
      ts      : this.nowFn(),
    });
  }

  isFilterActive(): boolean {
    return this.filterModeState !== DEFAULT_FILTER_MODE;
  }

  removeByIdHashes(idHashes: ReadonlyArray<string>): void {
    let removedAny = false;
    for (const idHash of idHashes) {
      const idx = this.active.findIndex(n => n.id_hash === idHash);
      if (idx < 0) continue;   // unknown / already-gone id — skip (partial-failure safe)
      this.active.splice(idx, 1);
      this.byId.delete(idHash);
      // Unread bookkeeping: a removed item that was never read stops counting.
      if (!this.readSet.has(idHash) && this.unread > 0) this.unread--;
      this.readSet.delete(idHash);
      removedAny = true;
    }
    if (!removedAny) return;   // nothing matched — no persist, no emit
    this.schedulePersist();
    this.bus.emit<StoreNotificationsChangedPayload>({
      type    : "store_notifications_changed",
      payload : { changeKind: "removed" },
      source  : "NotificationStore",
      ts      : this.nowFn(),
    });
  }

  async hydrateHistory(api: NotificationHistoryApiClient, opts: HydrateHistoryOptions): Promise<void> {
    if (this.historyHydrated) return;

    // Window filter — client-side equivalent of classic's server-side `hours`
    // on senders-visible (the param only drops senders by last_activity
    // cutoff; counts are unaffected — design note §1 window-equivalence).
    const cutoffMs = this.nowFn() - opts.effectiveHours * 3_600_000;
    const inWindow = opts.senders.filter(rec => {
      if (!rec.sender_id) return false;
      const ts = rec.last_activity !== undefined ? Date.parse(rec.last_activity) : Number.NaN;
      return !Number.isNaN(ts) && ts >= cutoffMs;
    });

    // Per-sender conversation fetch, classic-mirroring params: `hours` =
    // effective window, `anchor` = the sender's last_activity (classic's
    // activity-anchored window loading).
    const fetches = inWindow.map(rec => {
      const base   = `/api/notifications/conversation-by-date/${encodeURIComponent(rec.sender_id as string)}/${encodeURIComponent(opts.userEmail)}`;
      const params = new URLSearchParams();
      params.append("hours", String(opts.effectiveHours));
      params.append("anchor", rec.last_activity as string);
      return api.get<Record<string, ReadonlyArray<ServerHistoryRow>>>(`${base}?${params.toString()}`);
    });

    // Best-effort batch: a rejected sender fetch is skipped, the rest seed.
    const settled = await Promise.allSettled(fetches);
    const rows: Notification[] = [];
    for (const result of settled) {
      if (result.status !== "fulfilled") continue;
      for (const dateRows of Object.values(result.value)) {
        for (const raw of dateRows) {
          const norm = this.normalizeHistoryRow(raw);
          if (!norm) continue;
          if (this.byId.has(norm.id_hash)) continue;   // live-first wins
          rows.push(norm);
          // WS2 / C2-d (D3): load-time responded-split. A responded history row
          // carries the user's answer in `response_value.value`; expand it into
          // a synthetic `{id}-response` OUTGOING bubble immediately after the
          // incoming prompt (mirrors legacy notifications.js:14317-14330). This
          // is the F5-independent half — it consumes the answer the server
          // already persisted; the live echo of a freshly-sent reply is F5.
          const outgoing = this.buildOutgoingResponse(raw, norm);
          if (outgoing && !this.byId.has(outgoing.id_hash)) rows.push(outgoing);
        }
      }
    }

    // Seed ascending by ts (cosmetic — the card template re-sorts per date
    // bucket internally; this just keeps active[] roughly chronological).
    rows.sort((a, b) => a.ts - b.ts);
    for (const n of rows) {
      this.active.push(n);
      this.byId.set(n.id_hash, n);
    }

    // NO unread mutation, NO persistence — the localStorage envelope and the
    // per-sender new_count (SenderStore.hydrate) own unread accounting.

    this.historyHydrated = true;
    // Single emission for the whole snapshot — renderer reconciles once.
    this.bus.emit<StoreNotificationsChangedPayload>({
      type    : "store_notifications_changed",
      payload : { changeKind: "hydrated" },
      source  : "NotificationStore",
      ts      : this.nowFn(),
    });
  }

  isHistoryHydrated(): boolean {
    return this.historyHydrated;
  }

  flushPersistenceForTesting(): void {
    if (this.persistTimer !== null) {
      this.clearTimeoutFn(this.persistTimer);
      this.persistTimer = null;
      this.persistNow();
    }
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    if (this.persistTimer !== null) {
      this.clearTimeoutFn(this.persistTimer);
      this.persistTimer = null;
    }
    for (const off of this.unsubscribers) off();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Hydration on construct
  // -------------------------------------------------------------------------

  private hydrate(): void {
    const env = this.storage.getJSON<UnreadCountEnvelope>(STORAGE_KEY, STORAGE_SCHEMA_VERSION);
    if (env !== null && typeof env.count === "number" && env.count >= 0) {
      this.unread = env.count;
    }
    // Emit a "hydrated" change so renderers can paint the unread badge from
    // localStorage immediately, without waiting for the first WS frame.
    this.bus.emit<StoreNotificationsChangedPayload>({
      type    : "store_notifications_changed",
      payload : { changeKind: "hydrated" },
      source  : "NotificationStore",
      ts      : this.nowFn(),
    });
  }

  // -------------------------------------------------------------------------
  // Subscriptions
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<QueueUpdatePayload>("notification_queue_update", (e) => this.onQueueUpdate(e)),
    );
    this.unsubscribers.push(
      this.bus.on<ResponsePayload>("notification_responded", (e) => this.onResponded(e)),
    );
    this.unsubscribers.push(
      this.bus.on<ExpiredPayload>("notification_expired", (e) => this.onExpired(e)),
    );
    this.unsubscribers.push(
      this.bus.on<{ ts?: number }>("sys_time_update", () => this.sweepExpired()),
    );
  }

  // -------------------------------------------------------------------------
  // Reducers
  // -------------------------------------------------------------------------

  private onQueueUpdate(e: LupinEvent<QueueUpdatePayload>): void {
    const env = e.payload;
    if (!env.notification) {
      // Resync-only update — server reports queue_size + unplayed_count but
      // no new notification. We do NOT trust the server's unplayed_count over
      // our local readSet bookkeeping (different semantics: server-side
      // "played" vs client-side "user acknowledged"). No-op.
      return;
    }
    // R5 — `session_topic` is control metadata, not a message: route the name
    // to SenderStore via the bus and DO NOT card it (legacy notifications.js:5862
    // "skip history card"). The discriminator + session_name are raw-only fields
    // (dropped by normalize()), so intercept here, BEFORE normalization.
    const raw  = env.notification;
    const kind = raw.notification_type ?? raw.type;
    if (kind === "session_topic") {
      if (raw.sender_id !== undefined && raw.session_name !== undefined) {
        this.bus.emit<SessionTopicPayload>({
          type   : "session_topic",
          payload: { sender_id: raw.sender_id, session_name: raw.session_name },
          source : "notification-store",
          ts     : this.nowFn(),
        });
      }
      return;
    }
    const norm = this.normalize(env.notification);
    if (!norm) return;

    if (this.byId.has(norm.id_hash)) {
      // Idempotent re-arrival — server may re-emit on reconnect. Don't dupe
      // unread count; emit "updated" so renderer can repaint timestamps.
      this.byId.set(norm.id_hash, norm);
      // Replace in active array preserving position.
      const idx = this.active.findIndex(n => n.id_hash === norm.id_hash);
      if (idx >= 0) this.active[idx] = norm;
      this.emit("updated", norm.id_hash);
      return;
    }

    this.active.push(norm);
    this.byId.set(norm.id_hash, norm);
    // Per Pass 1 F3: every arrival bumps unread (no addressed-to-self
    // discrimination is feasible client-side without an addressee field).
    this.unread++;
    this.schedulePersist();
    this.emit("added", norm.id_hash);
  }

  private onResponded(e: LupinEvent<ResponsePayload>): void {
    const id = e.payload.id_hash ?? e.payload.notification_id;
    if (!id) return;
    const n = this.byId.get(id);
    if (!n) return;
    if (n.responded) return;

    const updated: Notification = { ...n, responded: true };
    this.byId.set(id, updated);
    const idx = this.active.findIndex(x => x.id_hash === id);
    if (idx >= 0) this.active[idx] = updated;
    this.emit("updated", id);
  }

  private onExpired(e: LupinEvent<ExpiredPayload>): void {
    const id = e.payload.id_hash ?? e.payload.notification_id;
    if (!id) return;
    this.expireToHistory(id, undefined);
  }

  private sweepExpired(): void {
    const now = this.nowFn();
    for (const n of [...this.active]) {   // snapshot — expireToHistory mutates active
      if (n.expires_at !== undefined && n.expires_at < now) {
        this.expireToHistory(n.id_hash, "local-sweep");
      }
    }
  }

  private expireToHistory(idHash: string, source: "local-sweep" | undefined): void {
    if (!this.byId.has(idHash)) return;
    // Was it already in history? Idempotent if the active array doesn't
    // contain it any more.
    const idx = this.active.findIndex(n => n.id_hash === idHash);
    if (idx < 0) return;
    const n = this.active[idx] as Notification;
    this.active.splice(idx, 1);
    this.archived.push(n);
    // The byId map retains the entry — history queries can still look up by id.

    // Unread bookkeeping: an item moving to history shouldn't keep counting
    // toward unread. If it wasn't in readSet, decrement unread.
    if (!this.readSet.has(idHash) && this.unread > 0) {
      this.unread--;
      this.schedulePersist();
    }

    if (source) {
      this.bus.emit<StoreNotificationsChangedPayload>({
        type    : "store_notifications_changed",
        payload : { changeKind: "expired", id_hash: idHash, source },
        source  : "NotificationStore",
        ts      : this.nowFn(),
      });
    } else {
      this.emit("expired", idHash);
    }
  }

  // -------------------------------------------------------------------------
  // Field normalization (server contract → client interface)
  // -------------------------------------------------------------------------

  // Hydration variant of normalize() for conversation-by-date rows. Differs
  // deliberately from the live normalizer (design note §2):
  //   - identity comes from the DB row `id` (the cross-surface dedupe key)
  //   - action_required is FORCED false — historical action-required rows
  //     (state responded/expired) paint as plain conversation messages and
  //     never resurrect in the live AR pane
  //   - expires_at is NEVER set — historical rows must not feed the
  //     sys_time_update local sweep
  //   - DB-null optionals (title/abstract/progress_group_id/time_display
  //     arrive as null) are copied only when they are strings
  private normalizeHistoryRow(raw: ServerHistoryRow): Notification | null {
    if (!raw.id || typeof raw.id !== "string") return null;
    if (!raw.message || typeof raw.message !== "string") return null;

    const ts = raw.timestamp ? Date.parse(raw.timestamp) : Number.NaN;
    if (Number.isNaN(ts)) return null;

    const norm: Notification = {
      id_hash         : raw.id,
      ts,
      sender_id       : typeof raw.sender_id === "string" ? raw.sender_id : "",
      message         : raw.message,
      action_required : false,
    };
    if (typeof raw.title === "string")             norm.title             = raw.title;
    if (typeof raw.abstract === "string")          norm.abstract          = raw.abstract;
    if (typeof raw.progress_group_id === "string") norm.progress_group_id = raw.progress_group_id;
    if (typeof raw.time_display === "string")      norm.time_display      = raw.time_display;
    return norm;
  }

  // WS2 / C2-d (D3): build the synthetic OUTGOING reply for a responded history
  // row, mirroring legacy notifications.js:14317-14330 — the user's answer in
  // `response_value.value` becomes a `{id}-response` outgoing bubble timestamped
  // at `responded_at` (falls back to the prompt's ts). Returns null for the
  // common prompt-only case (no/empty response value), so non-responded rows are
  // untouched. `incoming` is the already-normalized prompt (supplies sender_id +
  // the id_hash stem + the ts fallback).
  private buildOutgoingResponse(raw: ServerHistoryRow, incoming: Notification): Notification | null {
    const rv = raw.response_value;
    const value = rv !== null && typeof rv === "object" && typeof (rv as { value?: unknown }).value === "string"
      ? (rv as { value: string }).value
      : "";
    if (value === "") return null;
    const respondedAt = typeof raw.responded_at === "string" ? Date.parse(raw.responded_at) : Number.NaN;
    return {
      id_hash         : `${incoming.id_hash}-response`,
      ts              : Number.isNaN(respondedAt) ? incoming.ts : respondedAt,
      sender_id       : incoming.sender_id,
      message         : value,
      action_required : false,
      direction       : "outgoing",
    };
  }

  private normalize(raw: ServerNotificationFields): Notification | null {
    const id_hash = raw.id_hash ?? raw.id;
    if (!id_hash || typeof id_hash !== "string") return null;
    if (!raw.message || typeof raw.message !== "string") return null;

    const ts = raw.timestamp ? Date.parse(raw.timestamp) : this.nowFn();
    if (Number.isNaN(ts)) return null;

    const norm: Notification = {
      id_hash,
      ts,
      sender_id       : raw.sender_id ?? "",
      message         : raw.message,
      action_required : raw.response_requested === true,
    };
    if (raw.title !== undefined)            norm.title         = raw.title;
    if (raw.response_type !== undefined)    norm.response_type = raw.response_type;
    if (raw.response_options)               norm.options       = raw.response_options;
    if (raw.response_default !== undefined) norm.default_value = raw.response_default;
    if (raw.timeout_seconds !== undefined && raw.response_requested === true) {
      norm.expires_at = ts + raw.timeout_seconds * 1000;
    }
    // Phase 5 D-B (2026-05-05) — copy renderer-surfaced fields when present.
    if (raw.voice_persona !== undefined)     norm.voice_persona     = raw.voice_persona;
    if (raw.abstract !== undefined)          norm.abstract          = raw.abstract;
    if (raw.progress_group_id !== undefined) norm.progress_group_id = raw.progress_group_id;
    if (raw.was_expired !== undefined)       norm.was_expired       = raw.was_expired;
    if (raw.time_display !== undefined)      norm.time_display      = raw.time_display;
    if (raw.prediction_hint !== undefined)   norm.prediction_hint   = raw.prediction_hint;
    return norm;
  }

  // -------------------------------------------------------------------------
  // Persistence (debounced)
  // -------------------------------------------------------------------------

  private schedulePersist(): void {
    if (this.persistTimer !== null) {
      this.clearTimeoutFn(this.persistTimer);
    }
    this.persistTimer = this.setTimeoutFn(() => {
      this.persistTimer = null;
      this.persistNow();
    }, PERSIST_DEBOUNCE_MS);
  }

  private persistNow(): void {
    const env: UnreadCountEnvelope = {
      count      : this.unread,
      lastSeenTs : this.nowFn(),
    };
    this.storage.setJSON<UnreadCountEnvelope>(STORAGE_KEY, env, STORAGE_SCHEMA_VERSION);
  }

  // B3 (01-C) — filter-mode persistence (mirrors CommonsStore.hydrateFilter /
  // persistFilter). A missing/corrupt/invalid envelope degrades to the "own"
  // default rather than throwing.
  private hydrateFilterMode(): NotificationFilterMode {
    const env = this.storage.getJSON<FilterModeEnvelope>(FILTER_STORAGE_KEY, FILTER_SCHEMA_VERSION);
    if (env !== null && (env.mode === "own" || env.mode === "others" || env.mode === "all")) {
      return env.mode;
    }
    return DEFAULT_FILTER_MODE;
  }

  private persistFilterMode(): void {
    this.storage.setJSON<FilterModeEnvelope>(
      FILTER_STORAGE_KEY, { mode: this.filterModeState }, FILTER_SCHEMA_VERSION,
    );
  }

  // -------------------------------------------------------------------------
  // Single-id emission helper
  // -------------------------------------------------------------------------

  private emit(changeKind: NotificationChangeKind, idHash: string): void {
    this.bus.emit<StoreNotificationsChangedPayload>({
      type    : "store_notifications_changed",
      payload : { changeKind, id_hash: idHash },
      source  : "NotificationStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Factory — production code constructs via createNotificationStore.
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createNotificationStore(opts: NotificationStoreOptions): NotificationStore {
  return new NotificationStoreImpl(opts);
}
