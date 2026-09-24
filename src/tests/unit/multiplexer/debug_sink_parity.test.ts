// Parity B-6 — the three debug writers.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1):
//   - `log`              notifications.js:21154   gated on `this.debug`, prefixed `[Notifications]`
//   - `error`            notifications.js:21161   UNGATED, prefixed `[Notifications ERROR]`
//   - `wsDiag`           notifications.js:21166   UNGATED, prefixed `[WS-DIAG]`
//   - `addDebugMessage`  notifications.js:21171   the sink all three funnel into
//
// 🔴 WHAT THIS FILE MOSTLY GUARDS IS THAT THE CONSOLE STILL GETS EVERYTHING.
// This is a TEE, not a redirect: the panel keeps 20 lines and drops every extra
// arg (legacy's `addDebugMessage` takes no `...args` — G6), so the console is
// strictly the better record and the one a developer with devtools open is
// actually reading. A refactor that "routed" a call to the panel would take
// information away from the person best placed to use it, and would look like
// a tidy-up in a diff. So every writer is asserted on BOTH sides.
//
// 🔴 AND THAT THE PANEL IS OPTIONAL. Legacy's sink looks up `#debug-log` on
// every call and no-ops when it is absent, which is its state before the DOM
// parses. This client's panel registers itself at mount instead, so the
// no-panel arm is the state of the page before boot reaches the mount — the
// same behaviour reached by a different mechanism, and therefore worth its own
// arm rather than an assumption.
//
// ⚠️ THE `DEBUG_ENABLED === false` ARM CANNOT BE DRIVEN FROM HERE and is not
// tested. It is a hard-coded `true` (G2) because legacy's `this.debug` is set
// once and never cleared — no INI key, no UI control, no query param. Writing
// it as a constant rather than a variable nobody assigns is the honest shape,
// and the cost is that `log`'s early return is unreachable; it carries a
// `c8 ignore` naming that reason. Named here as a GAP, not bridged.
//
// Run: npx tsx --test src/tests/unit/multiplexer/debug_sink_parity.test.ts

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import {
  log,
  error,
  wsDiag,
  setDebugPanel,
  currentDebugPanel,
  DEBUG_ENABLED,
  type DebugPanelSink,
} from "../../../lupin_app/static/js/multiplexer/shared/debugSink";

// --------------------------------------------------------------------------
// A console spy that RECORDS, and a panel that RECORDS. Both are needed on
// every arm: an assertion that only watches one of them cannot tell a tee from
// a redirect, which is the exact defect this file exists to catch.
// --------------------------------------------------------------------------

interface ConsoleCall { level: "log" | "error"; args: unknown[] }

let consoleCalls : ConsoleCall[];
let panelCalls   : Array<{ message: string; type: string }>;
let realLog      : typeof console.log;
let realError    : typeof console.error;

const recordingPanel: DebugPanelSink = {
  addDebugMessage( message, type ) { panelCalls.push( { message, type } ); },
};

beforeEach( () => {
  consoleCalls = [];
  panelCalls   = [];
  realLog      = console.log;
  realError    = console.error;
  console.log   = ( ...args: unknown[] ) => { consoleCalls.push( { level: "log",   args } ); };
  console.error = ( ...args: unknown[] ) => { consoleCalls.push( { level: "error", args } ); };
} );

afterEach( () => {
  console.log   = realLog;
  console.error = realError;
  setDebugPanel( null );
} );

// --------------------------------------------------------------------------

test( "the spies can see a call at all — positive control before any absence is read", () => {
  // 🔴 EVERY "the panel got nothing" ASSERTION BELOW IS WORTHLESS IF THE PANEL
  // FAKE IS NEVER REACHED. An unreached recorder and a correctly-silent one
  // print the same empty array.
  setDebugPanel( recordingPanel );
  log( "seen" );
  assert.equal( consoleCalls.length, 1, "the console spy never fired — it is not installed" );
  assert.equal( panelCalls.length,   1, "the panel fake never fired — it is not registered" );
} );

