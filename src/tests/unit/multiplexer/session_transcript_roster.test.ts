// SessionTranscriptRoster — row 27760534, plan §4 "Roster and identity", slice 7. ACs B4.4b and
// B4.4c (multiplexer half). 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE FIXTURE IS THE MEASUREMENT (B4.4c). The roster below holds TWO seats whose ids share
// their first 8 hex characters. With one seat, or with distinct prefixes, a client that
// resolves by the full id and one that matches the first prefix hit return the same answer,
// and the test could not tell them apart.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSessionTranscriptRoster,
  parseSenderId,
  resolveTranscriptSeat,
  SESSION_TRANSCRIPT_ROSTER_ENDPOINT,
  type TranscriptRosterRow,
} from "../../../lupin_app/static/js/multiplexer/stores/SessionTranscriptRoster";
import type { EventBus } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { LupinEventType } from "../../../lupin_app/static/js/multiplexer/shared/types";

// Two seats, ONE 8-hex prefix — the twin-prefix fixture B4.4c requires.
const RADIO = "e14bd712-700e-46ce-88ea-8db62604ceb4";
const TWIN  = "e14bd712-0000-4000-8000-000000000001";
const MARIA = "2b76a19a-1111-4111-8111-111111111111";

const ROWS: TranscriptRosterRow[] = [
  { session_id : RADIO, persona : "mr radio", project : "lupin", transcript_watchable : true },
  { session_id : TWIN,  persona : "sam",      project : "lupin", transcript_watchable : true },
  { session_id : MARIA, persona : "maría",    project : "lupin", transcript_watchable : true },
];

const chip = ( senderId: string, personaName: string | null = null ) => ( { senderId, personaName } );

test( "parseSenderId: the REAL shape's project is the host's first label, not the whole host", () => {
  // Captured from a live seat's get_session_info() sender_id, 2026-09-28 — the real producer.
  assert.deepEqual( parseSenderId( "claude.code@lupin.deepily.ai#e14bd712" ), { project : "lupin", prefix : "e14bd712" } );
  assert.deepEqual( parseSenderId( "claude.code@lupin-mobile.deepily.ai#1b9a6410" ), { project : "lupin-mobile", prefix : "1b9a6410" } );
} );

test( "B4.4b on the REAL shape: a live seat's chip resolves against the roster's short project key", () => {
  const rows: TranscriptRosterRow[] = [ { session_id : RADIO, persona : "mr radio", project : "lupin", transcript_watchable : true } ];
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin.deepily.ai#e14bd712" ), rows ), RADIO,
    "comparing the whole host 'lupin.deepily.ai' to 'lupin' matched nothing — review finding, slice 7" );
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin-mobile.deepily.ai#e14bd712" ), rows ), null );
} );

test( "parseSenderId splits project and prefix, and refuses anything else", () => {
  assert.deepEqual( parseSenderId( "claude.code@lupin#E14BD712" ), { project : "lupin", prefix : "e14bd712" } );
  assert.equal( parseSenderId( "claude.code@lupin" ), null );
  assert.equal( parseSenderId( "deep-research@lupin#not-hex" ), null );
} );

test( "B4.4b: a chip resolves to the roster row's FULL id, never its own 8-hex", () => {
  const id = resolveTranscriptSeat( chip( "claude.code@lupin#2b76a19a" ), ROWS );
  assert.equal( id, MARIA );
  assert.notEqual( id, "2b76a19a" );
} );

test( "B4.4c: two seats sharing a prefix are told apart by persona — both directions", () => {
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#e14bd712", "Mr Radio" ), ROWS ), RADIO );
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#e14bd712", "Sam" ), ROWS ), TWIN,
    "a first-prefix-match client would return RADIO here" );
} );

test( "B4.4c: an ambiguous prefix with no deciding persona resolves to NOTHING, not a guess", () => {
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#e14bd712" ), ROWS ), null );
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#e14bd712", "tiffany" ), ROWS ), null );
} );

test( "B4.4b: a chip with no roster row, a foreign project, or an unwatchable seat resolves to nothing", () => {
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#deadbeef" ), ROWS ), null, "the chip outlived its seat" );
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin-mobile#2b76a19a" ), ROWS ), null );
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#2b76a19a" ),
    [ { ...ROWS[ 2 ]!, transcript_watchable : false } ] ), null );
  assert.equal( resolveTranscriptSeat( chip( "no-hash-here" ), ROWS ), null );
} );

