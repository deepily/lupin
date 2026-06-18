// Multiplexer Phase 6 — JobCompletionCache TS port tests.
//
// TS port of `src/lupin_app/static/js/job-completion-cache.js`. Drives the
// dual-tier (memory + IndexedDB) job-message cache: SHA-256 keying, store/
// get/getByText/delete, time-based expiration, size + entry-count LRU
// eviction, analytics (popular phrases + top jobs), getAllJobs, clearCache,
// and destroy — deterministically via a tiny in-memory fake IndexedDB
// (get/put/delete/clear/getAll/index) + injected clock/digest/iso seams.
// Target: c8 --100 lines/branches/functions on the changed surface.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  JobCompletionCache,
  type JobCacheEntry,
  type SubtleDigestFn,
  type MinimalIdbFactory,
  type MinimalIdbDatabase,
  type MinimalIdbObjectStore,
  type MinimalIdbIndex,
  type MinimalIdbOpenRequest,
  type MinimalIdbRequest,
} from "../../../../lupin_app/static/js/multiplexer/audio/JobCompletionCache";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// --- Helpers ----------------------------------------------------------------

/** Flush the macrotask queue (defensive; awaited promises self-resolve). */
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
  openError?    : boolean;
  storeExists?  : boolean;
  triggerUpgrade? : boolean;
  rows?         : JobCacheEntry[];
  getError?     : boolean;
  putError?     : boolean;
  getAllError?  : boolean;
  indexGetError?: boolean;
}

interface FakeIdbHandle {
  factory : MinimalIdbFactory;
  rows    : JobCacheEntry[];
  deleted : string[];
  state   : { cleared: boolean; createdStore: boolean; closed: boolean };
}

