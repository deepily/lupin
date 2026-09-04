// THE FLEET-SIZE DIAL — the control that reports the cap the spawn path enforces.
//
// Rick ruled by voice 2026-09-03 that the dial's maximum must be CONFIGURABLE —
// `cc session fleet size cap maximum`, shipping 18 — so he can tweak it over time.
//
// 🔴 WHAT THESE TESTS ARE FOR, and it is not "does it paint". Two implementations would
// look perfect on screen today and be wrong tomorrow:
//
//   1. THE CEILING BAKED IN. `max="18"` in the markup, or `18` in the painter, agrees
//      with today's key exactly — until somebody moves the key. Every assertion written
//      against the shipped value passes on that implementation, which is why the paints
//      below feed 42 and 7 and never 18.
//   2. THE CEILING CLAMPED to something else. A dial silently trimmed below what the
//      operator typed cannot be told apart from a key that was ignored.
//
// Harness copied from fleet_status_panel.test.ts: load the class via
// vm.runInThisContext sliced before the DOM-ready init, Object.create the prototype to
// skip the constructor, hand-set the few fields the methods read, drive under happy-dom.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/fleet_size_cap_dial.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type DialUI = Record<string, unknown> & {
  fetchFleetSizeCap: () => Promise<Record<string, unknown> | null>;
  _fleetSizeCapEls: () => Record<string, HTMLElement> | null;
  _paintFleetSizeCap: ( payload: unknown ) => boolean;
  refreshFleetSizeCap: () => Promise<boolean>;
  refreshFleetStatus: () => Promise<void>;
  authedFetch: ( url: string, init?: unknown ) => Promise<unknown>;
  error: ( msg: string ) => void;
  log: ( msg: string ) => void;
  _fleetStatusFetchInFlight: boolean;
};

function newUI(): DialUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as DialUI;
  ui.debug                     = false;
  ui.log                       = (): void => {};
  ui.error                     = (): void => {};
  ui._fleetStatusFetchInFlight = false;
  return ui;
}

// The dial cluster as it ships: NO `max` attribute — that is the point.
function buildDialDOM(): void {
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.id = "section-fleet-status";
  section.innerHTML = `
    <div class="fleet-size-cap-controls" id="fleet-size-cap-controls" hidden>
      <span class="fleet-size-cap-field">
        <label for="fleet-size-cap">Fleet cap <output id="fleet-size-cap-value">—</output></label>
        <input type="range" id="fleet-size-cap" min="1" step="1" disabled />
      </span>
      <span id="fleet-size-cap-status"></span>
    </div>
    <div id="fleet-status-container"></div>`;
  document.body.appendChild( section );
}

function fakeResponse( status: number, ok: boolean, jsonBody: unknown ): unknown {
  return { status, ok, json: async () => jsonBody };
}

const slider = (): HTMLInputElement =>
  document.getElementById( "fleet-size-cap" ) as HTMLInputElement;
const root = (): HTMLElement =>
  document.getElementById( "fleet-size-cap-controls" ) as HTMLElement;

beforeEach( () => { document.body.replaceChildren(); } );

// ─────────────────────────── the ceiling comes from the payload ───────────────────────

test( "the slider's max is the payload's ceiling, not the shipped 18", () => {
  const ui = newUI();
  buildDialDOM();
  assert.equal( ui._paintFleetSizeCap( { cap: 8, ceiling: 42 } ), true );
  assert.equal( slider().max, "42", "the ceiling is served verbatim" );
  assert.notEqual( slider().max, "18", "18 would pass on a hardcoded implementation" );
} );

test( "the floor is 1 and the handle sits on the live cap", () => {
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 5, ceiling: 42 } );
  assert.equal( slider().min, "1" );
  assert.equal( slider().value, "5" );
  assert.equal( document.getElementById( "fleet-size-cap-value" )!.textContent, "5 / 42" );
} );

test( "a second paint moves the ceiling — it is read every time, never cached", () => {
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 8, ceiling: 42 } );
  ui._paintFleetSizeCap( { cap: 3, ceiling: 7 } );
  assert.equal( slider().max, "7", "a painter that set max once would still read 42" );
  assert.equal( slider().value, "3" );
} );

// ─────────────────────────── it declines rather than lying ────────────────────────────

test( "an unusable payload leaves the cluster HIDDEN, never parked at HTML defaults", () => {
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 8, ceiling: 42 } );
  assert.equal( root().hidden, false, "positive control: it does paint when it can" );

  assert.equal( ui._paintFleetSizeCap( null ), false );
  assert.equal( root().hidden, true );

  ui._paintFleetSizeCap( { cap: 8, ceiling: 42 } );
  assert.equal( ui._paintFleetSizeCap( { cap: 8 } ), false, "a missing ceiling is unusable" );
  assert.equal( root().hidden, true );
} );

test( "a page without the cluster is a no-op, not a throw", () => {
  const ui = newUI();
  document.body.replaceChildren();
  assert.equal( ui._paintFleetSizeCap( { cap: 8, ceiling: 42 } ), false );
} );

test( "the control says on its face that it reports rather than sets", () => {
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 8, ceiling: 18 } );
  assert.match( document.getElementById( "fleet-size-cap-status" )!.textContent!, /read-only/ );
  assert.equal( slider().disabled, true );
} );

// ─────────────────────────── the fetch ────────────────────────────────────────────────

test( "fetchFleetSizeCap reads /api/arbiter/fleet-size-cap and returns the body", async () => {
  const ui = newUI();
  const seen: string[] = [];
  ui.authedFetch = async ( url: string ) => {
    seen.push( url );
    return fakeResponse( 200, true, { cap: 8, ceiling: 42 } );
  };
  assert.deepEqual( await ui.fetchFleetSizeCap(), { cap: 8, ceiling: 42 } );
  assert.deepEqual( seen, [ "/api/arbiter/fleet-size-cap" ] );
} );

test( "a non-2xx returns null and REPORTS via error(), which is not gated on debug", async () => {
  const ui = newUI();
  let reported = "";
  ui.error = ( msg: string ) => { reported = msg; };
  ui.authedFetch = async () => fakeResponse( 503, false, null );
  assert.equal( await ui.fetchFleetSizeCap(), null );
  assert.match( reported, /503/ );
} );

test( "a network throw returns null rather than propagating", async () => {
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "offline" ); };
  assert.equal( await ui.fetchFleetSizeCap(), null );
} );

// ─────────────────────────── the wiring ───────────────────────────────────────────────

test( "refreshFleetStatus REACHES the dial — the table and the cap are read together", async () => {
  const ui = newUI();
  buildDialDOM();
  const seen: string[] = [];
  ui.authedFetch = async ( url: string ) => {
    seen.push( url );
    if ( url === "/api/arbiter/fleet-size-cap" ) return fakeResponse( 200, true, { cap: 6, ceiling: 42 } );
    return fakeResponse( 200, true, { status: "ok", fleet_arbiter: { sessions: [] } } );
  };

  await ui.refreshFleetStatus();

  assert.ok( seen.includes( "/api/arbiter/fleet-size-cap" ),
             `the refresh must reach the dial's endpoint — saw ${JSON.stringify( seen )}` );
  assert.equal( slider().max, "42", "and the answer must reach the control" );
  assert.equal( slider().value, "6" );
} );
