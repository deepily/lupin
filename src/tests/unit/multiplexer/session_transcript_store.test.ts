// SessionTranscriptStore — row 27760534, plan §4, slice 6. ACs B4.1, B4.2, B4.4 (store half),
// B4.5, plus the byte-bounded ring (§5 C8). 100% lines/branches/functions per the multiplexer
// coverage mandate.
//
// The legacy twin of these rules lives in notifications.js (`ccConsole*`) and is asserted by
// src/tests/unit/notifications_js/the_console_*.test.ts. The two share no code by ruling; if a
// rule here changes, its legacy twin must change with it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSessionTranscriptStore,
  transcriptBlockBytes,
  SESSION_TRANSCRIPT_RING_MAX_BYTES,
  type SessionTranscriptStore,
  type TranscriptBlock,
} from "../../../lupin_app/static/js/multiplexer/stores/SessionTranscriptStore";
import type { EventBus } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { LupinEventType } from "../../../lupin_app/static/js/multiplexer/shared/types";

const SEAT   = "4cecf18a-66f7-442f-98f3-98d61d680654";
const OTHER  = "449359bc-c735-4970-8fc0-e83b635c8548";
const EPOCH  = "57238c9d-c227-469e-b707-13b7752a7399";
const EPOCH2 = "a1b2c3d4-0000-4000-8000-000000000002";

type Body = { file_epoch?: string | null; offset?: number; next_offset?: number; blocks?: unknown };

interface Harness {
  bus     : EventBus;
  store   : SessionTranscriptStore;
  sent    : Array<Record<string, unknown>>;
  gets    : string[];
  logs    : string[];
  changes : number;
  respond : ( path: string ) => Body | Error | Promise<Body>;
}

function make( opts: { ringMaxBytes?: number; sendThrows?: boolean } = {} ): Harness {
  const bus = createEventBusForTesting();
  const h   = {
    bus, sent : [], gets : [], logs : [], changes : 0,
    respond : ( _p: string ): Body | Error | Promise<Body> => ( { file_epoch : EPOCH, offset : 0, next_offset : 100, blocks : [ { kind : "text", text : "backlog" } ] } ),
  } as unknown as Harness;
  bus.on( "store_session_transcript_changed", () => { h.changes += 1; } );
  h.store = createSessionTranscriptStore( {
    bus,
    api  : { get : async <T>( path: string ): Promise<T> => {
      h.gets.push( path );
      const r = await h.respond( path );
      if ( r instanceof Error ) throw r;
      return r as unknown as T;
    } },
    send : ( env ) => {
      if ( opts.sendThrows ) throw new Error( "channel is not started" );
      h.sent.push( env as Record<string, unknown> );
    },
    ringMaxBytes : opts.ringMaxBytes,
    logFn        : ( m ) => h.logs.push( m ),
  } );
  return h;
}

function emit( bus: EventBus, type: string, payload: unknown ): void {
  bus.emit( { type : type as LupinEventType, payload, source : "test", ts : 0 } );
}
const auth   = ( h: Harness ) => emit( h.bus, "auth_success", {} );
const append = ( h: Harness, over: Record<string, unknown> = {} ) => emit( h.bus, "cc_transcript_append", {
  cc_session_id : SEAT, file_epoch : EPOCH, offset : 100, next_offset : 200,
  blocks : [ { kind : "text", text : "live" } ], ...over,
} );
const state  = ( h: Harness, over: Record<string, unknown> = {} ) => emit( h.bus, "cc_transcript_state", {
  cc_session_id : SEAT, file_epoch : EPOCH, state : "live", ...over,
} );
const flush  = () => new Promise( ( r ) => setImmediate( r ) );
const texts  = ( h: Harness ) => h.store.snapshot().blocks.map( b => b.text );

async function openedAndAuthed( opts = {} ): Promise<Harness> {
  const h = make( opts );
  auth( h );
  await h.store.open( SEAT );
  return h;
}

// ── open, watch, auth ──────────────────────────────────────────────────────

