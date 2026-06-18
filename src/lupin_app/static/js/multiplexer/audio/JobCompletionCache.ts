/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6 (TTS-playback frontier) — JobCompletionCache.
//
// TypeScript port of `src/lupin_app/static/js/job-completion-cache.js`
// (JS→TS multiplexer migration, umbrella 312ba8ab). A richer sibling of
// TtsAudioCache: a dual-tier (in-memory Map + IndexedDB) cache of job-
// completion *messages* keyed by jobId, with a SHA-256 text hash, LRU
// eviction bounded by both a byte-size budget and a max-entry count,
// time-based expiration, and lightweight analytics (popular phrases +
// most-replayed jobs).
//
// Preserves the legacy contract: `generateCacheKey` / `store` / `get` /
// `getByText` / `delete` / `isCacheExpired` / `getAnalytics` / `getAllJobs`
// / `clearCache` / `destroy`. Two intentional, documented deviations:
//
//   1. Constructor takes an options dict (matching the multiplexer's
//      AudioRecorder / SequentialAudioManager / TtsAudioCache idiom) — same
//      shape as the legacy `options` arg, so no caller changes. The module is
//      net-new to the multiplexer tree (no existing TS consumers).
//   2. The legacy constructor eagerly fires `initializeIndexedDB()` as a
//      fire-and-forget promise, leaving callers no way to await readiness
//      (every method just races on `if (this.db)`). The port preserves the
//      eager auto-init but additionally exposes the settled init as a public
//      `ready` promise (it never rejects — open failures fall back to a
//      memory-only cache, exactly as the legacy `.catch` did). This makes the
//      otherwise-untestable eager init deterministically awaitable.
//
// Runtime dependencies (the IndexedDB factory, `crypto.subtle.digest`,
// `Date.now`, and `new Date().toISOString()`) are injectable through the
// options dict — they default to the platform globals but let the unit suite
// drive the dual-cache state machine, expiration, eviction, and the IDB
// error fallbacks deterministically without a real browser database.

/** A single cached job-completion record (in-memory + IndexedDB row shape). */
export interface JobCacheEntry {
  jobId        : string;
  text         : string;
  textHash     : string;
  timestamp    : string;            // Caller-supplied or ISO `nowIso()`.
  timestampMs  : number;            // `now()` at store time (expiry basis).
  userId       : string | null;
  size         : number;            // UTF-8 byte length of `text`.
  replayCount  : number;
  lastReplayed : string | null;
  metadata     : Record<string, unknown>;
}

/** One entry of the popular-phrases analytics readout. */
export interface PopularPhrase { phrase: string; count: number; }
/** One entry of the most-replayed-jobs analytics readout. */
export interface TopJob { jobId: string; replayCount: number; }