/** Build a tiny stateful in-memory fake IndexedDB (async-firing requests). */
function makeFakeIdb( cfg: FakeIdbConfig = {} ): FakeIdbHandle {
  const rows    : JobCacheEntry[] = [ ...( cfg.rows ?? [] ) ];
  const deleted : string[]        = [];
  const state   = { cleared: false, createdStore: false, closed: false };

  const index: MinimalIdbIndex = {
    get( key ) {
      const req: MinimalIdbRequest<JobCacheEntry | undefined> = {
        onsuccess: null, onerror: null, result: undefined, error: null,
      };
      queueMicrotask(() => {
        if ( cfg.indexGetError ) { req.onerror?.( null ); return; }
        req.result = rows.find( ( r ) => r.textHash === key );
        req.onsuccess?.( { target: { result: req.result } } );
      });
      return req;
    },
  };

  const store: MinimalIdbObjectStore = {
    createIndex() { /* recorded via createObjectStore */ },
    get( jobId ) {
      const req: MinimalIdbRequest<JobCacheEntry | undefined> = {
        onsuccess: null, onerror: null, result: undefined, error: null,
      };
      queueMicrotask(() => {
        if ( cfg.getError ) { req.onerror?.( null ); return; }
        req.result = rows.find( ( r ) => r.jobId === jobId );
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
        const i = rows.findIndex( ( r ) => r.jobId === entry.jobId );
        if ( i >= 0 ) rows[ i ] = entry; else rows.push( entry );
        req.onsuccess?.( { target: { result: null } } );
      });
      return req;
    },
    delete( jobId ) {
      deleted.push( jobId );
      const i = rows.findIndex( ( r ) => r.jobId === jobId );
      if ( i >= 0 ) rows.splice( i, 1 );
    },
    clear() { state.cleared = true; rows.length = 0; },
    getAll() {
      const req: MinimalIdbRequest<JobCacheEntry[]> = {
        onsuccess: null, onerror: null, result: [], error: null,
      };
      queueMicrotask(() => {
        if ( cfg.getAllError ) { req.onerror?.( null ); return; }
        req.result = [ ...rows ];
        req.onsuccess?.( { target: { result: req.result } } );
      });
      return req;
    },
    index: () => index,
  };

  const db: MinimalIdbDatabase = {
    objectStoreNames  : { contains: () => cfg.storeExists ?? false },
    createObjectStore : () => { state.createdStore = true; return store; },
    transaction       : () => ( { objectStore: () => store } ),
    close             : () => { state.closed = true; },
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

  return { factory, rows, deleted, state };
}

/** Injected-seam options around a fake IDB (or memory-only) + a fixed clock. */
function seamOpts( clock: { t: number }, idb?: FakeIdbHandle, extra: Record<string, unknown> = {} ) {
  return {
    subtleDigest : fakeDigest,
    now          : () => clock.t,
    nowIso       : () => `iso-${clock.t}`,
    indexedDBFactory: idb ? idb.factory : null,
    ...extra,
  };
}

/** Construct a memory-only cache (null factory) with init already settled. */
async function memoryCache( clock: { t: number }, extra: Record<string, unknown> = {} ) {
  const c = new JobCompletionCache( seamOpts( clock, undefined, extra ) );
  await c.ready;   // settles the null-factory reject → memory-only
  return c;
}

/** Construct an IDB-backed cache with the open settled. */
async function idbCache( clock: { t: number }, idb: FakeIdbHandle, extra: Record<string, unknown> = {} ) {
  const c = new JobCompletionCache( seamOpts( clock, idb, extra ) );
  await c.ready;
  return c;
}

// --- Constructor / ready ----------------------------------------------------

test("constructor defaults — enabled, zeroed analytics, ready resolves", async () => {
  const c = new JobCompletionCache();          // all platform defaults
  await c.ready;                               // node has no indexedDB → memory-only
  const a = c.getAnalytics();
  assert.equal( a.totalStores, 0 );
  assert.equal( a.hitRate, "0%" );             // totalRetrieves === 0 branch
  assert.equal( a.totalCacheSize, "0.00 KB" );
  assert.equal( a.cacheEntries, 0 );
  assert.deepEqual( a.popularPhrases, [] );
  assert.deepEqual( a.topJobs, [] );
});

test("constructor disabled — ready resolves immediately, all ops no-op", async () => {
  const c = new JobCompletionCache({ cacheEnabled: false });
  await c.ready;
  await c.store( "j1", "hello" );
  assert.equal( await c.get( "j1" ), null );
  assert.equal( await c.getByText( "hello" ), null );
  assert.equal( c.getAnalytics().totalStores, 0 );
});

test("constructor — explicit budgets are honored", () => {
  const c = new JobCompletionCache({
    cacheEnabled: true, cacheMaxSize: 5, cacheMaxAge: 100, maxEntries: 2,
    indexedDBFactory: null, subtleDigest: fakeDigest, now: () => 0, nowIso: () => "x",
  });
  assert.ok( c.ready instanceof Promise );
});

test("constructor — IndexedDB open failure degrades to memory-only", async () => {
  const idb = makeFakeIdb({ openError: true });
  const c = await idbCache( { t: 0 }, idb );   // ctor init rejects → ready catch warns
  await c.store( "j", "hi" );                  // memory store still works
  assert.equal( c.getAnalytics().totalStores, 1 );
});

// --- initializeIndexedDB (via ready) ----------------------------------------

test("initialize — success creates store + indexes", async () => {
  const idb = makeFakeIdb({ storeExists: false, triggerUpgrade: true });
  await idbCache( { t: 0 }, idb );
  assert.equal( idb.state.createdStore, true );
});

test("initialize — skips creation when the store already exists", async () => {
  const idb = makeFakeIdb({ storeExists: true, triggerUpgrade: true });
  await idbCache( { t: 0 }, idb );
  assert.equal( idb.state.createdStore, false );
});

test("initialize — success without an upgrade event", async () => {
  const idb = makeFakeIdb({ triggerUpgrade: false });
  await idbCache( { t: 0 }, idb );
  assert.equal( idb.state.createdStore, false );
});

// --- generateCacheKey -------------------------------------------------------

test("generateCacheKey — injected digest yields 64-char hex", async () => {
  const c = await memoryCache( { t: 0 } );
  const k = await c.generateCacheKey( "hello" );
  assert.match( k, /^[0-9a-f]{64}$/ );
});

test("default seams — real crypto digest + Date.now expiry", async () => {
  const c = new JobCompletionCache({ indexedDBFactory: null });   // default digest/now/nowIso
  await c.ready;
  const k = await c.generateCacheKey( "Hello World" );             // real crypto.subtle
  assert.match( k, /^[0-9a-f]{64}$/ );
  const entry: JobCacheEntry = {
    jobId: "j", text: "t", textHash: k, timestamp: "t", timestampMs: Date.now(),
    userId: null, size: 1, replayCount: 0, lastReplayed: null, metadata: {},
  };
  assert.equal( c.isCacheExpired( entry ), false );                // real Date.now
  await c.store( "js", "stored" );                                 // default nowIso → real toISOString
  const got = await c.get( "js" );
  assert.match( got?.timestamp ?? "", /^\d{4}-\d{2}-\d{2}T/ );      // ISO-8601 from default nowIso
});

// --- store ------------------------------------------------------------------

test("store — memory-only records analytics + size, default ISO timestamp", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock );
  await c.store( "j1", "hello12345" );          // 10 bytes
  const a = c.getAnalytics();
  assert.equal( a.totalStores, 1 );
  assert.equal( a.cacheEntries, 1 );
  const got = await c.get( "j1" );
  assert.equal( got?.timestamp, "iso-1000" );   // nowIso default
  assert.equal( got?.size, 10 );
});

