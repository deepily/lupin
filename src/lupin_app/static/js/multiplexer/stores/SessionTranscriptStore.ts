/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Console tee — SessionTranscriptStore (row 27760534, plan §4, slice 6).
//
// Holds ONE watched seat's transcript for the multiplexer's console pane: the byte
// stream's position (epoch + next offset), a byte-bounded ring of display blocks, and the
// watch lifecycle on the queue socket.
//
// 🔴 THE LEGACY CLIENT HOLDS THE SAME BEHAVIOUR IN MODULE-LEVEL FUNCTIONS
// (`ccConsole*` in notifications.js), AND THE TWO SHARE NO CODE BY RULING. Parity is held by
// tests, not by an import. Keep the rules below and theirs saying the same thing.
//
// The rules, from plan §3:
//   · GAP: a chunk whose `offset` is not `last_next_offset` is DROPPED, and exactly one REST
//     repair reads forward from `last_next_offset` (`?since_offset=`). Rendering a chunk that
//     does not abut would splice the transcript silently.
//   · EPOCH: a chunk from a different `file_epoch`, or an `epoch_mismatch` / `rotated` state,
//     CLEARS the ring and re-reads the backlog. The old offsets named a file that is gone, so
//     there is no gap to repair, only a buffer to discard.
//   · WATCH: unwatch the old seat BEFORE watching the new one; a tab never holds two watches.
//   · AUTH: nothing is sent before `auth_success` (B4.5). The gate is the EventBus
//     `auth_success` event, not the transport's `authReady`, which is protected and
//     unreachable from here. Every `auth_success` re-sends the current watch, which is how a
//     reconnect resumes: the server forgets watchers when a socket closes.
//   · RING: bounded in UTF-8 bytes of block text (plan §5 C8), evicting oldest-first; the
//     newest block always stays. "Load earlier" (slice 7) is how evicted blocks come back.

import type { EventBus } from "../shared/EventBus";
import type { LupinEvent } from "../shared/types";

/** Narrowed ApiClient surface — this store only reads the backlog endpoint. */
export interface SessionTranscriptApiClient {
  get<T>( path: string ): Promise<T>;
}

/** One display block, as the server's mapper emits it. */
export interface TranscriptBlock {
  kind       : string;
  text?      : string;
  role?      : string;
  ts?        : string;
  truncated? : boolean;
}

export interface SessionTranscriptSnapshot {
  watchedCcSessionId : string | null;
  fileEpoch          : string | null;
  lastNextOffset     : number | null;
  /** The file offset of the oldest block held, for "load earlier". Null until a read lands. */
  earliestOffset     : number | null;
  blocks             : ReadonlyArray<TranscriptBlock>;
  ringBytes          : number;
  evictedBlocks      : number;
  /** The last `cc_transcript_state` for the watched seat: live, ended, … or null. */
  streamState        : string | null;
  repairing          : boolean;
}

export interface SessionTranscriptStore {
  /** Watch a seat by its FULL stable id. Unwatches the previous seat first. */
  open( ccSessionId: string ): Promise<void>;
  /** Unwatch and clear. Leaves zero live watches. */
  close(): void;
  snapshot(): SessionTranscriptSnapshot;
  /** Test/cleanup helper: detach EventBus listeners. */
  destroy(): void;
}

export interface SessionTranscriptStoreOptions {
  bus           : EventBus;
  api           : SessionTranscriptApiClient;
  /** The queue transport's public `send( envelope )`. */
  send          : ( envelope: unknown ) => void;
  ringMaxBytes? : number;
  endpoint?     : string;
  logFn?        : ( message: string ) => void;
}

/** Plan §5's provisional default, pending Open sub-question 5. One constant, one change. */
export const SESSION_TRANSCRIPT_RING_MAX_BYTES = 256 * 1024;
export const SESSION_TRANSCRIPT_ENDPOINT       = "/api/cc-transcript";

interface BacklogBody {
  file_epoch?  : string | null;
  offset?      : number;
  next_offset? : number;
  blocks?      : unknown;
}

interface AppendPayload {
  cc_session_id? : unknown;
  file_epoch?    : unknown;
  offset?        : unknown;
  next_offset?   : unknown;
  blocks?        : unknown;
}

interface StatePayload {
  cc_session_id? : unknown;
  file_epoch?    : unknown;
  state?         : unknown;
}

const ENCODER = new TextEncoder();

/**
 * A block's size for the ring budget: the UTF-8 byte length of its text (plan §5 C8).
 *
 * Ensures:
 *   - a non-negative integer; a block with no text is 0
 */
export function transcriptBlockBytes( block: TranscriptBlock ): number {
  return ENCODER.encode( block.text ?? "" ).length;
}

function isFrame( value: unknown ): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray( value );
}

function blocksOf( value: unknown ): TranscriptBlock[] {
  // An EMPTY block is content, and dropping one is indistinguishable from a block that never
  // arrived — so only non-objects are filtered, never empties.
  return Array.isArray( value ) ? value.filter( isFrame ) as unknown as TranscriptBlock[] : [];
}

