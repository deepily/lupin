/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer F0 (00b) — TtsQueueStore.
//
// The notification-level TTS queue + active-item identity that four downstream
// plans (01 B4 active-bubble gate, 02 countdown, 03 multi-item queue render,
// 05 Q&A correlation) independently need but no other store provides. It is a
// LOGIC-LEVEL store with NO DOM surface — its parity is behavioral, proven by
// unit tests + downstream consumption.
//
// Model (two fields, ported from legacy `notifications.js`):
//   - `active`  — the item whose TTS is currently being SPOKEN. `current()`
//     returns its `id_hash` (or null). Maps 1:1 to legacy `this.activeTTSItem`
//     (`:309`). This is the F0-a active id Plan 01 B4 gates the lit bubble on.
//   - `queue`   — the FIFO TAIL of items waiting to be spoken (=== `pending()`),
//     NOT including the active head. Ported from legacy `this.ttsQueue` (`:308`).
//
// Distinct from AudioStore's PCM-chunk counter `burstLength()` (OQ-F0.4): that
// counts raw audio frames of ONE utterance; this counts whole NOTIFICATIONS.
//
// Active-id origin (OQ-F0.3, RATIFIED): the id is inherently CLIENT-SIDE — it is
// absent from the `/ws/audio` server path — and is captured at speak-initiation
// (the F0-d boot seam, ported from legacy `playNotificationAudio` `:15007`)
// which reads `Notification.id_hash` and calls `enqueue()`. AudioStore stays
// id-blind; this store is the SOLE owner of the active id (00b↔00c ownership).
//
// F0-f — completion-driven self-advance + stop-clear (00b↔00c boundary, COND-2):
//   - `store_audio_ended` (00c Phase-6 engine, signal-OUT only) → `advance()`:
//     pop the spoken head, roll `current()` to the next pending item (or null).
//     F0 owns advance() + the id-roll; 00c never calls them.
//   - `store_audio_state_change{state:"idle"}` (AudioStore stop signal) → clear
//     `current()` → null WITHOUT advancing (halt + de-light; pending retained).
//     Distinct from natural-ended = advance (Cheech 01-D obligation).

import type { EventBus } from "../shared/EventBus";
import type {
  AudioPlaybackState,
  LupinEvent,
  StoreActionRequiredChangedPayload,
  StoreAudioStateChangePayload,
  StoreTtsQueueChangedPayload,
  TtsQueueItem,
} from "../shared/types";

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface TtsQueueStore {
  /**
   * F0-a active id — the `id_hash` of the notification whose TTS is currently
   * being spoken, or `null` when nothing plays. THIS is the structural contract
   * Rio's B4 driver consumes via `TtsQueueStoreLike { current(): string | null }`.
   */
  current(): string | null;
  /**
   * F0-a active ITEM object (or null when nothing plays). A pure READ-ONLY getter
   * over the existing private `active` head — the active-slot card renderer (WP4)
   * needs the full TtsQueueItem (icon/text/time), not just `current()`'s id_hash.
   * Consume-surface completion: zero new state, zero mutation, zero events.
   */
  activeItem(): TtsQueueItem | null;
  /** The FIFO tail of items waiting to be spoken (excludes the active head). */
  pending(): ReadonlyArray<TtsQueueItem>;
  /** Number of PENDING items (excludes the active head). Named distinctly from
   *  AudioStore.burstLength() per OQ-F0.4 — no naming collision. */
  itemQueueLength(): number;
  /** Append an item. With nothing active it becomes the active head immediately
   *  (legacy auto-promote), so `current()` === item.id_hash. */
  enqueue(item: TtsQueueItem): void;
  /** Pop the active head; promote the next pending item to active (or null).
   *  70cbff3e: a NO-OP while focus mode is active (pause-the-ROLL belt). */
  advance(): void;
  /**
   * 70cbff3e — focus-mode read. True while the queue-roll is PAUSED awaiting the
   * user's response to an action-required notification whose TTS just finished
   * (legacy `ttsFocusModeActive`, notifications.js:312). The renderer reads this
   * directly each paint (chrome header → "Paused: N waiting" + Resume button).
   */
  focusMode(): boolean;
  /**
   * 70cbff3e — manual Resume (the focus Resume button). Exits focus mode and
   * rolls the queue to the next pending item (legacy `toggleTTSFocusMode` →
   * `exitTTSFocusMode`, notifications.js:17348/17309). No-op when not focused.
   */
  resumeFocus(): void;
  /** Remove an item by id_hash from anywhere; resync `current()` if it was the
   *  active head. No-op for an absent id. */
  removeById(idHash: string): void;
  /** Empty both the active head and the pending tail. */
  clear(): void;
  /** Test/cleanup helper: detach EventBus listeners. */
  disposeForTesting(): void;
}

