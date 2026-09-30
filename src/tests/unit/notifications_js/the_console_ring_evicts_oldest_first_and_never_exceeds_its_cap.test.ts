// The legacy console's ring buffer is byte-bounded, and "byte" means UTF-8 bytes of block
// text (plan §5 C8). Row 27760534: the first cut named the ring byte-bounded and never
// bounded it — ringBytes only ever grew, and it counted UTF-16 code units, not bytes.
//
// What these cases pin:
//   · the ring never holds more than CC_CONSOLE_RING_MAX_BYTES after an append
//   · eviction is OLDEST-first, so what survives is the most recent output
//   · the newest block survives even when it alone is over budget
//   · the size is UTF-8, so a multi-byte character costs more than one unit
//   · a reset (new seat / epoch change) zeroes the eviction count with the ring
import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Block   = { kind: string; text: string };
type Outcome = { action: string; blocksAdded?: number; blocksEvicted?: number };
type State   = { blocks: Block[]; ringBytes: number; evictedBlocks: number };

let beginWatch : ( id: string | null ) => unknown[];
let endWatch   : ( ) => unknown[];
let applyChunk : ( chunk: unknown ) => Outcome;
let blockBytes : ( block: unknown ) => number;
let state      : State;
let CAP        : number;

const SEAT  = "4cecf18a-66f7-442f-98f3-98d61d680654";
const EPOCH = "57238c9d-c227-469e-b707-13b7752a7399";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );

  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) +
    "\n;globalThis.__ccRingBeginWatch = ccConsoleBeginWatch;" +
    "\n;globalThis.__ccRingEndWatch   = ccConsoleEndWatch;" +
    "\n;globalThis.__ccRingApplyChunk = ccConsoleApplyChunk;" +
    "\n;globalThis.__ccRingBlockBytes = ccConsoleBlockBytes;" +
    "\n;globalThis.__ccRingState      = ccConsoleState;" +
    "\n;globalThis.__ccRingCap        = CC_CONSOLE_RING_MAX_BYTES;"
  );
  const g    = globalThis as Record<string, unknown>;
  beginWatch = g.__ccRingBeginWatch as typeof beginWatch;
  endWatch   = g.__ccRingEndWatch   as typeof endWatch;
  applyChunk = g.__ccRingApplyChunk as typeof applyChunk;
  blockBytes = g.__ccRingBlockBytes as typeof blockBytes;
  state      = g.__ccRingState      as State;
  CAP        = g.__ccRingCap        as number;

  assert.equal( typeof blockBytes, "function", "ccConsoleBlockBytes loaded" );
  assert.ok( CAP > 0, "the cap is a positive number of bytes" );
} );

beforeEach( () => { endWatch(); beginWatch( SEAT ); } );

// Feed a sequence of abutting chunks, each carrying the given blocks.
let nextOffset = 0;
function feed( blocks: Block[] ) {
  const out = applyChunk( {
    cc_session_id : SEAT, file_epoch : EPOCH, offset : nextOffset, next_offset : nextOffset + 1,
    blocks, ts : "2026-09-28T00:00:00Z",
  } );
  nextOffset += 1;
  return out;
}
beforeEach( () => { nextOffset = 0; } );

const ascii = ( n: number, tag: string ) => ( { kind : "text", text : tag + "x".repeat( n - tag.length ) } );

test( "the size is UTF-8 bytes, not UTF-16 code units", () => {
  assert.equal( blockBytes( { kind : "text", text : "abc" } ), 3 );
  assert.equal( blockBytes( { kind : "text", text : "é" } ),   2, "é is 2 bytes in UTF-8, 1 code unit" );
  assert.equal( blockBytes( { kind : "text", text : "🦉" } ),  4, "an emoji is 4 bytes, 2 code units" );
  assert.equal( blockBytes( { kind : "text", text : "" } ),    0 );
  assert.equal( blockBytes( { kind : "thinking" } ),           0, "no text is 0, never NaN" );
} );

test( "under the cap nothing is evicted", () => {
  const out = feed( [ ascii( 100, "a" ), ascii( 100, "b" ) ] );
  assert.equal( out.action, "appended" );
  assert.equal( out.blocksEvicted, 0 );
  assert.equal( state.blocks.length, 2 );
  assert.equal( state.ringBytes, 200 );
} );

test( "the ring never holds more than the cap after an append", () => {
  const quarter = Math.floor( CAP / 4 );
  for ( let i = 0; i < 12; i++ ) feed( [ ascii( quarter, `b${i}-` ) ] );
  assert.ok( state.ringBytes <= CAP, `ringBytes ${state.ringBytes} must not exceed cap ${CAP}` );
  const recount = state.blocks.reduce( ( n, b ) => n + blockBytes( b ), 0 );
  assert.equal( state.ringBytes, recount, "ringBytes matches a recount of what is held" );
} );

test( "eviction is OLDEST-first: the most recent output survives", () => {
  const quarter = Math.floor( CAP / 4 );
  for ( let i = 0; i < 12; i++ ) feed( [ ascii( quarter, `b${i}-` ) ] );
  const tags = state.blocks.map( b => b.text.split( "-" )[ 0 ] );
  assert.deepEqual( tags, [ "b8", "b9", "b10", "b11" ], "the last four quarters survive, in order" );
  assert.equal( state.evictedBlocks, 8 );
} );

test( "one append that overflows reports how many it evicted", () => {
  const half = Math.floor( CAP / 2 );
  feed( [ ascii( half, "old1-" ), ascii( half, "old2-" ) ] );
  const out = feed( [ ascii( half, "new-" ) ] );
  assert.equal( out.blocksEvicted, 1 );
  assert.equal( state.blocks[ 0 ].text.startsWith( "old2-" ), true );
} );

test( "the NEWEST block survives even when it alone is over budget", () => {
  feed( [ ascii( 10, "small-" ) ] );
  const out = feed( [ ascii( CAP + 500, "huge-" ) ] );
  assert.equal( state.blocks.length, 1, "everything older went" );
  assert.ok( state.blocks[ 0 ].text.startsWith( "huge-" ), "the block that just arrived stayed" );
  assert.equal( out.blocksEvicted, 1 );
} );

test( "multi-byte text is budgeted in bytes: fewer blocks fit than code units suggest", () => {
  // Each block is CAP/8 characters of a 2-byte letter, so CAP/4 bytes: four fit, not eight.
  const n = Math.floor( CAP / 8 );
  for ( let i = 0; i < 8; i++ ) feed( [ { kind : "text", text : `${i}` + "é".repeat( n - 1 ) } ] );
  assert.ok( state.ringBytes <= CAP );
  assert.equal( state.blocks.length, 4, "a code-unit count would have kept all 8" );
} );

test( "switching seats zeroes the eviction count with the ring", () => {
  const quarter = Math.floor( CAP / 4 );
  for ( let i = 0; i < 6; i++ ) feed( [ ascii( quarter, `b${i}-` ) ] );
  assert.ok( state.evictedBlocks > 0, "precondition: something was evicted" );
  beginWatch( "449359bc-c735-4970-8fc0-e83b635c8548" );
  assert.equal( state.evictedBlocks, 0 );
  assert.equal( state.ringBytes, 0 );
  assert.equal( state.blocks.length, 0 );
} );
