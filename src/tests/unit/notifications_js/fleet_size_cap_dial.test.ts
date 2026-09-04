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
  setFleetSizeCap: ( cap: number ) => Promise<Record<string, unknown> | null>;
  _wireFleetSizeCap: () => boolean;
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
        <input type="range" id="fleet-size-cap" min="1" step="1" />
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

test( "the status line reports WHO is occupying the cap", () => {
  // Replaced the old `/read-only/` assertion — see THE WRITE PATH section below for why.
  // The number that matters when you are about to move this dial is the headroom, and
  // "every session counts, managers included" is Rick's ruling, not a detail.
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 8, ceiling: 18, live: { total: 6, managers: 2, workers: 4 } } );
  const status = document.getElementById( "fleet-size-cap-status" )!.textContent!;
  assert.match( status, /6 live/ );
  assert.match( status, /2 manager/ );
  assert.match( status, /4 worker/ );
} );

test( "a missing split leaves the status line empty rather than inventing numbers", () => {
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 8, ceiling: 18, live: null } );
  assert.equal( document.getElementById( "fleet-size-cap-status" )!.textContent, "" );
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

// ─────────────────────────── THE WRITE PATH ───────────────────────────────────────────
//
// 🔴 WHAT CHANGED, AND THE TEST THAT WENT WITH IT. This file used to carry
// "the control says on its face that it reports rather than sets", asserting
// `/read-only/` in the status line and `disabled === true` on the handle. That test
// was CORRECT for a dial that reported, and it is replaced rather than deleted because
// the behaviour it pinned is the thing Rick asked to be removed: he specified a cap
// "ADJUSTABLE BY A SLIDER", and a read-only dial is a thermometer where he asked for a
// thermostat. The tests below pin the setting behaviour in its place.

test( "the control is enabled and does NOT advertise itself as read-only", () => {
  const ui = newUI();
  buildDialDOM();
  ui._paintFleetSizeCap( { cap: 8, ceiling: 18 } );
  assert.equal( slider().disabled, false, "the handle must be draggable" );
  assert.doesNotMatch( document.getElementById( "fleet-size-cap-status" )!.textContent!,
                       /read-only/,
                       "a status line still claiming read-only would be the one part of " +
                       "the change an operator can see, and it would be wrong" );
} );

test( "a DRAG does not write — only the readout moves", async () => {
  // 🔴 THE EXPENSIVE MISTAKE THIS PINS. A range input fires `input` continuously while
  // the handle moves, so binding the write there turns one drag from 4 to 18 into
  // fourteen PUTs — fourteen configuration-file writes, and a fleet cap that is briefly
  // every number in between. The write belongs on `change`, which fires once on release.
  const ui = newUI();
  buildDialDOM();
  const calls: unknown[] = [];
  ui.authedFetch = async ( url: string, init?: unknown ) => {
    calls.push( { url, init } );
    return fakeResponse( 200, true, { cap: 9, ceiling: 18 } );
  };
  ui._paintFleetSizeCap( { cap: 4, ceiling: 18 } );   // the paint binds the handlers

  slider().value = "9";
  slider().dispatchEvent( new Event( "input" ) );
  await Promise.resolve();

  assert.deepEqual( calls, [], "an `input` event must reach no network at all" );
  assert.equal( document.getElementById( "fleet-size-cap-value" )!.textContent, "9 / 18",
                "but the readout follows the handle, so the operator sees what they are picking" );
} );

test( "RELEASE writes — one PUT, carrying the value, to the cap endpoint", async () => {
  const ui = newUI();
  buildDialDOM();
  const calls: { url: string; init: { method?: string; body?: string } }[] = [];
  ui.authedFetch = async ( url: string, init: { method?: string; body?: string } ) => {
    calls.push( { url, init } );
    return fakeResponse( 200, true, { cap: 9, ceiling: 18, live: null } );
  };
  ui._paintFleetSizeCap( { cap: 4, ceiling: 18 } );   // the paint binds the handlers

  slider().value = "9";
  slider().dispatchEvent( new Event( "change" ) );
  await new Promise( ( done ) => setTimeout( done, 0 ) );

  assert.equal( calls.length, 1, `exactly one write per release — saw ${calls.length}` );
  assert.equal( calls[ 0 ].url, "/api/arbiter/fleet-size-cap" );
  assert.equal( calls[ 0 ].init.method, "PUT" );
  assert.deepEqual( JSON.parse( calls[ 0 ].init.body! ), { cap: 9 } );
} );