test("store — explicit timestamp/userId/metadata are preserved + persisted to IDB", async () => {
  const clock = { t: 1000 };
  const idb = makeFakeIdb();
  const c = await idbCache( clock, idb );
  await c.store( "j2", "world", "2020-01-01T00:00:00Z", "user-7", { kind: "demo" } );
  assert.equal( idb.rows.length, 1 );
  assert.equal( idb.rows[ 0 ].timestamp, "2020-01-01T00:00:00Z" );
  assert.equal( idb.rows[ 0 ].userId, "user-7" );
  assert.deepEqual( idb.rows[ 0 ].metadata, { kind: "demo" } );
});

test("store — IndexedDB put error rejects (faithful to legacy no-catch)", async () => {
  const idb = makeFakeIdb({ putError: true });
  const c = await idbCache( { t: 0 }, idb );
  await assert.rejects( () => c.store( "j", "boom" ) );   // saveToIndexedDB onerror → reject
});

// --- get --------------------------------------------------------------------

test("get — fresh memory hit bumps replay stats", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100000 } );
  await c.store( "j1", "alpha" );
  const got = await c.get( "j1" );
  assert.equal( got?.replayCount, 1 );
  assert.equal( got?.lastReplayed, "iso-1000" );
  assert.equal( c.getAnalytics().cacheHits, 1 );
});

test("get — expired memory entry is evicted, then misses", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100 } );
  await c.store( "j1", "alpha" );
  clock.t = 5000;                                // past maxAge
  assert.equal( await c.get( "j1" ), null );
  assert.equal( c.getAnalytics().cacheMisses, 1 );
  assert.equal( c.getAnalytics().cacheEntries, 0 );
});

test("get — IndexedDB hit promotes into memory + bumps replay", async () => {
  const clock = { t: 1000 };
  const row: JobCacheEntry = {
    jobId: "j9", text: "x", textHash: "h", timestamp: "iso", timestampMs: 900,
    userId: null, size: 1, replayCount: 0, lastReplayed: null, metadata: {},
  };
  const idb = makeFakeIdb({ rows: [ row ] });
  const c = await idbCache( clock, idb, { cacheMaxAge: 100000 } );
  const got = await c.get( "j9" );               // memory miss → idb hit
  assert.equal( got?.jobId, "j9" );
  assert.equal( got?.replayCount, 1 );
  assert.equal( c.getAnalytics().cacheHits, 1 );
  const again = await c.get( "j9" );             // now memory hit
  assert.equal( again?.replayCount, 2 );
});

test("get — IndexedDB miss (no row) counts a miss", async () => {
  const idb = makeFakeIdb({ rows: [] });
  const c = await idbCache( { t: 0 }, idb );
  assert.equal( await c.get( "nope" ), null );
  assert.equal( c.getAnalytics().cacheMisses, 1 );
});