test( "open reads the backlog TAIL (no direction) and then watches from its next_offset", async () => {
  const h = await openedAndAuthed();
  assert.deepEqual( h.gets, [ `/api/cc-transcript/${ SEAT }` ] );
  assert.deepEqual( h.sent, [ { type : "cc_transcript_watch", cc_session_id : SEAT, from_offset : 100, file_epoch : EPOCH } ] );
  assert.deepEqual( texts( h ), [ "backlog" ] );
  const s = h.store.snapshot();
  assert.equal( s.fileEpoch, EPOCH );
  assert.equal( s.lastNextOffset, 100 );
  assert.equal( s.earliestOffset, 0 );
} );

test( "B4.5: before auth_success nothing reaches the socket, and nothing throws", async () => {
  const h = make();
  await h.store.open( SEAT );
  assert.deepEqual( h.sent, [], "the watch was withheld" );
  auth( h );
  assert.deepEqual( h.sent, [ { type : "cc_transcript_watch", cc_session_id : SEAT, from_offset : 100, file_epoch : EPOCH } ],
    "auth_success sends the withheld watch, from where the backlog left off" );
} );

test( "every later auth_success (a reconnect) re-sends the watch from the current offset", async () => {
  const h = await openedAndAuthed();
  append( h );
  h.sent.length = 0;
  auth( h );
  assert.deepEqual( h.sent, [ { type : "cc_transcript_watch", cc_session_id : SEAT, from_offset : 200, file_epoch : EPOCH } ] );
} );

test( "auth_success before any read has landed sends nothing (the read will send it)", () => {
  const h = make();
  auth( h );
  void h.store.open( SEAT );   // read in flight
  auth( h );
  assert.deepEqual( h.sent, [] );
} );

test( "a transport that throws is logged, never raised to the caller", async () => {
  const h = await openedAndAuthed( { sendThrows : true } );
  assert.equal( h.sent.length, 0 );
  assert.ok( h.logs.some( m => m.includes( "send cc_transcript_watch failed" ) ) );
} );

test( "open with an empty id does nothing", async () => {
  const h = make();
  await h.store.open( "" );
  assert.deepEqual( h.gets, [] );
  assert.equal( h.store.snapshot().watchedCcSessionId, null );
} );

// ── B4.4: the watch lifecycle ──────────────────────────────────────────────

test( "B4.4: switching seats UNWATCHES the old one BEFORE watching the new one", async () => {
  const h = await openedAndAuthed();
  h.sent.length = 0;
  await h.store.open( OTHER );
  assert.deepEqual( h.sent.map( e => [ e.type, e.cc_session_id ] ), [
    [ "cc_transcript_unwatch", SEAT ],
    [ "cc_transcript_watch",   OTHER ],
  ] );
} );

test( "re-opening the SAME seat is a no-op, not an unwatch-rewatch churn", async () => {
  const h = await openedAndAuthed();
  h.sent.length = 0;
  await h.store.open( SEAT );
  assert.deepEqual( h.sent, [] );
  assert.equal( h.gets.length, 1 );
} );

test( "close leaves ZERO live watches and an empty buffer", async () => {
  const h = await openedAndAuthed();
  h.sent.length = 0;
  h.store.close();
  assert.deepEqual( h.sent, [ { type : "cc_transcript_unwatch", cc_session_id : SEAT } ] );
  const s = h.store.snapshot();
  assert.equal( s.watchedCcSessionId, null );
  assert.equal( s.blocks.length, 0 );
  h.sent.length = 0;
  h.store.close();
  assert.deepEqual( h.sent, [], "closing with nothing watched sends nothing" );
} );

test( "a backlog read that resolves after the seat changed is discarded, not spliced in", async () => {
  const h = make();
  auth( h );
  let release!: ( b: Body ) => void;
  h.respond = ( p ) => p.includes( SEAT ) ? new Promise<Body>( r => { release = r; } )
                                          : { file_epoch : EPOCH2, offset : 0, next_offset : 5, blocks : [ { kind : "text", text : "other" } ] };
  const first = h.store.open( SEAT );
  await h.store.open( OTHER );
  release( { file_epoch : EPOCH, offset : 0, next_offset : 100, blocks : [ { kind : "text", text : "STALE" } ] } );
  await first;
  assert.deepEqual( texts( h ), [ "other" ] );
  assert.equal( h.store.snapshot().fileEpoch, EPOCH2 );
} );