/** The human-readable analytics snapshot. */
export interface JobCacheAnalytics {
  totalStores    : number;
  totalRetrieves : number;
  cacheHits      : number;
  cacheMisses    : number;
  hitRate        : string;
  totalCacheSize : string;
  cacheEntries   : number;
  popularPhrases : PopularPhrase[];
  topJobs        : TopJob[];
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

export interface MinimalIdbIndex {
  get( key: string ): MinimalIdbRequest<JobCacheEntry | undefined>;
}

export interface MinimalIdbObjectStore {
  createIndex( name: string, keyPath: string, options: { unique: boolean } ): void;
  get( key: string ): MinimalIdbRequest<JobCacheEntry | undefined>;
  put( entry: JobCacheEntry ): MinimalIdbRequest<unknown>;
  delete( key: string ): void;
  clear(): void;
  getAll(): MinimalIdbRequest<JobCacheEntry[]>;
  index( name: string ): MinimalIdbIndex;
}

export interface MinimalIdbTransaction {
  objectStore( name: string ): MinimalIdbObjectStore;
}

export interface MinimalIdbDatabase {
  objectStoreNames : { contains( name: string ): boolean };
  createObjectStore( name: string, options: { keyPath: string } ): MinimalIdbObjectStore;
  transaction( storeNames: string[], mode: string ): MinimalIdbTransaction;
  close(): void;
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

export interface JobCompletionCacheOptions {
  cacheEnabled?     : boolean;
  cacheMaxSize?     : number;
  cacheMaxAge?      : number;
  maxEntries?       : number;
  // Test seams — default to the platform globals when omitted.
  indexedDBFactory? : MinimalIdbFactory | null;
  subtleDigest?     : SubtleDigestFn;
  now?              : () => number;
  nowIso?           : () => string;
}

const DEFAULT_MAX_SIZE   = 10 * 1024 * 1024;            // 10 MB of text
const DEFAULT_MAX_AGE    = 30 * 24 * 60 * 60 * 1000;    // 30 days
const DEFAULT_MAX_ENTRIES = 1000;
const DB_NAME    = "JobCompletionCache";
const DB_VERSION = 1;
const STORE_NAME = "jobMessages";
const ANALYTICS_TOP_N    = 10;
const PHRASE_PREVIEW_LEN  = 50;
const JOBID_PREVIEW_LEN   = 20;
const DB_QUERY_MEMORY_FLOOR = 50; // Skip the getAll DB scan once memory has this many.

interface JobCacheAnalyticsState {
  totalStores    : number;
  totalRetrieves : number;
  cacheHits      : number;
  cacheMisses    : number;
  totalCacheSize : number;
  popularPhrases : Map<string, number>;
  topJobs        : Map<string, number>;
}

function defaultIndexedDBFactory(): MinimalIdbFactory | null {
  /* c8 ignore next */ // browser-only true-arm: node/SSR + the unit suite have no global `indexedDB`, so this arm never runs under test (tests inject `indexedDBFactory` or pass null). The `return null` false-arm below IS exercised.
  if ( typeof indexedDB !== "undefined" ) return indexedDB as unknown as MinimalIdbFactory;
  return null;
}

export class JobCompletionCache {
  private readonly cacheEnabled : boolean;
  private readonly cacheMaxSize : number;
  private readonly cacheMaxAge  : number;
  private readonly maxEntries   : number;

  private readonly indexedDBFactory : MinimalIdbFactory | null;
  private readonly subtleDigest     : SubtleDigestFn;
  private readonly now              : () => number;
  private readonly nowIso           : () => string;

  private readonly messageCache : Map<string, JobCacheEntry> = new Map();
  private db : MinimalIdbDatabase | null = null;

  private readonly analytics : JobCacheAnalyticsState = {
    totalStores    : 0,
    totalRetrieves : 0,
    cacheHits      : 0,
    cacheMisses    : 0,
    totalCacheSize : 0,
    popularPhrases : new Map(),
    topJobs        : new Map(),
  };

  /**
   * Settled IndexedDB-init promise (never rejects — open failures degrade to a
   * memory-only cache). Resolves immediately when caching is disabled.
   */
  readonly ready : Promise<void>;

  constructor( options: JobCompletionCacheOptions = {} ) {
    this.cacheEnabled = options.cacheEnabled !== false; // Default true.
    this.cacheMaxSize = options.cacheMaxSize ?? DEFAULT_MAX_SIZE;
    this.cacheMaxAge  = options.cacheMaxAge ?? DEFAULT_MAX_AGE;
    this.maxEntries   = options.maxEntries ?? DEFAULT_MAX_ENTRIES;

    this.indexedDBFactory = options.indexedDBFactory ?? defaultIndexedDBFactory();
    this.subtleDigest = options.subtleDigest
      ?? (( algorithm, data ) => crypto.subtle.digest( algorithm, data ));
    this.now    = options.now ?? (() => Date.now());
    this.nowIso = options.nowIso ?? (() => new Date().toISOString());

    // Eager auto-init (legacy behavior), surfaced as an awaitable `ready`.
    if ( this.cacheEnabled ) {
      this.ready = this.initializeIndexedDB().catch( ( err ) => {
        console.warn( "JobCompletionCache: IndexedDB initialization failed, using memory cache only:", err );
      } );
    } else {
      this.ready = Promise.resolve();
    }
  }

  /** SHA-256 hex digest of `text` (used as the cross-tier text hash). */
  async generateCacheKey( text: string ): Promise<string> {
    const encoder    = new TextEncoder();
    const data       = encoder.encode( text );
    const hashBuffer = await this.subtleDigest( "SHA-256", data );
    const hashArray  = Array.from( new Uint8Array( hashBuffer ) );
    return hashArray.map( ( b ) => b.toString( 16 ).padStart( 2, "0" ) ).join( "" );
  }