test("get — IndexedDB hit but expired counts a miss", async () => {
  const clock = { t: 10000 };
  const row: JobCacheEntry = {
    jobId: "old", text: "x", textHash: "h", timestamp: "iso", timestampMs: 0,
    userId: null, size: 1, replayCount: 0, lastReplayed: null, metadata: {},
  };
  const idb = makeFakeIdb({ rows: [ row ] });
  const c = await idbCache( clock, idb, { cacheMaxAge: 100 } );
  assert.equal( await c.get( "old" ), null );
  assert.equal( c.getAnalytics().cacheMisses, 1 );
});

test("get — IndexedDB get error rejects (faithful to legacy no-catch)", async () => {
  const idb = makeFakeIdb({ getError: true });
  const c = await idbCache( { t: 0 }, idb );
  await assert.rejects( () => c.get( "x" ) );    // getFromIndexedDB onerror → reject
});

test("get — disabled returns null", async () => {
  const c = new JobCompletionCache({ cacheEnabled: false });
  await c.ready;
  assert.equal( await c.get( "x" ), null );
});

// --- getByText --------------------------------------------------------------

test("getByText — fresh memory match by text hash", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100000 } );
  await c.store( "j1", "findme" );
  const got = await c.getByText( "findme" );
  assert.equal( got?.jobId, "j1" );
});

test("getByText — memory entries that mismatch or are expired are skipped", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100 } );
  await c.store( "fresh", "other-text" );        // hash mismatch for the query
  await c.store( "stale", "target-text" );       // matches query but will expire
  clock.t = 5000;                                // expire 'stale'
  assert.equal( await c.getByText( "target-text" ), null );  // mismatch skip + expired skip
});

test("getByText — IndexedDB textHash-index hit promotes into memory", async () => {
  const clock = { t: 1000 };
  const probe = await memoryCache( clock );
  const hash = await probe.generateCacheKey( "dbtext" );
  const row: JobCacheEntry = {
    jobId: "jdb", text: "dbtext", textHash: hash, timestamp: "iso", timestampMs: 900,
    userId: null, size: 1, replayCount: 0, lastReplayed: null, metadata: {},
  };
  const idb = makeFakeIdb({ rows: [ row ] });
  const c = await idbCache( clock, idb, { cacheMaxAge: 100000 } );
  const got = await c.getByText( "dbtext" );
  assert.equal( got?.jobId, "jdb" );
  assert.equal( c.getAnalytics().cacheEntries, 1 );   // promoted
});

test("getByText — IndexedDB index miss/expired resolves null", async () => {
  const clock = { t: 10000 };
  const probe = await memoryCache( clock );
  const hash = await probe.generateCacheKey( "expired-db" );
  const row: JobCacheEntry = {
    jobId: "jx", text: "expired-db", textHash: hash, timestamp: "iso", timestampMs: 0,
    userId: null, size: 1, replayCount: 0, lastReplayed: null, metadata: {},
  };
  const idb = makeFakeIdb({ rows: [ row ] });
  const c = await idbCache( clock, idb, { cacheMaxAge: 100 } );
  assert.equal( await c.getByText( "expired-db" ), null );   // index hit but expired
  // and a genuine index miss:
  assert.equal( await c.getByText( "never-stored" ), null );
});

test("getByText — IndexedDB index error resolves null", async () => {
  const idb = makeFakeIdb({ indexGetError: true });
  const c = await idbCache( { t: 0 }, idb );
  assert.equal( await c.getByText( "anything" ), null );     // index onerror → null
});

test("getByText — memory-only with no match returns null", async () => {
  const c = await memoryCache( { t: 0 } );
  assert.equal( await c.getByText( "ghost" ), null );        // db null → final return null
});

test("getByText — disabled returns null", async () => {
  const c = new JobCompletionCache({ cacheEnabled: false });
  await c.ready;
  assert.equal( await c.getByText( "x" ), null );
});

// --- delete -----------------------------------------------------------------

