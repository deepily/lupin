// Parity — the legacy client and the multiplexer open the SAME console page for the same card.
// Row 27760534, Rick's ruling 2026-09-28.
//
// Both clients now offer a console button on a sender card, and both open
// `/app/console?seat=<full id>&title=<title>`. Legacy notifications.js is plain script and cannot
// import the multiplexer's modules, so two things are written twice:
//
//   1. the URL — legacy `ccConsoleBuildPageHref` vs the multiplexer's `buildConsolePageHref`
//   2. the seat — legacy `ccConsoleResolveSessionId` (+ `ccConsoleParseSenderId`) vs the
//      multiplexer's `resolveTranscriptSeat` (+ `parseSenderId`)
//
// A second copy agrees with the first only until someone edits one of them. This file is what
// turns that edit into a red: every input below goes through BOTH implementations and the
// outputs must be identical strings.
//
// 🔴 THE INPUTS ARE CHOSEN TO DISCRIMINATE. A title of plain ASCII letters encodes the same
// under encodeURIComponent, encodeURI and no encoding at all, so it would let an unencoded
// builder agree with an encoded one (the lesson in
// both_clients_issue_the_same_request_for_every_control.test.ts). Each title here carries a
// character that at least one wrong encoder mangles, and a control below proves it.
// Likewise every roster carries TWINS sharing an 8-hex prefix — with distinct prefixes, a
// resolver that ignores the persona tie-break agrees with one that applies it.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { buildConsolePageHref, parseConsolePageQuery } from "../../../lupin_app/static/js/multiplexer/console/consolePageUrl";
import { resolveTranscriptSeat, type TranscriptRosterRow } from "../../../lupin_app/static/js/multiplexer/stores/SessionTranscriptRoster";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Chip = { project?: string | null; personaName?: string | null };

let legacyHref    : ( seat: string, title: string ) => string;
let legacyParse   : ( senderId: string ) => { project: string; prefix: string } | null;
let legacyResolve : ( cardId: string | null, roster: TranscriptRosterRow[], chip?: Chip ) => { ccSessionId: string | null; reason: string };

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) +
    "\n;globalThis.__ccParityHref    = ccConsoleBuildPageHref;" +
    "\n;globalThis.__ccParityParse   = ccConsoleParseSenderId;" +
    "\n;globalThis.__ccParityResolve = ccConsoleResolveSessionId;",
    { filename : NOTIFICATIONS_JS }
  );
  const g       = globalThis as Record<string, unknown>;
  legacyHref    = g.__ccParityHref    as typeof legacyHref;
  legacyParse   = g.__ccParityParse   as typeof legacyParse;
  legacyResolve = g.__ccParityResolve as typeof legacyResolve;
  assert.equal( typeof legacyHref,    "function" );
  assert.equal( typeof legacyParse,   "function" );
  assert.equal( typeof legacyResolve, "function" );
} );

/** The legacy seat for a card: parse the sender id, then resolve — the painter's own path. */
function legacySeat( senderId: string, personaName: string | null, rows: TranscriptRosterRow[] ): string | null {
  const parsed = legacyParse( senderId );
  if ( parsed === null ) return null;
  return legacyResolve( parsed.prefix, rows, { project : parsed.project, personaName } ).ccSessionId;
}


// ── the URL ──────────────────────────────────────────────────────────────────

const SEAT = "449359bc-c735-4970-8fc0-e83b635c8548";

const TITLES = [
  "🦉 Mr. Radio — console",          // emoji (surrogate pair) + em dash + spaces
  "Rosa & Cheech — console",          // & would split the query
  "#1 seat — console",                // # would end the URL at a fragment
  "a+b=c? — console",                 // + reads as a space, = and ? as syntax
  "100% — console",                   // a bare % is an invalid escape
  "María's 🌹 — console",            // Latin-1 letter + apostrophe + emoji
  "path/with/slashes — console",      // / kept by encodeURI, escaped by encodeURIComponent
  "",                                  // empty title
];

test( "every title builds the same href in both clients", () => {
  for ( const title of TITLES ) {
    assert.equal( legacyHref( SEAT, title ), buildConsolePageHref( SEAT, title ), `title ${ JSON.stringify( title ) }` );
  }
} );

test( "an odd seat string builds the same href too (both encode the seat)", () => {
  for ( const seat of [ SEAT, "a b&c#d", "ÆØ" ] ) {
    assert.equal( legacyHref( seat, "t" ), buildConsolePageHref( seat, "t" ), `seat ${ JSON.stringify( seat ) }` );
  }
} );

test( "the legacy href round-trips through the console page's own parser", () => {
  for ( const title of TITLES.filter( ( t ) => t.trim() !== "" ) ) {
    const query = parseConsolePageQuery( legacyHref( SEAT, title ).split( "?" )[ 1 ] as string );
    assert.equal( query.seat,  SEAT );
    assert.equal( query.title, title.trim() );
  }
} );

test( "CONTROL: the titles discriminate — a wrong encoder disagrees on every one", () => {
  // encodeURI keeps & # + = ? / and lets a bare % through as-is; no encoding keeps everything.
  // If a title encoded identically under both, the parity assertion above could not tell a
  // correct builder from those. Every non-empty title must separate at least one of them.
  const correct = ( t: string ) => encodeURIComponent( t );
  for ( const title of TITLES.filter( ( t ) => t !== "" ) ) {
    let viaEncodeUri: string;
    try { viaEncodeUri = encodeURI( title ); } catch { viaEncodeUri = "<throws>"; }
    const separates = correct( title ) !== viaEncodeUri || correct( title ) !== title;
    assert.equal( separates, true, `title ${ JSON.stringify( title ) } does not discriminate` );
  }
  // And at least the syntax-bearing ones separate encodeURIComponent from encodeURI.
  for ( const title of [ "Rosa & Cheech — console", "#1 seat — console", "a+b=c? — console", "path/with/slashes — console" ] ) {
    assert.notEqual( encodeURIComponent( title ), encodeURI( title ), title );
  }
} );