test( "the dial repaints from what the SERVER persisted, not from what was dragged", async () => {
  // 🔴 THE UNFALSIFIABLE-ECHO GUARD, and it is the reason the endpoint re-reads the file.
  // The server here answers 7 for a request of 9 — which is what a clamp, a concurrent
  // edit or a partial write would look like. A client that painted its own input would
  // show 9 and the spawn path would enforce 7, and nothing on screen would say so.
  const ui = newUI();
  buildDialDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { cap: 7, ceiling: 18, live: null } );
  ui._paintFleetSizeCap( { cap: 4, ceiling: 18 } );   // the paint binds the handlers

  slider().value = "9";
  slider().dispatchEvent( new Event( "change" ) );
  await new Promise( ( done ) => setTimeout( done, 0 ) );

  assert.equal( slider().value, "7", "the handle must follow the FILE, not the finger" );
  assert.equal( document.getElementById( "fleet-size-cap-value" )!.textContent, "7 / 18" );
} );

test( "a REFUSED write surfaces the server's reason and snaps the handle back", async () => {
  const ui = newUI();
  buildDialDOM();
  let reported = "";
  ui.error = ( msg: string ) => { reported = msg; };
  let call = 0;
  ui.authedFetch = async () => {
    call += 1;
    // The PUT is refused; the follow-up GET reports what is actually enforced.
    if ( call === 1 ) return fakeResponse( 422, false, { detail: "ceiling is 18" } );
    return fakeResponse( 200, true, { cap: 4, ceiling: 18, live: null } );
  };
  ui._paintFleetSizeCap( { cap: 4, ceiling: 18 } );   // the paint binds the handlers

  slider().value = "99";
  slider().dispatchEvent( new Event( "change" ) );
  await new Promise( ( done ) => setTimeout( done, 0 ) );

  assert.match( reported, /ceiling is 18/,
                "the server refuses for reasons an operator can act on; swallowing the " +
                "text turns a fixable config problem into a dead slider" );
  assert.equal( slider().value, "4",
                "and the handle returns to the cap that is actually enforced rather than " +
                "sitting at a number the operator never got" );
} );

test( "wiring twice binds once — a listener per refresh would multiply the writes", async () => {
  // The paint runs on EVERY fleet refresh. If the binding rode along with it, a page
  // open for ten refreshes would fire ten PUTs on one release.
  const ui = newUI();
  buildDialDOM();
  const calls: unknown[] = [];
  ui.authedFetch = async () => {
    calls.push( 1 );
    return fakeResponse( 200, true, { cap: 9, ceiling: 18, live: null } );
  };
  // ⚠️ THE PAINT ITSELF BINDS, so by the time this test calls the binder explicitly the
  // control is ALREADY wired — which is exactly the condition being tested. The paint is
  // the only moment the element is known to exist, and it runs on every fleet refresh;
  // the whole reason the binder is idempotent is that it is called from there.
  assert.equal( ui._paintFleetSizeCap( { cap: 4, ceiling: 18 } ), true );
  assert.equal( ui._wireFleetSizeCap(), false, "the paint already bound it" );
  assert.equal( ui._wireFleetSizeCap(), false, "and it stays bound exactly once" );
  ui._paintFleetSizeCap( { cap: 4, ceiling: 18 } );   // a second refresh must add nothing

  slider().value = "9";
  slider().dispatchEvent( new Event( "change" ) );
  await new Promise( ( done ) => setTimeout( done, 0 ) );

  assert.equal( calls.length, 1, `one release is one write — saw ${calls.length}` );
} );

test( "a page without the cluster wires nothing rather than throwing", () => {
  const ui = newUI();
  document.body.replaceChildren();
  assert.equal( ui._wireFleetSizeCap(), false );
} );
