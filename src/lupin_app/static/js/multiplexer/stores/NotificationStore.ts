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
  StoreNotificationsChangedPayload,
  VoicePersona,
} from "../shared/types";

// Persisted envelope shape (StorageService prepends `lupin:` prefix; key is
// `notifications:unread-count`).
interface UnreadCountEnvelope {
  count       : number;
  lastSeenTs  : number;
}

const STORAGE_KEY            = "notifications:unread-count";
const STORAGE_SCHEMA_VERSION = 1;
const PERSIST_DEBOUNCE_MS    = 250;

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

  // Debounced persistence state.
  private persistTimer : unknown = null;

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