test( "a failed backlog read is logged and leaves the console empty, not broken", async () => {
  const h = make();
  auth( h );
  h.respond = () => new Error( "503" );
  await h.store.open( SEAT );
  assert.equal( h.store.snapshot().blocks.length, 0 );
  assert.deepEqual( h.sent, [], "no watch without a position to watch from" );
  assert.ok( h.logs.some( m => m.includes( "backlog read failed" ) ) );
} );

test( "a backlog body missing every field is read as an empty stream at offset 0", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( {} );
  await h.store.open( SEAT );
  const s = h.store.snapshot();
  assert.equal( s.fileEpoch, null );
  assert.equal( s.earliestOffset, 0 );
  assert.equal( s.lastNextOffset, 0 );
  assert.deepEqual( h.sent, [ { type : "cc_transcript_watch", cc_session_id : SEAT, from_offset : 0, file_epoch : null } ] );
} );

// ── B4.1: the gap rule ─────────────────────────────────────────────────────

test( "a contiguous chunk is appended and advances the offset", async () => {
  const h = await openedAndAuthed();
  append( h );
  assert.deepEqual( texts( h ), [ "backlog", "live" ] );
  assert.equal( h.store.snapshot().lastNextOffset, 200 );
} );

test( "B4.1: a GAPPED chunk is dropped and exactly one REST repair reads forward from last_next_offset", async () => {
  const h = await openedAndAuthed();
  h.respond = () => ( { file_epoch : EPOCH, offset : 100, next_offset : 300, blocks : [ { kind : "text", text : "repaired" } ] } );
  append( h, { offset : 250, next_offset : 300, blocks : [ { kind : "text", text : "DROPPED" } ] } );
  append( h, { offset : 300, next_offset : 350, blocks : [ { kind : "text", text : "DURING-REPAIR" } ] } );
  await flush();
  assert.deepEqual( h.gets.slice( 1 ), [ `/api/cc-transcript/${ SEAT }?since_offset=100` ], "exactly one repair" );
  assert.deepEqual( texts( h ), [ "backlog", "repaired" ], "neither the gapped chunk nor one arriving mid-repair rendered" );
  assert.equal( h.store.snapshot().lastNextOffset, 300 );
  assert.equal( h.store.snapshot().repairing, false );
} );

test( "a failed repair is logged and clears the repairing flag, so the next chunk can try again", async () => {
  const h = await openedAndAuthed();
  h.respond = () => new Error( "timeout" );
  append( h, { offset : 999 } );
  await flush();
  assert.ok( h.logs.some( m => m.includes( "gap repair from 100 failed" ) ) );
  assert.equal( h.store.snapshot().repairing, false );
} );

test( "a repair that finds a new epoch clears instead of splicing", async () => {
  const h = await openedAndAuthed();
  h.respond = ( p ) => p.includes( "since_offset" )
    ? { file_epoch : EPOCH2, offset : 0, next_offset : 10, blocks : [ { kind : "text", text : "WRONG-FILE" } ] }
    : { file_epoch : EPOCH2, offset : 0, next_offset : 10, blocks : [ { kind : "text", text : "new file" } ] };
  append( h, { offset : 999 } );
  await flush(); await flush();
  assert.deepEqual( texts( h ), [ "new file" ] );
  assert.equal( h.store.snapshot().fileEpoch, EPOCH2 );
} );

test( "a repair body with no epoch, blocks or offset appends nothing and keeps the offset", async () => {
  const h = await openedAndAuthed();
  h.respond = () => ( {} );
  append( h, { offset : 999 } );
  await flush();
  assert.deepEqual( texts( h ), [ "backlog" ] );
  assert.equal( h.store.snapshot().lastNextOffset, 100 );
} );

test( "a repair that resolves after the seat changed is discarded", async () => {
  const h = await openedAndAuthed();
  let release!: ( b: Body ) => void;
  h.respond = ( p ) => p.includes( "since_offset" ) ? new Promise<Body>( r => { release = r; } )
                                                    : { file_epoch : EPOCH2, offset : 0, next_offset : 5, blocks : [] };
  append( h, { offset : 999 } );
  await h.store.open( OTHER );
  release( { file_epoch : EPOCH, offset : 100, next_offset : 300, blocks : [ { kind : "text", text : "STALE" } ] } );
  await flush();
  assert.deepEqual( texts( h ), [] );
  assert.equal( h.store.snapshot().watchedCcSessionId, OTHER );
} );

