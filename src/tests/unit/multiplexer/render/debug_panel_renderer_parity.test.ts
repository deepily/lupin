// Parity B-6 — the Debug Information panel.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1):
//   - `addDebugMessage`  notifications.js:21171   timestamp · textContent · insertBefore · while > 20
//   - the markup          notifications.html:1394  section · `#debug-log.debug-log-scrollable` · the seeded line
//   - `.debug-info` / `.debug-log-scrollable`  notifications.css:352 and :359
//
// 🔴 THE FOUR RULES HERE ARE ALL ONES A GREEN SUITE HIDES, because a panel that
// gets any of them wrong still looks like a panel:
//   - NEWEST FIRST (G4). Somebody reading this has just seen something break
//     and wants the last line. Append-instead-of-prepend renders 20 lines in a
//     300px box exactly as convincingly as prepend does, and the line they need
//     is off the bottom.
//   - CAPPED AT 20, AFTER EVERY INSERT (G5). An uncapped log looks better right
//     up until a busy load, and legacy sees ~629 writer calls.
//   - `textContent`, NEVER `innerHTML` (G3). A message carrying markup renders
//     as text; the difference is invisible until the message is hostile.
//   - IT NEVER REVEALS ITSELF, NOT EVEN ON AN ERROR (B6). A panel that popped
//     open would move the page under the operator at the moment they were
//     reading something else.
//
// ⚠️ ONE DELIBERATE SHAPE MATCH THAT READS LIKE A BUG: the seeded line's class
// is BARE `debug-info`, with no type token, while every other line carries one.
// That is legacy's markup verbatim (notifications.html:1401) against legacy's
// `addDebugMessage`, which always appends a type. Tidying it would differ from
// the lead by one class token on one div.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/debug_panel_renderer_parity.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  createDebugPanelRenderer,
  DEBUG_LOG_CAP,
  DEBUG_SEEDED_LINE,
  DEBUG_LINE_CLASS,
  DEBUG_SEEDED_CLASS,
  type DebugPanelRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render/DebugPanelRenderer";
import {
  log,
  error,
  wsDiag,
  currentDebugPanel,
  setDebugPanel,
} from "../../../../lupin_app/static/js/multiplexer/shared/debugSink";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const FIXED_CLOCK = () => new Date( "2026-09-23T20:30:07" );
const STAMP       = FIXED_CLOCK().toLocaleTimeString();

let realLog   : typeof console.log;
let realError : typeof console.error;

beforeEach( () => {
  // The writers tee to the console on every call; silence it so a 25-line cap
  // test does not print 25 lines into the runner's output.
  realLog       = console.log;
  realError     = console.error;
  console.log   = () => {};
  console.error = () => {};
} );

afterEach( () => {
  console.log   = realLog;
  console.error = realError;
  setDebugPanel( null );
} );

interface Mounted { root: HTMLElement; renderer: DebugPanelRenderer }

function mount(): Mounted {
  const root     = document.createElement( "div" );
  const renderer = createDebugPanelRenderer( { nowDateFn: FIXED_CLOCK } );
  renderer.mount( root );
  return { root, renderer };
}

const logEl   = ( root: HTMLElement ): HTMLElement =>
  root.querySelector<HTMLElement>( '[data-testid="multiplexer-debug-log"]' )!;
const lines   = ( root: HTMLElement ): HTMLElement[] =>
  Array.from( logEl( root ).children ) as HTMLElement[];
const texts   = ( root: HTMLElement ): string[] =>
  lines( root ).map( ( el ) => el.textContent ?? "" );

// --- the mounted shape ----------------------------------------------------

test( "the panel mounts a header and a scrollable log, and the log is reachable", () => {
  // 🔴 POSITIVE CONTROL FOR EVERY TEST BELOW. They all read `logEl(root)`; if
  // the testid moved, each of them would throw on a null rather than assert
  // anything — but a `children.length` read off a missing node is the kind of
  // failure that gets "fixed" by loosening the selector.
  const { root } = mount();

  assert.ok( root.querySelector( '[data-testid="multiplexer-debug-panel-header"]' ),
    "the section header did not render" );
  assert.ok( root.querySelector( ".debug-panel-body" ), "the collapsible body did not render" );
  assert.ok( logEl( root ), "the log element is not reachable by its testid" );
  assert.equal( logEl( root ).className, "debug-log-scrollable",
    "the log lost legacy's class — the sheet's 300px/scroll rules key on it" );
} );

