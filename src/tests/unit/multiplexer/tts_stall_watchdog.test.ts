// Row 26bfde78 — the TTS stall watchdog. A stuck stream must release the TTS
// slot, because since A-2 #2d a held slot also holds every arriving Action
// Required card: the operator sees the fleet go quiet, with no console error and
// nothing on screen to explain it.
//
// NOT A PARITY TEST, and deliberately claims no parity row. Legacy has no
// watchdog on the TTS slot either — it awaits an AudioContext resume unbounded
// (notifications.js:4690-4692) and has nothing at all for a stream that sends no
// end frame. Rick ratified this as a DELIBERATE DIVERGENCE FROM THE LEAD on
// 2026-09-19, because legacy predates #2d and does not couple the slot to card
// delivery, so the same hole costs materially less there. Citing a legacy
// coordinate here would be a false citation for behaviour legacy does not have.
//
// Legacy's only neighbouring timer guards FOCUS MODE, not the slot
// (notifications.js:22904-22921, TTS_FOCUS_MODE_FALLBACK_MS) — a different hold
// with a different cause. It is named here so the next reader does not find it
// and conclude this row was already built.
//
// Run: npx tsx --test src/tests/unit/multiplexer/tts_stall_watchdog.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createAudioStore,
  TTS_STALL_FIRST_AUDIO_MS,
  TTS_STALL_TAIL_SLACK_MS,
} from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import type {
  AudioBufferSourceLike,
  AudioContextStateLike,
  AudioDestinationNodeLike,
  SchedulableAudioContext,
} from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import type { AudioBufferLike } from "../../../lupin_app/static/js/multiplexer/audio/pcm-decoder";
import type {
  StoreAudioEndedPayload,
  StoreTtsSlotReleasedPayload,
  TtsQueueItem,
  TtsRequestStartedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Stubs — the same shape audio_store.test.ts uses, plus a controllable clock and
// a source that can REFUSE to fire onended (the autoplay-blocked case, which is
// precisely the one a flag-only watchdog would fail to release).
// ---------------------------------------------------------------------------

class StubAudioBuffer implements AudioBufferLike {
  readonly numberOfChannels : number;
  readonly length           : number;
  readonly sampleRate       : number;
  readonly duration         : number;
  constructor( channels: number, length: number, sampleRate: number ) {
    this.numberOfChannels = channels;
    this.length           = length;
    this.sampleRate       = sampleRate;
    this.duration         = length / sampleRate;
  }
  copyToChannel( _src: Float32Array, _ch: number, _off?: number ): void {}
}

class StubBufferSource implements AudioBufferSourceLike {
  buffer  : AudioBufferLike | null = null;
  onended : ( () => void ) | null  = null;
  readonly startTimes : number[] = [];
  stopped = false;
  connect( _destination: AudioDestinationNodeLike ): void {}
  start( when?: number ): void { this.startTimes.push( when as number ); }
  stop(): void { this.stopped = true; }
  fireEnded(): void { if ( this.onended ) this.onended(); }
}

class StubSchedulableContext implements SchedulableAudioContext {
  currentTime : number;
  state       : AudioContextStateLike;
  readonly destination    : AudioDestinationNodeLike = {};
  readonly createdSources : StubBufferSource[] = [];
  constructor( opts: { currentTime?: number; state?: AudioContextStateLike } = {} ) {
    this.currentTime = opts.currentTime ?? 0;
    this.state       = opts.state       ?? "running";
  }
  createBuffer( channels: number, length: number, sampleRate: number ): AudioBufferLike {
    return new StubAudioBuffer( channels, length, sampleRate );
  }
  createBufferSource(): AudioBufferSourceLike {
    const src = new StubBufferSource();
    this.createdSources.push( src );
    return src;
  }
  suspend(): Promise<void> { this.state = "suspended"; return Promise.resolve(); }
  resume(): Promise<void>  { this.state = "running";   return Promise.resolve(); }
}

/** `seconds` of 24 kHz 16-bit mono PCM — one second is 48,000 bytes, the same
 *  arithmetic used to measure the real corpus quoted in AudioStore's header. */
function pcmSeconds( seconds: number ): ArrayBuffer {
  return new Int16Array( Math.round( 24_000 * seconds ) ).buffer;
}

/** A deterministic timer queue. Records what was armed, in order, and lets a
 *  test fire the outstanding deadline by hand. */
function fakeTimers() {
  let seq = 0;
  const live = new Map<number, () => void>();
  const armedMs : number[] = [];
  return {
    setTimeoutFn : ( cb: () => void, ms: number ): unknown => {
      const id = ++seq;
      live.set( id, cb );
      armedMs.push( ms );
      return id;
    },
    clearTimeoutFn : ( id: unknown ): void => { live.delete( id as number ); },
    /** Every delay ever armed, in arm order. */
    armedMs,
    /** The most recent delay armed. */
    last : (): number => armedMs[ armedMs.length - 1 ]!,
    /** How many deadlines are outstanding right now (0 or 1 by design). */
    outstanding : (): number => live.size,
    /** Fire every outstanding deadline. */
    fire : (): void => {
      const cbs = [ ...live.values() ];
      live.clear();
      for ( const cb of cbs ) cb();
    },
  };
}

function setup( opts: { currentTime?: number } = {} ) {
  const bus    = createEventBusForTesting();
  const timers = fakeTimers();
  const ended  : number[] = [];
  bus.on<StoreAudioEndedPayload>( "store_audio_ended", () => ended.push( 1 ) );

  let ctx: StubSchedulableContext | null = null;
  const store = createAudioStore( {
    bus,
    audioContextFactory : (): SchedulableAudioContext => {
      ctx = new StubSchedulableContext( { currentTime: opts.currentTime } );
      return ctx;
    },
    nowFn          : () => 1_000_000,
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  } );

  const request = (): void => {
    bus.emit<TtsRequestStartedPayload>( {
      type: "tts_request_started", payload: { idHash: "A" }, source: "test", ts: 0,
    } );
  };
  const streamComplete = (): void => {
    bus.emit( { type: "audio_streaming_complete", payload: {}, source: "test", ts: 0 } );
  };
  const feed = ( seconds: number ): void => { store.binaryHandler( pcmSeconds( seconds ) ); };
  const getCtx = (): StubSchedulableContext => {
    if ( ctx === null ) throw new Error( "test bug: no chunk has been fed yet" );
    return ctx;
  };

  return { bus, store, timers, ended, request, streamComplete, feed, getCtx };
}

// ---------------------------------------------------------------------------
// The defect itself — a stuck stream releases the slot
// ---------------------------------------------------------------------------

test( "a request whose stream never yields one chunk releases the slot on the first-audio window", () => {
  const { timers, ended, request } = setup();
  request();
  assert.equal( timers.outstanding(), 1, "armed on the request, not on arriving audio" );
  assert.equal( timers.last(), TTS_STALL_FIRST_AUDIO_MS );
  assert.deepEqual( ended, [], "nothing released before the deadline" );
  timers.fire();
  assert.equal( ended.length, 1, "the slot was released" );
} );

test( "a stream that sends no end frame releases once its own audio has played out", () => {
  const { timers, ended, request, feed, getCtx } = setup();
  request();
  feed( 3 );                                  // 3 s of audio, no end frame ever
  assert.equal( timers.last(), 3000 + TTS_STALL_TAIL_SLACK_MS,
    "the deadline is the audio's own duration plus the tail slack — derived, not picked" );
  getCtx().currentTime = 3;                   // it has now played out
  assert.deepEqual( ended, [] );
  timers.fire();
  assert.equal( ended.length, 1 );
} );

test( "an autoplay-blocked source that never fires onended is still released", () => {
  // The case a flag-only watchdog would miss: maybeComplete's activeSources gate
  // holds while a scheduled source sits there forever, so the watchdog must stop
  // and drop the sources itself.
  const { timers, ended, request, feed, getCtx } = setup();
  request();
  feed( 2 );
  const source = getCtx().createdSources[ 0 ]!;
  assert.equal( source.stopped, false );
  timers.fire();
  assert.equal( source.stopped, true, "the stuck source was stopped, not merely abandoned" );
  assert.equal( ended.length, 1 );
} );

// ---------------------------------------------------------------------------
// The derived deadline — a long but live stream is never cut off
// ---------------------------------------------------------------------------

test( "every chunk re-arms the deadline, so audio that keeps arriving is never cut off", () => {
  const { timers, request, feed, getCtx } = setup();
  request();
  feed( 20 );
  assert.equal( timers.last(), 20_000 + TTS_STALL_TAIL_SLACK_MS );
  feed( 20 );
  assert.equal( timers.last(), 40_000 + TTS_STALL_TAIL_SLACK_MS, "the cursor advanced by the second buffer" );
  feed( 20 );
  assert.equal( timers.last(), 60_000 + TTS_STALL_TAIL_SLACK_MS );
  // 60 s of audio is twice the whole first-audio window and six times the longest
  // utterance in the measured corpus (10.22 s), and the deadline is still ahead of
  // it — there is no total-duration cap for a long stream to run into.
  assert.ok( timers.last() > TTS_STALL_FIRST_AUDIO_MS );
  assert.equal( timers.outstanding(), 1, "exactly one deadline outstanding, never a pile" );
  assert.equal( getCtx().createdSources.length, 3 );
} );

test( "the deadline shrinks to the bare tail slack once the scheduled audio has played out", () => {
  // Exercises the Math.max clamp: nextStartTime is BEHIND currentTime here, and a
  // negative remainder would arm a deadline that fires at once.
  const { timers, request, feed, getCtx } = setup();
  request();
  feed( 2 );
  getCtx().currentTime = 99;        // the clock ran far past the scheduled end
  feed( 0.5 );                      // schedules at currentTime, so remaining = 0.5 s
  assert.equal( timers.last(), 500 + TTS_STALL_TAIL_SLACK_MS );
  assert.ok( timers.last() > 0, "never a negative or zero delay" );
} );

// ---------------------------------------------------------------------------
// Disarming — the watchdog never fires on a healthy or halted utterance
// ---------------------------------------------------------------------------

test( "the end frame disarms the watchdog: after a clean completion nothing is outstanding", () => {
  const { timers, ended, request, feed, getCtx, streamComplete } = setup();
  request();
  feed( 1 );
  streamComplete();
  getCtx().createdSources[ 0 ]!.fireEnded();
  assert.equal( ended.length, 1, "released by the real end, not by the watchdog" );
  assert.equal( timers.outstanding(), 0, "no deadline left to fire against the NEXT utterance" );
  timers.fire();
  assert.equal( ended.length, 1, "firing an empty queue releases nothing a second time" );
} );

test( "stop() disarms, and disarming twice is safe", () => {
  const { timers, ended, request, feed, store } = setup();
  request();
  feed( 1 );
  assert.equal( timers.outstanding(), 1 );
  store.stop();
  assert.equal( timers.outstanding(), 0 );
  store.stop();                       // haltSources again — the already-null arm
  assert.equal( timers.outstanding(), 0 );
  timers.fire();
  assert.deepEqual( ended, [], "a stopped utterance is not released a second time by a stale timer" );
} );

test( "a manual pause disarms and resume re-derives from the audio still scheduled", () => {
  // A paused utterance is held by the operator, not stuck. suspend() freezes the
  // context clock while the watchdog runs on wall time, so leaving it armed would
  // call a paused stream stuck for no reason but the operator's own hand.
  const { timers, store, request, feed, getCtx } = setup();
  request();
  feed( 8 );
  assert.equal( timers.outstanding(), 1 );
  store.pause();
  assert.equal( timers.outstanding(), 0, "a manual pause is not a stall" );
  getCtx().currentTime = 3;           // 3 s played before the pause
  store.resume();
  assert.equal( timers.outstanding(), 1 );
  assert.equal( timers.last(), 5000 + TTS_STALL_TAIL_SLACK_MS, "5 s of audio left, re-derived" );
} );

test( "pause() from a state that is not playing arms nothing", () => {
  const { timers, store } = setup();
  store.pause();                       // idle — the early return
  assert.equal( timers.outstanding(), 0 );
  assert.deepEqual( timers.armedMs, [] );
} );

// ---------------------------------------------------------------------------
// The coupling this row exists for — A-2 #2d
// ---------------------------------------------------------------------------

test( "the watchdog's release runs the whole real chain: the TTS slot is freed for the queue store", () => {
  // Not a mock of the release — the real TtsQueueStore on the real bus, so the
  // assertion is that store_tts_slot_released actually reaches the consumer that
  // A-2 #2d gates Action Required activation on.
  const { bus, timers, request, feed } = setup();
  const released : string[] = [];
  bus.on<StoreTtsSlotReleasedPayload>( "store_tts_slot_released", ( e ) => released.push( e.payload.releasedId ) );

  const queue = createTtsQueueStore( { bus, nowFn: () => 7 } );
  const item : TtsQueueItem = { id_hash: "STUCK", ttsText: "hello", addedAt: 1, action_required: false };
  queue.enqueue( item );
  assert.equal( queue.isPlaying(), true, "the slot is held" );

  request();
  feed( 1 );
  assert.deepEqual( released, [], "still held while the stream might yet be alive" );

  timers.fire();
  assert.deepEqual( released, [ "STUCK" ], "the watchdog released the slot through the real chain" );
  assert.equal( queue.isPlaying(), false );
  assert.equal( queue.current(), null );
} );

// ---------------------------------------------------------------------------
// The machine must survive the release, or the stall is traded for a deafness
// that outlives it
// ---------------------------------------------------------------------------

test( "a watchdog fire during an unresolved decode leaves the machine able to play the NEXT utterance", () => {
  // `decoding` accepts only CHUNK_DECODED / DECODE_FAILED. A decode promise that
  // never settles parks the machine there, and a release that ignored that would
  // free this slot while making every later utterance silent — the next
  // CHUNK_ARRIVED has no transition out of `decoding` either.
  const bus    = createEventBusForTesting();
  const timers = fakeTimers();
  const ended  : number[] = [];
  bus.on<StoreAudioEndedPayload>( "store_audio_ended", () => ended.push( 1 ) );

  let settle : ( ( b: AudioBufferLike ) => void ) | null = null;
  const store = createAudioStore( {
    bus,
    audioContextFactory : (): SchedulableAudioContext => new StubSchedulableContext(),
    // The Blob door is the async one; hold its promise open forever on the first
    // call so the machine parks in `decoding`.
    decodeBlobFn   : () => new Promise<AudioBufferLike>( ( res ) => { settle = res; } ),
    nowFn          : () => 1_000_000,
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  } );

  bus.emit<TtsRequestStartedPayload>( {
    type: "tts_request_started", payload: { idHash: "A" }, source: "test", ts: 0,
  } );
  store.binaryHandler( new Blob( [ pcmSeconds( 1 ) ] ) );
  assert.equal( store.state(), "decoding", "parked on a decode that never settles" );
  assert.notEqual( settle, null, "the decode really was entered" );

  timers.fire();
  assert.equal( ended.length, 1, "the slot was released" );
  assert.equal( store.state(), "error",
    "and the machine was moved somewhere that accepts a fresh chunk — not left in `decoding`" );

  // The proof that matters: the NEXT utterance can still start.
  store.binaryHandler( pcmSeconds( 1 ) );
  assert.equal( store.state(), "playing", "the next utterance plays; the release did not deafen the client" );
} );