test( "DEBUG_ENABLED is on, and is a constant — legacy's `this.debug` is set once and never cleared", () => {
  assert.equal( DEBUG_ENABLED, true );
} );

// --- registration ---------------------------------------------------------

test( "the page starts with NO panel, and writes still reach the console", () => {
  assert.equal( currentDebugPanel(), null,
    "a panel is registered before any mount — a previous test leaked its sink" );

  log( "before mount" );
  error( "before mount" );
  wsDiag( "before mount" );

  assert.equal( consoleCalls.length, 3,
    "a writer dropped its line when no panel was registered — legacy's sink no-ops, its console does not" );
  assert.deepEqual( panelCalls, [] );
} );

test( "registering replaces the previous sink rather than adding to it", () => {
  const first : Array<string> = [];
  setDebugPanel( { addDebugMessage : ( m ) => { first.push( m ); } } );
  setDebugPanel( recordingPanel );

  log( "after the swap" );

  assert.deepEqual( first, [],
    "the replaced sink still received a line — two mounted panels would each paint every message" );
  assert.equal( panelCalls.length, 1 );
} );

test( "clearing with null restores the console-only behaviour the page has before mount", () => {
  setDebugPanel( recordingPanel );
  log( "while registered" );
  setDebugPanel( null );
  log( "after clearing" );

  assert.equal( currentDebugPanel(), null );
  assert.equal( panelCalls.length,   1, "a line reached a deregistered panel" );
  assert.equal( consoleCalls.length, 2, "the console stopped when the panel was cleared" );
} );

// --- log ------------------------------------------------------------------

test( "🔴 log tees: `[Notifications] ` to the console, UNPREFIXED to the panel, typed info", () => {
  setDebugPanel( recordingPanel );
  log( "socket opened" );

  assert.deepEqual( consoleCalls, [ { level: "log", args: [ "[Notifications] socket opened" ] } ] );
  assert.deepEqual( panelCalls,   [ { message: "socket opened", type: "info" } ] );
} );

test( "🔴 log's extra args reach the CONSOLE ONLY — the panel drops them (G6)", () => {
  // The whole justification for keeping every console call is here: legacy's
  // `addDebugMessage` takes no `...args`, so the panel line for a failure
  // reads "playback failed" and the error object exists only in the console.
  const detail = { code: 1006 };
  setDebugPanel( recordingPanel );
  log( "playback failed", detail, "extra" );

  assert.deepEqual( consoleCalls[ 0 ]!.args,
    [ "[Notifications] playback failed", detail, "extra" ] );
  assert.deepEqual( panelCalls, [ { message: "playback failed", type: "info" } ],
    "the panel received an extra arg — legacy's sink has no parameter for one" );
} );

// --- error ----------------------------------------------------------------

test( "🔴 error goes to console.error, and the panel line is prefixed `ERROR: ` and typed error", () => {
  setDebugPanel( recordingPanel );
  error( "token expired" );

  assert.deepEqual( consoleCalls,
    [ { level: "error", args: [ "[Notifications ERROR] token expired" ] } ] );
  assert.deepEqual( panelCalls, [ { message: "ERROR: token expired", type: "error" } ] );
} );

test( "🔴 error is NOT gated by the debug flag, unlike log", () => {
  // An error that only appeared when debugging was on would be missing from
  // exactly the session someone is trying to explain afterwards. Legacy's
  // `error` sits outside the `if ( this.debug )` that wraps `log`'s body.
  //
  // 🔴 READ AS A PAIR, NEVER ALONE. "`error` does not mention DEBUG_ENABLED" is
  // also what a renamed constant, a moved function or a typo'd search would
  // print, so `log` — which MUST mention it — is the positive control that
  // proves the search can find the name at all.
  const src = readWriterSource();

  assert.equal( writerBody( src, "log" ).includes( "DEBUG_ENABLED" ), true,
    "positive control: `log` no longer consults DEBUG_ENABLED, so the search below proves nothing" );
  assert.equal( writerBody( src, "error" ).includes( "DEBUG_ENABLED" ), false,
    "`error` now consults DEBUG_ENABLED — legacy's does not, and a silenced error is a lost incident" );
  assert.equal( writerBody( src, "wsDiag" ).includes( "DEBUG_ENABLED" ), false,
    "`wsDiag` now consults DEBUG_ENABLED — legacy's `wsDiag` sits outside the flag too" );
} );

