// Flow-ratio OPERATOR CONTROLS (the threshold/window sliders) — frontend unit tests.
//
// These cover the five methods that shipped with the control cluster and had no
// JavaScript tests at all: fetchFlowRatioSettings, _paintFlowRatioSettings,
// saveFlowRatioSettings, resetFlowRatioSettings, initFlowRatioControls.
//
// THE FIXTURE VARIES ITS ANSWER PER CALL, ON PURPOSE. A fake that returns the same
// good payload however it is called cannot tell a retry from a no-retry: both make
// exactly one visible panel and both go green. Every retry test below drives a FIRST
// call that fails and a SECOND that succeeds, and asserts the panel is hidden after
// the first and visible after the second. That difference is the whole behaviour.
//
// ⚠️ WHAT THIS FILE CANNOT SEE. happy-dom does no cascade and no layout, so
// `root.hidden = true` reads back as hidden here whatever the stylesheet says. The
// companion rule that makes the attribute actually hide the cluster —
// `.flow-ratio-controls[hidden] { display: none }` — is asserted by
// src/tests/unit/test_flow_ratio_hidden_attribute_is_honoured.py, and was measured
// in Chromium. A green run here is not evidence the panel hides in a browser.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/flow_ratio_controls.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type Settings = Record<string, unknown>;

type FlowUI = Record<string, unknown> & {
  fetchFlowRatioSettings  : () => Promise<Settings | null>;
  _paintFlowRatioSettings : ( s: unknown ) => boolean;
  saveFlowRatioSettings   : ( patch: unknown ) => Promise<Settings | null>;
  resetFlowRatioSettings  : () => Promise<Settings | null>;
  initFlowRatioControls   : () => void;
  authedFetch             : ( url: string, opts?: unknown ) => Promise<unknown>;
};

const errors: string[] = [];

function newUI(): FlowUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as FlowUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = ( m: string ): void => { errors.push( m ); };
  return ui;
}

// Mirrors the shipped markup, including the .flow-ratio-field wrappers that keep a
// label with its own slider, and the `hidden` attribute exactly as the page ships it
// — so these tests start from the state a real first load starts from.
function buildClusterDOM(): void {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.innerHTML = `
    <span id="task-list-flow-ratio"></span>
    <div class="flow-ratio-controls" id="flow-ratio-controls" hidden>
      <span class="flow-ratio-field">
        <label for="flow-ratio-threshold">Gate opens below
          <output id="flow-ratio-threshold-value">&mdash;</output></label>
        <input type="range" id="flow-ratio-threshold" min="0" max="200" step="10" />
      </span>
      <span class="flow-ratio-field">
        <label for="flow-ratio-window">Window
          <output id="flow-ratio-window-value">&mdash;</output></label>
        <input type="range" id="flow-ratio-window" min="1" max="14" step="1" />
      </span>
      <button type="button" id="flow-ratio-reset">Reset</button>
      <span id="flow-ratio-controls-status" class="flow-ratio-controls-status"></span>
    </div>`;
  document.body.appendChild( host );
}

function fakeResponse( status: number, ok: boolean, jsonBody: unknown ): unknown {
  return { status, ok, json: async () => jsonBody };
}

const GOOD: Settings = { window_hours: 24, allow_below: 1.0,
                         window_source: "config", threshold_source: "config" };
const SETTINGS_URL = "/api/tasks/flow-ratio/settings";

const root      = (): HTMLElement => document.getElementById( "flow-ratio-controls" )!;
const statusTxt = (): string => document.getElementById( "flow-ratio-controls-status" )!.textContent!;
const text      = ( id: string ): string => document.getElementById( id )!.textContent!;
const slider    = ( id: string ): HTMLInputElement => document.getElementById( id ) as HTMLInputElement;

beforeEach( () => { buildClusterDOM(); errors.length = 0; } );

// The paint is a promise chain, so the microtask queue must drain before the DOM
// reflects it. One macrotask turn does that and is honest about what it waits for.
const settle = (): Promise<void> => new Promise( r => setTimeout( r, 0 ) );

