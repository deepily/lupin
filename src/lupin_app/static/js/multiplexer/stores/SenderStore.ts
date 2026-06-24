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
// Cold-load hydration (2026-06-11): type-only import of the ONE canonical
// senders-visible row shape — SessionStripStore owns the definition because
// WP9 introduced it; both stores consume the SAME records from the single
// boot fetch. No runtime coupling.
import type { ServerSenderHydrationRecord } from "./SessionStripStore";

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
  /**
   * Cold-load hydration (2026-06-11) — bulk-seed sender records from the
   * boot-time senders-visible snapshot (same records the strip hydrates from).
   * Merge is NEVER-REGRESS: a live event may have arrived before the snapshot
   * resolved, so hydration only fills forward — `last_active_ts` and
   * `unread_count` take max(existing, snapshot), `voice_persona` is set only
   * when absent, `conversation_mode_active` and `display_name` are untouched.
   * Records without a sender_id are skipped. Emits a single
   * `store_senders_changed { changeKind: "hydrated" }` for the whole snapshot.
   */
  hydrate(records: ReadonlyArray<ServerSenderHydrationRecord>): void;
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

  hydrate(records: ReadonlyArray<ServerSenderHydrationRecord>): void {
    for (const rec of records) {
      const senderId = rec.sender_id;
      if (!senderId) continue;

      const parsedActivity = rec.last_activity !== undefined ? Date.parse(rec.last_activity) : Number.NaN;
      const activityTs     = Number.isNaN(parsedActivity) ? 0 : parsedActivity;
      const newCount       = typeof rec.new_count === "number" && rec.new_count > 0 ? rec.new_count : 0;

      let record = this.senders.get(senderId);
      if (!record) {
        record = {
          sender_id                : senderId,
          display_name             : senderId,
          last_active_ts           : activityTs,
          unread_count             : newCount,
          conversation_mode_active : false,
        };
        this.senders.set(senderId, record);
      } else {
        // Never-regress merge — see interface docstring.
        record.last_active_ts = Math.max(record.last_active_ts, activityTs);
        record.unread_count   = Math.max(record.unread_count, newCount);
      }

      const persona = rec.voice_persona;
      if (record.voice_persona === undefined && persona && persona.released !== true) {
        record.voice_persona = this.normalizeVoicePersona(persona);
      }

      // Worker-badge silencing (Rick 2026-06-24): cold-load rows carry the
      // manager lineage at `rec.manager_persona` (same field SessionStripStore
      // hydrates from). Fill-forward only — set is_worker when the snapshot says
      // "managed", never clobber a live-set true back to false (a live assigned
      // event may have arrived before this snapshot resolved).
      if (rec.manager_persona != null) {
        record.is_worker = true;
      }
    }
    // Single emission for the whole snapshot — consumers reconcile from list().
    this.emit("hydrated");
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
        this.handlePersonaUpdate(senderId, n.type, n.voice_persona ?? null, this.managerPresent(n.payload));
      }
      return;
    }

    // Regular-notification path — lookup-or-create + bump last_active + bump unread.
    // Worker-badge silencing (Rachel hardening 2026-06-24): the server stamps
    // manager_persona on EVERY notification's payload (legacy reads it from every
    // notification — notifications.js:5685). Fill-forward is_worker here too
    // (set-true-ONLY, never clear) so a worker whose FIRST event is a plain
    // notification — e.g. a silent WS reconnect with no fresh assigned/hydrate —
    // is silenced immediately, with no count flash before the persona event.
    const isWorker = this.managerPresent(n.payload);
    const existing = this.senders.get(senderId);
    if (!existing) {
      const record: SenderRecord = {
        sender_id                : senderId,
        display_name             : senderId,        // best default until renderer overrides
        last_active_ts           : ts,
        unread_count             : 1,
        conversation_mode_active : false,           // Phase 6c Node D — default off; flipped by handleConversationModeUpdate
      };
      if (isWorker) record.is_worker = true;
      this.senders.set(senderId, record);
      this.emit("added", senderId);
      return;
    }

    existing.last_active_ts = ts;
    existing.unread_count++;
    if (isWorker) existing.is_worker = true;
    this.emit("updated", senderId);
  }

  private handlePersonaUpdate(
    senderId  : string,
    type      : string,
    persona   : ServerVoicePersona | null,
    isWorker  : boolean,
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

    record.voice_persona = this.normalizeVoicePersona(persona);
    // Worker-badge silencing (Rick 2026-06-24): the assigned event carries the
    // manager lineage at `payload.manager_persona` (same field SessionStripStore
    // reads). A managed worker (manager present) gets is_worker=true so the
    // renderer suppresses its numeric .sender-new-count; a root/manager session
    // (no manager) gets is_worker=false. Authoritative on every (re-)assignment.
    record.is_worker = isWorker;
    this.emit("updated", senderId);
  }

  // True when the notification payload carries a non-null `manager_persona` —
  // i.e. this sender is a MANAGED worker. Mirrors SessionStripStore's
  // `managerPersonaField` read so the card and strip agree on worker status.
  private managerPresent(payload: Record<string, unknown> | null | undefined): boolean {
    if (!payload) return false;
    return payload["manager_persona"] != null;
  }

  // Server persona → client VoicePersona (5 canonical fields per D-E
  // ratification). Shared by the live voice_persona_assigned path and
  // cold-load hydrate().
  private normalizeVoicePersona(persona: ServerVoicePersona): VoicePersona {
    return {
      name     : (persona.name ?? persona.display_name ?? "") + "",
      voice_id : persona.voice_id ?? "",
      icon     : persona.icon ?? "",
      color    : persona.color ?? "",
      borrowed : persona.borrowed === true,
    };
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

  private emit(changeKind: SenderChangeKind, senderId?: string): void {
    const payload: StoreSendersChangedPayload = { changeKind };
    // "hydrated" carries no single id; added/updated/removed always do.
    if (senderId !== undefined) payload.sender_id = senderId;
    this.bus.emit<StoreSendersChangedPayload>({
      type    : "store_senders_changed",
      payload,
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