  /** Open (and, on first run, create) the job-messages object store. */
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
        console.log( "JobCompletionCache: IndexedDB initialized" );
        resolve();
      };

      request.onupgradeneeded = ( event ) => {
        const db = event.target?.result as MinimalIdbDatabase;
        if ( !db.objectStoreNames.contains( STORE_NAME ) ) {
          const store = db.createObjectStore( STORE_NAME, { keyPath: "jobId" } );
          store.createIndex( "timestamp", "timestamp", { unique: false } );
          store.createIndex( "textHash", "textHash", { unique: false } );
          store.createIndex( "userId", "userId", { unique: false } );
        }
      };
    } );
  }

  /**
   * Store a job-completion message under `jobId` in both cache tiers.
   *
   * Ensures:
   *   - no-ops when caching is disabled
   *   - records analytics (store count, total size, phrase frequency)
   *   - runs an eviction pass to honor the size + entry-count budgets
   */
  async store(
    jobId     : string,
    text      : string,
    timestamp : string | null = null,
    userId    : string | null = null,
    metadata  : Record<string, unknown> = {},
  ): Promise<void> {
    if ( !this.cacheEnabled ) return;

    const ts       = timestamp ?? this.nowIso();
    const textHash = await this.generateCacheKey( text );

    const cacheEntry : JobCacheEntry = {
      jobId,
      text,
      textHash,
      timestamp    : ts,
      timestampMs  : this.now(),
      userId,
      size         : new Blob( [ text ] ).size,
      replayCount  : 0,
      lastReplayed : null,
      metadata,
    };

    this.analytics.totalStores++;
    this.analytics.totalCacheSize += cacheEntry.size;
    this.updatePhraseFrequency( text );

    this.messageCache.set( jobId, cacheEntry );

    if ( this.db ) {
      await this.saveToIndexedDB( this.db, cacheEntry );
    }

    await this.evictOldEntries();

    console.log( `JobCompletionCache: Stored job ${jobId} (${cacheEntry.size} bytes)` );
  }

  /**
   * Retrieve the cached message for `jobId` (memory first, then IndexedDB).
   *
   * Ensures:
   *   - returns the entry on a fresh hit (and bumps its replay stats), null
   *     on miss / expired / disabled
   *   - promotes an IndexedDB hit back into the memory cache
   */
  async get( jobId: string ): Promise<JobCacheEntry | null> {
    if ( !this.cacheEnabled ) return null;

    this.analytics.totalRetrieves++;

    // In-memory cache first.
    if ( this.messageCache.has( jobId ) ) {
      const cached = this.messageCache.get( jobId ) as JobCacheEntry;
      if ( !this.isCacheExpired( cached ) ) {
        this.analytics.cacheHits++;
        this.recordReplay( jobId, cached );
        return cached;
      }
      // Drop the expired entry.
      this.messageCache.delete( jobId );
      this.analytics.totalCacheSize -= cached.size;
    }

    // IndexedDB.
    if ( this.db ) {
      const cached = await this.getFromIndexedDB( this.db, jobId );
      if ( cached && !this.isCacheExpired( cached ) ) {
        this.messageCache.set( jobId, cached ); // Promote back into memory.
        this.analytics.cacheHits++;
        this.recordReplay( jobId, cached );
        return cached;
      }
    }

    this.analytics.cacheMisses++;
    return null;
  }

  /** Bump replay count + last-replayed timestamp and mirror to topJobs. */
  private recordReplay( jobId: string, entry: JobCacheEntry ): void {
    entry.replayCount++;
    entry.lastReplayed = this.nowIso();
    this.analytics.topJobs.set( jobId, entry.replayCount );
  }

  /**
   * Find a cached entry by its text content (via the SHA-256 textHash).
   *
   * Ensures:
   *   - returns a fresh memory match, else a fresh IndexedDB `textHash`-index
   *     match (promoted into memory), else null (disabled → null)
   */
  async getByText( text: string ): Promise<JobCacheEntry | null> {
    if ( !this.cacheEnabled ) return null;

    const textHash = await this.generateCacheKey( text );

    // Search in-memory cache.
    for ( const entry of this.messageCache.values() ) {
      if ( entry.textHash === textHash && !this.isCacheExpired( entry ) ) {
        return entry;
      }
    }

    // Search IndexedDB by the textHash index.
    if ( this.db ) {
      const transaction = this.db.transaction( [ STORE_NAME ], "readonly" );
      const store       = transaction.objectStore( STORE_NAME );
      const index       = store.index( "textHash" );

      return new Promise( ( resolve ) => {
        const request = index.get( textHash );
        request.onsuccess = () => {
          const result = request.result;
          if ( result && !this.isCacheExpired( result ) ) {
            this.messageCache.set( result.jobId, result ); // Promote into memory.
            resolve( result );
          } else {
            resolve( null );
          }
        };
        request.onerror = () => resolve( null );
      } );
    }

    return null;
  }

  /** Remove `jobId` from both cache tiers. */
  async delete( jobId: string ): Promise<void> {
    const entry = this.messageCache.get( jobId );
    if ( entry ) {
      this.messageCache.delete( jobId );
      this.analytics.totalCacheSize -= entry.size;
    }

    if ( this.db ) {
      const transaction = this.db.transaction( [ STORE_NAME ], "readwrite" );
      transaction.objectStore( STORE_NAME ).delete( jobId );
    }

    console.log( `JobCompletionCache: Deleted job ${jobId}` );
  }

  /**
   * Read a single row from IndexedDB; rejects on store error.
   *
   * Requires: caller passes an open `db` (only ever invoked from an
   * `if ( this.db )` branch), so no redundant null-guard is needed.
   */
  private getFromIndexedDB( db: MinimalIdbDatabase, jobId: string ): Promise<JobCacheEntry | null> {
    return new Promise( ( resolve, reject ) => {
      const transaction = db.transaction( [ STORE_NAME ], "readonly" );
      const store       = transaction.objectStore( STORE_NAME );
      const request     = store.get( jobId );

      request.onsuccess = () => resolve( request.result ?? null );
      request.onerror   = () => reject( request.error );
    } );
  }

  /**
   * Write a single row to IndexedDB; rejects on store error.
   *
   * Requires: caller passes an open `db` (only ever invoked from an
   * `if ( this.db )` branch), so no redundant null-guard is needed.
   */
  private saveToIndexedDB( db: MinimalIdbDatabase, entry: JobCacheEntry ): Promise<void> {
    return new Promise( ( resolve, reject ) => {
      const transaction = db.transaction( [ STORE_NAME ], "readwrite" );
      const store       = transaction.objectStore( STORE_NAME );
      const request     = store.put( entry );

      request.onsuccess = () => resolve();
      request.onerror   = () => reject( request.error );
    } );
  }

  /** True when `entry` is older than `cacheMaxAge`. */
  isCacheExpired( entry: JobCacheEntry ): boolean {
    return this.now() - entry.timestampMs > this.cacheMaxAge;
  }

  /** Evict expired entries, then oldest-first until within size + count budgets. */
  private async evictOldEntries(): Promise<void> {
    let totalSize = 0;
    const entries = Array.from( this.messageCache.values() );

    // Oldest first.
    entries.sort( ( a, b ) => a.timestampMs - b.timestampMs );

    // Drop expired entries; tally the survivors' size.
    const validEntries = entries.filter( ( entry ) => {
      if ( this.isCacheExpired( entry ) ) {
        this.messageCache.delete( entry.jobId );
        this.analytics.totalCacheSize -= entry.size;
        return false;
      }
      totalSize += entry.size;
      return true;
    } );

    // Evict oldest survivors while over either budget.
    while (
      ( totalSize > this.cacheMaxSize || validEntries.length > this.maxEntries )
      && validEntries.length > 0
    ) {
      const oldest = validEntries.shift() as JobCacheEntry;
      this.messageCache.delete( oldest.jobId );
      totalSize -= oldest.size;
      this.analytics.totalCacheSize -= oldest.size;

      if ( this.db ) {
        const transaction = this.db.transaction( [ STORE_NAME ], "readwrite" );
        transaction.objectStore( STORE_NAME ).delete( oldest.jobId );
      }
    }
  }

  /** Track normalized-phrase frequency for the analytics readout. */
  private updatePhraseFrequency( text: string ): void {
    const normalizedText = text.toLowerCase().trim();
    const count = this.analytics.popularPhrases.get( normalizedText ) ?? 0;
    this.analytics.popularPhrases.set( normalizedText, count + 1 );
  }

  /** Human-readable analytics: hit rate, size, top phrases, and top jobs. */
  getAnalytics(): JobCacheAnalytics {
    const hitRate = this.analytics.totalRetrieves > 0
      ? ( this.analytics.cacheHits / this.analytics.totalRetrieves * 100 ).toFixed( 2 )
      : "0";

    const popularPhrases : PopularPhrase[] = Array.from( this.analytics.popularPhrases.entries() )
      .sort( ( a, b ) => b[ 1 ] - a[ 1 ] )
      .slice( 0, ANALYTICS_TOP_N )
      .map( ( [ phrase, count ] ) => ( {
        phrase : phrase.substring( 0, PHRASE_PREVIEW_LEN ) + ( phrase.length > PHRASE_PREVIEW_LEN ? "..." : "" ),
        count,
      } ) );

    const topJobs : TopJob[] = Array.from( this.analytics.topJobs.entries() )
      .sort( ( a, b ) => b[ 1 ] - a[ 1 ] )
      .slice( 0, ANALYTICS_TOP_N )
      .map( ( [ jobId, replayCount ] ) => ( {
        jobId : jobId.substring( 0, JOBID_PREVIEW_LEN ) + ( jobId.length > JOBID_PREVIEW_LEN ? "..." : "" ),
        replayCount,
      } ) );

    return {
      totalStores    : this.analytics.totalStores,
      totalRetrieves : this.analytics.totalRetrieves,
      cacheHits      : this.analytics.cacheHits,
      cacheMisses    : this.analytics.cacheMisses,
      hitRate        : `${hitRate}%`,
      totalCacheSize : `${( this.analytics.totalCacheSize / 1024 ).toFixed( 2 )} KB`,
      cacheEntries   : this.messageCache.size,
      popularPhrases,
      topJobs,
    };
  }

  /**
   * List cached jobs (newest first), optionally filtered by `userId`.
   *
   * Ensures:
   *   - returns fresh memory entries, supplemented by a fresh IndexedDB
   *     `getAll` scan only when memory holds fewer than the DB-query floor
   */
  async getAllJobs( userId: string | null = null ): Promise<JobCacheEntry[]> {
    const jobs : JobCacheEntry[] = [];

    // Memory cache.
    for ( const entry of this.messageCache.values() ) {
      if ( ( !userId || entry.userId === userId ) && !this.isCacheExpired( entry ) ) {
        jobs.push( entry );
      }
    }

    // Supplement from IndexedDB only when memory is sparse.
    if ( this.db && jobs.length < DB_QUERY_MEMORY_FLOOR ) {
      const transaction = this.db.transaction( [ STORE_NAME ], "readonly" );
      const store       = transaction.objectStore( STORE_NAME );

      const dbJobs = await new Promise<JobCacheEntry[]>( ( resolve ) => {
        const request = store.getAll();
        request.onsuccess = () => {
          const results = request.result.filter( ( entry ) => {
            const matchesUser = !userId || entry.userId === userId;
            const notExpired  = !this.isCacheExpired( entry );
            const notInMemory = !this.messageCache.has( entry.jobId );
            return matchesUser && notExpired && notInMemory;
          } );
          resolve( results );
        };
        request.onerror = () => resolve( [] );
      } );

      jobs.push( ...dbJobs );
    }

    // Newest first.
    return jobs.sort( ( a, b ) => b.timestampMs - a.timestampMs );
  }

  /** Empty both cache tiers and reset size + analytics maps. */
  clearCache(): void {
    this.messageCache.clear();

    if ( this.db ) {
      const transaction = this.db.transaction( [ STORE_NAME ], "readwrite" );
      transaction.objectStore( STORE_NAME ).clear();
    }

    this.analytics.totalCacheSize = 0;
    this.analytics.popularPhrases.clear();
    this.analytics.topJobs.clear();

    console.log( "JobCompletionCache: Cache cleared" );
  }

  /** Clear the cache and close the IndexedDB connection. */
  destroy(): void {
    this.clearCache();
    if ( this.db ) {
      this.db.close();
    }
  }
  /* c8 ignore next */ // tsx phantom-branch artifact on the class-closing line (no executable code; c8 source-map view fabricates a branch here).
}