class SessionTranscriptStoreImpl implements SessionTranscriptStore {
  private readonly bus          : EventBus;
  private readonly api          : SessionTranscriptApiClient;
  private readonly sendFn       : ( envelope: unknown ) => void;
  private readonly ringMaxBytes : number;
  private readonly endpoint     : string;
  private readonly logFn        : ( message: string ) => void;
  private readonly unsubscribers: Array<() => void> = [];

  private authed         = false;
  private watched        : string | null = null;
  private fileEpoch      : string | null = null;
  private lastNextOffset : number | null = null;
  private earliestOffset : number | null = null;
  private blocks         : TranscriptBlock[] = [];
  private ringBytes      = 0;
  private evictedBlocks  = 0;
  private streamState    : string | null = null;
  private repairing      = false;
  // Bumped on every seat change or clear, so a read that resolves after the world moved
  // on is recognised as stale and discarded rather than spliced into the wrong stream.
  private generation     = 0;

  constructor( opts: SessionTranscriptStoreOptions ) {
    this.bus          = opts.bus;
    this.api          = opts.api;
    this.sendFn       = opts.send;
    this.ringMaxBytes = opts.ringMaxBytes ?? SESSION_TRANSCRIPT_RING_MAX_BYTES;
    this.endpoint     = opts.endpoint ?? SESSION_TRANSCRIPT_ENDPOINT;
    /* c8 ignore next */ // production-default fallback: a silent log; tests inject a collector.
    this.logFn        = opts.logFn ?? ( () => { /* silent by default */ } );

    this.unsubscribers.push(
      this.bus.on( "auth_success",         () => this.onAuthSuccess() ),
      this.bus.on<AppendPayload>( "cc_transcript_append", ( e ) => this.onAppend( e ) ),
      this.bus.on<StatePayload>(  "cc_transcript_state",  ( e ) => this.onState( e ) ),
    );
  }

  // ── public surface ───────────────────────────────────────────────────────

  async open( ccSessionId: string ): Promise<void> {
    if ( !ccSessionId ) return;
    if ( ccSessionId === this.watched ) return;   // already there: no unwatch/watch churn

    if ( this.watched ) this.trySend( { type: "cc_transcript_unwatch", cc_session_id: this.watched } );
    this.resetStream();
    this.watched = ccSessionId;
    this.changed();

    await this.readBacklog();
  }

  close(): void {
    if ( this.watched ) this.trySend( { type: "cc_transcript_unwatch", cc_session_id: this.watched } );
    this.resetStream();
    this.watched = null;
    this.changed();
  }

  snapshot(): SessionTranscriptSnapshot {
    return {
      watchedCcSessionId : this.watched,
      fileEpoch          : this.fileEpoch,
      lastNextOffset     : this.lastNextOffset,
      earliestOffset     : this.earliestOffset,
      blocks             : this.blocks.slice(),
      ringBytes          : this.ringBytes,
      evictedBlocks      : this.evictedBlocks,
      streamState        : this.streamState,
      repairing          : this.repairing,
    };
  }

  destroy(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
  }

  // ── the socket ───────────────────────────────────────────────────────────

  private onAuthSuccess(): void {
    this.authed = true;
    // A (re)connect: the server holds no watch for this socket yet. Resume from where we
    // are, or — before the first read has landed — let the backlog read send it.
    if ( this.watched && this.lastNextOffset !== null ) this.sendWatch();
  }

  // Callers send only once a read has set lastNextOffset: readBacklog sets it first, and
  // onAuthSuccess checks it. So it is never null here, and no fallback is written for it.
  private sendWatch(): void {
    this.trySend( {
      type          : "cc_transcript_watch",
      cc_session_id : this.watched,
      from_offset   : this.lastNextOffset,
      file_epoch    : this.fileEpoch,
    } );
  }

  /**
   * Send, or do nothing — never throw into a caller (B4.5).
   *
   * Before `auth_success` the envelope is NOT sent: the watch that matters is re-sent from
   * `onAuthSuccess`, so dropping it here loses nothing. After auth, a transport that throws
   * (channel stopped mid-reconnect) is logged, and the next `auth_success` re-sends.
   */
  private trySend( envelope: Record<string, unknown> ): void {
    if ( !this.authed ) return;
    try {
      this.sendFn( envelope );
    } catch ( error ) {
      this.logFn( `SessionTranscriptStore: send ${ String( envelope.type ) } failed: ${ String( error ) }` );
    }
  }

  // ── frames ───────────────────────────────────────────────────────────────

