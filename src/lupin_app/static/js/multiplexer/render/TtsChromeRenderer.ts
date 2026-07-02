/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6b — TtsChromeRenderer.
//
// Owns the TTS pane chrome (Pause/Resume toggle, Stop, Skip + queue-length
// indicator). Consumes the Phase 2 `renderTtsChrome` template + the Phase 1
// `AudioStore.stop()` extension.
//
// Lifecycle:
//   - mount(root) atomically renders the chrome into root via replaceChildren()
//     (single childList mutation). Throws on second mount without unmount per
//     the Phase 6a F-26 contract.
//   - subscribes to BOTH `store_audio_state_change` AND `store_audio_chunk_decoded`.
//     A shared `pendingRender` flag + a single `requestAnimationFrame` callback
//     coalesces storms — 100 chunk_decoded events in one tick yield ≤1 render
//     (per Pass 1 F-13 + Q-B9 symmetric coalescing).
//   - unmount() unsubscribes + clears any pending RAF + replaces children. Idempotent.
//
// Click semantics (per Pass 2 A6 + Phase 2 template handler shape):
//   - Pause/Resume toggle button: dispatches AudioStore.pause() when state=playing,
//     resume() when state=paused. Disabled in idle/decoding/ended/error.
//   - Stop button: dispatches AudioStore.stop() (Phase 1.3 NEW; transitions to
//     idle + clears queue counter; distinct from skip's terminal-ended).
//   - Skip button: dispatches AudioStore.skip().
//
// currentTrackName is omitted in Phase 4 because AudioStore does NOT yet expose
// `currentNotificationIdHash()` — Phase 0 prereq #3 still pending verification
// (see 90-execution-log.md side-effect-tasks checklist).

import type { EventBus } from "../shared/EventBus";
import type {
  AudioPlaybackState,
  StoreAudioChunkDecodedPayload,
  StoreAudioStateChangePayload,
  StoreTtsQueueChangedPayload,
  TtsQueueItem,
} from "../shared/types";
import { renderTtsChrome } from "./templates/ttsChrome";
import { renderTtsActiveCard } from "./templates/ttsActiveCard";
import { renderTtsMinimizedCard } from "./templates/ttsMinimizedCard";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

// ---------------------------------------------------------------------------
// Public interfaces
// ---------------------------------------------------------------------------

export interface AudioStoreLike {
  state(): AudioPlaybackState;
  burstLength(): number;   // OQ-F0.4: AudioStore PCM burst counter (renamed from queueLength)
  pause(): void;
  resume(): void;
  stop(): void;
  skip(): void;
}

// WP4 — the TtsQueueStore surface the renderer consumes: read-only queries +
// mutators dispatched via card/chrome handlers. NO advance(): the store
// self-advances on store_audio_ended (TtsQueueStore.ts:168); the renderer never
// calls advance() and never subscribes store_audio_ended (COND-2).
export interface TtsQueueStoreLike {
  current(): string | null;
  activeItem(): TtsQueueItem | null;
  pending(): ReadonlyArray<TtsQueueItem>;
  itemQueueLength(): number;
  removeById(idHash: string): void;
  clear(): void;
}

export interface TtsChromeRendererStores {
  audio    : AudioStoreLike;
  ttsQueue : TtsQueueStoreLike;   // WP4 — notification-item queue (active + pending)
}

export interface TtsChromeRenderer {
  /**
   * Mount onto `root`. Renders chrome immediately (initial paint) and
   * subscribes to AudioStore events for subsequent updates.
   *
   * Throws Error("TtsChromeRenderer already mounted") on second call without
   * intervening unmount() (Phase 6a F-26 contract).
   */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe + cancel pending render + clear children. Idempotent. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render (bypasses RAF). */
  forceRenderForTesting(): void;
}

export interface TtsChromeRendererOptions {
  eventBus              : EventBus;
  stores                : TtsChromeRendererStores;
  /**
   * Test injection — when provided, wraps `requestAnimationFrame` so storm-safety
   * tests can flush the coalesced render synchronously. Production code uses
   * the global RAF.
   */
  requestAnimationFrameFn? : (cb: FrameRequestCallback) => number;
  cancelAnimationFrameFn?  : (handle: number) => void;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class TtsChromeRendererImpl implements TtsChromeRenderer {
  private readonly bus    : EventBus;
  private readonly stores : TtsChromeRendererStores;
  private readonly raf    : (cb: FrameRequestCallback) => number;
  private readonly caf    : (handle: number) => void;
  private readonly unsubscribers: Array<() => void> = [];

  private root: HTMLElement | null = null;
  // Lane 0a — persistent `.section-header` bar + `.section-content` body wrapper.
  private content : HTMLElement | null = null;
  private header  : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted = false;
  private pendingRender = false;
  private rafHandle: number | null = null;

  constructor(opts: TtsChromeRendererOptions) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
    /* c8 ignore next */ // production-default fallback: globalThis.requestAnimationFrame is the runtime browser scheduler; tests always inject a deterministic raf.
    this.raf    = opts.requestAnimationFrameFn ?? ((cb): number => globalThis.requestAnimationFrame(cb));
    /* c8 ignore next */ // production-default fallback: globalThis.cancelAnimationFrame pairs with the RAF default above.
    this.caf    = opts.cancelAnimationFrameFn  ?? ((h): void => globalThis.cancelAnimationFrame(h));
  }