test( "a repair that fails after the seat changed does not touch the new seat's state", async () => {
  const h = await openedAndAuthed();
  let fail!: ( e: Error ) => void;
  h.respond = ( p ) => p.includes( "since_offset" ) ? new Promise<Body>( ( _r, j ) => { fail = j; } )
                                                    : { file_epoch : EPOCH2, offset : 0, next_offset : 5, blocks : [] };
  append( h, { offset : 999 } );
  await h.store.open( OTHER );
  fail( new Error( "late" ) );
  await flush();
  assert.equal( h.store.snapshot().repairing, false );
} );

// ── B4.2: epochs ───────────────────────────────────────────────────────────

test( "B4.2: a chunk from a new epoch CLEARS the buffer and re-reads the backlog", async () => {
  const h = await openedAndAuthed();
  h.respond = () => ( { file_epoch : EPOCH2, offset : 0, next_offset : 40, blocks : [ { kind : "text", text : "fresh" } ] } );
  append( h, { file_epoch : EPOCH2, offset : 0, blocks : [ { kind : "text", text : "NOT-RENDERED" } ] } );
  await flush();
  assert.deepEqual( texts( h ), [ "fresh" ], "no pre-change block survives, and the triggering chunk did not render" );
  assert.equal( h.store.snapshot().fileEpoch, EPOCH2 );
  assert.equal( h.gets.at( -1 ), `/api/cc-transcript/${ SEAT }`, "re-read the TAIL, not a forward read from the old offset" );
} );

test( "B4.2: epoch_mismatch clears and re-reads — never a continuation", async () => {
  const h = await openedAndAuthed();
  h.respond = () => ( { file_epoch : EPOCH2, offset : 0, next_offset : 40, blocks : [ { kind : "text", text : "fresh" } ] } );
  state( h, { state : "epoch_mismatch", file_epoch : EPOCH2 } );
  await flush();
  assert.deepEqual( texts( h ), [ "fresh" ] );
} );

test( "a rotation behaves like an epoch mismatch", async () => {
  const h = await openedAndAuthed();
  h.respond = () => ( { file_epoch : EPOCH2, offset : 0, next_offset : 40, blocks : [] } );
  state( h, { state : "rotated" } );
  await flush();
  assert.deepEqual( texts( h ), [] );
  assert.equal( h.store.snapshot().fileEpoch, EPOCH2 );
} );

test( "live and ended are recorded without disturbing the buffer", async () => {
  const h = await openedAndAuthed();
  state( h, { state : "live" } );
  assert.equal( h.store.snapshot().streamState, "live" );
  state( h, { state : "ended" } );
  assert.equal( h.store.snapshot().streamState, "ended" );
  assert.deepEqual( texts( h ), [ "backlog" ] );
  state( h, { state : 7 } );
  assert.equal( h.store.snapshot().streamState, null, "a non-string state is recorded as unknown" );
} );

// Row a68b10a3: the server answers a watch on a missing seat with state `refused` + a `reason`.
test( "a refused frame records its reason; the next frame without one clears it", async () => {
  const h = await openedAndAuthed();
  state( h, { state : "refused", reason : "not_found" } );
  assert.equal( h.store.snapshot().streamState,  "refused" );
  assert.equal( h.store.snapshot().streamReason, "not_found" );
  state( h, { state : "live" } );
  assert.equal( h.store.snapshot().streamReason, null, "a stale reason outlived its frame" );
  for ( const reason of [ 7, "", null ] ) {
    state( h, { state : "refused", reason } );
    assert.equal( h.store.snapshot().streamReason, null, `reason ${ JSON.stringify( reason ) } is recorded as none` );
  }
} );

test( "a refused reason does not follow the reader to the next seat, or survive a close", async () => {
  const h = await openedAndAuthed();
  state( h, { state : "refused", reason : "not_found" } );
  await h.store.open( OTHER );
  assert.equal( h.store.snapshot().streamState,  null );
  assert.equal( h.store.snapshot().streamReason, null, "the last seat's refusal reason leaked onto the new seat" );
  h.store.close();
  assert.equal( h.store.snapshot().streamReason, null );
} );