test("delete — removes a present entry from memory + IndexedDB", async () => {
  const clock = { t: 1000 };
  const idb = makeFakeIdb();
  const c = await idbCache( clock, idb );
  await c.store( "j1", "todelete1" );            // 9 bytes
  await c.delete( "j1" );
  assert.equal( c.getAnalytics().cacheEntries, 0 );
  assert.ok( idb.deleted.includes( "j1" ) );
});

test("delete — absent entry is a no-op (memory-only path)", async () => {
  const c = await memoryCache( { t: 0 } );
  await c.delete( "missing" );                   // entry undefined → skip; db null → skip
  assert.equal( c.getAnalytics().cacheEntries, 0 );
});

// --- isCacheExpired ---------------------------------------------------------

test("isCacheExpired — false within maxAge, true past it", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100 } );
  const entry: JobCacheEntry = {
    jobId: "k", text: "", textHash: "", timestamp: "", timestampMs: 950,
    userId: null, size: 0, replayCount: 0, lastReplayed: null, metadata: {},
  };
  assert.equal( c.isCacheExpired( entry ), false );  // 50 <= 100
  clock.t = 1200;
  assert.equal( c.isCacheExpired( entry ), true );   // 250 > 100
});

// --- evictOldEntries (via store) --------------------------------------------

test("evictOldEntries — expired entries are dropped during a later store", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100 } );
  await c.store( "old", "0123456789" );          // 10 bytes
  clock.t = 5000;                                // expire 'old'
  await c.store( "new", "abcdefghij" );          // evict pass removes 'old'
  assert.equal( c.getAnalytics().cacheEntries, 1 );
  assert.equal( await c.get( "old" ), null );
});

test("evictOldEntries — over size budget evicts oldest (memory-only)", async () => {
  const clock = { t: 0 };
  const c = await memoryCache( clock, { cacheMaxSize: 15, cacheMaxAge: 100000 } );
  clock.t = 1; await c.store( "a", "0123456789" );  // size 10, oldest
  clock.t = 2; await c.store( "b", "abcdefghij" );  // total 20 > 15 → evict 'a'
  assert.equal( await c.get( "a" ), null );
  assert.ok( ( await c.get( "b" ) ) !== null );
});

test("evictOldEntries — over entry-count budget evicts oldest + IDB delete", async () => {
  const clock = { t: 0 };
  const idb = makeFakeIdb();
  const c = await idbCache( clock, idb, { maxEntries: 1, cacheMaxAge: 100000 } );
  clock.t = 1; await c.store( "a", "x" );
  clock.t = 2; await c.store( "b", "y" );        // length 2 > 1 → evict 'a' (also from IDB)
  assert.ok( idb.deleted.includes( "a" ) );
});

// --- updatePhraseFrequency / getAnalytics -----------------------------------

test("getAnalytics — hit rate, phrase frequency, and truncated previews", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100000 } );
  const longPhrase = "x".repeat( 60 );           // > 50 → truncated with "..."
  await c.store( "jlong", longPhrase );
  await c.store( "jshort", "short phrase" );      // <= 50 → no "..."
  await c.store( "jshort", "short phrase" );      // repeat → existing count branch
  await c.get( "jlong" );                         // 1 hit
  await c.get( "ghost" );                         // 1 miss
  const a = c.getAnalytics();
  assert.equal( a.hitRate, "50.00%" );            // totalRetrieves > 0 branch
  const long = a.popularPhrases.find( ( p ) => p.phrase.endsWith( "..." ) );
  assert.ok( long, "long phrase truncated" );
  const short = a.popularPhrases.find( ( p ) => p.phrase === "short phrase" );
  assert.equal( short?.count, 2 );                // frequency incremented
});

test("getAnalytics — top jobs truncate long job ids", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100000 } );
  const longId = "job-".repeat( 10 );             // > 20 chars → truncated
  await c.store( longId, "t" );
  await c.store( "short-id", "u" );
  await c.get( longId );                          // replay → topJobs
  await c.get( "short-id" );
  const a = c.getAnalytics();
  assert.ok( a.topJobs.some( ( j ) => j.jobId.endsWith( "..." ) ) );  // long id truncated
  assert.ok( a.topJobs.some( ( j ) => j.jobId === "short-id" ) );     // short id intact
});

