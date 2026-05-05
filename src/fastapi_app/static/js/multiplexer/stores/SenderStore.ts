// Multiplexer Phase 4 — SenderStore.
//
// Plain reducer over Map<sender_id, SenderRecord>. Consumes
// `notification_queue_update` (the server-canonical channel for both regular
// notifications AND custom state-update types per the 2026-04-29 cleanup —
// see `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/`).
//
// Spec drift recorded in execution log § "Spec drifts re-audited at execute
// time": design says subscribe to separate `voice_persona_assigned` /
// `voice_persona_released` events, but post-cleanup these are routed via
// `notification_queue_update` with `notification.type` discriminator. Same
// reducer, different dispatch shape.
//
// Per Pass 1 F3 + alignment with NotificationStore: regular arrivals bump
// unread on every event; no addressed-to-self predicate is feasible
// client-side (no addressee field on the wire). State-update typed
// notifications (voice_persona_assigned / voice_persona_released /
// conversation_mode_changed) do NOT bump unread / last_active — they only
// affect the persona slot.

import type { EventBus } from "../shared/EventBus";
import type {
  LupinEvent,
  SenderChangeKind,
  SenderRecord,
  StoreSendersChangedPayload,
  VoicePersona,
} from "../shared/types";

// State-update notification types — see notifications.py:359 valid_types
// and the 2026-04-29 cleanup design doc.
const STATE_UPDATE_TYPES = new Set<string>([
  "voice_persona_assigned",
  "voice_persona_released",
  "conversation_mode_changed",
]);

// Server payload shape for notification_queue_update — same as
// NotificationStore consumes; SenderStore only needs the `notification`
// branch.
interface QueueUpdatePayload {
  notification?: ServerNotificationFields;
}

interface ServerNotificationFields {
  type           ?: string;
  sender_id      ?: string;
  timestamp      ?: string;
  voice_persona  ?: ServerVoicePersona | null;
}

// Server persona shape — superset of client `VoicePersona`; we extract the
// 5 canonical fields per D-E ratification.
interface ServerVoicePersona {
  name         ?: string;
  display_name ?: string;
  voice_id     ?: string;
  icon         ?: string;
  color        ?: string;
  borrowed     ?: boolean;
  released     ?: boolean;
  [k: string]  : unknown;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface SenderStore {
  get(senderId: string): SenderRecord | undefined;
  list(): ReadonlyArray<SenderRecord>;
  /** Test/cleanup helper: detach EventBus listeners. */
  disposeForTesting(): void;
}

export interface SenderStoreOptions {
  bus    : EventBus;
  nowFn? : () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class SenderStoreImpl implements SenderStore {
  private readonly bus   : EventBus;
  private readonly nowFn : () => number;

  private readonly senders = new Map<string, SenderRecord>();

  private readonly unsubscribers: Array<() => void> = [];

  constructor(opts: SenderStoreOptions) {
    this.bus   = opts.bus;
    this.nowFn = opts.nowFn ?? (() => Date.now());
    this.subscribe();
  }

  get(senderId: string): SenderRecord | undefined {
    return this.senders.get(senderId);
  }

  list(): ReadonlyArray<SenderRecord> {
    return Array.from(this.senders.values());
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

    const ts = n.timestamp ? Date.parse(n.timestamp) : this.nowFn();
    if (Number.isNaN(ts)) return;

    if (n.type && STATE_UPDATE_TYPES.has(n.type)) {
      // State-update path — only touch the persona slot.
      this.handlePersonaUpdate(senderId, n.type, n.voice_persona ?? null);
      return;
    }

    // Regular-notification path — lookup-or-create + bump last_active + bump unread.
    const existing = this.senders.get(senderId);
    if (!existing) {
      const record: SenderRecord = {
        sender_id      : senderId,
        display_name   : senderId,        // best default until renderer overrides
        last_active_ts : ts,
        unread_count   : 1,
      };
      this.senders.set(senderId, record);
      this.emit("added", senderId);
      return;
    }

    existing.last_active_ts = ts;
    existing.unread_count++;
    this.emit("updated", senderId);
  }

  private handlePersonaUpdate(
    senderId : string,
    type     : string,
    persona  : ServerVoicePersona | null,
  ): void {
    let record = this.senders.get(senderId);
    if (!record) {
      // First time we hear about this sender is a persona event — create the
      // record with last_active and unread untouched (persona events don't
      // count as user-facing arrivals).
      record = {
        sender_id      : senderId,
        display_name   : senderId,
        last_active_ts : this.nowFn(),
        unread_count   : 0,
      };
      this.senders.set(senderId, record);
    }

    if (type === "voice_persona_released") {
      delete record.voice_persona;
      this.emit("updated", senderId);
      return;
    }

    // voice_persona_assigned — persona must be present + non-released.
    if (!persona || persona.released === true) return;

    const vp: VoicePersona = {
      name     : (persona.name ?? persona.display_name ?? "") + "",
      voice_id : persona.voice_id ?? "",
      icon     : persona.icon ?? "",
      color    : persona.color ?? "",
      borrowed : persona.borrowed === true,
    };
    record.voice_persona = vp;
    this.emit("updated", senderId);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private emit(changeKind: SenderChangeKind, senderId: string): void {
    this.bus.emit<StoreSendersChangedPayload>({
      type    : "store_senders_changed",
      payload : { changeKind, sender_id: senderId },
      source  : "SenderStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createSenderStore(opts: SenderStoreOptions): SenderStore {
  return new SenderStoreImpl(opts);
}