// ---------------------------------------------------------------------------
// THE DEFECT: the paint sat inside the bind guard, so it happened exactly once.
// ---------------------------------------------------------------------------

test( "initFlowRatioControls: a FAILED first paint is retried on the next tick", async () => {
  const ui = newUI();
  let call = 0;
  // DISCRIMINATING: tick 1 gets a 500, tick 2 gets the real payload. A one-shot
  // paint leaves the panel hidden forever and fails the second assertion.
  ui.authedFetch = async ( url: string ) => {
    if ( url !== SETTINGS_URL ) return fakeResponse( 200, true, {} ) as never;
    call += 1;
    return fakeResponse( call === 1 ? 500 : 200, call !== 1, call === 1 ? null : GOOD ) as never;
  };

  ui.initFlowRatioControls();
  await settle();
  assert.equal( root().hidden, true, "tick 1 failed, so the cluster stays hidden" );

  ui.initFlowRatioControls();
  await settle();
  assert.equal( root().hidden, false, "tick 2 succeeded, so the cluster is now visible" );
  assert.equal( call, 2, "tick 2 actually re-fetched — it did not short-circuit at a guard" );
  assert.equal( statusTxt(), "from config" );
} );

test( "initFlowRatioControls: the listeners bind ONCE however many ticks run", async () => {
  const ui = newUI();
  const patches: unknown[] = [];
  let settingsCalls = 0;
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string; body?: string };
    if ( url === SETTINGS_URL && o.method === "PATCH" ) {
      patches.push( JSON.parse( o.body! ) );
      return fakeResponse( 200, true, GOOD ) as never;
    }
    if ( url === SETTINGS_URL ) { settingsCalls += 1; return fakeResponse( 500, false, null ) as never; }
    return fakeResponse( 200, true, {} ) as never;
  };

  // Three ticks, every one a FAILED paint — the retry path is exactly the one that
  // would rebind if the bind and the paint were still sharing a guard.
  ui.initFlowRatioControls(); await settle();
  ui.initFlowRatioControls(); await settle();
  ui.initFlowRatioControls(); await settle();
  assert.equal( settingsCalls, 3, "each failed tick retried the paint" );

  slider( "flow-ratio-threshold" ).value = "150";
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "change" ) );
  await settle();
  assert.equal( patches.length, 1,
    "one operator change must PATCH once — a rebind would multiply the writes" );
  assert.deepEqual( patches[ 0 ], { allow_below: 1.5 },
    "the slider shows 150% and the WIRE carries the ratio 1.5 — converting in one place only" );
} );

test( "initFlowRatioControls: a SUCCEEDED paint is not refetched on later ticks", async () => {
  const ui = newUI();
  let settingsCalls = 0;
  ui.authedFetch = async ( url: string ) => {
    if ( url === SETTINGS_URL ) { settingsCalls += 1; return fakeResponse( 200, true, GOOD ) as never; }
    return fakeResponse( 200, true, {} ) as never;
  };
  ui.initFlowRatioControls(); await settle();
  ui.initFlowRatioControls(); await settle();
  ui.initFlowRatioControls(); await settle();
  assert.equal( settingsCalls, 1,
    "repainting every tick would fight an operator mid-drag; one success is enough" );
  assert.equal( root().hidden, false );
} );

test( "initFlowRatioControls: overlapping ticks keep at most ONE fetch in flight", async () => {
  const ui = newUI();
  let settingsCalls = 0;
  let release: ( () => void ) | null = null;
  ui.authedFetch = async ( url: string ) => {
    if ( url !== SETTINGS_URL ) return fakeResponse( 200, true, {} ) as never;
    settingsCalls += 1;
    await new Promise<void>( r => { release = r; } );
    return fakeResponse( 200, true, GOOD ) as never;
  };
  ui.initFlowRatioControls();   // starts a fetch and parks it
  ui.initFlowRatioControls();   // must NOT start a second one
  assert.equal( settingsCalls, 1 );
  release!();
  await settle();
  assert.equal( root().hidden, false );
} );

