// Row 26bfde78 — the TTS slot watchdog (Rick's ruling, 2026-09-19).
// Run via `npx tsx --test src/tests/unit/multiplexer/tts_slot_watchdog.test.ts`.
//
// A stuck item must release the TTS slot, because since A-2 #2d a held slot also
// holds arriving Action Required cards. The two failures that raise nothing — an
// autoplay-blocked context and a stream with no end frame — look identical from the
// store: audio arrived, and no completion ever came.
//
// 🔴 EVERY RELEASE ASSERTION NAMES THE PATH. A natural end and a watchdog release
// both vacate the slot, so "the slot is free" cannot tell which ran. The watchdog
// announces itself with tts_slot_watchdog_released; the tests that expect it assert
// that event, and the tests that must NOT trip it assert its absence.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTtsQueueStore,
  TTS_SLOT_WATCHDOG_GRACE_MS,
} from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import type {
  AudioPlaybackState,
  StoreAudioChunkDecodedPayload,
  StoreAudioStateChangePayload,
  StoreTtsSlotReleasedPayload,
  TtsQueueItem,
  TtsSlotWatchdogReleasedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

const GRACE = 1_000;   // a short grace keeps the arithmetic readable; the production value is separate

// ---------------------------------------------------------------------------
// A fake clock: timers fire only when the test moves time forward.
// ---------------------------------------------------------------------------

function fakeClock( cancellable = true ) {
  let now = 0;
  let seq = 0;
  const timers = new Map<number, { at: number; cb: () => void }>();
  return {
    now      : () => now,
    setTimeoutFn   : ( cb: () => void, ms: number ) => { const id = ++seq; timers.set( id, { at: now + ms, cb } ); return id; },
    clearTimeoutFn : ( id: unknown ) => { if ( cancellable ) timers.delete( id as number ); },
    advance( ms: number ) {
      const until = now + ms;
      for ( ;; ) {
        const due = [ ...timers.entries() ].filter( ( [ , t ] ) => t.at <= until ).sort( ( a, b ) => a[ 1 ].at - b[ 1 ].at )[ 0 ];
        if ( !due ) break;
        timers.delete( due[ 0 ] );
        now = due[ 1 ].at;
        due[ 1 ].cb();
      }
      now = until;
    },
    pending  : () => timers.size,
  };
}

function setup( opts: { cancellable?: boolean } = {} ) {
  const bus   = createEventBusForTesting();
  const clock = fakeClock( opts.cancellable ?? true );
  const fired    : TtsSlotWatchdogReleasedPayload[] = [];
  const released : string[] = [];
  bus.on<TtsSlotWatchdogReleasedPayload>( "tts_slot_watchdog_released", ( e ) => fired.push( e.payload ) );
  bus.on<StoreTtsSlotReleasedPayload>( "store_tts_slot_released", ( e ) => released.push( e.payload.releasedId ) );
  // The halt behaves as AudioStore.stop does: it silences, then reports idle on the bus.
  let halts = 0;
  const haltAudio = () => {
    halts++;
    bus.emit<StoreAudioStateChangePayload>( {
      type : "store_audio_state_change", payload: { state: "idle", prev: "playing" }, source: "AudioStore", ts: 0 } );
  };
  const store = createTtsQueueStore( {
    bus,
    nowFn           : clock.now,
    watchdogGraceMs : GRACE,
    setTimeoutFn    : clock.setTimeoutFn,
    clearTimeoutFn  : clock.clearTimeoutFn,
    haltAudio,
  } );
  const chunk = ( durationMs: number ) => bus.emit<StoreAudioChunkDecodedPayload>( {
    type : "store_audio_chunk_decoded", payload: { durationMs, sampleRate: 24000, frameCount: 1, firstInUtterance: false }, source: "test", ts: 0 } );
  const ended = () => bus.emit( { type: "store_audio_ended", payload: {}, source: "test", ts: 0 } );
  const state = ( s: AudioPlaybackState ) => bus.emit<StoreAudioStateChangePayload>( {
    type : "store_audio_state_change", payload: { state: s, prev: "playing" }, source: "test", ts: 0 } );
  return { bus, clock, store, fired, released, chunk, ended, state, halts: () => halts };
}

function item( id: string, actionRequired = false ): TtsQueueItem {
  return { id_hash: id, ttsText: `say ${id}`, addedAt: 0, action_required: actionRequired } as TtsQueueItem;
}

// ---------------------------------------------------------------------------
// The two silent failures
// ---------------------------------------------------------------------------

test( "autoplay-blocked: audio arrives, never plays, never ends — the watchdog releases the slot at audio end + grace", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.chunk( 2_000 );                                   // 2s of audio scheduled on a context that never runs
  t.clock.advance( 2_000 + GRACE - 1 );
  assert.deepEqual( t.fired, [], "fired before the received audio could have finished plus grace" );
  assert.equal( t.store.current(), "A" );
  t.clock.advance( 1 );
  assert.deepEqual( t.fired, [ { releasedId: "A", heldMs: 2_000 + GRACE } ] );
  assert.equal( t.store.current(), null, "the slot must be free" );
  assert.deepEqual( t.released, [ "A" ], "consumers waiting on the slot must hear it was released" );
} );

