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
  LupinEvent,
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
  /** The FIFO tail of items waiting to be spoken (excludes the active head). */
  pending(): ReadonlyArray<TtsQueueItem>;
  /** Number of PENDING items (excludes the active head). Named distinctly from
   *  AudioStore.burstLength() per OQ-F0.4 — no naming collision. */
  itemQueueLength(): number;
  /** Append an item. With nothing active it becomes the active head immediately
   *  (legacy auto-promote), so `current()` === item.id_hash. */
  enqueue(item: TtsQueueItem): void;
  /** Pop the active head; promote the next pending item to active (or null). */
  advance(): void;
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
    // No-op when already empty (avoids a spurious null→null emission).
    if (this.active === null && this.queue.length === 0) return;
    this.active = null;
    this.queue.length = 0;
    this.emit();
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
    this.unsubscribers.push(
      this.bus.on("store_audio_ended", () => this.advance()),
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
  }

  private onAudioStateChange(e: LupinEvent<StoreAudioStateChangePayload>): void {
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
