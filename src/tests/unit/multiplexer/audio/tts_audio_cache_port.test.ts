// Multiplexer Phase 6 — TtsAudioCache TS port tests.
//
// TS port of `src/lupin_app/static/js/tts-audio-cache.js`. Drives the
// dual-tier (memory + IndexedDB) cache state machine, SHA-256 keying,
// time-based expiration, the size-bounded cursor cleanup sweep, the IDB
// open/get/put/clear paths, and the memory-only fallback — all
// deterministically via a tiny in-memory fake IndexedDB + injected
// clock / digest / interval seams. Target: c8 --100 lines/branches/functions
// on the changed surface.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  TtsAudioCache,
  type CacheEntry,
  type SubtleDigestFn,
  type MinimalIdbFactory,
  type MinimalIdbDatabase,
  type MinimalIdbObjectStore,
  type MinimalIdbOpenRequest,
  type MinimalIdbRequest,
  type MinimalIdbCursor,
} from "../../../../lupin_app/static/js/multiplexer/audio/TtsAudioCache";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// --- Helpers ----------------------------------------------------------------

const blob = ( size = 10 ) => {
  const b = new Blob([ "x".repeat( size ) ], { type: "audio/mpeg" });
  // happy-dom Blob.size reflects byte length; assert our intent holds.
  return b;
};

/** Flush pending microtasks + the macrotask queue (IDB callbacks fire async). */
const flush = () => new Promise<void>( ( r ) => setTimeout( r, 0 ) );

/** Deterministic digest: 32-byte buffer whose first byte is the byte-sum. */
const fakeDigest: SubtleDigestFn = ( _algorithm, data ) => {
  const bytes = new Uint8Array( data as ArrayBuffer );
  let sum = 0;
  for ( const b of bytes ) sum = ( sum + b ) & 0xff;
  const out = new Uint8Array( 32 );
  out[ 0 ] = sum;
  return Promise.resolve( out.buffer );
};

interface FakeIdbConfig {
  openError?      : boolean;
  storeExists?    : boolean;
  triggerUpgrade? : boolean;
  rows?           : CacheEntry[];
  getError?       : boolean;
  putError?       : boolean;
}

interface FakeIdbHandle {
  factory : MinimalIdbFactory;
  puts    : CacheEntry[];
  deleted : string[];
  state   : { cleared: boolean; createdStore: boolean };
}

/** Build a tiny in-memory fake IndexedDB that fires callbacks asynchronously. */
function makeFakeIdb( cfg: FakeIdbConfig = {} ): FakeIdbHandle {
  const puts    : CacheEntry[] = [];
  const deleted : string[]     = [];
  const state   = { cleared: false, createdStore: false };
  const rows    = cfg.rows ?? [];

  const store: MinimalIdbObjectStore = {
    createIndex() { /* recorded via createObjectStore below */ },
    get( key ) {
      const req: MinimalIdbRequest<CacheEntry | undefined> = {
        onsuccess: null, onerror: null, result: undefined, error: null,
      };
      queueMicrotask(() => {
        if ( cfg.getError ) { req.onerror?.( null ); return; }
        req.result = rows.find( ( r ) => r.key === key );
        req.onsuccess?.( { target: { result: req.result } } );
      });
      return req;
    },
    put( entry ) {
      const req: MinimalIdbRequest = {
        onsuccess: null, onerror: null, result: null,
        error: cfg.putError ? new Error( "put failed" ) : null,
      };
      queueMicrotask(() => {
        if ( cfg.putError ) { req.onerror?.( null ); return; }
        puts.push( entry );
        req.onsuccess?.( { target: { result: null } } );
      });
      return req;
    },
    clear() { state.cleared = true; },
    openCursor() {
      const req: MinimalIdbRequest<MinimalIdbCursor | null> = {
        onsuccess: null, onerror: null, result: null, error: null,
      };
      let i = 0;
      const step = () => {
        if ( i >= rows.length ) { req.onsuccess?.( { target: { result: null } } ); return; }
        const row = rows[ i++ ];
        const cursor: MinimalIdbCursor = {
          value    : row,
          delete   : () => { deleted.push( row.key ); },
          continue : () => { queueMicrotask( step ); },
        };
        req.onsuccess?.( { target: { result: cursor } } );
      };
      queueMicrotask( step );
      return req;
    },
  };

  const db: MinimalIdbDatabase = {
    objectStoreNames  : { contains: () => cfg.storeExists ?? false },
    createObjectStore : () => { state.createdStore = true; return store; },
    transaction       : () => ( { objectStore: () => store } ),
  };

  const factory: MinimalIdbFactory = {
    open() {
      const req: MinimalIdbOpenRequest = {
        onsuccess: null, onerror: null, onupgradeneeded: null,
        result: db, error: cfg.openError ? new Error( "open failed" ) : null,
      };
      queueMicrotask(() => {
        if ( cfg.openError ) { req.onerror?.( null ); return; }
        if ( cfg.triggerUpgrade ?? true ) req.onupgradeneeded?.( { target: { result: db } } );
        req.onsuccess?.( null );
      });
      return req;
    },
  };

  return { factory, puts, deleted, state };
}