test( "initFlowRatioControls: no cluster on the page is a no-op that fetches nothing", async () => {
  document.body.replaceChildren();          // the multiplexer page: same file, no cluster
  const ui = newUI();
  let calls = 0;
  ui.authedFetch = async () => { calls += 1; return fakeResponse( 200, true, GOOD ) as never; };
  assert.doesNotThrow( () => ui.initFlowRatioControls() );
  await settle();
  assert.equal( calls, 0, "a page without the cluster must not poll its settings" );
} );

// ---------------------------------------------------------------------------
// _paintFlowRatioSettings — it now REPORTS whether it painted, because the caller
// retries on false.
// ---------------------------------------------------------------------------

test( "_paintFlowRatioSettings: a good payload paints, unhides, and returns true", () => {
  const ui = newUI();
  assert.equal( ui._paintFlowRatioSettings( GOOD ), true );
  assert.equal( root().hidden, false );
  // PERCENT on screen, ratio on the wire: allow_below 1.0 is a 100% gate.
  assert.equal( slider( "flow-ratio-threshold" ).value, "100" );
  assert.equal( text( "flow-ratio-threshold-value" ), "100%" );
  // DAYS on screen, HOURS on the wire: window_hours 24 is a one-day slider.
  assert.equal( slider( "flow-ratio-window" ).value, "1" );
  assert.equal( text( "flow-ratio-window-value" ), "1d" );
  assert.equal( statusTxt(), "from config" );
} );

test( "_paintFlowRatioSettings: an override is NAMED, since a number cannot say so itself", () => {
  const ui = newUI();
  ui._paintFlowRatioSettings( { ...GOOD, threshold_source: "override" } );
  assert.equal( statusTxt(), "saved override" );
  ui._paintFlowRatioSettings( { ...GOOD, window_source: "override" } );
  assert.equal( statusTxt(), "saved override" );
} );

test( "_paintFlowRatioSettings: every unusable payload HIDES and returns false", () => {
  const ui = newUI();
  const junk: unknown[] = [
    null,
    undefined,
    {},
    { allow_below: 1.0 },                              // no window
    { window_hours: 24 },                              // no threshold
    { allow_below: "1.0", window_hours: 24 },          // a string, not a number
    { allow_below: 1.0, window_hours: null },
    { allow_below: NaN, window_hours: 24 },
    { allow_below: Infinity, window_hours: 24 }
  ];
  for ( const payload of junk ) {
    root().hidden = false;
    const label = JSON.stringify( payload ) ?? "undefined";
    assert.equal( ui._paintFlowRatioSettings( payload ), false, label );
    assert.equal( root().hidden, true,
      `sliders must not sit at HTML defaults showing a threshold the gate is not using: ${label}` );
  }
} );

test( "_paintFlowRatioSettings: no cluster returns false rather than throwing", () => {
  document.body.replaceChildren();
  assert.equal( newUI()._paintFlowRatioSettings( GOOD ), false );
} );

// ---------------------------------------------------------------------------
// fetchFlowRatioSettings — every failure returns null, none throw, and the real
// ones announce themselves through error() rather than the debug-gated log().
// ---------------------------------------------------------------------------

test( "fetchFlowRatioSettings: a 2xx returns the payload", async () => {
  const ui = newUI();
  const seen: string[] = [];
  ui.authedFetch = async ( url: string ) => { seen.push( url ); return fakeResponse( 200, true, GOOD ) as never; };
  assert.deepEqual( await ui.fetchFlowRatioSettings(), GOOD );
  assert.deepEqual( seen, [ SETTINGS_URL ] );
} );

