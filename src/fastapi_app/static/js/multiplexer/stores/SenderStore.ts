/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
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
// speakerphone_changed / conversation_mode_changed) do NOT bump unread /
// last_active — they only mutate state-specific slots.
//
// Phase 6c Node D (Step D1 — 2026-05-19): state-update routing extended
// for conversation-mode events. Path III bridge ratified by Tiberius
// 2026-05-19 (a wire-compat decision, not a scope decision): the reducer
// listens to BOTH `speakerphone_changed` (current server-emitted name;
// payload field `on`) AND `conversation_mode_changed` (post-rename target;
// payload field `active`). Both dispatch to `handleConversationModeUpdate`
// which reads `payload.active ?? payload.on` (nullish-coalesce). The
// single-pin invariant — only one sender may have
// `conversation_mode_active === true` at any time — is enforced
// atomically via dual-emission: prior-pinned cleared FIRST, new-pinned
// set SECOND. Legacy precedent for the dual-name client-side mapping:
// `notifications.js:5552-5567`. The `mic_monopoly` field originally
// designed alongside `conversation_mode_active` was DEFERRED via Path δ
// ratification (Rick, 2026-05-19) — see TODO.md "Phase 6c follow-on:
// mic-monopoly indicator" for the system-wide-semantic question gating
// re-scope.

import type { EventBus } from "../shared/EventBus";
import type {
  LupinEvent,
  SenderChangeKind,
  SenderRecord,
  StoreSendersChangedPayload,
  VoicePersona,
} from "../shared/types";

// State-update notification types — see notifications.py:359 valid_types
// and the 2026-04-29 cleanup design doc. Server-canonical type names
// (post-Phase-3 of the 2026.05.11 speakerphone refactor).
//
// `conversation_mode_changed` is included as the post-rename target name
// per Phase 6c Node D Path III bridge: the multiplexer listens for both
// names so it works pre- and post- a future server-side rename. Today
// only `speakerphone_changed` reaches the wire; that's a known transition
// state and the bridge handles it (see header comment).
// `session_reaped` (added 2026-06-05) is the reap → focus-bar signal: when a
// manager harvests a worker, the producer (Tiberius's `dismiss_sessions`)
// deletes the worker's bridge and emits this state-update with the envelope
// `sender_id` set to the REAPED worker (exactly like `voice_persona_released`).
// The handler removes that sender from the store outright so FocusTrayRenderer
// (which lists `senders.list()` minus the pin) reconciles the badge away —
// the user's visual confirmation that the reap landed.
// See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md
const STATE_UPDATE_TYPES = new Set<string>([
  "voice_persona_assigned",
  "voice_persona_released",
  "speakerphone_changed",
  "conversation_mode_changed",
  "session_reaped",
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
  // Generic payload bag — different notification types carry different
  // shapes (Phase 6c conversation-mode events use `payload.active` /
  // `payload.on` for the mode flag; legacy speakerphone_changed adds
  // optional `payload.displaced` + `payload.displaced_by`). Narrowed at
  // the use site rather than typed here, since this interface spans
  // multiple notification types.
  payload        ?: Record<string, unknown> | null;
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
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
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
      // State-update path — dispatch by type to the slot-specific handler.
      // Conversation-mode events (both `speakerphone_changed` current-wire
      // and `conversation_mode_changed` post-rename) mutate the
      // `conversation_mode_active` slot. Persona events mutate the
      // `voice_persona` slot. `session_reaped` removes the sender outright.
      // None of them bump unread / last_active.
      if (n.type === "session_reaped") {
        this.handleSessionReaped(senderId);
      } else if (n.type === "conversation_mode_changed" || n.type === "speakerphone_changed") {
        this.handleConversationModeUpdate(senderId, n);
      } else {
        this.handlePersonaUpdate(senderId, n.type, n.voice_persona ?? null);
      }
      return;
    }

    // Regular-notification path — lookup-or-create + bump last_active + bump unread.
    const existing = this.senders.get(senderId);
    if (!existing) {
      const record: SenderRecord = {
        sender_id                : senderId,
        display_name             : senderId,        // best default until renderer overrides
        last_active_ts           : ts,
        unread_count             : 1,
        conversation_mode_active : false,           // Phase 6c Node D — default off; flipped by handleConversationModeUpdate
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
        sender_id                : senderId,
        display_name             : senderId,
        last_active_ts           : this.nowFn(),
        unread_count             : 0,
        conversation_mode_active : false,
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

  private handleConversationModeUpdate(
    senderId : string,
    n        : ServerNotificationFields,
  ): void {
    // Path III bridge (see header comment): accept either `payload.active`
    // (post-rename target) or `payload.on` (current `speakerphone_changed`
    // wire field). Nullish-coalesce gives `active` precedence when both
    // are present; coerces undefined/null/missing to `false`.
    const payload = (n.payload ?? {}) as { active?: boolean; on?: boolean };
    const active  = (payload.active ?? payload.on) === true;

    let record = this.senders.get(senderId);
    if (!record) {
      // First time we hear about this sender is a conversation-mode event —
      // create the record. last_active / unread untouched (conv-mode events
      // are state-update, not user-facing arrivals).
      record = {
        sender_id                : senderId,
        display_name             : senderId,
        last_active_ts           : this.nowFn(),
        unread_count             : 0,
        conversation_mode_active : false,
      };
      this.senders.set(senderId, record);
    }

    if (active) {
      // Single-pin invariant via dual-emission: clear any other pinned
      // sender FIRST (each prior-pinned clear emits "updated"), then set
      // this sender's flag (emits "updated"). Server-side mutex normally
      // guarantees at most one prior pin, but the client reconciles
      // defensively in case events arrive out of order.
      for (const [otherId, other] of this.senders) {
        if (otherId !== senderId && other.conversation_mode_active === true) {
          other.conversation_mode_active = false;
          this.emit("updated", otherId);
        }
      }
      if (record.conversation_mode_active !== true) {
        record.conversation_mode_active = true;
        this.emit("updated", senderId);
      }
      return;
    }

    // Deactivation — only emit if state actually changed.
    if (record.conversation_mode_active === true) {
      record.conversation_mode_active = false;
      this.emit("updated", senderId);
    }
  }

  private handleSessionReaped(senderId: string): void {
    // Reap → focus-bar badge drop. The worker named by `senderId` (envelope)
    // was harvested by its manager; remove it from the store entirely and
    // emit a "removed" change so FocusTrayRenderer reconciles its tray badge
    // away. No-op when the sender was never tracked (e.g. a worker that never
    // sent a notification has no badge) — nothing to remove, no spurious emit.
    // See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md
    if (!this.senders.has(senderId)) return;
    this.senders.delete(senderId);
    this.emit("removed", senderId);
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

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSenderStore(opts: SenderStoreOptions): SenderStore {
  return new SenderStoreImpl(opts);
}