/** A standard injected-seam options bundle around a fake IDB + fixed clock. */
function seamOpts( clock: { t: number }, idb?: FakeIdbHandle, extra: Record<string, unknown> = {} ) {
  return {
    subtleDigest  : fakeDigest,
    now           : () => clock.t,
    setIntervalFn : () => { /* no-op by default */ },
    ...( idb ? { indexedDBFactory: idb.factory } : {} ),
    ...extra,
  };
}

// --- Constructor ------------------------------------------------------------

test("constructor defaults — caching enabled, zeroed stats, default seams assigned", () => {
  const c = new TtsAudioCache();
  const s = c.getStats();
  assert.equal( s.enabled, true );
  assert.equal( s.hits, 0 );
  assert.equal( s.misses, 0 );
  assert.equal( s.stores, 0 );
  assert.equal( s.hitRate, "0%" );      // total === 0 branch
  assert.equal( s.totalSize, "0.00 MB" );
  assert.equal( s.entries, 0 );
});

test("constructor explicit options — cacheEnabled:false disables lookups", async () => {
  const c = new TtsAudioCache({
    cacheEnabled: false, maxAge: 1, maxSize: 1, debug: true,
  });
  assert.equal( c.getStats().enabled, false );
  assert.equal( await c.checkCache( "x" ), null );   // disabled → null
  await c.saveToCache( "x", blob() );                // disabled → no-op
  assert.equal( c.getStats().stores, 0 );
});

test("default seams — real crypto digest, Date.now expiry, global setInterval", async () => {
  const idb  = makeFakeIdb();
  const origSetInterval = globalThis.setInterval;
  let scheduled = false;
  // Cover the default setIntervalFn body without leaking a real interval.
  globalThis.setInterval = ( (): number => { scheduled = true; return 0; } ) as unknown as typeof setInterval;
  try {
    // Omit subtleDigest / now / setIntervalFn → exercise their default bodies.
    const c = new TtsAudioCache({ indexedDBFactory: idb.factory });
    const key = await c.generateCacheKey( "Hello World" );      // real crypto.subtle
    assert.match( key, /^[0-9a-f]{64}$/ );
    assert.equal( c.isExpired( { key, text: "", audioBlob: blob(), timestamp: Date.now(), size: 10 } ), false ); // real Date.now
    await c.initialize();                                       // success → scheduleCleanup → global setInterval
    assert.equal( scheduled, true );
  } finally {
    globalThis.setInterval = origSetInterval;
  }
});

// --- generateCacheKey -------------------------------------------------------

test("generateCacheKey — injected digest yields 64-char hex, normalizes text", async () => {
  const c = new TtsAudioCache( seamOpts( { t: 0 } ) );
  const k1 = await c.generateCacheKey( "  HELLO  " );
  const k2 = await c.generateCacheKey( "hello" );           // trim + lowercase → same key
  assert.equal( k1, k2 );
  assert.match( k1, /^[0-9a-f]{64}$/ );
});