test( "fetchFlowRatioSettings: every failure shape returns null and SAYS SO OUT LOUD", async () => {
  const ui = newUI();

  ui.authedFetch = async () => fakeResponse( 401, false, null ) as never;
  assert.equal( await ui.fetchFlowRatioSettings(), null, "401" );

  ui.authedFetch = async () => fakeResponse( 500, false, null ) as never;
  assert.equal( await ui.fetchFlowRatioSettings(), null, "500" );

  ui.authedFetch = async () => { throw new Error( "ECONNREFUSED" ); };
  assert.equal( await ui.fetchFlowRatioSettings(), null, "network throw" );

  ui.authedFetch = async () => ( { status: 200, ok: true,
                                   json: async () => { throw new Error( "bad json" ); } } ) as never;
  assert.equal( await ui.fetchFlowRatioSettings(), null, "unparseable body" );

  ui.authedFetch = async () => fakeResponse( 200, true, "not an object" ) as never;
  assert.equal( await ui.fetchFlowRatioSettings(), null, "wrong shape" );

  // The CHANNEL is the point: log() is gated on this.debug, so with debug off a
  // silent failure is indistinguishable from a control nobody ever built.
  assert.equal( errors.length, 4,
    "the two HTTP failures and the two throws each reached error()" );
} );

// ---------------------------------------------------------------------------
// saveFlowRatioSettings / resetFlowRatioSettings
// ---------------------------------------------------------------------------

test( "saveFlowRatioSettings: repaints from the SERVER's answer, never from the request", async () => {
  const ui = newUI();
  // The operator asks for 2.5; the server clamps to 1.75. Echoing the request would
  // leave the slider showing a number the gate is not using.
  const CLAMPED = { ...GOOD, allow_below: 1.75, threshold_source: "override" };
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string };
    if ( url === SETTINGS_URL && o.method === "PATCH" ) return fakeResponse( 200, true, CLAMPED ) as never;
    return fakeResponse( 200, true, { ratio: 0.5, window_hours: 24 } ) as never;
  };
  assert.deepEqual( await ui.saveFlowRatioSettings( { allow_below: 2.5 } ), CLAMPED );
  assert.equal( text( "flow-ratio-threshold-value" ), "175%" );
  assert.equal( statusTxt(), "saved override" );
} );

test( "saveFlowRatioSettings: a 403 repaints to the server's real values, so no slider lies", async () => {
  const ui = newUI();
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string };
    if ( o.method === "PATCH" ) return fakeResponse( 403, false, null ) as never;
    return fakeResponse( 200, true, GOOD ) as never;
  };
  assert.equal( await ui.saveFlowRatioSettings( { allow_below: 2.5 } ), null );
  assert.equal( slider( "flow-ratio-threshold" ).value, "100",
    "the refused value must not be left sitting on the control" );
} );

test( "saveFlowRatioSettings: a non-403 failure names its status", async () => {
  const ui = newUI();
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string };
    if ( o.method === "PATCH" ) return fakeResponse( 422, false, null ) as never;
    return fakeResponse( 500, false, null ) as never;   // the follow-up repaint fails too
  };
  assert.equal( await ui.saveFlowRatioSettings( { window_hours: 999 } ), null );
  assert.equal( statusTxt(), "not saved (HTTP 422)" );
} );

test( "saveFlowRatioSettings: a network throw is reported, not swallowed", async () => {
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "ECONNREFUSED" ); };
  assert.equal( await ui.saveFlowRatioSettings( { allow_below: 1.2 } ), null );
  assert.equal( statusTxt(), "not saved (network)" );
} );

test( "saveFlowRatioSettings: a missing cluster does not turn a failed write into a throw", async () => {
  document.body.replaceChildren();
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "ECONNREFUSED" ); };
  assert.equal( await ui.saveFlowRatioSettings( { allow_below: 1.2 } ), null );

  ui.authedFetch = async () => fakeResponse( 403, false, null ) as never;
  assert.equal( await ui.saveFlowRatioSettings( { allow_below: 1.2 } ), null );
} );

test( "resetFlowRatioSettings: DELETEs, then repaints from what config actually says", async () => {
  const ui = newUI();
  const methods: string[] = [];
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string };
    if ( o.method === "DELETE" ) { methods.push( "DELETE" ); return fakeResponse( 200, true, GOOD ) as never; }
    return fakeResponse( 200, true, { ratio: 0.5, window_hours: 24 } ) as never;
  };
  assert.deepEqual( await ui.resetFlowRatioSettings(), GOOD );
  assert.deepEqual( methods, [ "DELETE" ] );
  assert.equal( statusTxt(), "from config" );
  assert.equal( root().hidden, false );
} );

