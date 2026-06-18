/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6 (TTS-playback frontier) — TtsAudioCache.
//
// TypeScript port of `src/lupin_app/static/js/tts-audio-cache.js`
// (JS→TS multiplexer migration, umbrella 312ba8ab). A lightweight persistent
// audio cache extracted from HybridTTS for the Fresh Queue UI: a dual-tier
// store (in-memory Map + IndexedDB) keyed by a SHA-256 of the normalized
// text, with time-based expiration and a size-bounded cleanup sweep.
//
// Preserves the legacy contract: `initialize` / `generateCacheKey` /
// `checkCache` / `saveToCache` / `isExpired` / `cleanup` / `getStats` /
// `clearCache` plus the same default tuning (24h maxAge, 50MB maxSize). One
// intentional, documented deviation from the legacy class:
//
//   1. Constructor takes an options dict (matching the multiplexer's
//      `AudioRecorder` / `SequentialAudioManager` idiom) — same shape as the
//      legacy `options` arg, so no caller changes. The module is net-new to
//      the multiplexer tree (no existing TS consumers).
//
// Browser/runtime dependencies (the IndexedDB factory, `crypto.subtle.digest`,
// `Date.now`, and `setInterval`) are injectable through the options dict —
// they default to the platform globals but let the unit suite drive the
// dual-cache state machine, expiration, cursor-based cleanup, and the IDB
// error fallback deterministically without a real browser database.

/** A single cached-audio record (in-memory + IndexedDB row shape). */
export interface CacheEntry {
  key       : string;
  text      : string;
  audioBlob : Blob;
  timestamp : number;
  size      : number;
}

/** The at-a-glance human-readable cache statistics snapshot. */
export interface CacheStats {
  enabled   : boolean;
  hits      : number;
  misses    : number;
  stores    : number;
  hitRate   : string;
  totalSize : string;
  entries   : number;
}

// --- Minimal structural IndexedDB surface -----------------------------------
// Only the fields/methods this cache actually touches are modeled, so the unit
// suite can supply a tiny in-memory fake instead of a full IDB polyfill.

/** A request carrying an `event.target.result` payload of type `T`. */
export interface IdbEventTarget<T> { target?: { result?: T } | null; }

export interface MinimalIdbRequest<T = unknown> {
  onsuccess : (( ev: IdbEventTarget<T> ) => void) | null;
  onerror   : (( ev: unknown ) => void) | null;
  result    : T;
  error     : unknown;
}

export interface MinimalIdbObjectStore {
  createIndex( name: string, keyPath: string, options: { unique: boolean } ): void;
  get( key: string ): MinimalIdbRequest<CacheEntry | undefined>;
  put( entry: CacheEntry ): MinimalIdbRequest<unknown>;
  clear(): void;
  openCursor(): MinimalIdbRequest<MinimalIdbCursor | null>;
}

export interface MinimalIdbCursor {
  value : CacheEntry;
  delete(): void;
  continue(): void;
}

export interface MinimalIdbTransaction {
  objectStore( name: string ): MinimalIdbObjectStore;
}

export interface MinimalIdbDatabase {
  objectStoreNames : { contains( name: string ): boolean };
  createObjectStore( name: string, options: { keyPath: string } ): MinimalIdbObjectStore;
  transaction( storeNames: string[], mode: string ): MinimalIdbTransaction;
}

export interface MinimalIdbOpenRequest {
  onsuccess       : (( ev: unknown ) => void) | null;
  onerror         : (( ev: unknown ) => void) | null;
  onupgradeneeded : (( ev: IdbEventTarget<MinimalIdbDatabase> ) => void) | null;
  result          : MinimalIdbDatabase;
  error           : unknown;
}

export interface MinimalIdbFactory {
  open( name: string, version: number ): MinimalIdbOpenRequest;
}

export type SubtleDigestFn = ( algorithm: string, data: BufferSource ) => Promise<ArrayBuffer>;