// --- initialize -------------------------------------------------------------

test("initialize — disabled cache is a no-op (no interval, db stays null)", async () => {
  let intervalCalls = 0;
  const c = new TtsAudioCache({
    cacheEnabled: false, debug: true,
    setIntervalFn: () => { intervalCalls++; },
  });
  await c.initialize();
  assert.equal( intervalCalls, 0 );
});

test("initialize — success creates store + index, arms cleanup", async () => {
  const idb = makeFakeIdb({ storeExists: false, triggerUpgrade: true });
  let armed = false;
  const c = new TtsAudioCache( seamOpts( { t: 0 }, idb, {
    debug: true, setIntervalFn: () => { armed = true; },
  } ) );
  await c.initialize();
  assert.equal( idb.state.createdStore, true );
  assert.equal( armed, true );
});

test("initialize — success skips store creation when it already exists", async () => {
  const idb = makeFakeIdb({ storeExists: true, triggerUpgrade: true });
  const c = new TtsAudioCache( seamOpts( { t: 0 }, idb ) );
  await c.initialize();
  assert.equal( idb.state.createdStore, false );
});

test("initialize — success without an upgrade event still opens", async () => {
  const idb = makeFakeIdb({ triggerUpgrade: false });
  const c = new TtsAudioCache( seamOpts( { t: 0 }, idb ) );
  await c.initialize();
  assert.equal( idb.state.createdStore, false );
});

test("initialize — open error falls back to memory-only (no throw)", async () => {
  const idb = makeFakeIdb({ openError: true });
  const c = new TtsAudioCache( seamOpts( { t: 0 }, idb ) );
  await c.initialize();                       // catch path: warns, db null
  // memory-only still works:
  await c.saveToCache( "m", blob() );
  assert.equal( c.getStats().stores, 1 );
});

test("initialize — null factory rejects, falls back to memory-only", async () => {
  const c = new TtsAudioCache({
    subtleDigest: fakeDigest, now: () => 0, setIntervalFn: () => {},
    indexedDBFactory: null,
  });
  await c.initialize();                       // initializeIndexedDB rejects → catch
  await c.saveToCache( "m", blob() );
  assert.equal( c.getStats().stores, 1 );
});

// --- checkCache -------------------------------------------------------------

test("checkCache — fresh memory hit returns the blob and counts a hit", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { debug: true } ) );
  const b = blob();
  await c.saveToCache( "alpha", b );          // db null → memory only
  const got = await c.checkCache( "alpha" );
  assert.equal( got, b );
  assert.equal( c.getStats().hits, 1 );
});

test("checkCache — expired memory entry is evicted, then misses", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { maxAge: 100 } ) );
  await c.saveToCache( "bravo", blob() );
  clock.t = 5000;                             // now far past maxAge
  const got = await c.checkCache( "bravo" );
  assert.equal( got, null );
  assert.equal( c.getStats().misses, 1 );
  assert.equal( c.getStats().entries, 0 );    // expired entry removed
});

test("checkCache — IndexedDB hit promotes into memory", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock ) );          // need key first
  const key = await c.generateCacheKey( "charlie" );
  const row : CacheEntry = { key, text: "charlie", audioBlob: blob(), timestamp: 900, size: 10 };
  const idb = makeFakeIdb({ rows: [ row ] });
  const c2 = new TtsAudioCache( seamOpts( clock, idb, { maxAge: 100000, debug: true } ) );
  await c2.initialize();
  const got = await c2.checkCache( "charlie" );               // memory miss → idb hit (debug log)
  assert.equal( got, row.audioBlob );
  assert.equal( c2.getStats().hits, 1 );
  assert.equal( c2.getStats().entries, 1 );                   // promoted
  const again = await c2.checkCache( "charlie" );             // now memory hit
  assert.equal( again, row.audioBlob );
});