test( "resetFlowRatioSettings: 403 and other failures each name themselves", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 403, false, null ) as never;
  assert.equal( await ui.resetFlowRatioSettings(), null );
  assert.equal( statusTxt(), "not reset — admin only" );

  ui.authedFetch = async () => fakeResponse( 500, false, null ) as never;
  assert.equal( await ui.resetFlowRatioSettings(), null );
  assert.equal( statusTxt(), "not reset (HTTP 500)" );
} );

test( "resetFlowRatioSettings: a missing cluster and a network throw are both survivable", async () => {
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "ECONNREFUSED" ); };
  assert.equal( await ui.resetFlowRatioSettings(), null );

  document.body.replaceChildren();
  ui.authedFetch = async () => fakeResponse( 403, false, null ) as never;
  assert.equal( await ui.resetFlowRatioSettings(), null );
} );

// ---------------------------------------------------------------------------
// The drag contract: `input` moves the LABEL only, `change` is what writes.
// ---------------------------------------------------------------------------

test( "the sliders label on `input` and only WRITE on `change`", async () => {
  const ui = newUI();
  let patches = 0;
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string };
    if ( o.method === "PATCH" ) patches += 1;
    return fakeResponse( 200, true, GOOD ) as never;
  };
  ui.initFlowRatioControls();
  await settle();

  slider( "flow-ratio-threshold" ).value = "150";
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "input" ) );
  slider( "flow-ratio-window" ).value = "7";
  slider( "flow-ratio-window" ).dispatchEvent( new Event( "input" ) );
  assert.equal( text( "flow-ratio-threshold-value" ), "150%" );
  assert.equal( text( "flow-ratio-window-value" ), "7d" );
  assert.equal( patches, 0, "a drag must not PATCH on every pixel" );

  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "change" ) );
  slider( "flow-ratio-window" ).dispatchEvent( new Event( "change" ) );
  await settle();
  assert.equal( patches, 2, "releasing each slider writes exactly once" );
} );

test( "the Reset button is wired to resetFlowRatioSettings", async () => {
  const ui = newUI();
  let deletes = 0;
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string };
    if ( o.method === "DELETE" ) deletes += 1;
    return fakeResponse( 200, true, GOOD ) as never;
  };
  ui.initFlowRatioControls();
  await settle();
  document.getElementById( "flow-ratio-reset" )!.dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( deletes, 1 );
} );

// ---------------------------------------------------------------------------
// THE GATE VERDICT AS A COLOUR, and the live preview while dragging.
// Spec: planning-is-prompting src/rnd/2026.09.01-gate-display-compaction.md
// ---------------------------------------------------------------------------

const clause = (): HTMLElement => document.getElementById( "task-list-flow-ratio" )!;

function paintedUI( threshold: number ): FlowUI {
  const ui = newUI();
  ui._flowRatioThreshold = threshold;
  return ui;
}

test( "the colour follows the VERDICT, not 'low is green'", () => {
  const ui = paintedUI( 1.0 );
  ui._renderFlowRatio( { ratio: 0.25, created: 5, closed: 20, window_hours: 24 } );
  assert.equal( clause().classList.contains( "flow-ratio-open" ), true, "0.25 < 1.0 admits" );
  assert.equal( clause().classList.contains( "flow-ratio-closed" ), false );

  ui._renderFlowRatio( { ratio: 1.4, created: 14, closed: 10, window_hours: 24 } );
  assert.equal( clause().classList.contains( "flow-ratio-closed" ), true, "1.4 >= 1.0 refuses" );
  assert.equal( clause().classList.contains( "flow-ratio-open" ), false );
} );

