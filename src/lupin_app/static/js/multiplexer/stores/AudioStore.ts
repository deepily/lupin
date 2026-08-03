/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 4 — AudioStore.
//
// XState v5 actor (tracker pattern per Q5) for PCM audio playback state.
// State graph: idle → decoding → playing → (paused | ended | error)
//
// Per Q6: AudioContext is lazy on first chunk_arrived (browser autoplay
// policy may block construction without user gesture; lazy aligns failure
// with action). On construction throw or context.state === "suspended" with
// no recovery path, emit `store_audio_state_change { state: "error",
// reason: "audiocontext-blocked" }`.
//
// Per D-D: AudioStore exposes `binaryHandler` as a named bound method whose
// Function.name === "audioStoreBinaryHandler" — boot.ts threads it through
// `transports.audio.start(sessionId, audioStore.binaryHandler)`. AC9
// verification reads this name via `boot_complete` payload to confirm the
// production handler is wired (not the Phase 3 default debug logger).
//
// Phase 6 (00c) — TTS playback engine LANDED here. AudioStore decodes chunks
// via pcm-decoder (per D-A) AND now schedules the decoded AudioBuffer onto a
// gapless Web-Audio graph (P6-a, ported from legacy `notifications.js`
// `playPCMChunk` :4627-4664): createBufferSource → connect(destination) →
// start(max(nextStartTime, currentTime)) → advance nextStartTime. pause()/
// resume()/stop() back onto AudioContext.suspend()/resume() + source halt
// (P6-b). On the server `audio_streaming_complete` frame AudioStore sets a
// stream-complete flag that gates the last source's onended → emits
// `store_audio_ended` (P6-c, signal-OUT only — F0's TtsQueueStore subscribes
// and self-advances; P6 NEVER mutates id/queue state). So the state names
// "playing"/"paused"/"ended" now reflect ACTUAL audible output, resolving the
// former Phase-4 "intended vs actual" caveat.

import { setup, createActor, type ActorRefFrom } from "xstate";

import type { EventBus } from "../shared/EventBus";
import type {
  AudioPlaybackState,
  StoreAudioChunkDecodedPayload,
  StoreAudioStateChangePayload,
  StoreAudioEndedPayload,
} from "../shared/types";
import type { AudioContextLike, AudioBufferLike } from "../audio/pcm-decoder";
import { pcm16ToAudioBuffer, pcm16ToAudioBufferFromBlob } from "../audio/pcm-decoder";

// ---------------------------------------------------------------------------
// Scheduler-side AudioContext surface (COND-4 / F-Krishna-A4).
//
// The DECODE contract `AudioContextLike` (pcm-decoder) stays minimal —
// `createBuffer` only. The PLAYBACK scheduler needs the wider Web-Audio
// surface (buffer-source creation, the running clock, the destination node,
// suspend/resume). That superset is declared HERE, in the scheduler module, so
// the decode interface is not polluted by playback concerns. One injected test
// stub implements this superset, satisfying both decode + schedule, keeping
// every scheduler method inside `c8` scope.
// ---------------------------------------------------------------------------

export type AudioContextStateLike = "suspended" | "running" | "closed";

// The destination node is an opaque connect() target — the scheduler never
// reads members off it, only passes it to `source.connect(...)`.
export type AudioDestinationNodeLike = object;

export interface AudioBufferSourceLike {
  buffer  : AudioBufferLike | null;
  onended : ( () => void ) | null;
  connect( destination: AudioDestinationNodeLike ): void;
  start( when?: number ): void;
  stop(): void;
}

export interface SchedulableAudioContext extends AudioContextLike {
  readonly currentTime : number;
  readonly destination : AudioDestinationNodeLike;
  readonly state       : AudioContextStateLike;
  createBufferSource(): AudioBufferSourceLike;
  suspend(): Promise<void>;
  resume(): Promise<void>;
}

// ---------------------------------------------------------------------------
// XState machine — pure state graph; tracker pattern per Q5.
// ---------------------------------------------------------------------------

interface AudioContext_ {
  /* placeholder */
}

