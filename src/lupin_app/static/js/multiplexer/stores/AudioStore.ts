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
  StoreTtsModeChangedPayload,
} from "../shared/types";
import type { AudioContextLike, AudioBufferLike } from "../audio/pcm-decoder";
import { pcm16ToAudioBuffer, pcm16ToAudioBufferFromBlob } from "../audio/pcm-decoder";
import { error as debugError } from "../shared/debugSink";

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

/**
 * The page-wide TTS mode (parity B-1, §6a ruling 3). `"instant"` streams PCM back
 * from ElevenLabs; `"reliable"` batches it through OpenAI. Legacy reads its
 * `#tts-mode` select at seven playback sites; the multiplexer reads this instead.
 */
export type TtsMode = "instant" | "reliable";

export interface AudioStore {
  state(): AudioPlaybackState;
  /**
   * The page-wide TTS mode. `"instant"` until the B-1 select says otherwise, and
   * NOT persisted — legacy's select is markup-only (notifications.html:134-137),
   * so a reload returns to instant on both clients.
   */
  ttsMode(): TtsMode;
  /** Write the page-wide TTS mode; emits `store_tts_mode_changed` on a real change. */
  setTtsMode( mode: TtsMode ): void;
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

// ---------------------------------------------------------------------------
// Row 26bfde78 — THE STALL WATCHDOG. Rick ruled 2026-09-19 that a stuck TTS
// stream must release the slot on a timeout, because since A-2 #2d a held slot
// also holds every arriving Action Required card: a dead stream does not merely
// stop speech, it queues the questions waiting on the operator, with no console
// error and nothing on screen to explain it.
//
// 🔴 THE DEADLINE IS DERIVED PER UTTERANCE, NOT PICKED. Rick left the timeout
// value unruled and said to derive it from measured stream durations, because
// too tight a constant cuts off a slow-but-live stream — a new defect traded for
// an old one. So there is no total-duration cap here at all. The deadline tracks
// `nextStartTime`, the scheduler's own cursor of when the audio decoded SO FAR
// finishes playing: every scheduled buffer pushes it out by that buffer's real
// duration. A genuinely long utterance re-arms itself for as long as its audio
// keeps arriving and can never be cut off, however long it runs.
//
// That leaves only two constants, and both bound a SILENCE, never a length:
//
//   TTS_STALL_TAIL_SLACK_MS — all scheduled audio has played out and the server
//     still has not sent its end frame. The server sends that frame immediately
//     after the last chunk, so this bounds DELIVERY, not speech.
//   TTS_STALL_FIRST_AUDIO_MS — the request went out and not one chunk has ever
//     decoded. Covers a stream that yields nothing and an AudioContext whose
//     resume() never settles (the promise neither resolves nor rejects, so the
//     .catch arm at resumeIfSuspended never runs either).
//
// MEASURED 2026-09-25, dev + test containers, ElevenLabs `pcm_24000` door:
//   - whole-utterance DELIVERY, server-side: n=17, min 0.23 s, max 1.32 s
//     (`[TTS-ELEVENLABS] ✓ Complete - N chunks in X.XXs`, speech.py:1325)
//   - audible length, summed from the per-chunk byte counts at 48,000 B/s:
//     n=10, min 2.24 s, median 3.18 s, max 10.22 s
//   - spoken-text corpus, `notifications` table, 30 days to 2026-09-25:
//     n=176,961, p50 75 chars, p99 808, max 3,088
// The two constants below are ~7.5x and ~23x the worst delivery observed. The
// audible figures are recorded because they are what a flat cap would have had
// to clear, and the text corpus is why no flat cap was chosen: at the p99 length
// a legitimate utterance runs far past any window short enough to be useful.
//
// ⚠️ THE POPULATIONS ARE SMALL AND ONE-DAY, and are stated rather than rounded
// away. n=17 and n=10 are what the two live containers held at 7 h uptime; no
// older corpus survives, because docker log rotation is the only archive and
// nothing persists a per-utterance duration. The text corpus is large but is a
// proxy — it is the message as SENT, and the `tts preview` limiter in
// lupin-app.ini truncates a spoken body over 100 chars to a fraction of itself,
// so the audible length is shorter than the character count implies by a factor
// this measurement does NOT pin down.
// ---------------------------------------------------------------------------

/** Row 26bfde78 — silence allowed after the last scheduled audio finishes, before
 *  the stream is called stuck. ~7.5x the worst delivery measured (1.32 s), and the
 *  same value as QueueTransport's HANDSHAKE_TIMEOUT_MS, the one other watchdog on
 *  a server frame in this client. */
export const TTS_STALL_TAIL_SLACK_MS  = 10_000;

/** Row 26bfde78 — silence allowed between the speech request and the first chunk
 *  that decodes. ~23x the worst delivery measured, and one full
 *  `websocket heartbeat interval seconds` (30) — a silence spanning an entire
 *  heartbeat cycle is one the transport layer has already had its own chance to
 *  notice. */
export const TTS_STALL_FIRST_AUDIO_MS = 30_000;

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
  /** Row 26bfde78 — the stall watchdog's timer. Test injection; production
   *  defaults to `globalThis.setTimeout` / `globalThis.clearTimeout`. */
  setTimeoutFn        ?: ( cb: () => void, ms: number ) => unknown;
  clearTimeoutFn      ?: ( id: unknown ) => void;
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
  private readonly setTimeoutFn   : ( cb: () => void, ms: number ) => unknown;
  private readonly clearTimeoutFn : ( id: unknown ) => void;