  private onAppend( e: LupinEvent<AppendPayload> ): void {
    const chunk = e.payload;
    if ( !isFrame( chunk ) ) return;
    if ( !this.watched || chunk.cc_session_id !== this.watched ) return;
    if ( this.repairing ) return;   // the repair read will cover this range; the next chunk re-checks

    const epoch = typeof chunk.file_epoch === "string" ? chunk.file_epoch : null;
    if ( this.fileEpoch !== null && epoch !== this.fileEpoch ) {
      this.clearAndReread();
      return;
    }
    if ( this.fileEpoch === null ) this.fileEpoch = epoch;

    const offset = typeof chunk.offset === "number" ? chunk.offset : null;
    if ( this.lastNextOffset !== null && offset !== this.lastNextOffset ) {
      void this.repairFrom( this.lastNextOffset );
      return;
    }

    if ( this.earliestOffset === null && offset !== null ) this.earliestOffset = offset;
    this.appendBlocks( blocksOf( chunk.blocks ) );
    if ( typeof chunk.next_offset === "number" ) this.lastNextOffset = chunk.next_offset;
    this.changed();
  }

  private onState( e: LupinEvent<StatePayload> ): void {
    const frame = e.payload;
    if ( !isFrame( frame ) ) return;
    if ( !this.watched || frame.cc_session_id !== this.watched ) return;

    const state = typeof frame.state === "string" ? frame.state : null;
    this.streamState = state;
    if ( state === "epoch_mismatch" || state === "rotated" ) {
      // Never a continuation: a silent rebase would hand us a new file labelled as our own.
      this.clearAndReread();
      return;
    }
    this.changed();
  }

  // ── reads ────────────────────────────────────────────────────────────────

  private path( query: string ): string {
    return `${ this.endpoint }/${ encodeURIComponent( this.watched as string ) }${ query }`;
  }

  /** Open, or re-open after a clear: the ruled backlog tail (no direction = Q6's tail). */
  private async readBacklog(): Promise<void> {
    const generation = this.generation;
    let body: BacklogBody;
    try {
      body = await this.api.get<BacklogBody>( this.path( "" ) );
    } catch ( error ) {
      this.logFn( `SessionTranscriptStore: backlog read failed: ${ String( error ) }` );
      return;
    }
    if ( generation !== this.generation ) return;   // the seat changed while we waited

    this.fileEpoch      = typeof body.file_epoch === "string" ? body.file_epoch : null;
    this.earliestOffset = typeof body.offset === "number" ? body.offset : 0;
    this.appendBlocks( blocksOf( body.blocks ) );
    this.lastNextOffset = typeof body.next_offset === "number" ? body.next_offset : 0;
    this.changed();
    this.sendWatch();
  }

  /** The gap rule's repair: exactly one forward read from where we are. */
  private async repairFrom( sinceOffset: number ): Promise<void> {
    const generation = this.generation;
    this.repairing   = true;
    this.changed();
    try {
      const body = await this.api.get<BacklogBody>( this.path( `?since_offset=${ sinceOffset }` ) );
      if ( generation !== this.generation ) return;
      if ( typeof body.file_epoch === "string" && this.fileEpoch !== null && body.file_epoch !== this.fileEpoch ) {
        this.repairing = false;
        this.clearAndReread();
        return;
      }
      this.appendBlocks( blocksOf( body.blocks ) );
      if ( typeof body.next_offset === "number" ) this.lastNextOffset = body.next_offset;
    } catch ( error ) {
      this.logFn( `SessionTranscriptStore: gap repair from ${ sinceOffset } failed: ${ String( error ) }` );
    } finally {
      if ( generation === this.generation ) {
        this.repairing = false;
        this.changed();
      }
    }
  }

  // ── buffer ───────────────────────────────────────────────────────────────

  private appendBlocks( blocks: TranscriptBlock[] ): void {
    for ( const block of blocks ) {
      this.blocks.push( block );
      this.ringBytes += transcriptBlockBytes( block );
    }
    // Oldest-first, and the NEWEST block always stays: evicting what just arrived would drop
    // live output the reader has not seen, and "load earlier" pages backwards so it could not
    // bring it back.
    while ( this.ringBytes > this.ringMaxBytes && this.blocks.length > 1 ) {
      const oldest = this.blocks.shift() as TranscriptBlock;
      this.ringBytes -= transcriptBlockBytes( oldest );
      this.evictedBlocks += 1;
      this.earliestOffset = null;   // no longer known: the held window no longer starts at a read boundary
    }
  }

  private resetStream(): void {
    this.generation    += 1;
    this.fileEpoch      = null;
    this.lastNextOffset = null;
    this.earliestOffset = null;
    this.blocks         = [];
    this.ringBytes      = 0;
    this.evictedBlocks  = 0;
    this.streamState    = null;
    this.repairing      = false;
  }

  private clearAndReread(): void {
    this.resetStream();
    this.changed();
    void this.readBacklog();
  }

  private changed(): void {
    this.bus.emit( {
      type    : "store_session_transcript_changed",
      payload : { ccSessionId: this.watched },
      source  : "SessionTranscriptStore",
      ts      : Date.now(),
    } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line.
export function createSessionTranscriptStore( opts: SessionTranscriptStoreOptions ): SessionTranscriptStore {
  return new SessionTranscriptStoreImpl( opts );
}
