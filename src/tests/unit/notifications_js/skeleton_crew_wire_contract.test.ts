// Row 6f72dc83 — wire contract test: a body the route really answered, through both clients.
//
// src/tests/fixtures/skeleton_crew_wire/responses.json is captured from the arbiter router's own
// handlers by test_skeleton_crew_wire_fixture.py, which fails when the route stops answering
// those bodies. So the input here is the server's output, not a shape typed from the design
// note. Each captured body is fed through the multiplexer (store, then renderer) and through the
// legacy paint, and the painted result is pinned to literals.
//
// The expected values below are written by hand. Derived from the fixture, they would always
// agree with it.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/skeleton_crew_wire_contract.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFleetStatusStore,
  FLEET_SIZE_CAP_ENDPOINT,
  FLEET_SKELETON_CREW_ENDPOINT,
  type FleetApiClient,
  type FleetSizeCap,
} from "../../../lupin_app/static/js/multiplexer/stores/FleetStatusStore";
import { createFleetStatusRenderer } from "../../../lupin_app/static/js/multiplexer/render/FleetStatusRenderer";

const HERE               = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS   = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const NOTIFICATIONS_HTML = resolve( HERE, "../../../lupin_app/static/html/notifications.html" );
const FIXTURE            = resolve( HERE, "../../fixtures/skeleton_crew_wire/responses.json" );

type Captured = { status: number; body: Record<string, unknown> };
const CAPTURED = JSON.parse( readFileSync( FIXTURE, "utf8" ) ) as Record<string, Captured>;

// What each captured body must paint, in both clients. Literals, not read from the fixture.
const PAINTS: Array<{ name: string; state: string; checked: boolean; warning: boolean }> = [
  { name: "get_never_flipped",                  state: "Skeleton crew: OFF", checked: false, warning: false },
  { name: "put_on",                             state: "Skeleton crew: ON",  checked: true,  warning: false },
  { name: "put_off_while_settings_mute_is_set", state: "Skeleton crew: OFF", checked: false, warning: true  },
  { name: "get_settings_file_unreadable",       state: "Skeleton crew: OFF", checked: false, warning: false },
];

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

beforeEach( () => { document.body.replaceChildren(); } );

test( "the fixture holds the five captured cases, each from a real answer", () => {
  assert.deepEqual( Object.keys( CAPTURED ).sort(), [
    "get_never_flipped",
    "get_settings_file_unreadable",
    "put_off_while_settings_mute_is_set",
    "put_on",
    "put_refused_for_an_api_key",
  ] );
  assert.equal( CAPTURED.put_refused_for_an_api_key.status, 403 );
  assert.equal( CAPTURED.put_on.status, 200 );
} );

// ─────────────────────────── multiplexer: store, then renderer ──────────────────────────

function multiplexerPaint( body: unknown ) {
  const bus   = createEventBusForTesting();
  const api: FleetApiClient = {
    get: async <T,>(): Promise<T> => body as T,
    put: async <T,>(): Promise<T> => body as T,
  };
  const store = createFleetStatusStore( { bus, api, nowFn: () => 0, errorFn: () => {} } );
  const root  = document.createElement( "section" );
  createFleetStatusRenderer( { eventBus: bus, stores: { fleet: store } } ).mount( root );
  const q = ( id: string ) => root.querySelector( `[data-testid="${id}"]` ) as HTMLElement;
  return { store, q };
}

for ( const want of PAINTS ) {
  test( `multiplexer: ${want.name} paints ${want.state}, checked=${want.checked}, warning=${want.warning}`, async () => {
    const { store, q } = multiplexerPaint( CAPTURED[ want.name ].body );
    await store.refreshSizeCap();
    assert.equal( q( "multiplexer-fleet-size-cap-controls" ).hidden, false, "the dial's numbers are usable" );
    assert.equal( q( "multiplexer-skeleton-crew-field" ).hidden, false );
    assert.equal( q( "multiplexer-skeleton-crew-state" ).textContent, want.state );
    assert.equal( ( q( "multiplexer-skeleton-crew-toggle" ) as HTMLInputElement ).checked, want.checked );
    assert.equal( q( "multiplexer-skeleton-crew-warning" ).hidden, !want.warning );
  } );
}

test( "multiplexer: the captured live block, with its extra `unknown` count, still paints the dial's line", async () => {
  const { store, q } = multiplexerPaint( CAPTURED.get_never_flipped.body );
  await store.refreshSizeCap();
  assert.equal( q( "multiplexer-fleet-size-cap-value" ).textContent, "8 / 18" );
  assert.equal( q( "multiplexer-fleet-size-cap-status" ).textContent, "0 live — 0 manager(s), 0 worker(s)" );
} );

