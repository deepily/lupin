// Multiplexer Phase 6 — SequentialAudioManager TS port tests.
//
// TS port of `src/lupin_app/static/js/sequential-audio-manager.js`. Drives
// the queue state machine, retry logic, blob-URL cleanup, Firefox tuning,
// and callback error-isolation deterministically via an injected audio
// factory + a queued (manually-drained) setTimeout seam. Target: c8 --100
// lines/branches/functions on the changed surface.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  SequentialAudioManager,
  type PlayableAudio,
} from "../../../../lupin_app/static/js/multiplexer/audio/SequentialAudioManager";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// --- Test doubles -----------------------------------------------------------

/** Controllable PlayableAudio: records listeners + lets tests fire events. */
class MockAudio implements PlayableAudio {
  src         = "";
  currentTime = 0;
  paused      = true;
  preload     = "";
  volume      = 0;
  played      = 0;
  private readonly listeners: Record<string, (( ev: unknown ) => void)[]> = {};
  constructor( src: string, private readonly playReturn: () => Promise<void> | void ) {
    this.src = src;
  }
  play(): Promise<void> | void {
    this.played++;
    this.paused = false;
    return this.playReturn();
  }
  pause(): void { this.paused = true; }
  addEventListener( type: string, listener: ( ev: unknown ) => void ): void {
    ( this.listeners[ type ] ??= [] ).push( listener );
  }
  fire( type: string, ev?: unknown ): void {
    ( this.listeners[ type ] ?? [] ).forEach( ( l ) => l( ev ) );
  }
}

/** Builds a harness: factory recording created audios + a drainable timer queue. */
function makeHarness( playReturn: () => Promise<void> | void = () => undefined ) {
  const created : MockAudio[] = [];
  const timers  : (() => void)[] = [];
  const revoked : string[] = [];
  let urlSeq = 0;
  return {
    created,
    timers,
    revoked,
    runTimers(): void {
      while ( timers.length > 0 ) {
        const cb = timers.shift() as () => void;
        cb();
      }
    },
    opts: {
      audioFactory    : ( src: string ) => { const a = new MockAudio( src, playReturn ); created.push( a ); return a; },
      createObjectURL : ( _blob: Blob ) => `blob:url-${urlSeq++}`,
      revokeObjectURL : ( url: string ) => { revoked.push( url ); },
      setTimeoutFn    : ( cb: () => void, _ms: number ) => { timers.push( cb ); },
    },
  };
}

const blob = () => new Blob([ "x" ], { type: "audio/mpeg" });
/** Flush all pending microtasks (chained promise .catch handlers). */
const flush = () => new Promise<void>( ( r ) => setTimeout( r, 0 ) );

// --- Constructor ------------------------------------------------------------

test("constructor defaults — initial stats are zeroed + idle", () => {
  const m = new SequentialAudioManager();
  assert.equal( m.isPlaying(), false );
  assert.equal( m.getQueueLength(), 0 );
  assert.deepEqual( m.getStats(), {
    chunksPlayed: 0, queueLength: 0, isPlaying: false,
    totalProcessed: 0, errorCount: 0, activeBlobUrls: 0,
  } );
});

test("constructor honors all options (left-hand ?? branches) + debug log", () => {
  const m = new SequentialAudioManager({
    onChunkStart: () => {}, onChunkEnd: () => {}, debug: true,
    maxQueueSize: 5, retryAttempts: 1, retryDelayMs: 10, cleanupDelayMs: 5,
    audioFactory: ( s ) => new MockAudio( s, () => undefined ),
    createObjectURL: () => "u", revokeObjectURL: () => {},
    setTimeoutFn: () => {}, userAgent: "Mozilla Firefox/1.0",
  });
  assert.equal( m.isPlaying(), false );
});

test("constructor falls back to empty UA when navigator is undefined", () => {
  const orig = globalThis.navigator;
  // @ts-expect-error — exercising the node-safety branch.
  delete (globalThis as { navigator?: unknown }).navigator;
  try {
    const m = new SequentialAudioManager();  // no userAgent → ternary false branch
    assert.equal( m.isPlaying(), false );
  } finally {
    Object.defineProperty( globalThis, "navigator", { value: orig, configurable: true } );
  }
});

// --- addChunk validation ----------------------------------------------------

test("addChunk rejects null (first || clause)", () => {
  const m = new SequentialAudioManager();
  assert.equal( m.addChunk( null ), false );
});

test("addChunk rejects a non-Blob (second || clause)", () => {
  const m = new SequentialAudioManager();
  assert.equal( m.addChunk( {} as unknown as Blob ), false );
});

// --- Happy-path playback ----------------------------------------------------

test("addChunk starts playback + invokes onChunkStart with index", () => {
  const starts: number[] = [];
  const h = makeHarness();
  const m = new SequentialAudioManager({ onChunkStart: ( i ) => starts.push( i ), ...h.opts });
  assert.equal( m.addChunk( blob() ), true );
  assert.equal( m.isPlaying(), true );
  assert.equal( m.getQueueLength(), 0 );      // shifted out for playback
  assert.deepEqual( starts, [ 1 ] );
  assert.equal( h.created.length, 1 );
  assert.equal( h.created[0].played, 1 );
});