export interface TtsQueueStoreOptions {
  bus    : EventBus;
  nowFn ?: () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class TtsQueueStoreImpl implements TtsQueueStore {
  private readonly bus   : EventBus;
  private readonly nowFn : () => number;

  // Two-field model (see file header). `active` is the spoken head; `queue` is
  // the pending FIFO tail (excludes `active`).
  private active: TtsQueueItem | null = null;
  private readonly queue: TtsQueueItem[] = [];

  // 70cbff3e — TTS focus mode (legacy ttsFocusModeActive). While true, the roll
  // is paused (advance() no-ops) awaiting a response to the action-required item
  // whose audio just finished. `focusModeNotificationId` is the id gating the
  // exit (legacy focusModeNotificationId, notifications.js:313); the EXIT
  // subscriber matches store_action_required_changed against it.
  private focusModeActive          = false;
  private focusModeNotificationId  : string | null = null;
  // Path B-2 guard (legacy notifications.js:17196/17267): ids seen RESOLVED
  // (responded|expired|cancelled) via store_action_required_changed. Checked at
  // enter so an item resolved WHILE its audio was still playing never enters
  // focus (it advances normally instead). Bounded — the consumed id is dropped.
  private readonly resolved        = new Set<string>();
  // A4 (Tiberius ruling): focus-exit advance respects manual pause. The last
  // audio state seen; exit rolls the queue only when NOT manually paused (mirrors
  // legacy `!isTTSPaused`, notifications.js:17336).
  private lastAudioState           : AudioPlaybackState | null = null;

  private readonly unsubscribers: Array<() => void> = [];

  constructor(opts: TtsQueueStoreOptions) {
    this.bus = opts.bus;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? (() => Date.now());
    this.subscribe();
  }

  current(): string | null {
    return this.active === null ? null : this.active.id_hash;
  }

  activeItem(): TtsQueueItem | null {
    return this.active;
  }

  pending(): ReadonlyArray<TtsQueueItem> {
    return this.queue.slice();
  }

  itemQueueLength(): number {
    return this.queue.length;
  }

  enqueue(item: TtsQueueItem): void {
    if (this.active === null) {
      // Nothing speaking — the new item becomes the active head immediately
      // (legacy `activateNextTTS` auto-promote). current() === item.id_hash.
      this.active = item;
    } else {
      // Something is already speaking — append to the pending tail.
      this.queue.push(item);
    }
    this.emit();
  }

  advance(): void {
    // 70cbff3e — pause-the-ROLL belt: while focused, advance() is a hard no-op.
    // The PRIMARY hold is that onAudioEnded enters focus instead of advancing;
    // this guard is the suspenders (a stray advance() while focused never rolls
    // the held queue). exitFocus() clears the flag BEFORE it calls advance().
    if (this.focusModeActive) return;
    // Discard the spoken head; promote the next pending item (or null when the
    // queue is empty). A no-op only when there is nothing active AND nothing
    // pending (a duplicate/late store_audio_ended → no negative index, no emit).
    if (this.active === null && this.queue.length === 0) return;
    this.active = this.queue.shift() ?? null;
    this.emit();
  }

  removeById(idHash: string): void {
    if (this.active !== null && this.active.id_hash === idHash) {
      // Removing the current item — resync: promote the next pending to active.
      this.active = this.queue.shift() ?? null;
      this.emit();
      return;
    }
    const idx = this.queue.findIndex((it) => it.id_hash === idHash);
    if (idx === -1) return;   // absent id — safe no-op.
    this.queue.splice(idx, 1);
    this.emit();
  }

  clear(): void {
    // No-op when already empty AND not focused (avoids a spurious null→null
    // emission). 70cbff3e: a focused-but-empty queue (active discarded at enter,
    // zero pending → "Paused: 0 waiting" + Clear-all) MUST still clear so the
    // Clear-all button resets focus — hence the `!focusModeActive` term.
    if (this.active === null && this.queue.length === 0 && !this.focusModeActive) return;
    this.active = null;
    this.queue.length = 0;
    this.focusModeActive         = false;
    this.focusModeNotificationId = null;
    this.emit();
  }

  focusMode(): boolean {
    return this.focusModeActive;
  }

  resumeFocus(): void {
    // Manual Resume (the focus Resume button) — the user chooses to resume the
    // queue early (legacy toggleTTSFocusMode :17348 → exitTTSFocusMode :17309).
    // exitFocus() is a no-op when not focused, so a stray click is harmless.
    this.exitFocus();
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    for (const off of this.unsubscribers) off();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // F0-f — completion-driven self-advance + stop-clear subscriptions.
  // -------------------------------------------------------------------------

  private subscribe(): void {
    // Natural utterance completion: 00c's Phase-6 engine emits store_audio_ended
    // (signal-OUT only — F0 reads no payload fields). F0 owns advance() + the
    // current() id-roll; 00c never calls them (COND-2 ownership boundary).
    // 70cbff3e: the handler is now AR-aware — an active action-required item that
    // finishes while unresolved ENTERS focus (holds the roll) instead of advancing.
    this.unsubscribers.push(
      this.bus.on("store_audio_ended", () => this.onAudioEnded()),
    );
    // Stop (NOT natural completion): AudioStore emits store_audio_state_change
    // {state:"idle"} on stop(). Stop = halt + de-light → clear current()→null
    // WITHOUT advancing (no head pop, no promote; pending retained).
    this.unsubscribers.push(
      this.bus.on<StoreAudioStateChangePayload>(
        "store_audio_state_change",
        (e) => this.onAudioStateChange(e),
      ),
    );
    // 70cbff3e — focus EXIT + Path B-2 tracking: the action-required store emits
    // store_action_required_changed on every AR lifecycle transition. A terminal
    // resolution (responded|expired|cancelled) matching the focus item exits focus
    // and rolls the queue; any resolution is also banked in `resolved` so a
    // resolve-during-playback never enters focus at the subsequent audio-ended.
    this.unsubscribers.push(
      this.bus.on<StoreActionRequiredChangedPayload>(
        "store_action_required_changed",
        (e) => this.onActionRequiredChanged(e),
      ),
    );
  }

  private onAudioStateChange(e: LupinEvent<StoreAudioStateChangePayload>): void {
    // 70cbff3e (A4): remember the last audio state so focus-exit can respect a
    // manual pause (mirrors legacy `!isTTSPaused` gate, notifications.js:17336).
    this.lastAudioState = e.payload.state;
    // Only the idle (stop) state de-lights. Every other playback sub-state
    // (playing / paused / decoding / ended / error) is id-blind to F0 — the
    // active id is driven by the queue + store_audio_ended, not by sub-states.
    if (e.payload.state !== "idle") return;
    // De-light WITHOUT advancing: null the active head, leave the pending tail.
    // (Stop ≠ ended — F0-f.) No-op when already de-lit, so no spurious emit.
    if (this.active === null) return;
    this.active = null;
    this.emit();
  }

  // -------------------------------------------------------------------------
  // 70cbff3e — focus-mode transitions.
  // -------------------------------------------------------------------------

  private onAudioEnded(): void {
    // Natural utterance completion. Legacy onTTSPlaybackComplete (notifications.js
    // :17176-17204): capture the just-completed head; if it was an ACTIVE
    // action-required item AND is still unresolved, ENTER focus (hold the roll)
    // instead of advancing. Otherwise advance normally.
    const justCompleted = this.active;
    if (
      justCompleted !== null &&
      justCompleted.action_required === true &&
      !this.resolved.has(justCompleted.id_hash)
    ) {
      this.enterFocus(justCompleted.id_hash);
      return;
    }
    // Non-AR, or an AR item resolved WHILE playing (Path B-2, legacy :17196):
    // consume it and DROP its resolved-bank entry (Clayton F1). The dedup guard
    // (NotificationStore.byId.has) masks reuse TODAY, but the monotonic set is
    // fragile beyond it: if an id ever leaves byId (archive/evict/clear) and an
    // identical-id AR re-arrives, a stale resolved.has would wrongly SKIP focus.
    // Dropping on consume keeps the set honest + tracks legacy's live-state read.
    if (justCompleted !== null) this.resolved.delete(justCompleted.id_hash);
    this.advance();
  }

  private enterFocus(idHash: string): void {
    // Legacy enterTTSFocusMode (:17262): discard the completed head (activeTTSItem
    // = null, :17201), pause the roll, show "Paused: N waiting" + Resume. The
    // pending tail is UNTOUCHED — it resumes on exit. focusMode is not carried in
    // the emit payload; the renderer reads focusMode() directly each paint.
    this.active                  = null;
    this.focusModeActive         = true;
    this.focusModeNotificationId = idHash;
    this.emit();
  }

  private exitFocus(): void {
    // Legacy exitTTSFocusMode (:17309): no-op when not focused (:17311).
    if (!this.focusModeActive) return;
    this.focusModeActive         = false;
    this.focusModeNotificationId = null;
    // A4 (Tiberius): respect a manual pause — resume the queue only when NOT
    // manually paused (legacy `!isTTSPaused`, :17336). When paused, de-focus
    // WITHOUT rolling: emit so the header/Resume clear, but hold the pending tail.
    // UNREACHABLE in the live UI (Clayton F2, verified): focus enters on audio-
    // ENDED, and deriveControlState("ended") disables the Pause toggle, so no
    // store_audio_state_change{paused} can fire during focus → lastAudioState
    // cannot be "paused" here. Kept for legacy faithfulness (the :17336 gate is
    // unreachable-during-focus for the identical reason); T12 exercises this
    // branch ONLY via synthetic event injection.
    if (this.lastAudioState === "paused") {
      this.emit();
      return;
    }
    // Not paused — roll the queue to the next pending item (legacy activateNextTTS
    // :17338). Inline the promote (NOT advance()) so we ALWAYS emit exactly once:
    // advance() no-op-without-emit on an empty queue would leave the focus header
    // stuck. Here the de-focus MUST repaint even when there's nothing to promote.
    this.active = this.queue.shift() ?? null;
    this.emit();
  }

  private onActionRequiredChanged(e: LupinEvent<StoreActionRequiredChangedPayload>): void {
    // Only TERMINAL resolutions matter to focus (A2 ruling: `failed` STAYS in
    // focus — the respondAndAwait POST can be retried; `responded-pending` / tick
    // / added / offline-* are non-terminal and ignored).
    const kind = e.payload.changeKind;
    if (kind !== "responded" && kind !== "expired" && kind !== "cancelled") return;
    // Bank the resolution for the Path B-2 enter-guard (covers resolve-while-
    // -playing, before this id's audio-ended fires).
    this.resolved.add(e.payload.id_hash);
    // EXIT focus iff this resolves the item we're focused on.
    if (this.focusModeActive && this.focusModeNotificationId === e.payload.id_hash) {
      this.exitFocus();
    }
  }

  private emit(): void {
    this.bus.emit<StoreTtsQueueChangedPayload>({
      type    : "store_tts_queue_changed",
      payload : {
        activeNotificationId : this.current(),
        pending              : this.queue.slice(),
      },
      source  : "TtsQueueStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTtsQueueStore(opts: TtsQueueStoreOptions): TtsQueueStore {
  return new TtsQueueStoreImpl(opts);
}
