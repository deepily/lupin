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
        <input type="range" id="flow-ratio-threshold" min="0.1" max="3" step="0.05" />
      </span>
      <span class="flow-ratio-field">
        <label for="flow-ratio-window">Window
          <output id="flow-ratio-window-value">&mdash;</output></label>
        <input type="range" id="flow-ratio-window" min="1" max="336" step="1" />
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

  slider( "flow-ratio-threshold" ).value = "1.5";
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "change" ) );
  await settle();
  assert.equal( patches.length, 1,
    "one operator change must PATCH once — a rebind would multiply the writes" );
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
  assert.equal( slider( "flow-ratio-threshold" ).value, "1" );
  assert.equal( text( "flow-ratio-threshold-value" ), "1.00" );
  assert.equal( slider( "flow-ratio-window" ).value, "24" );
  assert.equal( text( "flow-ratio-window-value" ), "24h" );
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
  assert.equal( text( "flow-ratio-threshold-value" ), "1.75" );
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
  assert.equal( slider( "flow-ratio-threshold" ).value, "1",
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

  slider( "flow-ratio-threshold" ).value = "2.25";
  slider( "flow-ratio-threshold" ).dispatchEvent( new Event( "input" ) );
  slider( "flow-ratio-window" ).value = "168";
  slider( "flow-ratio-window" ).dispatchEvent( new Event( "input" ) );
  assert.equal( text( "flow-ratio-threshold-value" ), "2.25" );
  assert.equal( text( "flow-ratio-window-value" ), "168h" );
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
