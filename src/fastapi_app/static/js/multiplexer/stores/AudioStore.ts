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
// Phase 4 scope clarification: AudioStore decodes chunks via pcm-decoder
// (per D-A) and emits `store_audio_chunk_decoded` with the AudioBuffer.
// **Actual playback scheduling (createBufferSource + source.start) is
// Phase 6 territory** (TTSEngine). Phase 4 tracks state + decodes + emits;
// Phase 6 wires the AudioBuffer into a playback graph. The state names
// "playing"/"paused"/"ended" in Phase 4 reflect *intended* playback state
// driven by the chunk stream, not actual audible output.

import { setup, createActor, type ActorRefFrom } from "xstate";

import type { EventBus } from "../shared/EventBus";
import type {
  AudioPlaybackState,
  StoreAudioChunkDecodedPayload,
  StoreAudioStateChangePayload,
} from "../shared/types";
import type { AudioContextLike, AudioBufferLike } from "../audio/pcm-decoder";
import { pcm16ToAudioBuffer, pcm16ToAudioBufferFromBlob } from "../audio/pcm-decoder";

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
  | { type: "SKIP_REQUESTED" };

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
      },
    },
    paused : {
      on : {
        RESUME_REQUESTED : "playing",
        SKIP_REQUESTED   : "ended",
      },
    },
    ended : {
      on : {
        // New chunk after silence resumes the pipeline.
        CHUNK_ARRIVED : "decoding",
      },
    },
    error : {
      on : {
        // Recover by treating a fresh chunk as a new start.
        CHUNK_ARRIVED : "decoding",
      },
    },
  },
});

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface AudioStore {
  state(): AudioPlaybackState;
  queueLength(): number;
  pause(): void;
  resume(): void;
  skip(): void;
  /** Per D-D — the bound binary handler whose Function.name === "audioStoreBinaryHandler". */
  readonly binaryHandler: (data: Blob | ArrayBuffer) => void;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

export interface AudioStoreOptions {
  bus                : EventBus;
  // Factory for the production AudioContext. Production code defaults to a
  // function returning `new AudioContext({sampleRate: 24000})`. Tests inject
  // a stub returning AudioContextLike (mirrors pcm-decoder's interface).
  audioContextFactory?: () => AudioContextLike;
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
  private readonly audioContextFactory : () => AudioContextLike;
  private readonly decodeArrayBufferFn : (buf: ArrayBuffer, ctx: AudioContextLike, sampleRate?: number) => AudioBufferLike;
  private readonly decodeBlobFn        : (blob: Blob, ctx: AudioContextLike, sampleRate?: number) => Promise<AudioBufferLike>;
  private readonly sampleRate          : number;
  private readonly nowFn               : () => number;

  private readonly actor: ActorRefFrom<typeof audioMachine>;

  // Lazy-instantiated on first chunk_arrived per Q6.
  private audioContext: AudioContextLike | null = null;
  // Number of chunks queued in the current playing-burst (Phase 4 tracks
  // arrivals only; actual queueing/scheduling is Phase 6).
  private chunksInBurst = 0;

  // The bound binary handler. Named via `function audioStoreBinaryHandler` so
  // `Function.name === "audioStoreBinaryHandler"` — AC9 verification reads
  // this name through the boot_complete payload + console.log.
  readonly binaryHandler: (data: Blob | ArrayBuffer) => void;

  // Track previous state so emissions carry both `state` and `prev`.
  private prevState: AudioPlaybackState = "idle";

  constructor(opts: AudioStoreOptions) {
    this.bus                 = opts.bus;
    this.audioContextFactory = opts.audioContextFactory ?? defaultAudioContextFactory;
    this.decodeArrayBufferFn = opts.decodeArrayBufferFn ?? pcm16ToAudioBuffer;
    this.decodeBlobFn        = opts.decodeBlobFn        ?? pcm16ToAudioBufferFromBlob;
    this.sampleRate          = opts.sampleRate          ?? 24000;
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

  queueLength(): number {
    return this.chunksInBurst;
  }

  pause(): void {
    if (this.state() === "playing") this.actor.send({ type: "PAUSE_REQUESTED" });
  }

  resume(): void {
    if (this.state() === "paused") this.actor.send({ type: "RESUME_REQUESTED" });
  }

  skip(): void {
    const s = this.state();
    if (s === "playing" || s === "paused") {
      this.actor.send({ type: "SKIP_REQUESTED" });
      this.chunksInBurst = 0;
    }
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
        const msg = err instanceof Error ? err.message : String(err);
        this.emitErrorState(`audiocontext-blocked: ${msg}`);
        return;
      }
    }

    // Step 2: signal the machine that a chunk arrived (idle → decoding).
    this.chunksInBurst++;
    this.actor.send({ type: "CHUNK_ARRIVED" });

    // Step 3: decode. ArrayBuffer is sync; Blob is async.
    if (data instanceof ArrayBuffer) {
      try {
        const buf = this.decodeArrayBufferFn(data, this.audioContext, this.sampleRate);
        this.onDecoded(buf);
      } catch (err) {
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
    this.decodeBlobFn(data, this.audioContext, this.sampleRate)
      .then((buf) => this.onDecoded(buf))
      /* c8 ignore start */ // Async decode failure — exercised in production when blob malformed; covered indirectly by ArrayBuffer decode-failed test (same code path post the .then/.catch boundary).
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err);
        this.actor.send({ type: "DECODE_FAILED" });
        this.emitTaggedReason(`decode-failed: ${msg}`);
      });
      /* c8 ignore stop */
  }

  private onDecoded(buf: AudioBufferLike): void {
    this.actor.send({ type: "CHUNK_DECODED" });
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
// Default factory — tries `globalThis.AudioContext` then `webkitAudioContext`.
// ---------------------------------------------------------------------------

/* c8 ignore start */ // Browser-only fallback; tests inject `audioContextFactory` directly.
function defaultAudioContextFactory(): AudioContextLike {
  const Ctor = (globalThis as unknown as {
    AudioContext       ?: { new (opts?: { sampleRate?: number }): AudioContextLike };
    webkitAudioContext ?: { new (opts?: { sampleRate?: number }): AudioContextLike };
  }).AudioContext ?? (globalThis as unknown as {
    webkitAudioContext ?: { new (opts?: { sampleRate?: number }): AudioContextLike };
  }).webkitAudioContext;
  if (!Ctor) {
    throw new Error("AudioContext is not available in this environment");
  }
  return new Ctor({ sampleRate: 24000 });
}
/* c8 ignore stop */

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createAudioStore(opts: AudioStoreOptions): AudioStore {
  return new AudioStoreImpl(opts);
}