test( "B7 — the header reads `Debug Information` with NO leading emoji, alone among the sections", () => {
  const { root } = mount();
  const header = root.querySelector( '[data-testid="multiplexer-debug-panel-header"]' )!;
  const title  = header.textContent ?? "";

  assert.ok( title.includes( "Debug Information" ) );
  assert.equal( /^\s*[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test( title ), false,
    `the header gained a leading glyph (${ JSON.stringify( title.slice( 0, 8 ) ) }) — legacy's <h3> is bare text` );
} );

test( "B8 — the header carries NO refresh, Clear or copy control; only the collapse chevron", () => {
  const { root } = mount();
  const header  = root.querySelector( '[data-testid="multiplexer-debug-panel-header"]' )!;
  const buttons = Array.from( header.querySelectorAll( "button" ) );

  assert.deepEqual( buttons.map( ( b ) => b.className ), [ "toggle-button" ],
    "the header gained a control legacy's Debug section does not have" );
} );

test( "B10 — the seeded line ships, and its class is BARE `debug-info` exactly as legacy's markup is", () => {
  const { root } = mount();

  assert.equal( lines( root ).length, 1, "the panel mounted with no seeded line, or with more than one" );
  assert.equal( texts( root )[ 0 ], `[${ STAMP }] ${ DEBUG_SEEDED_LINE }` );
  assert.equal( lines( root )[ 0 ]!.className, DEBUG_SEEDED_CLASS );
  assert.equal( DEBUG_SEEDED_CLASS, "debug-info",
    "the seeded class gained a type token — legacy's markup at notifications.html:1401 has none" );
} );

// --- registration ---------------------------------------------------------

test( "🔴 mounting REGISTERS the panel as the sink, so the writers reach it", () => {
  assert.equal( currentDebugPanel(), null, "a sink is registered before any mount" );
  const { root } = mount();

  assert.notEqual( currentDebugPanel(), null, "mount did not register the panel — every writer drops on the floor" );
  log( "socket opened" );
  assert.equal( texts( root )[ 0 ], `[${ STAMP }] socket opened` );
} );

test( "🔴 unmount DEREGISTERS, and a writer firing afterwards paints nothing", () => {
  // Deregistration has to happen BEFORE the DOM teardown: a writer landing in
  // between would paint into a detached node — invisible — and the module-level
  // reference would keep the torn-down pane alive.
  const { root, renderer } = mount();
  log( "while mounted" );
  assert.equal( lines( root ).length, 2 );

  renderer.unmount();

  assert.equal( currentDebugPanel(), null, "the sink survived unmount — it holds a detached pane" );
  assert.equal( root.children.length, 0, "unmount left the pane's subtree in the page" );
  log( "after unmount" );          // must not throw, must not paint
  assert.equal( root.children.length, 0 );
} );

test( "mounting twice is refused rather than silently building a second subtree", () => {
  const { root, renderer } = mount();
  assert.throws( () => renderer.mount( root ), /already mounted/ );
} );

test( "a remount after an unmount works, and starts from a fresh seeded line", () => {
  const { root, renderer } = mount();
  log( "old" );
  renderer.unmount();

  const root2 = document.createElement( "div" );
  renderer.mount( root2 );

  assert.deepEqual( texts( root2 ), [ `[${ STAMP }] ${ DEBUG_SEEDED_LINE }` ],
    "the remounted panel carried lines over from the previous mount" );
  assert.notEqual( currentDebugPanel(), null );
} );

// --- the four rules -------------------------------------------------------

test( "🔴 G4 — NEWEST FIRST. Each line is inserted above the last, the opposite of a console", () => {
  const { root } = mount();
  log( "first" );
  log( "second" );
  log( "third" );

  assert.deepEqual( texts( root ).map( ( t ) => t.replace( `[${ STAMP }] `, "" ) ),
    [ "third", "second", "first", DEBUG_SEEDED_LINE ],
    "the panel appends — the line an operator opened it to read is off the bottom of a 300px box" );
} );

test( "🔴 G5 — CAPPED AT 20, and the seeded line COUNTS toward the cap", () => {
  const { root } = mount();
  // One short of the cap: the seed plus 19 writes is exactly 20.
  for ( let i = 1; i <= DEBUG_LOG_CAP - 1; i++ ) log( `m${ i }` );

  assert.equal( lines( root ).length, DEBUG_LOG_CAP );
  assert.ok( texts( root ).some( ( t ) => t.includes( DEBUG_SEEDED_LINE ) ),
    "the seed was trimmed one line early — it is being counted twice or not at all" );

  log( "one over" );

  assert.equal( lines( root ).length, DEBUG_LOG_CAP, "the cap did not hold" );
  assert.equal( texts( root ).some( ( t ) => t.includes( DEBUG_SEEDED_LINE ) ), false,
    "the seeded line survived past the cap — it is exempt from a trim it should not be exempt from" );
  assert.ok( texts( root )[ 0 ]!.endsWith( "one over" ), "the newest line was the one trimmed" );
} );

test( "🔴 G5 — the trim is a `while`, so an overflow of MORE THAN ONE is trimmed all the way back", () => {
  // 🔴 CALLING THE WRITER IN A LOOP CANNOT TEST THIS, and the first cut of this
  // test did exactly that and passed with `if` in place — measured 2026-09-23.
  // One call inserts one line, so the log never exceeds the cap by more than
  // one, and `if` and `while` are indistinguishable. The difference only exists
  // when the log is ALREADY over by several, so the overflow is planted in the
  // DOM directly and one ordinary write is then made on top of it.
  //
  // ⚠️ THAT IS THE SEAM, NOT A TRICK. The log element is a plain div that this
  // renderer does not own exclusively — the seeded line arrives as markup in
  // legacy, and any future hydration or replay would put lines in the same way.
  // A cap written as `if` is correct only while nothing ever does that.
  const { root } = mount();
  const el = logEl( root );
  for ( let i = 0; i < DEBUG_LOG_CAP + 4; i++ ) {
    const extra = document.createElement( "div" );
    extra.className = "debug-info info";
    extra.textContent = `planted ${ i }`;
    el.appendChild( extra );
  }
  assert.equal( el.children.length, DEBUG_LOG_CAP + 5,
    "positive control: the planted overflow is not in the DOM, so nothing needs trimming" );

  log( "one ordinary write" );

  assert.equal( lines( root ).length, DEBUG_LOG_CAP,
    "the log is still over the cap after a write — the trim runs once, not until it is done" );
  assert.equal( texts( root )[ 0 ], `[${ STAMP }] one ordinary write` );
} );

test( "🔴 G3 — a message carrying markup renders as TEXT, never parsed", () => {
  const { root } = mount();
  const hostile = '<img src=x onerror="globalThis.__pwned = true">';
  log( hostile );

  const line = lines( root )[ 0 ]!;
  assert.equal( line.textContent, `[${ STAMP }] ${ hostile }` );
  assert.equal( line.querySelector( "img" ), null,
    "the message was parsed as markup — `textContent` was swapped for `innerHTML`" );
  assert.equal( ( globalThis as Record<string, unknown> ).__pwned, undefined );
} );

test( "🔴 B6 — an error does NOT reveal the panel: no collapse state changes, nothing scrolls into view", () => {
  const { root } = mount();
  const before = root.getAttribute( "data-collapsed" );

  error( "everything is on fire" );

  assert.equal( root.getAttribute( "data-collapsed" ), before,
    "an error changed the section's collapse state — the page moved under the operator" );
  assert.equal( lines( root )[ 0 ]!.textContent, `[${ STAMP }] ERROR: everything is on fire`,
    "the error line did not paint at all" );
} );

// --- the line's own shape -------------------------------------------------

test( "every written line reads `[<localeTime>] <message>` and carries `debug-info <type>`", () => {
  const { root } = mount();
  log( "an info line" );
  error( "an error line" );
  wsDiag( "a diagnostic" );

  const [ diag, err, info ] = lines( root );
  assert.equal( info!.className, `${ DEBUG_LINE_CLASS } info` );
  assert.equal( err!.className,  `${ DEBUG_LINE_CLASS } error` );
  assert.equal( diag!.className, `${ DEBUG_LINE_CLASS } info`,
    "a WS diagnostic is typed `error` — a healthy reconnect would read as a failure" );
  assert.deepEqual( texts( root ).slice( 0, 3 ), [
    `[${ STAMP }] WS-DIAG: a diagnostic`,
    `[${ STAMP }] ERROR: an error line`,
    `[${ STAMP }] an info line`,
  ] );
} );

test( "the timestamp is read PER LINE, not once at mount", () => {
  // A stamp captured at mount would make every line in a 20-line panel claim
  // the same instant — and would look completely normal in a fast test.
  let tick = 0;
  const root     = document.createElement( "div" );
  const renderer = createDebugPanelRenderer( {
    nowDateFn : () => new Date( Date.UTC( 2026, 8, 23, 20, 30, tick++ ) ),
  } );
  renderer.mount( root );
  log( "a" );
  log( "b" );

  const stamps = texts( root ).map( ( t ) => /^\[([^\]]+)\]/.exec( t )![ 1 ]! );
  assert.equal( new Set( stamps ).size, 3,
    `three lines share ${ 3 - new Set( stamps ).size + 1 } stamp(s) — the clock is read once, not per line` );
  renderer.unmount();
} );

test( "an empty message still produces a line, stamp and all", () => {
  const { root } = mount();
  log( "" );
  assert.equal( texts( root )[ 0 ], `[${ STAMP }] ` );
} );