  private readonly actor: ActorRefFrom<typeof audioMachine>;

  // Parity B-1 — the page-wide TTS mode. Held here rather than in ViewStateStore
  // because every playback path already reaches AudioStore, and it is deliberately
  // NOT persisted (§6a ruling 3).
  private ttsModeValue: TtsMode = "instant";

  // Parity B-1b — is the NEXT decoded chunk the first of this utterance? Set where
  // a new utterance is recognised (the same preState test that clears
  // streamComplete) and cleared by the decode that consumes it. A dedicated flag
  // rather than `chunksInBurst === 1`: that counter survives a natural completion,
  // so it can never read 1 again after the page's first utterance.
  private firstChunkPending = false;

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
  // Row 0b384107 — an error (decode failure, blocked or unresumable audio
  // context) struck the current utterance. Legacy advances the queue on an
  // audio error (notifications.js:4336-4340). Here a failed utterance may have
  // scheduled no source at all, so utterancePending never rose and the
  // stream-complete frame completed nothing: the item held the TTS slot
  // forever. With this set, that frame still ends the utterance, once. It is
  // NOT released per error: one decode failure emits two error changes, and a
  // blocked context emits one per chunk, so counting errors would skip items.
  private utteranceFailed  = false;

  // The bound binary handler. Named via `function audioStoreBinaryHandler` so
  // `Function.name === "audioStoreBinaryHandler"` — AC9 verification reads
  // this name through the boot_complete payload + console.log.
  readonly binaryHandler: (data: Blob | ArrayBuffer) => void;

  // Track previous state so emissions carry both `state` and `prev`.
  private prevState: AudioPlaybackState = "idle";

  // Row 26bfde78 — the stall watchdog's live timer handle, or null when disarmed.
  // Exactly one is ever outstanding: every arm disarms first, so a timer for the
  // audio scheduled at step N can never fire against step N+1's schedule.
  private stallTimer: unknown | null = null;

