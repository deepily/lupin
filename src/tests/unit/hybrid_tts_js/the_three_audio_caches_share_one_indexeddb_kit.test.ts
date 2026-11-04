// HybridTTS, JobCompletionCache and TTSAudioCache share one IndexedDB kit (row 6b74a018)
//
// The three files are plain browser JS in no tsconfig, so they have no c8 number. Each ends with a
// CommonJS export that createRequire reads, so the files' own bytes are under test.
// idb-cache-kit.js sets globalThis.LupinIdbKit, which is how the browser pages reach it too.
//
// Part 1 pins what the three classes did before the merge, through their public methods. Part 2
// pins the kit itself.
//
// Run via:
//   npx tsx --test src/tests/unit/hybrid_tts_js/the_three_audio_caches_share_one_indexeddb_kit.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE   = dirname( fileURLToPath( import.meta.url ) );
const JS_DIR = resolve( HERE, "../../../lupin_app/static/js" );
const req    = createRequire( import.meta.url );

const KIT_JS = resolve( JS_DIR, "idb-cache-kit.js" );

// SHA-256 of "hello", pinned as a literal so the tests do not derive it the way the code does.
const HELLO_SHA = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824";

// ---------------------------------------------------------------- fake IndexedDB

interface Fake {
    opened      : Array<[ string, number ]>;
    stores      : Record<string, { options: unknown; indexes: Array<[ string, string, unknown ]> }>;
    reads       : Array<[ string, string, unknown ]>;
    existing    : Set<string>;
    rows        : Map<unknown, unknown>;
    failOpen    : boolean;
    failRead    : boolean;
    db          : any;
}

function installFakeIndexedDB(): Fake {
    const fake: Fake = { opened: [], stores: {}, reads: [], existing: new Set(), rows: new Map(), failOpen: false, failRead: false, db: null };
    const db = {
        objectStoreNames : { contains: ( name: string ) => fake.existing.has( name ) },
        createObjectStore: ( name: string, options: unknown ) => {
            fake.stores[ name ] = { options, indexes: [] };
            return { createIndex: ( n: string, k: string, o: unknown ) => { fake.stores[ name ].indexes.push( [ n, k, o ] ); } };
        },
        transaction: ( names: string[], mode: string ) => ( {
            objectStore: ( name: string ) => ( {
                get: ( key: unknown ) => {
                    fake.reads.push( [ name, mode, key ] );
                    const request: any = { result: fake.rows.get( key ), error: new Error( "read-failed" ) };
                    queueMicrotask( () => fake.failRead ? request.onerror() : request.onsuccess() );
                    return request;
                }
            } )
        } )
    };
    fake.db = db;
    ( globalThis as any ).indexedDB = {
        open: ( name: string, version: number ) => {
            fake.opened.push( [ name, version ] );
            const request: any = { result: db, error: new Error( "open-failed" ) };
            queueMicrotask( () => {
                if ( fake.failOpen ) { request.onerror(); return; }
                request.onupgradeneeded( { target: request } );
                request.onsuccess();
            } );
            return request;
        }
    };
    return fake;
}

const fakeDb = ( fake: Fake ) => fake.db;

// ---------------------------------------------------------------- part 1: the classes as they behaved

function loadAll() {
    // The kit is loaded first, as the browser pages do; before the merge it does not exist, so the
    // pins of part 1 must not depend on it.
    try { req( KIT_JS ); } catch ( e ) { /* pre-merge tree */ }
    return {
        HybridTTS        : req( resolve( JS_DIR, "hybrid-tts.js" ) ),
        JobCompletionCache: req( resolve( JS_DIR, "job-completion-cache.js" ) ),
        TTSAudioCache    : req( resolve( JS_DIR, "tts-audio-cache.js" ) ),
    };
}

test( "HybridTTS.checkCache finds an entry in memory under the SHA-256 of the text", async () => {
    const { HybridTTS } = loadAll();
    const tts = Object.create( HybridTTS.prototype );
    tts.cacheEnabled = true;
    tts.cacheMaxAge  = 1e12;
    tts.audioCache   = new Map( [ [ HELLO_SHA, { timestamp: Date.now(), audioUrl: "u" } ] ] );

    assert.equal( ( await tts.checkCache( "hello" ) ).audioUrl, "u" );
} );

test( "HybridTTS.checkCache reads IndexedDB store audioCache by the hashed key", async () => {
    const { HybridTTS } = loadAll();
    const fake = installFakeIndexedDB();
    fake.rows.set( HELLO_SHA, { timestamp: Date.now(), audioBlob: new Blob( [ "x" ] ) } );
    const tts = Object.create( HybridTTS.prototype );
    tts.cacheEnabled = true;
    tts.cacheMaxAge  = 1e12;
    tts.audioCache   = new Map();
    tts.db           = fakeDb( fake );

    const found = await tts.checkCache( "hello" );
    assert.ok( found.audioUrl.startsWith( "blob:" ) );
    assert.deepEqual( fake.reads, [ [ "audioCache", "readonly", HELLO_SHA ] ] );
} );