test( "the first chunk of a watch with no epoch yet learns it from the frame", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { offset : 0, next_offset : 100, blocks : [] } );   // backlog with no epoch
  await h.store.open( SEAT );
  append( h );
  assert.equal( h.store.snapshot().fileEpoch, EPOCH );
  assert.deepEqual( texts( h ), [ "live" ] );
} );

// ── foreign and malformed traffic ──────────────────────────────────────────

test( "frames for another seat, with no console open, or malformed, are ignored", async () => {
  const h = make();
  append( h );
  state( h );
  assert.equal( h.changes, 0, "no console open" );
  auth( h );
  await h.store.open( SEAT );
  const before = texts( h );
  append( h, { cc_session_id : OTHER } );
  state( h, { cc_session_id : OTHER, state : "rotated" } );
  emit( h.bus, "cc_transcript_append", [] );
  emit( h.bus, "cc_transcript_append", null );
  emit( h.bus, "cc_transcript_state", "x" );
  assert.deepEqual( texts( h ), before );
} );

test( "a chunk with a non-numeric offset or next_offset is treated conservatively", async () => {
  const h = await openedAndAuthed();
  append( h, { offset : "100" } );
  await flush();
  assert.ok( h.gets.some( p => p.includes( "since_offset=100" ) ), "a non-number offset cannot abut, so it is a gap" );
} );

test( "a chunk without next_offset appends but keeps the offset where it was", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, blocks : [] } );
  await h.store.open( SEAT );
  append( h, { offset : 0, next_offset : undefined } );
  assert.deepEqual( texts( h ), [ "live" ] );
  assert.equal( h.store.snapshot().lastNextOffset, 0 );
} );

test( "blocks that are not objects are skipped; EMPTY blocks are kept", async () => {
  const h = await openedAndAuthed();
  append( h, { blocks : [ null, "x", [ 1 ], { kind : "thinking", text : "" }, { kind : "text", text : "ok" } ] } );
  assert.deepEqual( h.store.snapshot().blocks.map( b => b.kind ), [ "text", "thinking", "text" ] );
  append( h, { offset : 200, next_offset : 210, blocks : "not-a-list" } );
  assert.equal( h.store.snapshot().blocks.length, 3 );
} );

test( "a chunk with no epoch on a stream that has one is a new epoch, not a continuation", async () => {
  const h = await openedAndAuthed();
  h.respond = () => ( { file_epoch : EPOCH2, offset : 0, next_offset : 1, blocks : [] } );
  append( h, { file_epoch : undefined } );
  await flush();
  assert.equal( h.store.snapshot().fileEpoch, EPOCH2 );
} );

// ── the ring ───────────────────────────────────────────────────────────────

test( "the size is UTF-8 bytes, not UTF-16 code units", () => {
  assert.equal( transcriptBlockBytes( { kind : "text", text : "abc" } ), 3 );
  assert.equal( transcriptBlockBytes( { kind : "text", text : "é" } ),   2 );
  assert.equal( transcriptBlockBytes( { kind : "text", text : "🦉" } ),  4 );
  assert.equal( transcriptBlockBytes( { kind : "thinking" } as TranscriptBlock ), 0 );
  assert.equal( SESSION_TRANSCRIPT_RING_MAX_BYTES, 256 * 1024 );
} );

test( "the ring evicts OLDEST-first, never exceeds its cap, and keeps the newest", async () => {
  const h = make( { ringMaxBytes : 100 } );
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 0, next_offset : 1, blocks : [ { kind : "text", text : "a".repeat( 40 ) } ] } );
  await h.store.open( SEAT );
  let off = 1;
  for ( const tag of [ "b", "c", "d" ] ) {
    append( h, { offset : off, next_offset : off + 1, blocks : [ { kind : "text", text : tag.repeat( 40 ) } ] } );
    off += 1;
  }
  const s = h.store.snapshot();
  assert.ok( s.ringBytes <= 100 );
  assert.deepEqual( s.blocks.map( b => b.text?.[ 0 ] ), [ "c", "d" ] );
  assert.equal( s.evictedBlocks, 2 );
  assert.equal( s.earliestOffset, 2, "a whole segment is evicted, so the oldest held offset stays known" );
  assert.equal( s.canLoadEarlier, true );

  append( h, { offset : off, next_offset : off + 1, blocks : [ { kind : "text", text : "z".repeat( 500 ) } ] } );
  assert.deepEqual( h.store.snapshot().blocks.map( b => b.text?.[ 0 ] ), [ "z" ], "the newest stays even alone over budget" );
} );