test( "EXACTLY at the threshold reads closed — the comparison is strict", () => {
  // The case a reader most easily guesses wrong: 100% against a 100% threshold.
  const ui = paintedUI( 1.0 );
  ui._renderFlowRatio( { ratio: 1.0, created: 10, closed: 10, window_hours: 24 } );
  assert.equal( clause().textContent, " · 1d  ·  100%  ·  10 created / 10 closed" );
  assert.equal( clause().classList.contains( "flow-ratio-closed" ), true,
    "allow is `ratio < threshold`, so exactly-at is a refusal and must not read green" );
} );

test( "nothing closed is INFINITY and refuses; an idle window is a dash and admits", () => {
  const ui = paintedUI( 1.0 );
  ui._renderFlowRatio( { ratio: null, created: 4, closed: 0, window_hours: 24 } );
  assert.equal( clause().textContent, " · 1d  ·  ∞  ·  4 created / 0 closed" );
  assert.equal( clause().classList.contains( "flow-ratio-closed" ), true,
    "a window where nothing was finished is exactly what the gate is for" );

  ui._renderFlowRatio( { ratio: null, created: 0, closed: 0, window_hours: 24 } );
  assert.equal( clause().textContent, " · 1d  ·  —  ·  0 created / 0 closed" );
  assert.equal( clause().classList.contains( "flow-ratio-open" ), true,
    "an idle window is not a failing window" );
} );

test( "the hover carries the long form the short label drops", () => {
  const ui = paintedUI( 1.0 );
  ui._renderFlowRatio( { ratio: 0.25, created: 5, closed: 19, window_hours: 24 } );
  assert.equal( clause().title,
    "Closed vs New Ratio — 1d  ·  25%  ·  5 created / 19 closed",
    "the counts move to the hover so 200%-on-two-tickets stays checkable" );
} );

test( "dragging the slider moves the COLOUR, never the number", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 200, true, GOOD ) as never;
  ui._renderFlowRatio( { ratio: 1.4, created: 14, closed: 10, window_hours: 24 } );
  ui.initFlowRatioControls();
  await settle();

  const before = clause().textContent;
  assert.equal( clause().classList.contains( "flow-ratio-closed" ), true, "1.4 >= 1.0" );

  // Drag the threshold up past the ratio: the gate would now admit.
  slider( "flow-ratio-threshold" ).value = "200";
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "input" ) );
  assert.equal( clause().textContent, before,
    "the ratio measures the last 24h — the slider moves the comparison line, not it" );
  assert.equal( clause().classList.contains( "flow-ratio-open" ), true,
    "1.4 < 2.0, so the preview shows the gate opening" );
} );

test( "an UNCOMMITTED preview is marked, so it cannot be misread as state", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 200, true, GOOD ) as never;
  ui._renderFlowRatio( { ratio: 1.4, created: 14, closed: 10, window_hours: 24 } );
  ui.initFlowRatioControls();
  await settle();
  assert.equal( clause().classList.contains( "flow-ratio-preview" ), false, "committed to begin with" );

  slider( "flow-ratio-threshold" ).value = "200";
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "input" ) );
  assert.equal( clause().classList.contains( "flow-ratio-preview" ), true,
    "while dragging, the colour is a hypothetical and must say so" );

  // Committing the value clears the marker — the preview becomes the state.
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "change" ) );
  await settle();
  assert.equal( clause().classList.contains( "flow-ratio-preview" ), false,
    "a saved value is no longer a preview" );
} );

test( "_paintFlowRatioVerdict: absent clause is a no-op, not a throw", () => {
  document.body.replaceChildren();
  assert.doesNotThrow( () => newUI()._paintFlowRatioVerdict() );
  assert.doesNotThrow( () => newUI()._paintFlowRatioVerdict( 1.5 ) );
} );

test( "_flowRatioIsOpen: with no threshold known yet, nothing is accused of refusing", () => {
  const ui = newUI();
  assert.equal( ui._flowRatioIsOpen( { ratio: 99 }, undefined ), true,
    "before settings load there is no line to compare against; do not paint a red verdict" );
} );

// ── DAYS ON SCREEN, HOURS ON THE WIRE ────────────────────────────────────────
//
// Rick, 2026-09-01: "as an end user I don't care about values such as 82 hours".
// The slider moved to days; the store, the INI key and the PATCH body did not.
// These tests exist to keep those two facts from drifting apart, because a unit
// slip here is silent — a slider that PATCHes 7 instead of 168 still paints a
// plausible number and still goes green on every assertion that only reads the
// label.