test( "HybridTTS.checkCache rejects when the IndexedDB read fails", async () => {
    const { HybridTTS } = loadAll();
    const fake = installFakeIndexedDB();
    fake.failRead = true;
    const tts = Object.create( HybridTTS.prototype );
    tts.cacheEnabled = true;
    tts.audioCache   = new Map();
    tts.db           = fakeDb( fake );

    await assert.rejects( tts.checkCache( "hello" ), /read-failed/ );
} );

test( "HybridTTS constructor opens IndexedDB AudioCache store with a timestamp index", async () => {
    const { HybridTTS } = loadAll();
    const fake = installFakeIndexedDB();
    ( globalThis as any ).window       = { location: { host: "h" } };
    ( globalThis as any ).localStorage = { getItem: () => null };
    const tts = new HybridTTS( { audioElement: {} } );
    await new Promise( ( r ) => setTimeout( r, 5 ) );

    assert.equal( fake.opened.length, 1 );
    assert.deepEqual( fake.stores[ "audioCache" ].options, { keyPath: "key" } );
    assert.deepEqual( fake.stores[ "audioCache" ].indexes, [ [ "timestamp", "timestamp", { unique: false } ] ] );
    assert.ok( tts.db );
} );

test( "HybridTTS constructor warns and keeps going when IndexedDB will not open", async () => {
    const { HybridTTS } = loadAll();
    const fake = installFakeIndexedDB();
    fake.failOpen = true;
    ( globalThis as any ).window       = { location: { host: "h" } };
    ( globalThis as any ).localStorage = { getItem: () => null };
    const warned: string[] = [];
    const warn = console.warn;
    console.warn = ( ...a: unknown[] ) => { warned.push( String( a[ 0 ] ) ); };
    try {
        const tts = new HybridTTS( { audioElement: {} } );
        await new Promise( ( r ) => setTimeout( r, 5 ) );
        assert.equal( tts.db, null );
    } finally { console.warn = warn; }
    assert.match( warned.join( "|" ), /HybridTTS: IndexedDB initialization failed/ );
} );

test( "JobCompletionCache.get reads IndexedDB store jobMessages by job id", async () => {
    const { JobCompletionCache } = loadAll();
    const fake = installFakeIndexedDB();
    fake.rows.set( "job-1", { timestamp: Date.now(), replayCount: 0, size: 3 } );
    const cache = Object.create( JobCompletionCache.prototype );
    cache.cacheEnabled = true;
    cache.cacheMaxAge  = 1e12;
    cache.messageCache = new Map();
    cache.analytics    = { cacheHits: 0, cacheMisses: 0, topJobs: new Map() };
    cache.db           = fakeDb( fake );

    const found = await cache.get( "job-1" );
    assert.equal( found.replayCount, 1 );
    assert.deepEqual( fake.reads, [ [ "jobMessages", "readonly", "job-1" ] ] );
} );

test( "JobCompletionCache.get rejects when the IndexedDB read fails", async () => {
    const { JobCompletionCache } = loadAll();
    const fake = installFakeIndexedDB();
    fake.failRead = true;
    const cache = Object.create( JobCompletionCache.prototype );
    cache.cacheEnabled = true;
    cache.messageCache = new Map();
    cache.analytics    = { cacheHits: 0, cacheMisses: 0, topJobs: new Map() };
    cache.db           = fakeDb( fake );

    await assert.rejects( cache.get( "job-1" ), /read-failed/ );
} );

test( "JobCompletionCache.getByText finds an in-memory entry by the SHA-256 of the text", async () => {
    const { JobCompletionCache } = loadAll();
    const cache = Object.create( JobCompletionCache.prototype );
    cache.cacheEnabled = true;
    cache.cacheMaxAge  = 1e12;
    cache.messageCache = new Map( [ [ "job-9", { textHash: HELLO_SHA, timestamp: Date.now() } ] ] );
    cache.analytics    = { cacheHits: 0, cacheMisses: 0, topJobs: new Map(), totalRetrieves: 0 };

    assert.equal( ( await cache.getByText( "hello" ) ).textHash, HELLO_SHA );
} );

test( "JobCompletionCache.initializeIndexedDB creates jobMessages with its three indexes", async () => {
    const { JobCompletionCache } = loadAll();
    const fake = installFakeIndexedDB();
    const cache = Object.create( JobCompletionCache.prototype );
    cache.dbName    = "JobCompletionCache";
    cache.dbVersion = 1;
    const logged: string[] = [];
    const log = console.log;
    console.log = ( ...a: unknown[] ) => { logged.push( String( a[ 0 ] ) ); };
    try { await cache.initializeIndexedDB(); } finally { console.log = log; }

    assert.deepEqual( fake.opened, [ [ "JobCompletionCache", 1 ] ] );
    assert.deepEqual( fake.stores[ "jobMessages" ].options, { keyPath: "jobId" } );
    assert.deepEqual( fake.stores[ "jobMessages" ].indexes.map( ( i ) => i[ 0 ] ), [ "timestamp", "textHash", "userId" ] );
    assert.ok( cache.db );
    assert.deepEqual( logged, [ "JobCompletionCache: IndexedDB initialized" ] );
} );