test( "a chunk before any read has landed is ignored — the read will cover it", async () => {
  const h = make();
  auth( h );
  h.respond = () => new Error( "down" );
  await h.store.open( SEAT );
  append( h, { offset : 500, next_offset : 600 } );
  const s = h.store.snapshot();
  assert.deepEqual( s.blocks, [] );
  assert.equal( s.earliestOffset, null );
  assert.equal( s.canLoadEarlier, false );
} );

test( "a chunk arriving while a post-clear re-read is in flight is not duplicated", async () => {
  const h = await openedAndAuthed();
  let release!: ( b: Body ) => void;
  h.respond = () => new Promise<Body>( ( r ) => { release = r; } );
  state( h, { state : "epoch_mismatch", file_epoch : EPOCH2 } );   // clear + re-read (pending)
  append( h, { file_epoch : EPOCH2, offset : 0, next_offset : 50, blocks : [ { kind : "text", text : "dup" } ] } );
  release( { file_epoch : EPOCH2, offset : 0, next_offset : 50, blocks : [ { kind : "text", text : "dup" } ] } );
  await flush();
  assert.deepEqual( texts( h ), [ "dup" ], "the re-read supplied it once; the early chunk was not also spliced" );
} );

// ── load earlier (B4.3b, store half) ───────────────────────────────────────

test( "B4.3b: load earlier pages BACKWARDS from the oldest held offset and prepends", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [ { kind : "text", text : "tail" } ] } );
  await h.store.open( SEAT );
  assert.equal( h.store.snapshot().canLoadEarlier, true );

  h.respond = () => ( { file_epoch : EPOCH, offset : 100, next_offset : 300, blocks : [ { kind : "text", text : "older" } ] } );
  await h.store.loadEarlier();
  assert.ok( h.gets.at( -1 )!.endsWith( `?before_offset=300&max_bytes=${ 64 * 1024 }` ), h.gets.at( -1 ) );
  assert.deepEqual( texts( h ), [ "older", "tail" ] );
  assert.equal( h.store.snapshot().earliestOffset, 100 );

  h.respond = () => ( { file_epoch : EPOCH, offset : 0, next_offset : 100, blocks : [ { kind : "text", text : "first" } ] } );
  await h.store.loadEarlier();
  const s = h.store.snapshot();
  assert.deepEqual( texts( h ), [ "first", "older", "tail" ] );
  assert.equal( s.canLoadEarlier, false, "offset 0 is the start of the epoch" );
  assert.equal( s.loadingEarlier, false );

  const n = h.gets.length;
  await h.store.loadEarlier();
  assert.equal( h.gets.length, n, "at the start of the epoch it does not read again" );
} );

test( "B4.3b: with the ring full, an EVICTED block is reachable again through load earlier", async () => {
  const h = make( { ringMaxBytes : 50 } );
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 0, next_offset : 40, blocks : [ { kind : "text", text : "A".repeat( 40 ) } ] } );
  await h.store.open( SEAT );
  append( h, { offset : 40, next_offset : 80, blocks : [ { kind : "text", text : "B".repeat( 40 ) } ] } );
  assert.deepEqual( texts( h ).map( t => t?.[ 0 ] ), [ "B" ], "A was evicted" );

  h.respond = () => ( { file_epoch : EPOCH, offset : 0, next_offset : 40, blocks : [ { kind : "text", text : "A".repeat( 40 ) } ] } );
  await h.store.loadEarlier();
  assert.ok( h.gets.at( -1 )!.includes( "before_offset=40" ) );
  assert.deepEqual( texts( h ).map( t => t?.[ 0 ] ), [ "A", "B" ], "prepend does not evict the page just fetched" );
} );