test("second addChunk while playing queues instead of double-starting", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager( h.opts );
  m.addChunk( blob() );                        // plays
  m.addChunk( blob() );                        // queued
  assert.equal( m.getQueueLength(), 1 );
  assert.equal( h.created.length, 1 );
  h.created[0].fire( "ended" );                // first completes → second plays
  assert.equal( h.created.length, 2 );
  assert.equal( m.getQueueLength(), 0 );
});

test("ended drains the queue to idle + schedules blob cleanup", () => {
  const ends: number[] = [];
  const h = makeHarness();
  const m = new SequentialAudioManager({ onChunkEnd: ( i ) => ends.push( i ), ...h.opts });
  m.addChunk( blob() );
  h.created[0].fire( "ended" );
  assert.deepEqual( ends, [ 1 ] );
  assert.equal( m.isPlaying(), false );
  h.runTimers();                               // run the queued revoke timer
  assert.equal( h.revoked.length, 1 );
  assert.equal( m.getStats().activeBlobUrls, 0 );
});

// --- Error event ------------------------------------------------------------

test("audio error increments errorCount + advances (debug details, full error)", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ debug: true, ...h.opts });
  m.addChunk( blob() );
  m.addChunk( blob() );                        // give it a next chunk to advance to
  h.created[0].fire( "error", { target: { error: { code: 4, message: "boom" }, src: "blob:x" } } );
  assert.equal( m.getStats().errorCount, 1 );
  assert.equal( h.created.length, 2 );         // advanced to the queued chunk
});

test("audio error tolerates a target-less event (optional-chain branches)", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ debug: true, ...h.opts });
  m.addChunk( blob() );
  h.created[0].fire( "error", {} );            // no target → error?.code/message undefined
  assert.equal( m.getStats().errorCount, 1 );
  assert.equal( m.isPlaying(), false );
});

// --- Firefox tuning ---------------------------------------------------------

test("Firefox UA sets preload=auto + volume=1.0", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ userAgent: "Firefox/120", ...h.opts });
  m.addChunk( blob() );
  assert.equal( h.created[0].preload, "auto" );
  assert.equal( h.created[0].volume, 1.0 );
});

test("non-Firefox UA leaves preload/volume untouched", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ userAgent: "Chrome/120", ...h.opts });
  m.addChunk( blob() );
  assert.equal( h.created[0].preload, "" );
  assert.equal( h.created[0].volume, 0 );
});

// --- Callback error isolation -----------------------------------------------

test("a throwing onChunkStart is caught + playback proceeds", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ onChunkStart: () => { throw new Error( "x" ); }, ...h.opts });
  m.addChunk( blob() );
  assert.equal( m.isPlaying(), true );
  assert.equal( h.created[0].played, 1 );
});

test("a throwing onChunkEnd is caught + queue advances", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ onChunkEnd: () => { throw new Error( "x" ); }, ...h.opts });
  m.addChunk( blob() );
  h.created[0].fire( "ended" );
  assert.equal( m.isPlaying(), false );
});

// --- Retry logic ------------------------------------------------------------

test("play() returning a non-thenable skips the retry catch", () => {
  const h = makeHarness( () => ({} as unknown as Promise<void>) );  // defined, no .then
  const m = new SequentialAudioManager( h.opts );
  m.addChunk( blob() );
  assert.equal( h.created[0].played, 1 );
  assert.equal( h.timers.length, 0 );          // no retry scheduled
});

test("rejected play() retries to exhaustion then advances", async () => {
  const h = makeHarness( () => Promise.reject( new Error( "autoplay-blocked" ) ) );
  const m = new SequentialAudioManager({ retryAttempts: 2, ...h.opts });
  m.addChunk( blob() );
  // Drain: each rejection schedules a retry timer; running it re-plays + re-rejects.
  for ( let i = 0; i < 6 && (h.timers.length > 0 || m.isPlaying()); i++ ) {
    await flush();
    h.runTimers();
  }
  await flush();
  assert.equal( m.isPlaying(), false );        // exhausted → onChunkComplete → idle
  assert.ok( h.created[0].played >= 3 );        // initial + 2 retries
});

test("rejected play() that later succeeds keeps playing until ended", async () => {
  let calls = 0;
  const h = makeHarness( () => {
    calls++;
    return calls === 1 ? Promise.reject( new Error( "blocked" ) ) : Promise.resolve();
  });
  const m = new SequentialAudioManager({ retryAttempts: 3, ...h.opts });
  m.addChunk( blob() );
  await flush();
  h.runTimers();                               // retry → resolves
  await flush();
  assert.equal( m.isPlaying(), true );
  h.created[0].fire( "ended" );
  assert.equal( m.isPlaying(), false );
});

