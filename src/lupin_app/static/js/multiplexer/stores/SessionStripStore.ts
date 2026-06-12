/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer WP2 (parity bridge, 2026-06-10) — SessionStripStore.
//
// Authoritative model for the CC-session strip (the always-on horizontal row
// of per-session persona icons ported from the legacy `notifications.js`
// client). Plain reducer over Map<sender_id, StripSession>.
//
// Why a SEPARATE store from SenderStore: the strip needs two fields SenderStore
// deliberately drops — `manager_persona` (the lineage badge, legacy F11) and
// `assigned_at` (the chronological anchor that locks icon ordering) — plus an
// `active` flag distinguishing a persona-released-but-still-visible icon from
// a reaped-and-gone one. Rather than widen the shared SenderRecord (which would
// ripple into SenderStore + FocusTrayRenderer + two test suites and break lane
// isolation), the strip reduces the SAME wire event independently. Multiple
// stores over one `notification_queue_update` event is the established pattern:
// NotificationStore + SenderStore already both consume it.
//
// Wire contract (mirrors SenderStore's post-2026-04-29-cleanup routing): the
// state-update notification types ride `notification_queue_update` with a
// `notification.type` discriminator, NOT separate top-level events.
//
// Scope (WP2 core): voice_persona_assigned / voice_persona_released /
// session_reaped. The per-session speakerphone "conv-mode" badge and
// localStorage persistence of focus / hide-inactive state are deliberately
// OUT of this core (flagged follow-ons) — they are not in the WP2 AC line and
// the conv-mode semantics (per-session speakerphone vs. single-pin
// conversation mode) need a server-payload reconciliation first.
//
// See: src/rnd/v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/02-bridging-work-plan.md (WP2)

import type { EventBus } from "../shared/EventBus";
import type {
  LupinEvent,
  ManagerPersona,
  SessionStripChangeKind,
  StoreSessionStripChangedPayload,
  StripSession,
  VoicePersona,
} from "../shared/types";

// State-update notification types the strip reacts to. A subset of
// SenderStore's STATE_UPDATE_TYPES — the strip ignores conversation-mode +
// regular-notification events entirely (an icon only ever appears via a
// persona assignment).
const STRIP_STATE_TYPES = new Set<string>([
  "voice_persona_assigned",
  "voice_persona_released",
  "session_reaped",
]);

// Server payload shape for notification_queue_update — same envelope
// SenderStore + NotificationStore consume; the strip only needs the
// `notification` branch.
interface QueueUpdatePayload {
  notification?: ServerNotificationFields;
}

interface ServerNotificationFields {
  type          ?: string;
  sender_id     ?: string;
  timestamp     ?: string;
  voice_persona ?: ServerVoicePersona | null;
  // Generic payload bag — `voice_persona_assigned` carries the spawning
  // manager's persona at `payload.manager_persona` (null/absent for root
  // sessions). Narrowed at the use site.
  payload       ?: Record<string, unknown> | null;
}

// Server persona shape — superset of client VoicePersona. `assigned_at` (ISO
// string, per get_session_info) is the chronological anchor; the index
// signature accommodates the other server-only fields.
interface ServerVoicePersona {
  name         ?: string;
  display_name ?: string;
  voice_id     ?: string;
  icon         ?: string;
  color        ?: string;
  borrowed     ?: boolean;
  released     ?: boolean;
  assigned_at  ?: string;
  [k: string]  : unknown;
}

// Server manager-persona shape (payload.manager_persona). Loose by design —
// the strip extracts the three canonical fields it renders.
interface ServerManagerPersona {
  name        ?: string;
  icon        ?: string;
  color       ?: string;
  [k: string] : unknown;
}