test( "a row with no project or persona is still a candidate on the prefix", () => {
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#2b76a19a" ),
    [ { session_id : MARIA, transcript_watchable : true } ] ), MARIA );
  assert.equal( resolveTranscriptSeat( chip( "claude.code@lupin#e14bd712", "sam" ),
    [ { session_id : RADIO, transcript_watchable : true }, { session_id : TWIN, persona : null, transcript_watchable : true } ] ), null );
} );

// ── the store ─────────────────────────────────────────────────────────────

function make( body: unknown, opts: { admin?: boolean } = {} ) {
  const bus     = createEventBusForTesting();
  const gets    : string[] = [];
  const logs    : string[] = [];
  const changes : unknown[] = [];
  bus.on( "store_session_transcript_roster_changed", ( e ) => { changes.push( e.payload ); } );
  const roster = createSessionTranscriptRoster( {
    bus,
    api     : { get : async <T>( path: string ): Promise<T> => {
      gets.push( path );
      if ( body instanceof Error ) throw body;
      return body as T;
    } },
    isAdmin : () => opts.admin ?? true,
    logFn   : ( m ) => logs.push( m ),
  } );
  return { bus, roster, gets, logs, changes };
}
const emit  = ( bus: EventBus, type: string, payload: unknown ) =>
  bus.emit( { type : type as LupinEventType, payload, source : "test", ts : 0 } );
const flush = () => new Promise( ( r ) => setImmediate( r ) );

test( "auth_success reads the roster; resolve then answers from it", async () => {
  const h = make( { status : "ok", seats : ROWS } );
  assert.equal( h.roster.status(), null );
  emit( h.bus, "auth_success", {} );
  await flush();
  assert.deepEqual( h.gets, [ SESSION_TRANSCRIPT_ROSTER_ENDPOINT ] );
  assert.equal( h.roster.status(), "ok" );
  assert.equal( h.roster.resolve( chip( "claude.code@lupin#2b76a19a" ) ), MARIA );
  assert.deepEqual( h.changes, [ { status : "ok", seatCount : 3 } ] );
} );

test( "a strip ADD or HYDRATE re-reads; an update or removal does not", async () => {
  const h = make( { status : "ok", seats : [] } );
  emit( h.bus, "store_session_strip_changed", { changeKind : "added" } );
  emit( h.bus, "store_session_strip_changed", { changeKind : "hydrated" } );
  emit( h.bus, "store_session_strip_changed", { changeKind : "updated" } );
  emit( h.bus, "store_session_strip_changed", { changeKind : "removed" } );
  emit( h.bus, "store_session_strip_changed", undefined );
  await flush();
  assert.equal( h.gets.length, 2 );
} );

test( "a non-admin never reads the roster, so no chip ever offers a console", async () => {
  const h = make( { status : "ok", seats : ROWS }, { admin : false } );
  await h.roster.refresh();
  assert.deepEqual( h.gets, [] );
  assert.equal( h.roster.resolve( chip( "claude.code@lupin#2b76a19a" ) ), null );
} );

test( "an unreachable arbiter is reported as unreachable, with nothing resolvable", async () => {
  const h = make( { status : "unreachable", seats : [] } );
  await h.roster.refresh();
  assert.equal( h.roster.status(), "unreachable" );
  assert.equal( h.roster.resolve( chip( "claude.code@lupin#2b76a19a" ) ), null );
} );

test( "a malformed body degrades to an empty roster; a failed read is logged and keeps the old one", async () => {
  const h = make( { status : 7, seats : [ null, { persona : "no id" }, ROWS[ 2 ] ] } );
  await h.roster.refresh();
  assert.equal( h.roster.status(), null );
  assert.equal( h.roster.resolve( chip( "claude.code@lupin#2b76a19a" ) ), MARIA );

  const bad = make( { seats : "nope" } );
  await bad.roster.refresh();
  assert.equal( bad.roster.resolve( chip( "claude.code@lupin#2b76a19a" ) ), null );

  const down = make( new Error( "403" ) );
  await down.roster.refresh();
  assert.ok( down.logs.some( m => m.includes( "roster read failed" ) ) );
  assert.deepEqual( down.changes, [] );
} );

test( "destroy detaches every listener", async () => {
  const h = make( { status : "ok", seats : ROWS } );
  h.roster.destroy();
  emit( h.bus, "auth_success", {} );
  await flush();
  assert.deepEqual( h.gets, [] );
} );
