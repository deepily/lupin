/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6 (TTS-playback frontier) — SequentialAudioManager.
//
// TypeScript port of `src/lupin_app/static/js/sequential-audio-manager.js`
// (JS→TS multiplexer migration, umbrella 312ba8ab). The multiplexer's
// `AudioStore` explicitly defers actual playback scheduling to an unbuilt
// "Phase 6 TTSEngine"; this is the most bounded, self-contained entry into
// that frontier — a queue-based sequential audio player that guarantees
// chunks play one-at-a-time without overlap, using one HTMLAudioElement per
// chunk + the `ended` event for reliable timing.
//
// Preserves the legacy contract: `addChunk` / `stop` / `reset` / `getStats`
// / `isPlaying` / `getQueueLength` plus `onChunkStart` / `onChunkEnd`
// callbacks. Two intentional, documented deviations from the legacy class:
//
//   1. Constructor takes an options dict (matching the multiplexer's
//      `AudioRecorder` idiom) instead of the legacy positional
//      `(onChunkStart, onChunkEnd, debug)` signature. The module is net-new
//      to the multiplexer (no existing consumers), so there is no caller to
//      preserve positionally.
//   2. The legacy static `supportsPromiseBasedPlay` feature-test
//      (`'play' in HTMLAudioElement.prototype`, always true in modern
//      browsers) is replaced by a per-call runtime thenable check on the
//      value returned by `play()`. Same observable behavior, but it makes
//      both the promise and the non-promise branch deterministically
//      reachable under unit tests via an injected audio factory.
//
// Browser dependencies (Audio / URL.createObjectURL / setTimeout /
// navigator.userAgent) are injectable through the options dict — they
// default to the browser globals but allow the unit suite to drive the
// queue state machine, retry logic, and blob-URL cleanup deterministically.

/** The minimal HTMLAudioElement surface this manager drives. */
export interface PlayableAudio {
  src         : string;
  currentTime : number;
  paused      : boolean;
  preload     : string;
  volume      : number;
  play(): Promise<void> | void;
  pause(): void;
  addEventListener( type: string, listener: ( ev: unknown ) => void ): void;
}

/** Shape of the `error` event the audio element surfaces (legacy contract). */
interface AudioErrorEvent {
  target?: {
    error?: { code?: number; message?: string } | null;
    src?  : string;
  };
}

/** Constructs a playable audio element for a given (blob) URL. */
export type AudioFactory = ( src: string ) => PlayableAudio;

export interface SequentialAudioManagerOptions {
  onChunkStart?    : (( chunkIndex: number ) => void) | null;
  onChunkEnd?      : (( chunkIndex: number ) => void) | null;
  debug?           : boolean;
  maxQueueSize?    : number;
  retryAttempts?   : number;
  retryDelayMs?    : number;
  cleanupDelayMs?  : number;
  // Test seams — default to the browser globals when omitted.
  audioFactory?    : AudioFactory;
  createObjectURL? : ( blob: Blob ) => string;
  revokeObjectURL? : ( url: string ) => void;
  setTimeoutFn?    : ( cb: () => void, ms: number ) => void;
  userAgent?       : string;
}

export interface SequentialAudioStats {
  chunksPlayed   : number;
  queueLength    : number;
  isPlaying      : boolean;
  totalProcessed : number;
  errorCount     : number;
  activeBlobUrls : number;
}

const DEFAULT_MAX_QUEUE_SIZE   = 100;
const DEFAULT_RETRY_ATTEMPTS   = 3;
const DEFAULT_RETRY_DELAY_MS   = 100;
const DEFAULT_CLEANUP_DELAY_MS = 50;

export class SequentialAudioManager {
  private readonly onChunkStart   : (( chunkIndex: number ) => void) | null;
  private readonly onChunkEnd     : (( chunkIndex: number ) => void) | null;
  private readonly debug          : boolean;
  private readonly maxQueueSize   : number;
  private readonly retryAttempts  : number;
  private readonly retryDelayMs   : number;
  private readonly cleanupDelayMs : number;

  private readonly audioFactory    : AudioFactory;
  private readonly createObjectURL : ( blob: Blob ) => string;
  private readonly revokeObjectURL : ( url: string ) => void;
  private readonly setTimeoutFn    : ( cb: () => void, ms: number ) => void;
  private readonly isFirefox       : boolean;

  private chunkQueue           : Blob[] = [];
  private currentlyPlaying     : boolean = false;
  private currentAudio         : PlayableAudio | null = null;
  private chunksPlayed         : number = 0;
  private totalChunksProcessed : number = 0;
  private errorCount           : number = 0;
  private readonly blobUrls    : Set<string> = new Set();