test("checkCache — IndexedDB miss (no row) counts a miss", async () => {
  const idb = makeFakeIdb({ rows: [] });
  const c = new TtsAudioCache( seamOpts( { t: 0 }, idb, { debug: true } ) );
  await c.initialize();
  assert.equal( await c.checkCache( "delta" ), null );        // memory miss → idb miss (debug log)
  assert.equal( c.getStats().misses, 1 );
});

test("checkCache — IndexedDB get error resolves null, counts a miss", async () => {
  const idb = makeFakeIdb({ getError: true });
  const c = new TtsAudioCache( seamOpts( { t: 0 }, idb ) );
  await c.initialize();
  assert.equal( await c.checkCache( "golf-err" ), null );      // get onerror → null → miss
  assert.equal( c.getStats().misses, 1 );
});

test("checkCache — IndexedDB hit but expired counts a miss", async () => {
  const clock = { t: 1000 };
  const probe = new TtsAudioCache( seamOpts( clock ) );
  const key = await probe.generateCacheKey( "echo" );
  const row : CacheEntry = { key, text: "echo", audioBlob: blob(), timestamp: 0, size: 10 };
  const idb = makeFakeIdb({ rows: [ row ] });
  const c = new TtsAudioCache( seamOpts( clock, idb, { maxAge: 100 } ) );
  await c.initialize();
  assert.equal( await c.checkCache( "echo" ), null );          // row expired
  assert.equal( c.getStats().misses, 1 );
});

test("checkCache — digest failure is swallowed, returns null", async () => {
  const c = new TtsAudioCache({
    subtleDigest: () => Promise.reject( new Error( "digest boom" ) ),
    now: () => 0, setIntervalFn: () => {},
  });
  assert.equal( await c.checkCache( "foxtrot" ), null );        // catch → null
});

// --- saveToCache ------------------------------------------------------------

test("saveToCache — falsy blob is a no-op", async () => {
  const c = new TtsAudioCache( seamOpts( { t: 0 } ) );
  await c.saveToCache( "golf", null );
  assert.equal( c.getStats().stores, 0 );
});

test("saveToCache — memory-only path records store + size", async () => {
  const c = new TtsAudioCache( seamOpts( { t: 1000 }, undefined, { debug: true } ) );
  await c.saveToCache( "hotel", blob( 10 ) );
  const s = c.getStats();
  assert.equal( s.stores, 1 );
  assert.equal( s.entries, 1 );
});

test("saveToCache — persists to IndexedDB when open", async () => {
  const idb = makeFakeIdb();
  const c = new TtsAudioCache( seamOpts( { t: 1000 }, idb ) );
  await c.initialize();
  await c.saveToCache( "india", blob() );
  assert.equal( idb.puts.length, 1 );
  assert.equal( idb.puts[ 0 ].text, "india" );
});

test("saveToCache — IndexedDB put error is swallowed", async () => {
  const idb = makeFakeIdb({ putError: true });
  const c = new TtsAudioCache( seamOpts( { t: 1000 }, idb ) );
  await c.initialize();
  await c.saveToCache( "juliet", blob() );    // saveToIndexedDB rejects → catch
  assert.equal( idb.puts.length, 0 );
  // store counter NOT incremented because the await threw before stats bump:
  assert.equal( c.getStats().stores, 0 );
});

test("saveToCache — exceeding maxSize triggers a cleanup sweep", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { maxSize: 1 } ) );
  await c.saveToCache( "kilo", blob( 100 ) ); // totalSize 100 > maxSize 1 → cleanupIfNeeded → cleanup
  // entry is fresh → not evicted; totalSize unchanged by the (db-less) sweep.
  assert.equal( c.getStats().stores, 1 );
  assert.equal( c.getStats().entries, 1 );
});

// --- isExpired --------------------------------------------------------------

test("isExpired — false within maxAge, true past it", () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { maxAge: 100 } ) );
  const entry: CacheEntry = { key: "k", text: "", audioBlob: blob(), timestamp: 950, size: 1 };
  assert.equal( c.isExpired( entry ), false );   // 1000-950=50 <= 100
  clock.t = 1100;
  assert.equal( c.isExpired( entry ), true );    // 1100-950=150 > 100
});

