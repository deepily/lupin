// Row 6f72dc83 — the skeleton crew toggle in the legacy Fleet Status pane.
//
// Design: src/rnd/v0.2.2/2026.10.10-skeleton-crew-toggle-design.md §5 (the clients) and §9 (build row 9).
// Server contract: `skeleton_crew` (boolean) rides GET and PUT /api/arbiter/fleet-size-cap;
// PUT /api/arbiter/skeleton-crew takes { "on": bool } and answers the same body, re-read from the file.
//
// The switch lives inside #fleet-size-cap-controls, beside the dial, and is painted by the
// same _paintFleetSizeCap call, so it is never shown without a payload and never shown for a
// server that does not send the field (a switch that does nothing is worse than none).
//
// Harness copied from fleet_size_cap_dial.test.ts.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/skeleton_crew_toggle.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE               = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS   = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const NOTIFICATIONS_HTML = resolve( HERE, "../../../lupin_app/static/html/notifications.html" );

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

type Body = Record<string, unknown>;
type Call = { url: string; init?: { method?: string; body?: string } };
type CrewUI = Record<string, unknown> & {
  _paintFleetSizeCap: ( payload: unknown ) => boolean;
  refreshFleetSizeCap: () => Promise<boolean>;
  setSkeletonCrew: ( on: boolean ) => Promise<Body | null>;
  _wireSkeletonCrew: () => boolean;
  authedFetch: ( url: string, init?: Call[ "init" ] ) => Promise<unknown>;
  error: ( msg: string ) => void;
  log: ( msg: string ) => void;
};

const CAP = { cap: 6, ceiling: 18, live: { total: 5, managers: 2, workers: 3 } };
const OFF = { ...CAP, skeleton_crew: false };
const ON  = { ...CAP, skeleton_crew: true };

let errors: string[];

function newUI(): CrewUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as CrewUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = ( msg: string ): void => { errors.push( msg ); };
  return ui;
}

// The cluster exactly as the page ships it, cut out of the real HTML.
function shippedCluster(): string {
  const page  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const start = page.indexOf( 'id="fleet-size-cap-controls"' );
  const end   = page.indexOf( 'id="fleet-status-container"' );
  assert.ok( start > 0 && end > start, "the page must carry the cap cluster above the table" );
  return `<div ${page.slice( start, end ).replace( /<div\s*$/, "" )}`;
}

function build(): void {
  document.body.replaceChildren();
  document.body.innerHTML = shippedCluster();
}

function fakeResponse( status: number, ok: boolean, jsonBody: unknown ): unknown {
  return { status, ok, json: async () => jsonBody };
}

const toggle = (): HTMLInputElement => document.getElementById( "skeleton-crew-toggle" ) as HTMLInputElement;
const state  = (): HTMLElement      => document.getElementById( "skeleton-crew-state" ) as HTMLElement;
const field  = (): HTMLElement      => document.getElementById( "skeleton-crew-field" ) as HTMLElement;
const cluster = (): HTMLElement     => document.getElementById( "fleet-size-cap-controls" ) as HTMLElement;

beforeEach( () => { document.body.replaceChildren(); errors = []; } );

// ─────────────────────────── the page as shipped ────────────────────────────────────

test( "the shipped page carries a checkbox switch inside the cap cluster, hidden until painted", () => {
  build();
  assert.equal( toggle().type, "checkbox" );
  assert.equal( toggle().getAttribute( "role" ), "switch" );
  assert.equal( toggle().closest( "#fleet-size-cap-controls" )!.id, "fleet-size-cap-controls" );
  assert.equal( toggle().getAttribute( "data-testid" ), "skeleton-crew-toggle" );
  assert.equal( field().hidden, true, "no payload, no switch" );
  assert.equal( toggle().getAttribute( "aria-labelledby" ), state().id );
} );

// ─────────────────────────── paint ──────────────────────────────────────────────────

test( "the state is said in TEXT and the checkbox agrees: OFF, then ON", () => {
  const ui = newUI();
  build();
  assert.equal( ui._paintFleetSizeCap( OFF ), true );
  assert.equal( field().hidden, false );
  assert.equal( state().textContent, "Skeleton crew: OFF" );
  assert.equal( toggle().checked, false );
  assert.equal( toggle().disabled, false );
  assert.equal( toggle().getAttribute( "aria-checked" ), "false" );

  ui._paintFleetSizeCap( ON );
  assert.equal( state().textContent, "Skeleton crew: ON" );
  assert.equal( toggle().checked, true );
  assert.equal( toggle().getAttribute( "aria-checked" ), "true" );
} );

test( "a payload without a boolean `skeleton_crew` hides the switch but not the dial", () => {
  const ui = newUI();
  build();
  ui._paintFleetSizeCap( OFF );
  assert.equal( field().hidden, false, "positive control: it does show when the field is sent" );

  ui._paintFleetSizeCap( CAP );                  // an older server
  assert.equal( field().hidden, true );
  assert.equal( cluster().hidden, false, "the dial is unaffected" );

  ui._paintFleetSizeCap( { ...CAP, skeleton_crew: "yes" } );
  assert.equal( field().hidden, true, "only a real boolean counts" );
} );