  constructor( opts: SequentialAudioManagerOptions = {} ) {
    this.onChunkStart   = opts.onChunkStart   ?? null;
    this.onChunkEnd     = opts.onChunkEnd     ?? null;
    this.debug          = opts.debug          ?? false;
    this.maxQueueSize   = opts.maxQueueSize   ?? DEFAULT_MAX_QUEUE_SIZE;
    this.retryAttempts  = opts.retryAttempts  ?? DEFAULT_RETRY_ATTEMPTS;
    this.retryDelayMs   = opts.retryDelayMs   ?? DEFAULT_RETRY_DELAY_MS;
    this.cleanupDelayMs = opts.cleanupDelayMs ?? DEFAULT_CLEANUP_DELAY_MS;

    this.audioFactory    = opts.audioFactory    ?? (( src ) => new Audio( src ) as unknown as PlayableAudio);
    this.createObjectURL = opts.createObjectURL ?? (( blob ) => URL.createObjectURL( blob ));
    this.revokeObjectURL = opts.revokeObjectURL ?? (( url ) => { URL.revokeObjectURL( url ); });
    this.setTimeoutFn    = opts.setTimeoutFn    ?? (( cb, ms ) => { setTimeout( cb, ms ); });

    const ua        = opts.userAgent ?? (typeof navigator !== "undefined" ? navigator.userAgent : "");
    this.isFirefox  = ua.toLowerCase().includes( "firefox" );

    if ( this.debug ) console.log( "[SequentialAudioManager] Initialized" );
  }

  /**
   * Add an audio chunk to the playback queue.
   *
   * Requires:
   *   - audioBlob is a Blob instance
   *
   * Ensures:
   *   - returns true if the chunk was enqueued, false if input was invalid
   *   - drops the oldest chunk first when the queue is at maxQueueSize
   *   - starts playback if nothing is currently playing
   */
  addChunk( audioBlob: Blob | null | undefined ): boolean {
    if ( this.chunkQueue.length >= this.maxQueueSize ) {
      console.warn( `[SequentialAudioManager] Queue size limit reached (${this.maxQueueSize}), dropping oldest chunk` );
      this._cleanupOldestChunk();
    }

    if ( !audioBlob || !(audioBlob instanceof Blob) ) {
      console.error( "[SequentialAudioManager] Invalid audio chunk provided" );
      return false;
    }

    this.chunkQueue.push( audioBlob );
    if ( this.debug ) console.log( `[SequentialAudioManager] Added chunk to queue (${this.chunkQueue.length} total)` );

    if ( !this.currentlyPlaying ) this.playNextChunk();

    return true;
  }

  /** Play the next queued chunk, or settle to idle when the queue drains. */
  playNextChunk(): void {
    if ( this.chunkQueue.length === 0 ) {
      this.currentlyPlaying = false;
      this.currentAudio     = null;
      if ( this.debug ) console.log( "[SequentialAudioManager] Queue empty, playback complete" );
      return;
    }

    const nextChunk = this.chunkQueue.shift() as Blob;
    this.chunksPlayed++;
    this.totalChunksProcessed++;

    if ( this.debug ) console.log( `[SequentialAudioManager] Playing chunk ${this.chunksPlayed} (${this.chunkQueue.length} remaining)` );

    const blobUrl = this.createObjectURL( nextChunk );
    this.blobUrls.add( blobUrl );

    const audio           = this.audioFactory( blobUrl );
    this.currentAudio     = audio;
    this.currentlyPlaying = true;

    audio.addEventListener( "ended", () => { this.onChunkComplete(); } );
    audio.addEventListener( "error", ( ev: unknown ) => {
      this.errorCount++;
      const errEvent = ev as AudioErrorEvent;
      console.error( "[SequentialAudioManager] Audio playback error:", errEvent.target?.error );
      if ( this.debug ) {
        console.error( "[SequentialAudioManager] Error details:", {
          chunksPlayed : this.chunksPlayed,
          queueLength  : this.chunkQueue.length,
          errorCode    : errEvent.target?.error?.code,
          errorMessage : errEvent.target?.error?.message,
        } );
      }
      this.onChunkComplete(); // Continue to next chunk even on error.
    } );

    if ( this.isFirefox ) {
      audio.preload = "auto";
      audio.volume  = 1.0;
    }

    if ( this.onChunkStart ) {
      try {
        this.onChunkStart( this.chunksPlayed );
      } catch ( error ) {
        console.error( "[SequentialAudioManager] Error in onChunkStart callback:", error );
      }
    }

    this._playWithRetry( audio, 0 );
  }