export interface TtsAudioCacheOptions {
  cacheEnabled?     : boolean;
  maxAge?           : number;
  maxSize?          : number;
  debug?            : boolean;
  // Test seams — default to the platform globals when omitted.
  indexedDBFactory? : MinimalIdbFactory | null;
  subtleDigest?     : SubtleDigestFn;
  now?              : () => number;
  setIntervalFn?    : ( cb: () => void, ms: number ) => void;
}

const DEFAULT_MAX_AGE  = 24 * 60 * 60 * 1000; // 24 hours
const DEFAULT_MAX_SIZE = 50 * 1024 * 1024;    // 50 MB
const CLEANUP_INTERVAL_MS = 30 * 60 * 1000;   // 30 minutes
const DB_NAME    = "TTSAudioCache";
const DB_VERSION = 1;
const STORE_NAME = "audioCache";

interface CacheStatsCounters {
  hits      : number;
  misses    : number;
  stores    : number;
  totalSize : number;
}

/* c8 ignore start */ // production-default fallback: the browser's global `indexedDB`; node/SSR + the unit suite have no IndexedDB, so this arm is browser-only (tests always inject `indexedDBFactory` or pass null).
function defaultIndexedDBFactory(): MinimalIdbFactory | null {
  return typeof indexedDB !== "undefined" ? ( indexedDB as unknown as MinimalIdbFactory ) : null;
}
/* c8 ignore stop */

export class TtsAudioCache {
  private readonly cacheEnabled : boolean;
  private readonly maxAge       : number;
  private readonly maxSize      : number;
  private readonly debug        : boolean;

  private readonly indexedDBFactory : MinimalIdbFactory | null;
  private readonly subtleDigest     : SubtleDigestFn;
  private readonly now              : () => number;
  private readonly setIntervalFn    : ( cb: () => void, ms: number ) => void;

  private readonly memoryCache : Map<string, CacheEntry> = new Map();
  private db    : MinimalIdbDatabase | null = null;
  private stats : CacheStatsCounters = { hits: 0, misses: 0, stores: 0, totalSize: 0 };

  constructor( options: TtsAudioCacheOptions = {} ) {
    this.cacheEnabled = options.cacheEnabled !== false; // Default true.
    this.maxAge       = options.maxAge ?? DEFAULT_MAX_AGE;
    this.maxSize      = options.maxSize ?? DEFAULT_MAX_SIZE;
    this.debug        = options.debug ?? false;

    this.indexedDBFactory = options.indexedDBFactory ?? defaultIndexedDBFactory();
    this.subtleDigest = options.subtleDigest
      ?? (( algorithm, data ) => crypto.subtle.digest( algorithm, data ));
    this.now           = options.now ?? (() => Date.now());
    this.setIntervalFn = options.setIntervalFn ?? (( cb, ms ) => { setInterval( cb, ms ); });

    if ( this.debug ) console.log( "TtsAudioCache: Initialized with", options );
  }

  /**
   * Open the IndexedDB connection and arm the periodic cleanup sweep.
   *
   * Ensures:
   *   - no-ops when caching is disabled
   *   - falls back to a memory-only cache (no throw) if IndexedDB is
   *     unavailable or fails to open
   */
  async initialize(): Promise<void> {
    if ( !this.cacheEnabled ) {
      if ( this.debug ) console.log( "TtsAudioCache: Caching disabled" );
      return;
    }

    try {
      await this.initializeIndexedDB();
      this.scheduleCleanup();
      if ( this.debug ) console.log( "TtsAudioCache: Ready" );
    } catch ( error ) {
      console.warn( "TtsAudioCache: IndexedDB failed, using memory-only cache:", error );
    }
  }

  /** SHA-256 hex digest of the normalized (trimmed, lower-cased) text. */
  async generateCacheKey( text: string ): Promise<string> {
    const encoder    = new TextEncoder();
    const data       = encoder.encode( text.trim().toLowerCase() );
    const hashBuffer = await this.subtleDigest( "SHA-256", data );
    const hashArray  = Array.from( new Uint8Array( hashBuffer ) );
    return hashArray.map( ( b ) => b.toString( 16 ).padStart( 2, "0" ) ).join( "" );
  }

