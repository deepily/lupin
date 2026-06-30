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
} from "../shared/types";
import { renderTtsChrome } from "./templates/ttsChrome";

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

export interface TtsChromeRendererStores {
  audio: AudioStoreLike;
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

    // Initial paint — atomic.
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
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;
    if (this.rafHandle !== null) {
      this.caf(this.rafHandle);
      this.rafHandle = null;
    }
    this.pendingRender = false;
    if (this.root !== null) {
      this.root.replaceChildren();
      this.root = null;
    }
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
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount BEFORE root is nulled.
    if (this.root === null) return;
    const chrome = renderTtsChrome(
      {
        state       : this.stores.audio.state(),
        queueLength : this.stores.audio.burstLength(),   // OQ-F0.4 rename; render-field name (template contract) unchanged
        // currentTrackName intentionally omitted — Phase 0 prereq #3 pending.
      },
      {
        onPause  : () => this.stores.audio.pause(),
        onResume : () => this.stores.audio.resume(),
        onStop   : () => this.stores.audio.stop(),
        onSkip   : () => this.stores.audio.skip(),
      },
    );
    // replaceChildren — single childList mutation, atomic for the whole pane.
    this.root.replaceChildren(chrome);
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTtsChromeRenderer(opts: TtsChromeRendererOptions): TtsChromeRenderer {
  return new TtsChromeRendererImpl(opts);
}