// ── the seat ─────────────────────────────────────────────────────────────────

const TWIN_A = "4cecf18a-66f7-442f-98f3-98d61d680654";
const TWIN_B = "4cecf18a-0000-4b1c-9d2e-111111111111";
const TWIN_C = "4CECF18A-2222-4b1c-9d2e-333333333333";   // same prefix, upper-case spelling

const SENDER       = "claude.code@lupin.deepily.ai#4cecf18a";
const SENDER_UPPER = "claude.code@lupin.deepily.ai#4CECF18A";
const SENDER_OTHER = "claude.code@cosa.example.org#4cecf18a";   // a host outside .deepily.ai

function r( id: string, persona: string | null, extra: Partial<TranscriptRosterRow> = {} ): TranscriptRosterRow {
  return { session_id : id, project : "lupin", persona, transcript_watchable : true, ...extra };
}

type Case = { name: string; sender: string; persona: string | null; rows: TranscriptRosterRow[]; expected: string | null };

// `expected` is a LITERAL on every case, so the parity assertion is not two implementations
// agreeing on a mistake: each case is also pinned against what the seat must be.
const CASES: Case[] = [
  { name : "twins, persona picks A",            sender : SENDER, persona : "Mr. Radio", rows : [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ], expected : TWIN_A },
  { name : "twins, persona picks B",            sender : SENDER, persona : "Rosa",      rows : [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ], expected : TWIN_B },
  { name : "twins, reversed order, picks B",    sender : SENDER, persona : "Rosa",      rows : [ r( TWIN_B, "Rosa" ), r( TWIN_A, "Mr. Radio" ) ], expected : TWIN_B },
  { name : "twins, persona case-insensitive",   sender : SENDER, persona : "mr. RADIO", rows : [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ], expected : TWIN_A },
  { name : "twins, no persona on the card",     sender : SENDER, persona : null,        rows : [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ], expected : null },
  { name : "twins, persona matches neither",    sender : SENDER, persona : "Cheech",    rows : [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ], expected : null },
  { name : "twins, persona matches both",       sender : SENDER, persona : "Rosa",      rows : [ r( TWIN_A, "Rosa" ), r( TWIN_B, "Rosa" ) ],      expected : null },
  { name : "twins, one not watchable",          sender : SENDER, persona : null,        rows : [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa", { transcript_watchable : false } ) ], expected : TWIN_A },
  { name : "twins, other project filtered out", sender : SENDER, persona : null,        rows : [ r( TWIN_A, null ), r( TWIN_B, null, { project : "cosa" } ) ], expected : TWIN_A },
  { name : "row with no project is kept",       sender : SENDER, persona : null,        rows : [ r( TWIN_A, null, { project : null } ) ], expected : TWIN_A },
  { name : "prefix spelled upper-case in row",  sender : SENDER, persona : null,        rows : [ r( TWIN_C, null ) ], expected : TWIN_C },
  { name : "prefix spelled upper-case in chip", sender : SENDER_UPPER, persona : null,  rows : [ r( TWIN_A, null ) ], expected : TWIN_A },
  { name : "host outside .deepily.ai",          sender : SENDER_OTHER, persona : null,  rows : [ r( TWIN_A, null, { project : "cosa" } ) ], expected : TWIN_A },
  { name : "single seat, not watchable",        sender : SENDER, persona : null,        rows : [ r( TWIN_A, null, { transcript_watchable : false } ) ], expected : null },
  { name : "not in roster",                     sender : SENDER, persona : null,        rows : [ r( "449359bc-c735-4970-8fc0-e83b635c8548", null ) ], expected : null },
  { name : "malformed sender id",               sender : "notification.proxy", persona : null, rows : [ r( TWIN_A, null ) ], expected : null },
];

test( "the fixture's twins really share their first eight characters", () => {
  assert.equal( TWIN_A.slice( 0, 8 ), TWIN_B.slice( 0, 8 ) );
  assert.equal( TWIN_A.slice( 0, 8 ), TWIN_C.slice( 0, 8 ).toLowerCase() );
  assert.notEqual( TWIN_A, TWIN_B );
} );

for ( const c of CASES ) {
  test( `same seat in both clients: ${ c.name }`, () => {
    const mux    = resolveTranscriptSeat( { senderId : c.sender, personaName : c.persona }, c.rows );
    const legacy = legacySeat( c.sender, c.persona, c.rows );
    assert.equal( mux,    c.expected, "the multiplexer's seat" );
    assert.equal( legacy, c.expected, "the legacy client's seat" );
  } );
}

test( "without a chip, legacy keeps its old refusal for twins (no project, no persona)", () => {
  const out = legacyResolve( "4cecf18a", [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ] );
  assert.equal( out.reason, "ambiguous-prefix" );
  assert.equal( out.ccSessionId, null );
} );

test( "legacy names WHY a twin tie could not be broken", () => {
  const out = legacyResolve( "4cecf18a", [ r( TWIN_A, "Mr. Radio" ), r( TWIN_B, "Rosa" ) ], { project : "lupin", personaName : "Cheech" } );
  assert.equal( out.reason, "ambiguous-prefix" );
} );