test( "a stream with no end frame: the audio played out, the completion never came — released after grace", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.chunk( 500 ); t.clock.advance( 400 ); t.chunk( 500 );   // 1s of audio, the second chunk queued behind the first
  t.clock.advance( 600 + GRACE );                            // cursor ended at t=1000
  assert.equal( t.fired.length, 1 );
  assert.equal( t.fired[ 0 ].releasedId, "A" );
} );

test( "a request that never sends a single chunk is released after the grace alone", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.clock.advance( GRACE );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "A" ] );
} );

// ---------------------------------------------------------------------------
// It must never cut off live speech
// ---------------------------------------------------------------------------

test( "a natural end before the deadline never trips the watchdog", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.chunk( 2_000 );
  t.clock.advance( 2_000 );
  t.ended();
  t.clock.advance( 60_000 );
  assert.deepEqual( t.fired, [], "a completed item must not be released a second time" );
  assert.equal( t.store.current(), null );
  assert.equal( t.clock.pending(), 0, "no timer may outlive the item it guarded" );
} );

test( "a long live stream keeps moving its own deadline: two minutes of speech, far past the grace, never trips it", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  for ( let i = 0; i < 60; i++ ) { t.chunk( 2_000 ); t.clock.advance( 2_000 ); }
  assert.deepEqual( t.fired, [], "a stream that keeps delivering audio is alive, however long it runs" );
  t.ended();
  assert.equal( t.store.current(), null );
} );

// ---------------------------------------------------------------------------
// What the release does next
// ---------------------------------------------------------------------------

test( "the queue rolls to the next item, which gets a fresh deadline of its own", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.store.enqueue( item( "B" ) );
  t.clock.advance( GRACE );
  assert.equal( t.store.current(), "B" );
  t.clock.advance( GRACE - 1 );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "A" ], "B must not inherit A's deadline" );
  t.clock.advance( 1 );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "A", "B" ] );
} );

test( "a stuck Action Required item enters focus, which frees the slot for its own card", () => {
  const t = setup();
  t.store.enqueue( item( "Q", true ) );
  t.store.enqueue( item( "B" ) );
  t.clock.advance( GRACE );
  assert.equal( t.fired[ 0 ].releasedId, "Q" );
  assert.equal( t.store.focusMode(), true, "released like any completion: an unanswered question holds the roll" );
  assert.equal( t.store.current(), null );
  assert.deepEqual( t.released, [ "Q" ] );
} );

// ---------------------------------------------------------------------------
// A manual pause is not a stall
// ---------------------------------------------------------------------------