test( "JobCompletionCache.initializeIndexedDB rejects when IndexedDB will not open", async () => {
    const { JobCompletionCache } = loadAll();
    installFakeIndexedDB().failOpen = true;
    const cache = Object.create( JobCompletionCache.prototype );
    cache.dbName    = "JobCompletionCache";
    cache.dbVersion = 1;

    await assert.rejects( cache.initializeIndexedDB(), /open-failed/ );
} );

test( "TTSAudioCache.generateCacheKey hashes the trimmed, lower-cased text", async () => {
    const { TTSAudioCache } = loadAll();
    const cache = Object.create( TTSAudioCache.prototype );

    assert.equal( await cache.generateCacheKey( "  HELLO " ), HELLO_SHA );
} );

test( "TTSAudioCache.initializeIndexedDB creates audioCache with a timestamp index", async () => {
    const { TTSAudioCache } = loadAll();
    const fake = installFakeIndexedDB();
    const cache = Object.create( TTSAudioCache.prototype );
    cache.dbName    = "TTSAudioCache";
    cache.dbVersion = 1;
    await cache.initializeIndexedDB();

    assert.deepEqual( fake.opened, [ [ "TTSAudioCache", 1 ] ] );
    assert.deepEqual( fake.stores[ "audioCache" ].options, { keyPath: "key" } );
    assert.deepEqual( fake.stores[ "audioCache" ].indexes, [ [ "timestamp", "timestamp", { unique: false } ] ] );
    assert.ok( cache.db );
} );

test( "TTSAudioCache.initializeIndexedDB rejects when IndexedDB will not open", async () => {
    const { TTSAudioCache } = loadAll();
    installFakeIndexedDB().failOpen = true;
    const cache = Object.create( TTSAudioCache.prototype );
    cache.dbName    = "TTSAudioCache";
    cache.dbVersion = 1;

    await assert.rejects( cache.initializeIndexedDB(), /open-failed/ );
} );

// ---------------------------------------------------------------- part 2: the kit

test( "the kit exports sha256Hex, openStore and getOne, and publishes itself as a global", () => {
    const kit = req( KIT_JS );
    assert.deepEqual( Object.keys( kit ).sort(), [ "getOne", "openStore", "sha256Hex" ] );
    assert.equal( ( globalThis as any ).LupinIdbKit, kit );
} );

test( "sha256Hex returns the 64-character hex digest, with leading zeros kept", async () => {
    const kit = req( KIT_JS );
    assert.equal( await kit.sha256Hex( "hello" ), HELLO_SHA );
    assert.equal( await kit.sha256Hex( "" ), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" );
} );

test( "openStore creates the store and one index per name on first open, and resolves the db", async () => {
    const kit  = req( KIT_JS );
    const fake = installFakeIndexedDB();
    const db   = await kit.openStore( "N", 3, "S", "id", [ "a", "b" ] );

    assert.deepEqual( fake.opened, [ [ "N", 3 ] ] );
    assert.deepEqual( fake.stores[ "S" ], { options: { keyPath: "id" }, indexes: [ [ "a", "a", { unique: false } ], [ "b", "b", { unique: false } ] ] } );
    assert.equal( db, fakeDb( fake ) );
} );

test( "openStore leaves an existing store alone", async () => {
    const kit  = req( KIT_JS );
    const fake = installFakeIndexedDB();
    fake.existing.add( "S" );
    await kit.openStore( "N", 3, "S", "id", [ "a" ] );

    assert.deepEqual( fake.stores, {} );
} );

test( "openStore rejects with the request error", async () => {
    const kit = req( KIT_JS );
    installFakeIndexedDB().failOpen = true;

    await assert.rejects( kit.openStore( "N", 3, "S", "id", [] ), /open-failed/ );
} );

test( "getOne reads one row from the named store, read-only", async () => {
    const kit  = req( KIT_JS );
    const fake = installFakeIndexedDB();
    fake.rows.set( "k", "row" );

    assert.equal( await kit.getOne( fakeDb( fake ), "S", "k" ), "row" );
    assert.deepEqual( fake.reads, [ [ "S", "readonly", "k" ] ] );
} );

test( "getOne rejects with the request error", async () => {
    const kit  = req( KIT_JS );
    const fake = installFakeIndexedDB();
    fake.failRead = true;

    await assert.rejects( kit.getOne( fakeDb( fake ), "S", "k" ), /read-failed/ );
} );