test("retry is abandoned when the current audio changed (stale guard)", async () => {
  const h = makeHarness( () => Promise.reject( new Error( "blocked" ) ) );
  const m = new SequentialAudioManager({ retryAttempts: 3, ...h.opts });
  m.addChunk( blob() );
  await flush();                               // catch fires → retry timer queued
  m.stop();                                    // currentAudio → null (no longer === element)
  const playsBefore = h.created[0].played;
  h.runTimers();                               // guard: currentAudio !== element → skip
  await flush();
  assert.equal( h.created[0].played, playsBefore );
});

// --- stop / reset -----------------------------------------------------------

test("stop pauses non-paused audio, resets time, clears queue", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager( h.opts );
  m.addChunk( blob() );
  m.addChunk( blob() );
  assert.equal( h.created[0].paused, false );
  m.stop();
  assert.equal( h.created[0].paused, true );
  assert.equal( h.created[0].currentTime, 0 );
  assert.equal( m.getQueueLength(), 0 );
  assert.equal( m.isPlaying(), false );
  assert.equal( h.revoked.length, 1 );         // _cleanupCurrentAudio revoked the URL
});

test("stop on already-paused audio does not call pause (branch)", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager( h.opts );
  m.addChunk( blob() );
  h.created[0].paused = true;                  // simulate already paused
  m.stop();
  assert.equal( m.isPlaying(), false );
});

test("stop with nothing playing is a no-op (null currentAudio branch)", () => {
  const m = new SequentialAudioManager();
  m.stop();
  assert.equal( m.isPlaying(), false );
});

test("reset zeroes counters + releases remaining blob URLs", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ debug: true, ...h.opts });
  m.addChunk( blob() );                        // blobUrl tracked, counters bumped
  m.reset();
  assert.deepEqual( m.getStats(), {
    chunksPlayed: 0, queueLength: 0, isPlaying: false,
    totalProcessed: 0, errorCount: 0, activeBlobUrls: 0,
  } );
  assert.ok( h.revoked.length >= 1 );
});

// --- maxQueueSize handling --------------------------------------------------

test("queue at capacity drops the oldest chunk", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ maxQueueSize: 2, ...h.opts });
  m.addChunk( blob() );                        // plays (queue 0)
  m.addChunk( blob() );                        // queue 1
  m.addChunk( blob() );                        // queue 2 (at cap)
  m.addChunk( blob() );                        // cap reached → drop oldest, push → still 2
  assert.equal( m.getQueueLength(), 2 );
});

test("maxQueueSize 0 exercises the empty-queue cleanup branch", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ maxQueueSize: 0, ...h.opts });
  assert.equal( m.addChunk( blob() ), true );  // length(0) >= 0 → cleanup w/ empty queue, then plays
  assert.equal( m.isPlaying(), true );
});

// --- debug-log branch coverage ----------------------------------------------

test("debug=true logs during the scheduled blob-URL cleanup", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager({ debug: true, ...h.opts });
  m.addChunk( blob() );
  h.created[0].fire( "ended" );                // queues cleanup timer
  h.runTimers();                               // runs it with debug=true → log branch
  assert.equal( h.revoked.length, 1 );
});

test("reset with debug=false takes the non-logging _cleanupAllBlobUrls branch", () => {
  const h = makeHarness();
  const m = new SequentialAudioManager( h.opts );  // debug defaults false
  m.addChunk( blob() );
  m.reset();
  assert.equal( m.getStats().activeBlobUrls, 0 );
});

// --- default browser seams (no injection) -----------------------------------

test("default Audio/URL/setTimeout seams run when no overrides are injected", async () => {
  const m = new SequentialAudioManager({ retryAttempts: 0 });  // real browser globals
  assert.equal( m.addChunk( blob() ), true );   // default audioFactory + createObjectURL
  m.onChunkComplete();                          // default setTimeoutFn schedules real cleanup
  await flush();                                // real timer fires → default revokeObjectURL
  assert.equal( m.isPlaying(), false );
});

// --- _cleanupCurrentAudio: URL already gone (has() false branch) ------------

test("cleanup skips revoke when the blob URL was already released", () => {
  // Constant URL so two chunks share it; running the first chunk's cleanup
  // timer removes it from the set while the second chunk still references it.
  const created: MockAudio[] = [];
  const timers : (() => void)[] = [];
  const revoked: string[] = [];
  const m = new SequentialAudioManager({
    audioFactory    : ( s ) => { const a = new MockAudio( s, () => undefined ); created.push( a ); return a; },
    createObjectURL : () => "blob:dup",
    revokeObjectURL : ( u ) => { revoked.push( u ); },
    setTimeoutFn    : ( cb ) => { timers.push( cb ); },
  });
  m.addChunk( blob() );                        // chunk 1 plays, set={dup}
  m.addChunk( blob() );                        // chunk 2 queued
  created[0].fire( "ended" );                  // → cleanup timer queued, chunk 2 plays (re-adds dup)
  timers.shift()!();                           // run chunk-1 cleanup → revoke dup, delete from set
  assert.equal( revoked.length, 1 );
  m.stop();                                    // chunk 2: src=dup, but set no longer has dup → skip revoke
  assert.equal( revoked.length, 1 );           // unchanged → has()=false branch taken
});