// --- cleanup ----------------------------------------------------------------

test("cleanup — evicts expired memory entries and reduces totalSize", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { maxAge: 100, debug: true } ) );
  await c.saveToCache( "lima", blob( 10 ) );
  clock.t = 5000;                              // expire it
  await c.cleanup();                           // memory loop deletes it (removedSize>0 → debug log)
  assert.equal( c.getStats().entries, 0 );
});

test("cleanup — fresh entries survive (removedSize 0, debug log skipped)", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { maxAge: 100000, debug: true } ) );
  await c.saveToCache( "mike", blob( 10 ) );
  await c.cleanup();                           // nothing expired → removedSize 0
  assert.equal( c.getStats().entries, 1 );
});

test("cleanup — IndexedDB cursor sweep deletes expired rows (incl. size 0)", async () => {
  const clock = { t: 10000 };
  const expired1 : CacheEntry = { key: "e1", text: "", audioBlob: blob(), timestamp: 0, size: 50 };
  const fresh    : CacheEntry = { key: "f1", text: "", audioBlob: blob(), timestamp: 9999, size: 30 };
  const expired0 : CacheEntry = { key: "e0", text: "", audioBlob: blob(), timestamp: 0, size: 0 };
  const idb = makeFakeIdb({ rows: [ expired1, fresh, expired0 ] });
  const c = new TtsAudioCache( seamOpts( clock, idb, { maxAge: 100 } ) );
  await c.initialize();
  await c.cleanup();
  await flush();                               // let the async cursor sweep complete
  assert.deepEqual( idb.deleted.sort(), [ "e0", "e1" ] );   // both expired removed; size||0 hit
});

// --- scheduleCleanup --------------------------------------------------------

test("scheduleCleanup — armed interval callback runs cleanup", async () => {
  const clock = { t: 1000 };
  let captured: ( () => void ) | null = null;
  const idb = makeFakeIdb();
  const c = new TtsAudioCache( seamOpts( clock, idb, {
    maxAge: 100,
    setIntervalFn: ( cb: () => void ) => { captured = cb; },
  } ) );
  await c.initialize();
  await c.saveToCache( "november", blob( 10 ) );
  clock.t = 10_000_000;                        // expire everything (>> maxAge 100)
  assert.notEqual( captured, null );
  ( captured as unknown as () => void )();     // fire the armed sweep
  await flush();
  assert.equal( c.getStats().entries, 0 );     // cleanup ran via the interval cb
});

// --- getStats ---------------------------------------------------------------

test("getStats — computes a non-zero hit rate", async () => {
  const clock = { t: 1000 };
  const c = new TtsAudioCache( seamOpts( clock, undefined, { maxAge: 100000 } ) );
  await c.saveToCache( "oscar", blob() );
  await c.checkCache( "oscar" );               // hit
  await c.checkCache( "papa" );                // miss
  const s = c.getStats();
  assert.equal( s.hits, 1 );
  assert.equal( s.misses, 1 );
  assert.equal( s.hitRate, "50.0%" );          // total>0 branch
});

// --- clearCache -------------------------------------------------------------

test("clearCache — clears both tiers and resets stats (db open)", async () => {
  const idb = makeFakeIdb();
  const c = new TtsAudioCache( seamOpts( { t: 1000 }, idb, { debug: true } ) );
  await c.initialize();
  await c.saveToCache( "quebec", blob() );
  c.clearCache();
  assert.equal( idb.state.cleared, true );
  const s = c.getStats();
  assert.equal( s.entries, 0 );
  assert.equal( s.stores, 0 );
  assert.equal( s.totalSize, "0.00 MB" );
});

test("clearCache — memory-only (db null) resets without touching IndexedDB", async () => {
  const c = new TtsAudioCache( seamOpts( { t: 1000 } ) );
  await c.saveToCache( "romeo", blob() );
  c.clearCache();
  assert.equal( c.getStats().entries, 0 );
  assert.equal( c.getStats().stores, 0 );
});