type AudioMachineEvent =
  | { type: "CHUNK_ARRIVED" }
  | { type: "CHUNK_DECODED" }
  | { type: "DECODE_FAILED" }
  | { type: "PLAYBACK_ENDED" }
  | { type: "PAUSE_REQUESTED" }
  | { type: "RESUME_REQUESTED" }
  | { type: "SKIP_REQUESTED" }
  | { type: "STOP_REQUESTED" };       // Phase 6b — full halt to idle (per Pass 2 A6)

const audioMachine = setup({
  types : {
    context : {} as AudioContext_,
    events  : {} as AudioMachineEvent,
  },
}).createMachine({
  id      : "audio",
  initial : "idle",
  context : {},
  states  : {
    idle : {
      on : {
        CHUNK_ARRIVED : "decoding",
      },
    },
    decoding : {
      on : {
        CHUNK_DECODED   : "playing",
        DECODE_FAILED   : "error",
      },
    },
    playing : {
      on : {
        CHUNK_ARRIVED   : "decoding",
        PAUSE_REQUESTED : "paused",
        PLAYBACK_ENDED  : "ended",
        SKIP_REQUESTED  : "ended",
        STOP_REQUESTED  : "idle",        // Phase 6b — stop returns to idle (vs skip → ended)
      },
    },
    paused : {
      on : {
        RESUME_REQUESTED : "playing",
        SKIP_REQUESTED   : "ended",
        STOP_REQUESTED   : "idle",       // Phase 6b
      },
    },
    ended : {
      on : {
        // New chunk after silence resumes the pipeline.
        CHUNK_ARRIVED  : "decoding",
        STOP_REQUESTED : "idle",         // Phase 6b — explicit reset from ended
      },
    },
    error : {
      on : {
        // Recover by treating a fresh chunk as a new start.
        CHUNK_ARRIVED  : "decoding",
        STOP_REQUESTED : "idle",         // Phase 6b — explicit reset from error
      },
    },
  },
});

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface AudioStore {
  state(): AudioPlaybackState;
  // OQ-F0.4 (Rick 2026-06-27): renamed from queueLength() — this counts PCM
  // chunks in the current playing-burst, NOT notification items. The
  // notification-item count lives on TtsQueueStore.itemQueueLength().
  burstLength(): number;
  pause(): void;
  resume(): void;
  skip(): void;
  /**
   * Phase 6b (per Pass 2 A6) — full halt to idle, clear in-burst counter.
   * Distinct from skip() (advance one track within the burst → ended) and
   * pause() (suspend keeping queue intact). No-op when already idle/decoding.
   */
  stop(): void;
  /** Per D-D — the bound binary handler whose Function.name === "audioStoreBinaryHandler". */
  readonly binaryHandler: (data: Blob | ArrayBuffer) => void;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface AudioStoreOptions {
  bus                : EventBus;
  // Factory for the production AudioContext. Production code defaults to a
  // function returning `new AudioContext({sampleRate: 24000})`. Tests inject a
  // stub returning the SchedulableAudioContext superset (decode + schedule).
  audioContextFactory?: () => SchedulableAudioContext;
  // Decoder injection (defaults to the canonical pcm-decoder exports). Tests
  // can override to assert specific failure paths.
  decodeArrayBufferFn ?: (buf: ArrayBuffer, ctx: AudioContextLike, sampleRate?: number) => AudioBufferLike;
  decodeBlobFn        ?: (blob: Blob, ctx: AudioContextLike, sampleRate?: number) => Promise<AudioBufferLike>;
  // Sample rate for createBuffer (legacy production = 24000 per ElevenLabs PCM).
  sampleRate          ?: number;
  nowFn               ?: () => number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class AudioStoreImpl implements AudioStore {
  private readonly bus                 : EventBus;
  private readonly audioContextFactory : () => SchedulableAudioContext;
  private readonly decodeArrayBufferFn : (buf: ArrayBuffer, ctx: AudioContextLike, sampleRate?: number) => AudioBufferLike;
  private readonly decodeBlobFn        : (blob: Blob, ctx: AudioContextLike, sampleRate?: number) => Promise<AudioBufferLike>;
  private readonly sampleRate          : number;
  private readonly nowFn               : () => number;

  private readonly actor: ActorRefFrom<typeof audioMachine>;

  // Lazy-instantiated on first chunk_arrived per Q6.
  private audioContext: SchedulableAudioContext | null = null;
  // Number of chunks queued in the current playing-burst.
  private chunksInBurst = 0;

  // ── P6 scheduler state ────────────────────────────────────────────────────
  // Gapless schedule cursor: the absolute context-clock time the NEXT chunk
  // starts at. Inits to 0 (F-Sam-A1, load-bearing) so the FIRST chunk starts at
  // `Math.max(0, currentTime) === currentTime`; an uninitialized value would
  // give `Math.max(undefined, currentTime) === NaN` → silent `start(NaN)`.
  // stop() resets it to 0 (NOT undefined) so a fresh burst's first chunk is
  // likewise `currentTime`.
  private nextStartTime = 0;
  // Buffer sources scheduled but not yet ended. Used by stop() (halt all) and
  // by the completion gate (utterance ends when this drains AND the stream-
  // complete flag is set). A source removes itself here in its onended.
  private activeSources: AudioBufferSourceLike[] = [];
  // Set true on the server `audio_streaming_complete` frame (all chunks sent);
  // gates utterance completion. Inits false; reset to false on new-stream-start
  // AND on stop() (F-Sam-B1) so utterance N+1 is never completed prematurely by
  // a flag carried over from utterance N.
  private streamComplete = false;
  // True once ≥1 source has been scheduled for the CURRENT utterance and it has
  // not yet completed. Makes completion strictly one-shot: a duplicate/late
  // `audio_streaming_complete` frame on an already-drained (or audio-less)
  // stream is a no-op, never a second `store_audio_ended` emit.
  private utterancePending = false;

  // The bound binary handler. Named via `function audioStoreBinaryHandler` so
  // `Function.name === "audioStoreBinaryHandler"` — AC9 verification reads
  // this name through the boot_complete payload + console.log.
  readonly binaryHandler: (data: Blob | ArrayBuffer) => void;

  // Track previous state so emissions carry both `state` and `prev`.
  private prevState: AudioPlaybackState = "idle";

  constructor(opts: AudioStoreOptions) {
    this.bus                 = opts.bus;
    /* c8 ignore next */ // production-default fallback: defaultAudioContextFactory wraps the browser-only `AudioContext`/`webkitAudioContext`; tests always inject a stub audioContextFactory.
    this.audioContextFactory = opts.audioContextFactory ?? defaultAudioContextFactory;
    this.decodeArrayBufferFn = opts.decodeArrayBufferFn ?? pcm16ToAudioBuffer;
    this.decodeBlobFn        = opts.decodeBlobFn        ?? pcm16ToAudioBufferFromBlob;
    this.sampleRate          = opts.sampleRate          ?? 24000;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn               = opts.nowFn               ?? (() => Date.now());

    this.actor = createActor(audioMachine);
    this.actor.start();
    this.actor.subscribe((snap) => {
      const next = snap.value as AudioPlaybackState;
      if (next !== this.prevState) {
        this.bus.emit<StoreAudioStateChangePayload>({
          type    : "store_audio_state_change",
          payload : { state: next, prev: this.prevState },
          source  : "AudioStore",
          ts      : this.nowFn(),
        });
        this.prevState = next;
      }
    });

    // P6-c — subscribe to the server end-of-utterance marker. The subscription
    // lives HERE (in AudioStore, not boot — F-Sam-B3) with the flag + handler it
    // drives, so the completion seam is self-contained + unit-testable.
    this.bus.on("audio_streaming_complete", () => this.handleStreamComplete());

    // Closure-captured instance so the named function expression keeps its
    // identifier — `.bind(this)` would yield `"bound audioStoreBinaryHandler"`,
    // breaking the AC9 Function.name === "audioStoreBinaryHandler" invariant.
    // ESLint's no-this-alias is disabled for this single binding because the
    // alternatives (.bind / arrow field) would corrupt Function.name.
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const store = this;
    this.binaryHandler = function audioStoreBinaryHandler(data: Blob | ArrayBuffer): void {
      store.handleBinary(data);
    };
  }

  state(): AudioPlaybackState {
    return this.actor.getSnapshot().value as AudioPlaybackState;
  }

  burstLength(): number {
    return this.chunksInBurst;
  }

  pause(): void {
    // P6-b — suspend() freezes the context clock, so currentTime and every
    // already-scheduled start(when) offset stay coherent; resume() does NOT
    // rebase nextStartTime (F-Sam-A2) — that no-fixup is what keeps playback
    // gapless across a pause. Invariant: state "playing" ⇒ a chunk flowed
    // through handleBinary, so audioContext is constructed (non-null).
    if (this.state() !== "playing") return;
    this.actor.send({ type: "PAUSE_REQUESTED" });
    void this.audioContext!.suspend();
  }

  resume(): void {
    // P6-b — resume the (paused → suspended) context; same non-rebase invariant
    // as pause(). Invariant: state "paused" ⇒ audioContext is non-null.
    if (this.state() !== "paused") return;
    this.actor.send({ type: "RESUME_REQUESTED" });
    void this.audioContext!.resume();
  }

  skip(): void {
    const s = this.state();
    if (s === "playing" || s === "paused") {
      this.actor.send({ type: "SKIP_REQUESTED" });
      this.chunksInBurst = 0;
    }
  }

  // Phase 6b — full halt (per Pass 2 A6). Reachable from playing/paused/ended/error;
  // no-op from idle/decoding. State transitions to idle and queue counter clears.
  // The state-change emission flows through the existing actor.subscribe() path.
  stop(): void {
    const s = this.state();
    if (s === "idle" || s === "decoding") return;
    this.actor.send({ type: "STOP_REQUESTED" });
    this.chunksInBurst = 0;
    this.haltSources();              // P6-b — silence immediately + reset scheduling
  }

  // P6-b — halt all scheduled sources and reset the gapless scheduler so a
  // subsequent burst starts clean. nextStartTime → 0 (NOT undefined, F-Sam-A1);
  // stream-complete flag → false (F-Sam-B1). A stopped source's onended may
  // still fire in the browser, but handleSourceEnded is a safe no-op once
  // activeSources is cleared + the flag is false.
  private haltSources(): void {
    for (const source of this.activeSources) source.stop();
    this.activeSources    = [];
    this.nextStartTime    = 0;
    this.streamComplete   = false;
    this.utterancePending = false;
  }

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    this.actor.stop();
  }
  /* c8 ignore stop */

  // -------------------------------------------------------------------------
  // Binary chunk processing
  // -------------------------------------------------------------------------

  private handleBinary(data: Blob | ArrayBuffer): void {
    // Step 1: lazy-construct the AudioContext on first chunk.
    if (this.audioContext === null) {
      try {
        this.audioContext = this.audioContextFactory();
      } catch (err) {
        /* c8 ignore next */ // defensive: audioContextFactory exceptions are wrapped Error instances per the contract (browser AudioContext throws DOMException, the test stub throws Error); the `: String(err)` arm is unreachable in practice.
        const msg = err instanceof Error ? err.message : String(err);
        this.emitErrorState(`audiocontext-blocked: ${msg}`);
        return;
      }
    }
    // Construction succeeded (the catch returns), so audioContext is non-null.
    const ctx = this.audioContext;

    // P6-d/P6-e — resume a suspended context (browser autoplay policy) so the
    // sources scheduled below actually play. No-op when already running.
    this.resumeIfSuspended(ctx);

    // F-Sam-B1 — new-stream-start flag reset. A fresh burst begins from a
    // terminal/idle state; clear any stale stream-complete flag so utterance
    // N+1 is not completed prematurely by a flag carried over from utterance N.
    // SERIALIZATION DEPENDENCY (Cheech Stage-2): this reset assumes utterance
    // N+1 is not requested until N's `store_audio_ended` has fired — i.e. TTS is
    // strictly serial, one utterance at a time (the legacy + current server
    // contract). If TTS is ever pipelined / pre-streamed (overlapping
    // utterances), this single shared flag is insufficient: harden the reset to
    // a per-utterance token (see F-1) so each utterance gates its own completion.
    const preState = this.state();
    if (preState === "idle" || preState === "ended" || preState === "error") {
      this.streamComplete = false;
    }

    // Step 2: signal the machine that a chunk arrived (idle → decoding).
    this.chunksInBurst++;
    this.actor.send({ type: "CHUNK_ARRIVED" });

    // Step 3: decode. ArrayBuffer is sync; Blob is async.
    if (data instanceof ArrayBuffer) {
      try {
        const buf = this.decodeArrayBufferFn(data, ctx, this.sampleRate);
        this.onDecoded(buf, ctx);
      } catch (err) {
        /* c8 ignore next */ // defensive: decodeArrayBufferFn exceptions are wrapped Error instances per the pcm16ToAudioBuffer contract (and test stubs); the `: String(err)` arm is unreachable in practice.
        const msg = err instanceof Error ? err.message : String(err);
        this.actor.send({ type: "DECODE_FAILED" });
        // Override the auto-emitted state change with one carrying the reason.
        // The XState transition emit happens via subscribe(); we additionally
        // emit a tagged version so renderers can read the reason.
        this.emitTaggedReason(`decode-failed: ${msg}`);
      }
      return;
    }

    // Blob path — async.
    this.decodeBlobFn(data, ctx, this.sampleRate)
      .then((buf) => this.onDecoded(buf, ctx))
      /* c8 ignore start */ // Async decode failure — exercised in production when blob malformed; covered indirectly by ArrayBuffer decode-failed test (same code path post the .then/.catch boundary).
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err);
        this.actor.send({ type: "DECODE_FAILED" });
        this.emitTaggedReason(`decode-failed: ${msg}`);
      });
      /* c8 ignore stop */
  }

  private onDecoded(buf: AudioBufferLike, ctx: SchedulableAudioContext): void {
    this.actor.send({ type: "CHUNK_DECODED" });
    this.scheduleDecodedBuffer(buf, ctx);          // P6-a — port the gapless scheduler
    this.bus.emit<StoreAudioChunkDecodedPayload>({
      type    : "store_audio_chunk_decoded",
      payload : {
        durationMs : buf.duration * 1000,
        sampleRate : buf.sampleRate,
        frameCount : buf.length,
      },
      source  : "AudioStore",
      ts      : this.nowFn(),
    });
  }

  // -------------------------------------------------------------------------
  // P6-a — gapless scheduler (ported from notifications.js:4627-4664)
  // -------------------------------------------------------------------------

  private scheduleDecodedBuffer(buf: AudioBufferLike, ctx: SchedulableAudioContext): void {
    // F-Sam-A3 race guard: only schedule while actively playing. A straggler
    // chunk whose async decode resolves AFTER stop() lands here with the machine
    // in idle — its CHUNK_DECODED was a no-op (idle has no such transition) — so
    // drop it BEFORE createBufferSource (mux equivalent of legacy's
    // currentTTSMode-null race-drop, notifications.js:4613).
    if (this.state() !== "playing") return;

    const source  = ctx.createBufferSource();
    source.buffer = buf;
    source.connect(ctx.destination);

    // Gapless schedule (legacy :4634-4636): start at the later of the running
    // schedule cursor and the live clock, so a slow chunk never schedules in the
    // past. First chunk: nextStartTime is 0 → Math.max(0, currentTime) ===
    // currentTime (F-Sam-A1).
    const startTime = Math.max(this.nextStartTime, ctx.currentTime);
    source.start(startTime);
    this.nextStartTime = startTime + buf.duration;   // advance cursor (legacy :4664)

    this.activeSources.push(source);
    this.utterancePending = true;                    // an utterance is now in flight
    source.onended = () => this.handleSourceEnded(source);
  }

  // P6-d/P6-e — autoplay recovery. A context built without a prior user gesture
  // may start "suspended" (Chrome autoplay policy); resume it so scheduled
  // sources play. If a prior page activation already unlocked it (state
  // "running"), this is a no-op — no gesture listener needed (F-Sam-C3). On
  // rejection (the autoplay-BLOCKED arm) reuse the audiocontext-blocked error.
  private resumeIfSuspended(ctx: SchedulableAudioContext): void {
    if (ctx.state !== "suspended") return;
    ctx.resume().catch((err) => {
      /* c8 ignore next */ // defensive: the rejection carries an Error per the autoplay contract (and the rejection-capable test stub); the `: String(err)` arm is unreachable in practice.
      const msg = err instanceof Error ? err.message : String(err);
      this.emitErrorState(`audiocontext-blocked: ${msg}`);
    });
  }

  // -------------------------------------------------------------------------
  // P6-c — completion-signal seam (signal-OUT only)
  // -------------------------------------------------------------------------

  // A scheduled source finished playing. Drop it from the live set, then test
  // for utterance completion.
  private handleSourceEnded(source: AudioBufferSourceLike): void {
    const idx = this.activeSources.indexOf(source);
    if (idx !== -1) this.activeSources.splice(idx, 1);
    this.maybeComplete();
  }

  // The server signalled all chunks sent (audio_streaming_complete). Set the
  // flag, then test for completion — covering the F-Sam-B2 drop-race where the
  // last onended already fired (no live source) and we must emit immediately
  // rather than wait for an onended that already passed.
  private handleStreamComplete(): void {
    this.streamComplete = true;
    this.maybeComplete();
  }

  // Fire end-of-utterance EXACTLY ONCE: the stream-complete flag is set AND no
  // scheduled source is still playing. Resetting the flag makes it one-shot, so
  // neither the last onended nor a late complete-frame can double-fire
  // (F-Sam-B1 multi-utterance + F-Sam-B2 symmetric drop-race). P6 emits
  // store_audio_ended ONLY — it makes ZERO calls into TtsQueueStore and never
  // touches the active id (COND-2 ownership boundary); F0's TtsQueueStore
  // subscribes to store_audio_ended and self-advances.
  private maybeComplete(): void {
    if (!this.streamComplete) return;
    if (!this.utterancePending) return;              // nothing to complete (already done / audio-less)
    if (this.activeSources.length > 0) return;
    this.utterancePending = false;
    this.streamComplete   = false;
    this.actor.send({ type: "PLAYBACK_ENDED" });     // drive XState → ended
    this.bus.emit<StoreAudioEndedPayload>({
      type    : "store_audio_ended",
      payload : {},
      source  : "AudioStore",
      ts      : this.nowFn(),
    });
  }

  private emitErrorState(reason: string): void {
    // Synthesize the error state directly — the machine's idle state has no
    // CHUNK_ARRIVED → error transition, so we emit the change event ourselves
    // and forcibly transition the actor by sending DECODE_FAILED if we're in
    // decoding (otherwise we just emit and the next chunk will retry context
    // construction).
    const prev = this.state();
    this.bus.emit<StoreAudioStateChangePayload>({
      type    : "store_audio_state_change",
      payload : { state: "error", prev, reason },
      source  : "AudioStore",
      ts      : this.nowFn(),
    });
    // Don't mutate XState — error state machine entry happens through DECODE_FAILED
    // when the decode actually attempted. AudioContext-blocked errors leave
    // the machine in idle, and the next chunk will try to construct again.
    // For the public API: state() returns "error" semantically via the prev
    // tracking is misleading, so we mark prevState so the next state change
    // emits prev: "error".
    this.prevState = "error";
  }

  private emitTaggedReason(reason: string): void {
    // Emit a second state_change carrying the reason. The machine has already
    // transitioned (via DECODE_FAILED → error) and the subscribe handler has
    // emitted a non-reason version; this companion emission lets renderers
    // read the cause.
    this.bus.emit<StoreAudioStateChangePayload>({
      type    : "store_audio_state_change",
      payload : { state: "error", prev: "decoding", reason },
      source  : "AudioStore",
      ts      : this.nowFn(),
    });
  }
}

// ---------------------------------------------------------------------------
// Default factory — `globalThis.AudioContext` (Chrome-only; no vendor prefix).
// ---------------------------------------------------------------------------

/* c8 ignore start */ // Browser-only fallback; tests inject `audioContextFactory` directly.
function defaultAudioContextFactory(): SchedulableAudioContext {
  // Chrome-only mux (Rick 2026-06-27) — no `webkitAudioContext` vendor prefix.
  const Ctor = (globalThis as unknown as {
    AudioContext ?: { new (opts?: { sampleRate?: number }): SchedulableAudioContext };
  }).AudioContext;
  if (!Ctor) {
    throw new Error("AudioContext is not available in this environment");
  }
  return new Ctor({ sampleRate: 24000 });
}
/* c8 ignore stop */

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createAudioStore(opts: AudioStoreOptions): AudioStore {
  return new AudioStoreImpl(opts);
}