test( "the window slider PATCHES HOURS while it DISPLAYS DAYS", async () => {
  const ui = newUI();
  let body: Record<string, unknown> | null = null;
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string; body?: string };
    if ( o.method === "PATCH" ) body = JSON.parse( o.body as string );
    return fakeResponse( 200, true, GOOD ) as never;
  };
  ui.initFlowRatioControls();
  await settle();

  slider( "flow-ratio-window" ).value = "7";
  slider( "flow-ratio-window" ).dispatchEvent( new Event( "change" ) );
  await settle();

  // THE WHOLE POINT OF THIS TEST IS THE 168. Asserting only that a PATCH happened
  // would pass just as happily with the raw 7 on the wire, which the server would
  // clamp to a seven-HOUR window — a change of setting nobody asked for, invisible
  // on screen because the slider would paint "7d" straight back.
  assert.deepEqual( body, { window_hours: 168 },
    "7 days must reach the API as 168 hours" );
} );

test( "a saved override that is not a whole number of days paints at the nearest day", () => {
  const ui = newUI();
  // 82h is Rick's own example of a number no operator wants to read.
  ui._paintFlowRatioSettings( { ...GOOD, window_hours: 82 } );
  assert.equal( text( "flow-ratio-window-value" ), "3d" );
  assert.equal( slider( "flow-ratio-window" ).value, "3" );
} );

test( "a sub-day window floors at 1d rather than reading as 0d", () => {
  const ui = newUI();
  // 0d would look like the window had been switched off. It has not — the gate
  // still counts over that hour.
  ui._paintFlowRatioSettings( { ...GOOD, window_hours: 1 } );
  assert.equal( text( "flow-ratio-window-value" ), "1d" );
  assert.equal( slider( "flow-ratio-window" ).value, "1" );
} );

test( "_flowRatioWindowDays declines to render a window it cannot read", () => {
  const ui = newUI();
  for ( const bad of [ 0, -24, NaN, Infinity, null, undefined, "168" ] ) {
    assert.equal( ui._flowRatioWindowDays( bad as never ), null,
      `${String( bad )} is not a window` );
  }
  // The positive control: without it every assertion above would pass on a helper
  // that returned null for everything.
  assert.equal( ui._flowRatioWindowDays( 168 ), 7 );
} );

test( "the hover text names DAYS, not hours", () => {
  const ui = newUI();
  const long = ui._flowRatioLongForm(
    { ratio: 0.25, created: 5, closed: 20, window_hours: 168 } );
  assert.match( long, /7d/ );
  assert.match( long, /5 created \/ 20 closed/,
    "the counts on the face of it are the whole point of Rick's third tweak" );
  assert.doesNotMatch( long, /hrs/,
    "the long form was the last place the operator still saw raw hours" );
} );

test( "the threshold slider can reach 0, and 0 PATCHES as 0 rather than being dropped", async () => {
  const ui = newUI();
  let body: Record<string, unknown> | null = null;
  ui.authedFetch = async ( url: string, opts?: unknown ) => {
    const o = ( opts || {} ) as { method?: string; body?: string };
    if ( o.method === "PATCH" ) body = JSON.parse( o.body as string );
    return fakeResponse( 200, true, GOOD ) as never;
  };
  ui.initFlowRatioControls();
  await settle();

  const el = slider( "flow-ratio-threshold" );
  el.value = "0";
  // A slider whose min was still 10 would clamp this back to "10" and the test
  // would fail here rather than on the PATCH — which is the fixture doing its job.
  assert.equal( el.value, "0", "min must allow 0" );
  el.dispatchEvent( new Event( "change" ) );
  await settle();

  // 0 is falsy. A guard written as `if ( value )` would silently drop it from the
  // body and leave the gate at whatever it was, with the slider showing 0%.
  assert.deepEqual( body, { allow_below: 0 } );
} );