  mount(root: HTMLElement): void {
    if (this.mounted) {
      throw new Error("TtsChromeRenderer already mounted");
    }
    this.mounted = true;
    this.root = root;

    // Lane 0a — the uniform `.section-header` bar (🔊 Playing) + a
    // `.section-content` body wrapper. The header is a persistent sibling; the
    // transport chrome repaints into `this.content`.
    const header = renderSectionHeader( {
      icon   : "🔊",
      title  : "Playing",
      testid : "multiplexer-tts-header",
    } );
    this.header = header;
    const content = document.createElement( "div" );
    content.className = "section-content";
    content.setAttribute( "data-testid", "multiplexer-tts-content" );
    this.content = content;
    root.replaceChildren( header.header, content );
    this.collapseOff = wireSectionCollapse( root, header );

    // Initial paint — atomic (into the content wrapper).
    this.renderNow();

    // Q-B9 + Pass 1 F-13: BOTH state_change AND chunk_decoded are RAF-coalesced
    // through the shared pendingRender flag.
    this.unsubscribers.push(
      this.bus.on<StoreAudioStateChangePayload>(
        "store_audio_state_change",
        () => this.scheduleRender(),
      ),
    );
    this.unsubscribers.push(
      this.bus.on<StoreAudioChunkDecodedPayload>(
        "store_audio_chunk_decoded",
        () => this.scheduleRender(),
      ),
    );
    // WP4 — the notification-item queue changed (active/pending mutation). Same
    // RAF-coalesced render path. Deliberately NOT store_audio_ended: the store
    // self-advances on that event, so a second subscription here would
    // double-advance the queue (Clayton COND-2 auto-reject).
    this.unsubscribers.push(
      this.bus.on<StoreTtsQueueChangedPayload>(
        "store_tts_queue_changed",
        () => this.scheduleRender(),
      ),
    );
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;
    if (this.rafHandle !== null) {
      this.caf(this.rafHandle);
      this.rafHandle = null;
    }
    this.pendingRender = false;
    if (this.collapseOff !== null) {
      this.collapseOff();
      this.collapseOff = null;
    }
    if (this.root !== null) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.content = null;
    this.header  = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if (this.mounted) this.renderNow();
  }

  // -------------------------------------------------------------------------
  // RAF-coalesced render scheduling (Q-B9 / Pass 1 F-13)
  // -------------------------------------------------------------------------

  private scheduleRender(): void {
    if (this.pendingRender) return;        // storm safety: already queued
    this.pendingRender = true;
    this.rafHandle = this.raf(() => {
      this.pendingRender = false;
      this.rafHandle = null;
      this.renderNow();
    });
  }

  private renderNow(): void {
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount BEFORE content is nulled.
    if (this.content === null) return;

    const tts          = this.stores.ttsQueue;
    const activeItem   = tts.activeItem();
    const pending      = tts.pending();
    const pendingCount = tts.itemQueueLength();
    // Section-header chip = TOTAL notification items (active head + pending tail).
    const total        = (activeItem !== null ? 1 : 0) + pending.length;

    // Transport chrome (WP3). count = pending (waiting) item count. Focus mode is
    // deferred (§8.3 — its own follow-on cycle), so focusMode is omitted (false).
    const chrome = renderTtsChrome(
      {
        state       : this.stores.audio.state(),
        queueLength : pendingCount,
        // currentTrackName omitted — Phase 0 prereq #3 pending.
      },
      {
        onPause    : () => this.stores.audio.pause(),
        onResume   : () => this.stores.audio.resume(),
        onStop     : () => this.stores.audio.stop(),
        onSkip     : () => this.stores.audio.skip(),
        onClearAll : () => this.stores.ttsQueue.clear(),
      },
    );

    const children: Node[] = [ chrome ];

    // Active-slot card — the item currently being spoken (WP2 ttsActiveCard).
    if (activeItem !== null) {
      children.push( renderTtsActiveCard( activeItem, {
        onStop  : () => this.stores.audio.stop(),
        onDelete: ( id ) => this.stores.ttsQueue.removeById( id ),
      } ) );
    }

    // Pending minimized cards — 1-indexed queue positions (WP2 ttsMinimizedCard).
    pending.forEach( ( it, i ) => {
      children.push( renderTtsMinimizedCard( it, i + 1, {
        onDelete: ( id ) => this.stores.ttsQueue.removeById( id ),
      } ) );
    } );
    // Empty state (active null + pending empty) falls through to just the chrome,
    // whose idle panel shows "🔇 Nothing in the queue" when audio is idle.

    // replaceChildren — one atomic childList mutation. THIS is the
    // CLEAR-PRIOR-THEN-SET invariant: the whole body is rebuilt from current
    // store state every render, so a current() transition A→B leaves exactly the
    // B active card — A is cleared before B is set, never two lit bubbles.
    this.content.replaceChildren( ...children );

    /* c8 ignore next */ // defensive: header is set/nulled in lockstep with content, so non-null whenever renderNow runs.
    if (this.header !== null) this.header.setCount(total);
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTtsChromeRenderer(opts: TtsChromeRendererOptions): TtsChromeRenderer {
  return new TtsChromeRendererImpl(opts);
}