test( "multiplexer: the captured 200 from the write is held as the answer", async () => {
  const bus = createEventBusForTesting();
  const puts: Array<{ path: string; body: unknown }> = [];
  const api: FleetApiClient = {
    get: async <T,>(): Promise<T> => CAPTURED.get_never_flipped.body as T,
    put: async <T,>( path: string, body: unknown ): Promise<T> => {
      puts.push( { path, body } );
      return CAPTURED.put_on.body as T;
    },
  };
  const store = createFleetStatusStore( { bus, api, nowFn: () => 0, errorFn: () => {} } );
  await store.setSkeletonCrew( true );
  assert.deepEqual( puts, [ { path: FLEET_SKELETON_CREW_ENDPOINT, body: { on: true } } ] );
  assert.equal( ( store.sizeCap() as FleetSizeCap ).skeleton_crew!.on, true );
  assert.equal( ( store.sizeCap() as FleetSizeCap ).skeleton_crew!.set_by, "rick@example.com" );
} );

test( "multiplexer: the captured 403 is reported with the server's own sentence, then the cap is re-read", async () => {
  const bus     = createEventBusForTesting();
  const errors: string[] = [];
  const calls : string[] = [];
  const detail  = JSON.stringify( CAPTURED.put_refused_for_an_api_key.body );
  const api: FleetApiClient = {
    get: async <T,>( path: string ): Promise<T> => { calls.push( `GET ${path}` ); return CAPTURED.get_never_flipped.body as T; },
    put: async (): Promise<never> => {
      const e = new Error( `HTTP 403 ${FLEET_SKELETON_CREW_ENDPOINT}: ${detail}` ) as Error & { status: number };
      e.status = 403;
      throw e;
    },
  };
  const store = createFleetStatusStore( { bus, api, nowFn: () => 0, errorFn: ( m ) => errors.push( m ) } );
  await store.setSkeletonCrew( true );
  assert.deepEqual( errors, [ "Skeleton crew not saved: Only an administrator may change the skeleton crew switch." ] );
  assert.deepEqual( calls, [ `GET ${FLEET_SIZE_CAP_ENDPOINT}` ] );
  assert.equal( ( store.sizeCap() as FleetSizeCap ).skeleton_crew!.on, false );
} );

// ─────────────────────────── legacy: the paint and the write ────────────────────────────

type LegacyUI = Record<string, unknown> & {
  _paintFleetSizeCap: ( payload: unknown ) => boolean;
  setSkeletonCrew: ( on: boolean ) => Promise<Record<string, unknown> | null>;
  authedFetch: ( url: string, init?: unknown ) => Promise<unknown>;
  error: ( msg: string ) => void;
  log: ( msg: string ) => void;
};

function legacyUI(): LegacyUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as LegacyUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  return ui;
}

// The cluster exactly as the page ships it.
function buildLegacyCluster(): void {
  const page  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const start = page.indexOf( 'id="fleet-size-cap-controls"' );
  const end   = page.indexOf( 'id="fleet-status-container"' );
  document.body.innerHTML = `<div ${page.slice( start, end ).replace( /<div\s*$/, "" )}`;
}

const byId = ( id: string ): HTMLElement => document.getElementById( id ) as HTMLElement;

for ( const want of PAINTS ) {
  test( `legacy: ${want.name} paints ${want.state}, checked=${want.checked}, warning=${want.warning}`, () => {
    const ui = legacyUI();
    buildLegacyCluster();
    assert.equal( ui._paintFleetSizeCap( CAPTURED[ want.name ].body ), true );
    assert.equal( byId( "skeleton-crew-field" ).hidden, false );
    assert.equal( byId( "skeleton-crew-state" ).textContent, want.state );
    assert.equal( ( byId( "skeleton-crew-toggle" ) as HTMLInputElement ).checked, want.checked );
    assert.equal( byId( "skeleton-crew-warning" ).hidden, !want.warning );
  } );
}

test( "legacy: the captured 200 from the write comes back as the answer, and the 403 is reported verbatim", async () => {
  const ui = legacyUI();
  ui.authedFetch = async () => ( { status: 200, ok: true, json: async () => CAPTURED.put_on.body } );
  const answer = await ui.setSkeletonCrew( true );
  assert.equal( ( answer as { skeleton_crew: { on: boolean } } ).skeleton_crew.on, true );

  const errors: string[] = [];
  ui.error = ( m: string ) => { errors.push( m ); };
  ui.authedFetch = async () => ( { status: 403, ok: false, json: async () => CAPTURED.put_refused_for_an_api_key.body } );
  assert.equal( await ui.setSkeletonCrew( true ), null );
  assert.deepEqual( errors, [ "Skeleton crew not saved: Only an administrator may change the skeleton crew switch." ] );
} );