  /** Open (and, on first run, create) the audio-cache object store. */
  private initializeIndexedDB(): Promise<void> {
    return new Promise( ( resolve, reject ) => {
      const factory = this.indexedDBFactory;
      if ( !factory ) {
        reject( new Error( "IndexedDB unavailable" ) );
        return;
      }

      const request = factory.open( DB_NAME, DB_VERSION );

      request.onerror = () => reject( request.error );
      request.onsuccess = () => {
        this.db = request.result;
        resolve();
      };

      request.onupgradeneeded = ( event ) => {
        const db = event.target?.result as MinimalIdbDatabase;
        if ( !db.objectStoreNames.contains( STORE_NAME ) ) {
          const store = db.createObjectStore( STORE_NAME, { keyPath: "key" } );
          store.createIndex( "timestamp", "timestamp", { unique: false } );
        }
      };
    } );
  }

  /**
   * Look up cached audio for `text` (memory first, then IndexedDB).
   *
   * Ensures:
   *   - returns the cached Blob on a fresh hit, null on miss/expired/disabled
   *   - promotes an IndexedDB hit back into the memory cache
   *   - never throws — swallows lookup errors and returns null
   */
  async checkCache( text: string ): Promise<Blob | null> {
    if ( !this.cacheEnabled ) return null;

    try {
      const key = await this.generateCacheKey( text );

      // In-memory cache first (fastest).
      if ( this.memoryCache.has( key ) ) {
        const entry = this.memoryCache.get( key ) as CacheEntry;
        if ( !this.isExpired( entry ) ) {
          this.stats.hits++;
          if ( this.debug ) console.log( "TtsAudioCache: Memory hit for", text.substring( 0, 30 ) + "..." );
          return entry.audioBlob;
        }
        this.memoryCache.delete( key ); // Drop the expired entry.
      }

      // IndexedDB (persistent).
      if ( this.db ) {
        const entry = await this.getFromIndexedDB( this.db, key );
        if ( entry && !this.isExpired( entry ) ) {
          this.memoryCache.set( key, entry ); // Promote back into memory.
          this.stats.hits++;
          if ( this.debug ) console.log( "TtsAudioCache: IndexedDB hit for", text.substring( 0, 30 ) + "..." );
          return entry.audioBlob;
        }
      }

      this.stats.misses++;
      if ( this.debug ) console.log( "TtsAudioCache: Miss for", text.substring( 0, 30 ) + "..." );
      return null;
    } catch ( error ) {
      console.error( "TtsAudioCache: Check failed:", error );
      return null;
    }
  }

  /**
   * Persist `audioBlob` for `text` into both cache tiers.
   *
   * Ensures:
   *   - no-ops when caching is disabled or the blob is falsy
   *   - triggers a size-bounded cleanup after a successful store
   *   - never throws — swallows store errors
   */
  async saveToCache( text: string, audioBlob: Blob | null | undefined ): Promise<void> {
    if ( !this.cacheEnabled || !audioBlob ) return;

    try {
      const key   = await this.generateCacheKey( text );
      const entry : CacheEntry = {
        key,
        text      : text.substring( 0, 100 ), // Truncated copy for debugging.
        audioBlob,
        timestamp : this.now(),
        size      : audioBlob.size,
      };

      this.memoryCache.set( key, entry );

      if ( this.db ) {
        await this.saveToIndexedDB( this.db, entry );
      }

      this.stats.stores++;
      this.stats.totalSize += audioBlob.size;

      if ( this.debug ) console.log( `TtsAudioCache: Stored ${audioBlob.size} bytes for "${text.substring( 0, 30 )}..."` );

      await this.cleanupIfNeeded();
    } catch ( error ) {
      console.error( "TtsAudioCache: Save failed:", error );
    }
  }

  /**
   * Read a single row from IndexedDB; resolves null on miss or error.
   *
   * Requires: `this.db` is open (only ever called from the `if ( this.db )`
   * branch in `checkCache`), so no redundant null-guard is needed here.
   */
  private getFromIndexedDB( db: MinimalIdbDatabase, key: string ): Promise<CacheEntry | null> {
    return new Promise( ( resolve ) => {
      const transaction = db.transaction( [ STORE_NAME ], "readonly" );
      const store       = transaction.objectStore( STORE_NAME );
      const request     = store.get( key );

      request.onsuccess = () => resolve( request.result ?? null );
      request.onerror   = () => resolve( null );
    } );
  }