test( "error's extra args reach the console only", () => {
  const cause = new Error( "boom" );
  setDebugPanel( recordingPanel );
  error( "send failed", cause );

  assert.deepEqual( consoleCalls[ 0 ]!.args, [ "[Notifications ERROR] send failed", cause ] );
  assert.deepEqual( panelCalls, [ { message: "ERROR: send failed", type: "error" } ] );
} );

// --- wsDiag ---------------------------------------------------------------

test( "🔴 wsDiag is prefixed `WS-DIAG: ` in the panel but typed INFO, which is legacy's own choice", () => {
  // A diagnostic is not an error. Typing it `error` would make a healthy
  // reconnect look like a failure — and legacy's `wsDiag` omits the type
  // argument entirely, taking `addDebugMessage`'s `type = 'info'` default.
  setDebugPanel( recordingPanel );
  wsDiag( "reconnect scheduled" );

  assert.deepEqual( consoleCalls, [ { level: "log", args: [ "[WS-DIAG] reconnect scheduled" ] } ] );
  assert.deepEqual( panelCalls,   [ { message: "WS-DIAG: reconnect scheduled", type: "info" } ] );
} );

test( "wsDiag's extra args reach the console only", () => {
  setDebugPanel( recordingPanel );
  wsDiag( "frame", 42 );

  assert.deepEqual( consoleCalls[ 0 ]!.args, [ "[WS-DIAG] frame", 42 ] );
  assert.deepEqual( panelCalls, [ { message: "WS-DIAG: frame", type: "info" } ] );
} );

// --- the three prefixes are distinct --------------------------------------

test( "the three writers are distinguishable in the panel, which carries no level of its own", () => {
  // The panel line is the only record a non-developer sees, and it has one
  // `type` with two values. `ERROR: ` and `WS-DIAG: ` are what separate three
  // writers inside it — collapse two prefixes and the panel stops being a log.
  setDebugPanel( recordingPanel );
  log( "m" );
  error( "m" );
  wsDiag( "m" );

  assert.deepEqual( panelCalls.map( ( c ) => c.message ), [ "m", "ERROR: m", "WS-DIAG: m" ] );
  assert.equal( new Set( panelCalls.map( ( c ) => c.message ) ).size, 3 );
} );

// --------------------------------------------------------------------------

/** One exported function's body, from its signature to the first column-0 `}`. */
function writerBody( src: string, name: string ): string {
  const start = src.indexOf( `export function ${ name }(` );
  assert.notEqual( start, -1, `the source has no \`export function ${ name }\` — the search is looking for a name that moved` );
  const body = src.slice( start );
  const end  = body.indexOf( "\n}" );
  assert.notEqual( end, -1, `\`${ name }\` has no closing brace at column 0 — the slice ran to end-of-file` );
  return body.slice( 0, end );
}

function readWriterSource(): string {
  // Read the module's own text for the one claim no runtime arm can make: that
  // `error` does not consult the flag. Driving it would need the flag to be a
  // variable, and making it one to satisfy a test would invent a control the
  // product does not have.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { readFileSync } = require( "node:fs" ) as typeof import( "node:fs" );
  const { fileURLToPath } = require( "node:url" ) as typeof import( "node:url" );
  const { dirname, resolve } = require( "node:path" ) as typeof import( "node:path" );
  const here = dirname( fileURLToPath( import.meta.url ) );
  return readFileSync(
    resolve( here, "../../../lupin_app/static/js/multiplexer/shared/debugSink.ts" ), "utf8" );
}
