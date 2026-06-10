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

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface SessionStripStore {
  get(senderId: string): StripSession | undefined;
  list(): ReadonlyArray<StripSession>;
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

    const vp: VoicePersona = {
      name     : (persona.name ?? persona.display_name ?? "") + "",
      voice_id : persona.voice_id ?? "",
      icon     : persona.icon ?? "",
      color    : persona.color ?? "",
      borrowed : persona.borrowed === true,
    };

    const managerPersona = this.extractManagerPersona(n.payload);

    const existing = this.sessions.get(senderId);
    if (existing) {
      // Re-assignment: refresh persona + manager + reactivate. assigned_at is
      // the chronological anchor — keep the original first-seen value so icon
      // ordering stays stable across re-assigns.
      existing.voice_persona = vp;
      existing.active        = true;
      this.setOrClearManager(existing, managerPersona);
      this.emit("updated", senderId);
      return;
    }

    const assignedAt = this.parseAssignedAt(persona.assigned_at);
    const record: StripSession = {
      sender_id     : senderId,
      voice_persona : vp,
      assigned_at   : assignedAt,
      active        : true,
    };
    this.setOrClearManager(record, managerPersona);
    this.sessions.set(senderId, record);
    this.emit("added", senderId);
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

  private extractManagerPersona(payload: Record<string, unknown> | null | undefined): ManagerPersona | null {
    if (!payload) return null;
    const raw = payload["manager_persona"] as ServerManagerPersona | null | undefined;
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

  private emit(changeKind: SessionStripChangeKind, senderId: string): void {
    this.bus.emit<StoreSessionStripChangedPayload>({
      type    : "store_session_strip_changed",
      payload : { changeKind, sender_id: senderId },
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