test( "an unusable payload hides the whole cluster, switch included", () => {
  const ui = newUI();
  build();
  ui._paintFleetSizeCap( ON );
  assert.equal( ui._paintFleetSizeCap( null ), false );
  assert.equal( cluster().hidden, true );
} );

test( "a page without the switch is a no-op, not a throw (the dial still paints)", () => {
  const ui = newUI();
  document.body.innerHTML = `<div id="fleet-size-cap-controls" hidden>
    <output id="fleet-size-cap-value"></output><input type="range" id="fleet-size-cap" />
    <span id="fleet-size-cap-status"></span></div>`;
  assert.equal( ui._paintFleetSizeCap( ON ), true );
  assert.equal( ui._wireSkeletonCrew(), false );
} );

// ─────────────────────────── the write ──────────────────────────────────────────────

test( "setSkeletonCrew PUTs { on } to /api/arbiter/skeleton-crew and returns the server's re-read", async () => {
  const ui = newUI();
  const calls: Call[] = [];
  ui.authedFetch = async ( url, init ) => { calls.push( { url, init } ); return fakeResponse( 200, true, OFF ); };
  // The server read back "off" although "on" was asked: the caller must get "off".
  assert.deepEqual( await ui.setSkeletonCrew( true ), OFF );
  assert.equal( calls.length, 1 );
  assert.equal( calls[ 0 ].url, "/api/arbiter/skeleton-crew" );
  assert.equal( calls[ 0 ].init!.method, "PUT" );
  assert.deepEqual( JSON.parse( calls[ 0 ].init!.body! ), { on: true } );
} );

test( "a refusal returns null and reports the server's own detail via error()", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 403, false, { detail: "admin role required" } );
  assert.equal( await ui.setSkeletonCrew( true ), null );
  assert.deepEqual( errors, [ "Skeleton crew not saved: admin role required" ] );

  errors = [];
  ui.authedFetch = async () => ( { status: 500, ok: false, json: async () => { throw new Error( "not json" ); } } );
  assert.equal( await ui.setSkeletonCrew( false ), null );
  assert.deepEqual( errors, [ "Skeleton crew not saved: HTTP 500" ] );

  errors = [];
  ui.authedFetch = async () => fakeResponse( 422, false, { other: 1 } );
  await ui.setSkeletonCrew( false );
  assert.deepEqual( errors, [ "Skeleton crew not saved: HTTP 422" ] );
} );

test( "a network failure returns null and says so; a non-object 2xx body is null too", async () => {
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "offline" ); };
  assert.equal( await ui.setSkeletonCrew( true ), null );
  assert.deepEqual( errors, [ "Skeleton crew save failed: Error: offline" ] );

  ui.authedFetch = async () => fakeResponse( 200, true, null );
  assert.equal( await ui.setSkeletonCrew( true ), null );
} );

// ─────────────────────────── the wiring ─────────────────────────────────────────────

test( "change saves once, disables the switch with TEXT while in flight, then repaints from the server", async () => {
  const ui = newUI();
  build();
  ui._paintFleetSizeCap( OFF );
  ui._paintFleetSizeCap( OFF );                  // repeated paints must not re-bind

  let release!: ( r: unknown ) => void;
  const calls: Call[] = [];
  ui.authedFetch = ( url, init ) => {
    calls.push( { url, init } );
    return new Promise( ( r ) => { release = r; } );
  };

  toggle().checked = true;
  toggle().dispatchEvent( new Event( "change" ) );
  assert.equal( toggle().disabled, true );
  assert.equal( state().textContent, "Skeleton crew: turning ON…" );
  assert.equal( calls.length, 1, "one write per change, however many paints came before" );

  release( fakeResponse( 200, true, ON ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( toggle().disabled, false );
  assert.equal( toggle().checked, true );
  assert.equal( state().textContent, "Skeleton crew: ON" );
} );

test( "turning it OFF says turning OFF…", async () => {
  const ui = newUI();
  build();
  ui._paintFleetSizeCap( ON );
  let release!: ( r: unknown ) => void;
  ui.authedFetch = () => new Promise( ( r ) => { release = r; } );
  toggle().checked = false;
  toggle().dispatchEvent( new Event( "change" ) );
  assert.equal( state().textContent, "Skeleton crew: turning OFF…" );
  release( fakeResponse( 200, true, OFF ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( state().textContent, "Skeleton crew: OFF" );
} );

test( "a refused flip re-reads the file and the switch snaps back to what the server holds", async () => {
  const ui = newUI();
  build();
  ui._paintFleetSizeCap( OFF );
  const calls: Call[] = [];
  ui.authedFetch = async ( url, init ) => {
    calls.push( { url, init } );
    return init && init.method === "PUT"
      ? fakeResponse( 403, false, { detail: "admin role required" } )
      : fakeResponse( 200, true, OFF );
  };
  toggle().checked = true;
  toggle().dispatchEvent( new Event( "change" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.deepEqual( calls.map( ( c ) => c.url ), [ "/api/arbiter/skeleton-crew", "/api/arbiter/fleet-size-cap" ] );
  assert.equal( toggle().checked, false );
  assert.equal( state().textContent, "Skeleton crew: OFF" );
  assert.equal( toggle().disabled, false );
} );