  constructor(opts: AudioStoreOptions) {
    this.bus                 = opts.bus;
    /* c8 ignore next */ // production-default fallback: defaultAudioContextFactory wraps the browser-only `AudioContext`/`webkitAudioContext`; tests always inject a stub audioContextFactory.
    this.audioContextFactory = opts.audioContextFactory ?? defaultAudioContextFactory;
    this.decodeArrayBufferFn = opts.decodeArrayBufferFn ?? pcm16ToAudioBuffer;
    this.decodeBlobFn        = opts.decodeBlobFn        ?? pcm16ToAudioBufferFromBlob;
    this.sampleRate          = opts.sampleRate          ?? 24000;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests always inject a deterministic nowFn().
    this.nowFn               = opts.nowFn               ?? (() => Date.now());
    /* c8 ignore next */ // production-default fallback: globalThis.setTimeout is the runtime timer; tests always inject a deterministic setTimeoutFn.
    this.setTimeoutFn        = opts.setTimeoutFn        ?? (( cb, ms ) => globalThis.setTimeout( cb, ms ));
    /* c8 ignore next */ // production-default fallback: pairs with the setTimeout default above.
    this.clearTimeoutFn      = opts.clearTimeoutFn      ?? (( id )     => globalThis.clearTimeout( id as ReturnType<typeof globalThis.setTimeout> ));

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
    this.bus.on("tts_error", () => this.handleTtsError());
    // Row 26bfde78 — arm the stall watchdog the moment speech is REQUESTED, not
    // when audio arrives: a stream that yields no chunk at all never reaches this
    // store by any other route.
    this.bus.on("tts_request_started", () => this.armStall(TTS_STALL_FIRST_AUDIO_MS));

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

  ttsMode(): TtsMode {
    return this.ttsModeValue;
  }

  setTtsMode( mode: TtsMode ): void {
    // A no-op write emits nothing — a select fires `change` only on a real change,
    // but a restore path could write the same value and a repaint per identical
    // write is noise the pane would have to de-duplicate itself.
    if ( mode === this.ttsModeValue ) return;
    this.ttsModeValue = mode;
    this.bus.emit<StoreTtsModeChangedPayload>( {
      type    : "store_tts_mode_changed",
      payload : { mode },
      source  : "AudioStore",
      ts      : this.nowFn(),
    } );
  }

  pause(): void {
    // P6-b — suspend() freezes the context clock, so currentTime and every
    // already-scheduled start(when) offset stay coherent; resume() does NOT
    // rebase nextStartTime (F-Sam-A2) — that no-fixup is what keeps playback
    // gapless across a pause. Invariant: state "playing" ⇒ a chunk flowed
    // through handleBinary, so audioContext is constructed (non-null).
    if (this.state() !== "playing") return;
    this.actor.send({ type: "PAUSE_REQUESTED" });
    // Row 26bfde78 — suspend() freezes the context clock while the watchdog runs
    // on wall time, so a paused utterance would be called stuck for no reason
    // other than the operator holding it. A manual pause is not a stall.
    this.disarmStall();
    void this.audioContext!.suspend();
  }

  resume(): void {
    // P6-b — resume the (paused → suspended) context; same non-rebase invariant
    // as pause(). Invariant: state "paused" ⇒ audioContext is non-null.
    if (this.state() !== "paused") return;
    this.actor.send({ type: "RESUME_REQUESTED" });
    // Row 26bfde78 — re-derive from what is still scheduled. The clock resumed
    // where it froze and nextStartTime was never rebased (F-Sam-A2), so the
    // difference is again exactly the audio left to play.
    this.armStall( this.remainingAudioMs( this.audioContext! ) + TTS_STALL_TAIL_SLACK_MS );
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
    // Row 26bfde78 — a halted utterance has no deadline to miss.
    this.disarmStall();
    for (const source of this.activeSources) source.stop();
    this.activeSources    = [];
    this.nextStartTime    = 0;
    this.streamComplete   = false;
    this.utterancePending = false;
    this.utteranceFailed  = false;
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
      // B-1b — a new utterance begins here, so its first decode is the TTFA stamp.
      this.firstChunkPending = true;
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
    // B-1b — consume the flag: exactly one chunk per utterance carries it true. A
    // chunk whose decode THREW never reaches here, so the flag survives to the next
    // one, which is the behaviour wanted — TTFA is time-to-first-audio, and a chunk
    // that failed to decode produced none.
    const firstInUtterance = this.firstChunkPending;
    this.firstChunkPending = false;
    this.bus.emit<StoreAudioChunkDecodedPayload>({
      type    : "store_audio_chunk_decoded",
      payload : {
        durationMs : buf.duration * 1000,
        sampleRate : buf.sampleRate,
        frameCount : buf.length,
        firstInUtterance,
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
    // Row 26bfde78 — the derived deadline. `nextStartTime` now names the context
    // clock instant this utterance's decoded audio finishes, so the watchdog is
    // re-armed for exactly that much audio plus the tail slack. Each further
    // buffer pushes it out again: audio that keeps arriving keeps the deadline
    // ahead of itself, which is why no total-duration cap is needed or wanted.
    this.armStall( this.remainingAudioMs( ctx ) + TTS_STALL_TAIL_SLACK_MS );

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

  // Row cd6fe6d6 — the server reported the utterance failed. Legacy
  // handleTTSError (notifications.js:4483-4504) marks the stream complete and
  // calls onTTSPlaybackComplete. Here it is a failed utterance whose stream is
  // over, so maybeComplete ends it now, or when audio already scheduled has
  // played out; the server's trailing complete frame (speech.py:1318) then
  // finds nothing left to end. The same one completion a failed request gives.
  private handleTtsError(): void {
    this.utteranceFailed = true;
    this.streamComplete  = true;
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
    // Nothing to complete (already done / audio-less) — unless it failed (0b384107).
    if (!this.utterancePending && !this.utteranceFailed) return;
    if (this.activeSources.length > 0) return;
    // Row 26bfde78 — the utterance ended on its own; stand the watchdog down
    // before the release goes out.
    this.disarmStall();
    this.utterancePending = false;
    this.utteranceFailed  = false;
    this.streamComplete   = false;
    this.actor.send({ type: "PLAYBACK_ENDED" });     // drive XState → ended
    this.bus.emit<StoreAudioEndedPayload>({
      type    : "store_audio_ended",
      payload : {},
      source  : "AudioStore",
      ts      : this.nowFn(),
    });
  }

  // -------------------------------------------------------------------------
  // Row 26bfde78 — the stall watchdog (see the constants block at the top).
  // -------------------------------------------------------------------------

  /** Milliseconds of decoded audio still scheduled to play on `ctx`'s clock. */
  private remainingAudioMs( ctx: SchedulableAudioContext ): number {
    // Math.max clamps the arm that has already played out: nextStartTime is
    // behind currentTime once the last buffer finishes, and a negative delay
    // would arm a timer that fires immediately.
    return Math.max( 0, ( this.nextStartTime - ctx.currentTime ) * 1000 );
  }

  /** Arm the watchdog for `ms`, replacing any outstanding deadline. */
  private armStall( ms: number ): void {
    this.disarmStall();
    this.stallTimer = this.setTimeoutFn( () => this.onStallDeadline(), ms );
  }

  /** Stand the watchdog down. Safe to call when nothing is armed. */
  private disarmStall(): void {
    if ( this.stallTimer === null ) return;
    this.clearTimeoutFn( this.stallTimer );
    this.stallTimer = null;
  }

  /**
   * The deadline passed: no end frame, and no audio left that could still be
   * playing. Force the utterance to the same completion a real end gives, so the
   * WHOLE existing release chain runs unchanged — store_audio_ended →
   * TtsQueueStore.onAudioEnded → advance → emit → store_tts_slot_released →
   * ActionRequiredStore.activateHead. Nothing here reaches into the queue store;
   * the COND-2 ownership boundary is intact.
   *
   * Ensures:
   *   - every source that never reported `onended` is stopped and dropped, so
   *     the `activeSources.length > 0` gate in maybeComplete cannot hold. An
   *     autoplay-blocked context never fires onended at all, which is exactly
   *     the case a watchdog that only set the flags would fail to release.
   *   - `utteranceFailed` is set, mirroring handleTtsError: the utterance ended
   *     badly, and maybeComplete's "nothing to complete" guard must not swallow
   *     an utterance that scheduled no source.
   *   - a line reaches the console and the debug panel. The defect this row
   *     exists for is SILENT; a release that is equally silent replaces one
   *     unexplained state with another.
   */
  private onStallDeadline(): void {
    this.stallTimer = null;
    debugError(
      `TTS stall watchdog: no end frame and no audio left — releasing the slot ` +
      `(${this.activeSources.length} source(s) never ended, streamComplete=${this.streamComplete})`,
    );
    for ( const source of this.activeSources ) source.stop();
    this.activeSources    = [];
    this.nextStartTime    = 0;
    this.utteranceFailed  = true;
    this.streamComplete   = true;
    // A decode that never settles leaves the machine in `decoding`, and that
    // state accepts only CHUNK_DECODED / DECODE_FAILED — not the PLAYBACK_ENDED
    // maybeComplete is about to send, and not the CHUNK_ARRIVED the NEXT
    // utterance opens with. Releasing the slot but leaving the machine there
    // would trade this stall for a deafness that outlives it. DECODE_FAILED is
    // also simply true: the watchdog fired with that decode still outstanding.
    if ( this.state() === "decoding" ) this.actor.send( { type: "DECODE_FAILED" } );
    this.maybeComplete();
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
    this.utteranceFailed = true;
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
    this.utteranceFailed = true;
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