  /**
   * Write a single row to IndexedDB; rejects on store error.
   *
   * Requires: `this.db` is open (only ever called from the `if ( this.db )`
   * branch in `saveToCache`), so no redundant null-guard is needed here.
   */
  private saveToIndexedDB( db: MinimalIdbDatabase, entry: CacheEntry ): Promise<void> {
    return new Promise( ( resolve, reject ) => {
      const transaction = db.transaction( [ STORE_NAME ], "readwrite" );
      const store       = transaction.objectStore( STORE_NAME );
      const request     = store.put( entry );

      request.onsuccess = () => resolve();
      request.onerror   = () => reject( request.error );
    } );
  }

  /** True when `entry` is older than `maxAge`. */
  isExpired( entry: CacheEntry ): boolean {
    return this.now() - entry.timestamp > this.maxAge;
  }

  /** Run a cleanup sweep only when the tracked total size exceeds maxSize. */
  private async cleanupIfNeeded(): Promise<void> {
    if ( this.stats.totalSize > this.maxSize ) {
      await this.cleanup();
    }
  }

  /** Evict expired entries from both the memory cache and IndexedDB. */
  async cleanup(): Promise<void> {
    const beforeSize  = this.stats.totalSize;
    let   removedSize = 0;

    // Memory cache.
    for ( const [ key, entry ] of this.memoryCache ) {
      if ( this.isExpired( entry ) ) {
        this.memoryCache.delete( key );
        removedSize += entry.size;
      }
    }

    // IndexedDB (cursor sweep over every row).
    if ( this.db ) {
      const transaction = this.db.transaction( [ STORE_NAME ], "readwrite" );
      const store       = transaction.objectStore( STORE_NAME );
      const request     = store.openCursor();

      request.onsuccess = ( event ) => {
        const cursor = event.target?.result ?? null;
        if ( cursor ) {
          const entry = cursor.value;
          if ( this.isExpired( entry ) ) {
            cursor.delete();
            removedSize += entry.size || 0;
          }
          cursor.continue();
        }
      };
    }

    this.stats.totalSize = Math.max( 0, beforeSize - removedSize );
    if ( this.debug && removedSize > 0 ) {
      console.log( `TtsAudioCache: Cleaned up ${removedSize} bytes` );
    }
  }

  /** Arm the recurring 30-minute background cleanup sweep. */
  private scheduleCleanup(): void {
    this.setIntervalFn( () => { void this.cleanup(); }, CLEANUP_INTERVAL_MS );
  }

  /** Human-readable snapshot of cache hit-rate, size, and entry count. */
  getStats(): CacheStats {
    const total   = this.stats.hits + this.stats.misses;
    const hitRate = total > 0
      ? ( this.stats.hits / total * 100 ).toFixed( 1 )
      : "0";

    return {
      enabled   : this.cacheEnabled,
      hits      : this.stats.hits,
      misses    : this.stats.misses,
      stores    : this.stats.stores,
      hitRate   : `${hitRate}%`,
      totalSize : `${( this.stats.totalSize / 1024 / 1024 ).toFixed( 2 )} MB`,
      entries   : this.memoryCache.size,
    };
  }

  /** Empty both cache tiers and reset all statistics counters. */
  clearCache(): void {
    this.memoryCache.clear();

    if ( this.db ) {
      const transaction = this.db.transaction( [ STORE_NAME ], "readwrite" );
      transaction.objectStore( STORE_NAME ).clear();
    }

    this.stats = { hits: 0, misses: 0, stores: 0, totalSize: 0 };

    if ( this.debug ) console.log( "TtsAudioCache: Cache cleared" );
  }
  /* c8 ignore next */ // tsx phantom-branch artifact on the class-closing line (no executable code; c8 source-map view fabricates a branch here).
}