// WP9 cold-reload hydration — one entry from GET
// /api/notifications/senders-visible/{user_email}. The server already
// resolves voice_persona + manager_persona per sender for exactly this gap
// (notifications.py get_visible_senders → _voice_persona_for_sender_id +
// _manager_persona_for_sender_id). `voice_persona` carries `assigned_at`.
// A null voice_persona means no persona assigned → no strip icon (skipped).
//
// Cold-load notification hydration (2026-06-11): this interface is the ONE
// typed shape for a senders-visible row — SenderStore.hydrate and
// NotificationStore.hydrateHistory consume the SAME records from the single
// boot fetch (see boot.ts), so the activity/count fields are typed here
// rather than reached through the index signature.
export interface ServerSenderHydrationRecord {
  sender_id       ?: string;
  last_activity   ?: string;    // ISO timestamp of the sender's newest visible notification
  count           ?: number;    // total visible notifications for this sender
  new_count       ?: number;    // server-side unread count (notification badge seed)
  voice_persona   ?: ServerVoicePersona | null;
  manager_persona ?: ServerManagerPersona | null;
  [k: string]     : unknown;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface SessionStripStore {
  get(senderId: string): StripSession | undefined;
  list(): ReadonlyArray<StripSession>;
  /**
   * WP9 cold-reload hydration — bulk-load strip sessions from a server
   * snapshot (GET /api/notifications/senders-visible/{user_email}). Upserts
   * each record carrying a non-null voice_persona (idempotent; merges with any
   * live events that already arrived) and emits a single "hydrated" change so
   * the renderer reconciles once. Records without a voice_persona (or without
   * a sender_id) are skipped.
   */
  hydrate(records: ReadonlyArray<ServerSenderHydrationRecord>): void;
  /** Test/cleanup helper: detach EventBus listeners. */
  disposeForTesting(): void;
}

export interface SessionStripStoreOptions {
  bus    : EventBus;
  nowFn? : () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class SessionStripStoreImpl implements SessionStripStore {
  private readonly bus   : EventBus;
  private readonly nowFn : () => number;

  private readonly sessions = new Map<string, StripSession>();

  private readonly unsubscribers: Array<() => void> = [];

  constructor(opts: SessionStripStoreOptions) {
    this.bus = opts.bus;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? (() => Date.now());
    this.subscribe();
  }

  get(senderId: string): StripSession | undefined {
    return this.sessions.get(senderId);
  }

  list(): ReadonlyArray<StripSession> {
    return Array.from(this.sessions.values());
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

  // -------------------------------------------------------------------------
  // Reducer
  // -------------------------------------------------------------------------

  private onQueueUpdate(e: LupinEvent<QueueUpdatePayload>): void {
    const n = e.payload.notification;
    if (!n) return;
    const senderId = n.sender_id;
    if (!senderId) return;
    // The strip only reacts to its three state-update types; regular
    // notifications + conversation-mode events are ignored outright.
    if (!n.type || !STRIP_STATE_TYPES.has(n.type)) return;

    if (n.type === "session_reaped") {
      this.handleReaped(senderId);
    } else if (n.type === "voice_persona_released") {
      this.handleReleased(senderId);
    } else {
      this.handleAssigned(senderId, n);
    }
  }

  private handleAssigned(senderId: string, n: ServerNotificationFields): void {
    const persona = n.voice_persona;
    // voice_persona_assigned must carry a present, non-released persona.
    if (!persona || persona.released === true) return;

    const managerPersona = this.normalizeManagerPersona(this.managerPersonaField(n.payload));
    const kind = this.applyAssignment(senderId, persona, managerPersona);
    this.emit(kind, senderId);
  }

  // Shared upsert for both the live voice_persona_assigned path and WP9
  // hydration. Normalizes the persona, creates-or-refreshes the strip session,
  // sets/clears the manager lineage, and returns the change kind. Does NOT
  // emit — the caller decides ("added"/"updated" per-event vs one "hydrated").
  private applyAssignment(
    senderId       : string,
    persona        : ServerVoicePersona,
    managerPersona : ManagerPersona | null,
  ): "added" | "updated" {
    const vp: VoicePersona = {
      name     : (persona.name ?? persona.display_name ?? "") + "",
      voice_id : persona.voice_id ?? "",
      icon     : persona.icon ?? "",
      color    : persona.color ?? "",
      borrowed : persona.borrowed === true,
    };

    const existing = this.sessions.get(senderId);
    if (existing) {
      // Re-assignment: refresh persona + manager + reactivate. assigned_at is
      // the chronological anchor — keep the original first-seen value so icon
      // ordering stays stable across re-assigns.
      existing.voice_persona = vp;
      existing.active        = true;
      this.setOrClearManager(existing, managerPersona);
      return "updated";
    }

    const record: StripSession = {
      sender_id     : senderId,
      voice_persona : vp,
      assigned_at   : this.parseAssignedAt(persona.assigned_at),
      active        : true,
    };
    this.setOrClearManager(record, managerPersona);
    this.sessions.set(senderId, record);
    return "added";
  }

  hydrate(records: ReadonlyArray<ServerSenderHydrationRecord>): void {
    for (const rec of records) {
      const senderId = rec.sender_id;
      if (!senderId) continue;
      const persona = rec.voice_persona;
      // Cold-reload: only sessions WITH a persona get a strip icon (mirrors the
      // live-assign requirement); a null/released persona means inactive/no-icon.
      if (!persona || persona.released === true) continue;
      const managerPersona = this.normalizeManagerPersona(rec.manager_persona);
      this.applyAssignment(senderId, persona, managerPersona);
    }
    // Single emission for the whole snapshot — renderer reconciles from list().
    this.emit("hydrated");
  }

  private handleReleased(senderId: string): void {
    // Persona deallocated: the icon stays (retains last-known persona for
    // display) but flips inactive so the hide-inactive filter can hide it.
    // No-op if we never tracked this sender.
    const record = this.sessions.get(senderId);
    if (!record) return;
    if (!record.active) return;   // already inactive — no spurious emit
    record.active = false;
    this.emit("updated", senderId);
  }

  private handleReaped(senderId: string): void {
    // Reap → drop the icon entirely (legacy `_removeStripIcon`). No-op when the
    // sender was never tracked (a worker reaped before any persona event).
    if (!this.sessions.has(senderId)) return;
    this.sessions.delete(senderId);
    this.emit("removed", senderId);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private managerPersonaField(payload: Record<string, unknown> | null | undefined): ServerManagerPersona | null | undefined {
    if (!payload) return null;
    return payload["manager_persona"] as ServerManagerPersona | null | undefined;
  }

  private normalizeManagerPersona(raw: ServerManagerPersona | null | undefined): ManagerPersona | null {
    if (!raw) return null;
    return {
      name  : (raw.name ?? "") + "",
      icon  : raw.icon ?? "",
      color : raw.color ?? "",
    };
  }

  private setOrClearManager(record: StripSession, managerPersona: ManagerPersona | null): void {
    if (managerPersona !== null) {
      record.manager_persona = managerPersona;
    } else {
      delete record.manager_persona;
    }
  }

  private parseAssignedAt(iso: string | undefined): number {
    if (iso === undefined) return this.nowFn();
    const ms = Date.parse(iso);
    if (Number.isNaN(ms)) return this.nowFn();
    return ms;
  }

  private emit(changeKind: SessionStripChangeKind, senderId?: string): void {
    const payload: StoreSessionStripChangedPayload = { changeKind };
    // "hydrated" carries no single id; added/updated/removed always do.
    if (senderId !== undefined) payload.sender_id = senderId;
    this.bus.emit<StoreSessionStripChangedPayload>({
      type    : "store_session_strip_changed",
      payload,
      source  : "SessionStripStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSessionStripStore(opts: SessionStripStoreOptions): SessionStripStore {
  return new SessionStripStoreImpl(opts);
}