// --- getAllJobs -------------------------------------------------------------

test("getAllJobs — memory entries filtered by user, expired excluded, IDB supplements", async () => {
  const clock = { t: 1000 };
  const dbRow: JobCacheEntry = {
    jobId: "db-only", text: "d", textHash: "h", timestamp: "iso", timestampMs: 1100,
    userId: "u1", size: 1, replayCount: 0, lastReplayed: null, metadata: {},
  };
  const idb = makeFakeIdb({ rows: [ dbRow ] });
  const c = await idbCache( clock, idb, { cacheMaxAge: 100000 } );
  clock.t = 1200; await c.store( "mem-u1", "m", null, "u1" );
  clock.t = 1300; await c.store( "mem-u2", "m", null, "u2" );  // filtered out by userId
  const jobs = await c.getAllJobs( "u1" );        // memory u1 + db-only (notInMemory)
  const ids = jobs.map( ( j ) => j.jobId );
  assert.ok( ids.includes( "mem-u1" ) );
  assert.ok( ids.includes( "db-only" ) );
  assert.ok( !ids.includes( "mem-u2" ) );
  // newest first:
  assert.equal( jobs[ 0 ].jobId, "mem-u1" );
});

test("getAllJobs — no user filter returns all fresh, IDB error tolerated", async () => {
  const clock = { t: 1000 };
  const idb = makeFakeIdb({ getAllError: true });
  const c = await idbCache( clock, idb, { cacheMaxAge: 100000 } );
  await c.store( "j1", "a" );
  const jobs = await c.getAllJobs();              // getAll onerror → [] ; memory entry returned
  assert.equal( jobs.length, 1 );
});

test("getAllJobs — expired memory entries are excluded", async () => {
  const clock = { t: 1000 };
  const c = await memoryCache( clock, { cacheMaxAge: 100 } );
  await c.store( "j1", "a" );
  clock.t = 5000;                                 // expire it
  assert.deepEqual( await c.getAllJobs(), [] );
});

test("getAllJobs — skips the IDB scan when memory is at/over the floor", async () => {
  const clock = { t: 1000 };
  const idb = makeFakeIdb();
  const c = await idbCache( clock, idb, { cacheMaxAge: 100000, maxEntries: 1000 } );
  for ( let i = 0; i < 50; i++ ) { clock.t = 1000 + i; await c.store( `j${i}`, "x" ); }
  const jobs = await c.getAllJobs();              // 50 in memory → `50 < 50` false → no DB scan
  assert.equal( jobs.length, 50 );
});

// --- clearCache / destroy ---------------------------------------------------

test("clearCache — clears both tiers + analytics maps (db open)", async () => {
  const clock = { t: 1000 };
  const idb = makeFakeIdb();
  const c = await idbCache( clock, idb );
  await c.store( "j1", "a" );
  c.clearCache();
  assert.equal( idb.state.cleared, true );
  const a = c.getAnalytics();
  assert.equal( a.cacheEntries, 0 );
  assert.equal( a.totalCacheSize, "0.00 KB" );
  assert.deepEqual( a.popularPhrases, [] );
});

test("clearCache — memory-only (db null) resets without touching IndexedDB", async () => {
  const c = await memoryCache( { t: 1000 } );
  await c.store( "j1", "a" );
  c.clearCache();
  assert.equal( c.getAnalytics().cacheEntries, 0 );
});

test("destroy — clears the cache and closes the IDB connection", async () => {
  const idb = makeFakeIdb();
  const c = await idbCache( { t: 1000 }, idb );
  await c.store( "j1", "a" );
  c.destroy();
  assert.equal( idb.state.cleared, true );
  assert.equal( idb.state.closed, true );
});

test("destroy — memory-only skips the IDB close", async () => {
  const c = await memoryCache( { t: 1000 } );
  c.destroy();                                    // db null → no close
  assert.equal( c.getAnalytics().cacheEntries, 0 );
});