  /** Play with bounded retry on a rejected `play()` promise (autoplay gating). */
  private _playWithRetry( audioElement: PlayableAudio, attemptNumber: number ): void {
    const playResult = audioElement.play();

    if ( playResult !== undefined && typeof playResult.then === "function" ) {
      playResult.catch( ( error: unknown ) => {
        if ( attemptNumber < this.retryAttempts ) {
          console.warn( `[SequentialAudioManager] Play failed (attempt ${attemptNumber + 1}), retrying in ${this.retryDelayMs}ms:`, error );
          this.setTimeoutFn( () => {
            if ( this.currentAudio === audioElement ) {  // Still the current chunk?
              this._playWithRetry( audioElement, attemptNumber + 1 );
            }
          }, this.retryDelayMs );
        } else {
          console.error( `[SequentialAudioManager] Play failed after ${this.retryAttempts} attempts:`, error );
          this.onChunkComplete();
        }
      } );
    }
  }

  /** Handle completion (or errored skip) of the current chunk, then advance. */
  onChunkComplete(): void {
    if ( this.debug ) console.log( `[SequentialAudioManager] Chunk ${this.chunksPlayed} completed` );

    if ( this.currentAudio ) {
      const blobUrl = this.currentAudio.src;
      this.setTimeoutFn( () => {
        if ( this.blobUrls.has( blobUrl ) ) {
          this.revokeObjectURL( blobUrl );
          this.blobUrls.delete( blobUrl );
          if ( this.debug ) console.log( `[SequentialAudioManager] Cleaned up blob URL, ${this.blobUrls.size} remaining` );
        }
      }, this.cleanupDelayMs );
      this.currentAudio = null;
    }

    if ( this.onChunkEnd ) {
      try {
        this.onChunkEnd( this.chunksPlayed );
      } catch ( error ) {
        console.error( "[SequentialAudioManager] Error in onChunkEnd callback:", error );
      }
    }

    this.playNextChunk();
  }

  /** Stop playback and clear the queue (does not reset counters). */
  stop(): void {
    if ( this.debug ) console.log( "[SequentialAudioManager] Stopping playback" );

    this.chunkQueue = [];

    if ( this.currentAudio && !this.currentAudio.paused ) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
    }

    this._cleanupCurrentAudio();
    this.currentlyPlaying = false;
  }

  /** Stop, reset counters, and release every tracked blob URL. */
  reset(): void {
    this.stop();
    this.chunksPlayed         = 0;
    this.totalChunksProcessed = 0;
    this.errorCount           = 0;
    this._cleanupAllBlobUrls();
    if ( this.debug ) console.log( "[SequentialAudioManager] Reset complete" );
  }

  /** Snapshot of current playback statistics. */
  getStats(): SequentialAudioStats {
    return {
      chunksPlayed   : this.chunksPlayed,
      queueLength    : this.chunkQueue.length,
      isPlaying      : this.currentlyPlaying,
      totalProcessed : this.totalChunksProcessed,
      errorCount     : this.errorCount,
      activeBlobUrls : this.blobUrls.size,
    };
  }

  /** True while a chunk is actively playing (or queued to play). */
  isPlaying(): boolean {
    return this.currentlyPlaying;
  }

  /** Number of chunks still waiting in the queue. */
  getQueueLength(): number {
    return this.chunkQueue.length;
  }

  /** Drop the oldest queued chunk when the queue is full. */
  private _cleanupOldestChunk(): void {
    if ( this.chunkQueue.length > 0 ) {
      this.chunkQueue.shift();
      console.warn( "[SequentialAudioManager] Dropped oldest chunk due to queue size limit" );
    }
  }

  /** Revoke + forget the current audio element's blob URL. */
  private _cleanupCurrentAudio(): void {
    if ( this.currentAudio ) {
      const blobUrl = this.currentAudio.src;
      if ( this.blobUrls.has( blobUrl ) ) {
        this.revokeObjectURL( blobUrl );
        this.blobUrls.delete( blobUrl );
      }
      this.currentAudio = null;
    }
  }

  /** Revoke + forget every tracked blob URL. */
  private _cleanupAllBlobUrls(): void {
    this.blobUrls.forEach( ( url ) => { this.revokeObjectURL( url ); } );
    this.blobUrls.clear();
    if ( this.debug ) console.log( "[SequentialAudioManager] All blob URLs cleaned up" );
  }
  /* c8 ignore next */ // tsx phantom-branch artifact on the class-closing line (no executable code; c8 source-map view fabricates a branch here).
}