test( "load earlier ignores a second call while one is in flight", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [] } );
  await h.store.open( SEAT );
  let release!: ( b: Body ) => void;
  h.respond = () => new Promise<Body>( ( r ) => { release = r; } );
  const first = h.store.loadEarlier();
  await flush();
  assert.equal( h.store.snapshot().loadingEarlier, true );
  const n = h.gets.length;
  await h.store.loadEarlier();
  assert.equal( h.gets.length, n );
  release( { file_epoch : EPOCH, offset : 200, next_offset : 300, blocks : [] } );
  await first;
  assert.equal( h.store.snapshot().earliestOffset, 200 );
} );

test( "load earlier does nothing before any read, or with no seat", async () => {
  const h = make();
  await h.store.loadEarlier();
  assert.deepEqual( h.gets, [] );
} );

test( "a page that does not start BEFORE the asked offset is dropped, never looped on", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [ { kind : "text", text : "tail" } ] } );
  await h.store.open( SEAT );
  h.respond = () => ( { file_epoch : EPOCH, blocks : [ { kind : "text", text : "junk" } ] } );   // no offset
  await h.store.loadEarlier();
  assert.deepEqual( texts( h ), [ "tail" ] );
  assert.equal( h.store.snapshot().earliestOffset, 300 );
} );

test( "a page from a different epoch clears and re-reads instead of prepending", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [ { kind : "text", text : "tail" } ] } );
  await h.store.open( SEAT );
  h.respond = ( p ) => p.includes( "before_offset" )
    ? { file_epoch : EPOCH2, offset : 0, next_offset : 300, blocks : [ { kind : "text", text : "wrong" } ] }
    : { file_epoch : EPOCH2, offset : 0, next_offset : 10, blocks : [ { kind : "text", text : "new" } ] };
  await h.store.loadEarlier();
  await flush();
  assert.deepEqual( texts( h ), [ "new" ] );
  assert.equal( h.store.snapshot().fileEpoch, EPOCH2 );
  assert.equal( h.store.snapshot().loadingEarlier, false );
} );

test( "a failed page is logged and clears the loading flag", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [] } );
  await h.store.open( SEAT );
  h.respond = () => new Error( "503" );
  await h.store.loadEarlier();
  assert.ok( h.logs.some( m => m.includes( "load earlier before 300 failed" ) ) );
  assert.equal( h.store.snapshot().loadingEarlier, false );
} );

test( "a page that resolves after the seat changed is discarded", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [] } );
  await h.store.open( SEAT );
  let release!: ( b: Body | Error ) => void;
  h.respond = () => new Promise<Body>( ( r, j ) => { release = ( b ) => b instanceof Error ? j( b ) : r( b ); } );
  const pending = h.store.loadEarlier();
  await flush();
  h.respond = () => ( { file_epoch : EPOCH, offset : 0, next_offset : 5, blocks : [ { kind : "text", text : "other" } ] } );
  await h.store.open( OTHER );
  release( { file_epoch : EPOCH, offset : 0, next_offset : 300, blocks : [ { kind : "text", text : "stale" } ] } );
  await pending;
  assert.deepEqual( texts( h ), [ "other" ] );
  assert.equal( h.store.snapshot().loadingEarlier, false );
} );

test( "a page that FAILS after the seat changed leaves the new seat alone", async () => {
  const h = make();
  auth( h );
  h.respond = () => ( { file_epoch : EPOCH, offset : 300, next_offset : 400, blocks : [] } );
  await h.store.open( SEAT );
  let fail!: () => void;
  h.respond = () => new Promise<Body>( ( _r, j ) => { fail = () => j( new Error( "late" ) ); } );
  const pending = h.store.loadEarlier();
  await flush();
  h.respond = () => ( { file_epoch : EPOCH, offset : 0, next_offset : 5, blocks : [] } );
  await h.store.open( OTHER );
  fail();
  await pending;
  assert.equal( h.store.snapshot().watchedCcSessionId, OTHER );
  assert.equal( h.store.snapshot().loadingEarlier, false );
} );

test( "destroy detaches every listener", async () => {
  const h = await openedAndAuthed();
  h.store.destroy();
  const before = texts( h );
  append( h );
  assert.deepEqual( texts( h ), before );
} );