test( "a manual pause suspends the watchdog, and Play resumes it with the time that was left", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.chunk( 1_000 );
  t.clock.advance( 500 );                      // deadline is 1000 + GRACE; 500 + GRACE left
  t.state( "paused" );
  t.state( "paused" );                         // a repeated pause keeps the first remainder
  t.clock.advance( 3_600_000 );
  assert.deepEqual( t.fired, [], "an hour's pause is the operator's choice, not a stall" );
  t.state( "playing" );
  t.clock.advance( 500 + GRACE - 1 );
  assert.deepEqual( t.fired, [] );
  t.clock.advance( 1 );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "A" ] );
} );

test( "audio that arrives during a pause is added to the time left, not lost", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.state( "paused" );                         // GRACE left
  t.chunk( 3_000 );                            // + 3s of audio still to play
  t.state( "playing" );
  t.clock.advance( 3_000 + GRACE - 1 );
  assert.deepEqual( t.fired, [] );
  t.chunk( 1_000 );                            // the cursor was shifted by the pause, so this extends it
  t.clock.advance( 1_000 );
  assert.deepEqual( t.fired, [], "a chunk after resume must be measured from the shifted cursor" );
  t.clock.advance( GRACE );
  assert.equal( t.fired.length, 1 );
} );

test( "audio state changes and chunks with nothing in the slot are ignored", () => {
  const t = setup();
  t.state( "paused" );
  t.state( "playing" );
  t.chunk( 1_000 );
  t.clock.advance( 60_000 );
  assert.deepEqual( t.fired, [] );
  assert.equal( t.clock.pending(), 0 );
} );

test( "a timer that outlived its item does nothing when it fires", () => {
  const t = setup( { cancellable: false } );   // a clock that cannot cancel, so A's timer survives
  t.store.enqueue( item( "A" ) );              // A's timer: t = GRACE
  t.store.enqueue( item( "B" ) );
  t.clock.advance( GRACE / 2 );
  t.ended();                                   // A ends naturally; B holds the slot, its timer at 1.5 × GRACE
  t.clock.advance( GRACE / 2 );                // A's stale timer fires here
  assert.deepEqual( t.fired, [], "A's stale timer must not release B" );
  assert.equal( t.store.current(), "B" );
  t.clock.advance( GRACE / 2 );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "B" ], "B's own timer still works" );
} );

// ---------------------------------------------------------------------------
// Review findings (2026-09-24): the release must silence what it releases
// ---------------------------------------------------------------------------

test( "a release halts the stuck item's audio, so its late end cannot end the next holder", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.store.enqueue( item( "B" ) );
  t.chunk( 2_000 );
  t.clock.advance( 2_000 + GRACE );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "A" ] );
  assert.equal( t.halts(), 1, "the stuck item's audio must be halted when its slot is released" );
  assert.equal( t.store.current(), "B", "the halt's own idle must not de-light the item the release just promoted" );
} );

test( "a user's Stop still de-lights the slot — only the release's own halt is exempt", () => {
  const t = setup();
  t.store.enqueue( item( "A" ) );
  t.state( "idle" );
  assert.equal( t.store.current(), null );
  assert.equal( t.halts(), 0 );
} );

test( "an item that takes the slot during a manual pause starts suspended", () => {
  const t = setup();
  t.state( "paused" );                         // paused while nothing held the slot
  t.store.enqueue( item( "A" ) );
  t.clock.advance( 3_600_000 );
  assert.deepEqual( t.fired, [], "the timer must not run through a pause that began before the item arrived" );
  t.state( "playing" );
  t.clock.advance( GRACE - 1 );
  assert.deepEqual( t.fired, [] );
  t.clock.advance( 1 );
  assert.deepEqual( t.fired.map( ( f ) => f.releasedId ), [ "A" ] );
} );

test( "the production grace is the measured bound — 15s — not the test's", () => {
  assert.equal( TTS_SLOT_WATCHDOG_GRACE_MS, 15_000 );
} );
