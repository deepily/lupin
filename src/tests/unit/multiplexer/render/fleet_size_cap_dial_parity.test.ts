// Parity A-2 #5 (row 18d06df7) — the Fleet Status pane's fleet-size-cap dial, ported
// from legacy: ceiling and value from the arbiter, readout on `input`, saved on
// `change` with the slider disabled while saving, repainted from the server's answer.
//
// Legacy: the dial markup inside #section-fleet-status, notifications.html:735-752;
//   refreshFleetStatus re-reads it on the same tick, notifications.js:9396-9421.
//   The dial's methods (unnamed in io/phase2/A6.md): fetchFleetSizeCap js 9205 ·
//   _paintFleetSizeCap 9242 · setFleetSizeCap 9311 · _wireFleetSizeCap 9351.
// Spec: io/phase2/A6.md Q3 + B8 (the cap half); build plan §1 A-2 row 5.
//
// Store behaviour and renderer behaviour are both here, because the parity claim is
// the pair: a store that saves correctly behind a dial that never disables is not it.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFleetStatusStore,
  FLEET_STATE_ENDPOINT,
  FLEET_SIZE_CAP_ENDPOINT,
  type FleetApiClient,
  type FleetSizeCap,
} from "../../../../lupin_app/static/js/multiplexer/stores/FleetStatusStore";
import {
  createFleetStatusRenderer,
  type FleetStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/FleetStatusRenderer";
import type { FleetComposite } from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";
import type {
  StoreFleetSizeCapChangedPayload,
  StoreFleetStatusChangedPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const nowFn = (): number => 0;

const CAP_6_OF_18: FleetSizeCap = { cap: 6, ceiling: 18, live: { total: 5, managers: 2, workers: 3 } };
const COMPOSITE: FleetComposite = { app_timezone: "America/New_York", fleet_arbiter: { sessions: [] } };

// The ApiClient throws ApiError( status, url, <response text> ), whose message is
// `HTTP <status> <url>: <text>`. The fake builds the same shape, so the store's
// `detail` extraction is exercised against the real message format.
function apiError( status: number, text: string ): Error & { status: number } {
  const e = new Error( `HTTP ${status} ${FLEET_SIZE_CAP_ENDPOINT}: ${text}` ) as Error & { status: number };
  e.status = status;
  return e;
}

interface ApiCtx {
  api   : FleetApiClient;
  calls : string[];
  getCap: () => Promise<FleetSizeCap>;
  putCap: ( body: unknown ) => Promise<FleetSizeCap>;
}

function makeApi( overrides: Partial<Pick<ApiCtx, "getCap" | "putCap">> = {} ): ApiCtx {
  const ctx: ApiCtx = {
    calls  : [],
    getCap : async () => CAP_6_OF_18,
    putCap : async ( body ) => ( { ...CAP_6_OF_18, cap: ( body as { cap: number } ).cap } ),
    ...overrides,
    api    : null as unknown as FleetApiClient,
  };
  ctx.api = {
    get: async <T,>( path: string ): Promise<T> => {
      ctx.calls.push( `GET ${path}` );
      if ( path === FLEET_SIZE_CAP_ENDPOINT ) return ( await ctx.getCap() ) as unknown as T;
      return COMPOSITE as unknown as T;
    },
    put: async <T,>( path: string, body: unknown ): Promise<T> => {
      ctx.calls.push( `PUT ${path} ${JSON.stringify( body )}` );
      return ( await ctx.putCap( body ) ) as unknown as T;
    },
  };
  return ctx;
}

function makeStore( ctx: ApiCtx ) {
  const bus    = createEventBusForTesting();
  const errors : string[] = [];
  const events : StoreFleetSizeCapChangedPayload[] = [];
  bus.on<StoreFleetSizeCapChangedPayload>( "store_fleet_size_cap_changed", ( e ) => events.push( e.payload ) );
  const store = createFleetStatusStore( { bus, api: ctx.api, nowFn, errorFn: ( m ) => errors.push( m ) } );
  return { bus, store, errors, events };
}

// ---------------------------------------------------------------------------
// Store — the arbiter is the source of both numbers
// ---------------------------------------------------------------------------

test( "the dial's numbers come from GET /api/arbiter/fleet-size-cap", async () => {
  const ctx = makeApi();
  const { store, events } = makeStore( ctx );
  assert.equal( store.sizeCap(), null, "nothing before the first read" );
  await store.refreshSizeCap();
  assert.deepEqual( ctx.calls, [ `GET ${FLEET_SIZE_CAP_ENDPOINT}` ] );
  assert.deepEqual( store.sizeCap(), CAP_6_OF_18 );
  assert.deepEqual( events, [ { saving: false } ] );
} );

test( "the ⟳ / 60 s refresh re-reads the dial too, after the table (legacy :9412-9417)", async () => {
  const ctx = makeApi();
  const { store } = makeStore( ctx );
  await store.refresh();
  assert.deepEqual( ctx.calls, [ `GET ${FLEET_STATE_ENDPOINT}`, `GET ${FLEET_SIZE_CAP_ENDPOINT}` ] );
  assert.deepEqual( store.sizeCap(), CAP_6_OF_18 );
} );

test( "an unreadable cap clears the payload and says why (legacy :9218-9226)", async () => {
  const httpCtx = makeApi( { getCap: async () => { throw apiError( 503, "down" ); } } );
  const http    = makeStore( httpCtx );
  await http.store.refreshSizeCap();
  assert.equal( http.store.sizeCap(), null );
  assert.deepEqual( http.errors, [ "Fleet size cap unavailable (HTTP 503)" ] );

  const netCtx = makeApi( { getCap: async () => { throw new Error( "network down" ); } } );
  const net    = makeStore( netCtx );
  await net.store.refreshSizeCap();
  assert.equal( net.store.sizeCap(), null );
  assert.deepEqual( net.errors, [ "Fleet size cap fetch failed: Error: network down" ] );
} );

test( "a save PUTs { cap }, reports saving while in flight, and keeps the SERVER's answer", async () => {
  let release!: ( v: FleetSizeCap ) => void;
  // The server persisted 7 although 9 was asked: the store must hold 7.
  const ctx = makeApi( { putCap: () => new Promise( ( r ) => { release = r; } ) } );
  const { store, events } = makeStore( ctx );

  const saving = store.setSizeCap( 9 );
  assert.equal( store.sizeCapSaving(), 9, "saving names the requested value" );
  assert.deepEqual( events, [ { saving: true } ] );
  assert.deepEqual( ctx.calls, [ `PUT ${FLEET_SIZE_CAP_ENDPOINT} {"cap":9}` ] );

  release( { ...CAP_6_OF_18, cap: 7 } );
  await saving;
  assert.equal( store.sizeCapSaving(), null );
  assert.equal( store.sizeCap()!.cap, 7, "repainted from the server's answer, not the value sent" );
  assert.deepEqual( events, [ { saving: true }, { saving: false } ] );
} );

test( "a refused save reports the server's detail, then re-reads the enforced cap (legacy :9334-9341, :9387-9388)", async () => {
  const ctx = makeApi( { putCap: async () => { throw apiError( 409, JSON.stringify( { detail: "cap 30 is above the ceiling 18" } ) ); } } );
  const { store, errors } = makeStore( ctx );
  await store.setSizeCap( 30 );
  assert.deepEqual( errors, [ "Fleet cap not saved: cap 30 is above the ceiling 18" ] );
  assert.deepEqual( ctx.calls, [ `PUT ${FLEET_SIZE_CAP_ENDPOINT} {"cap":30}`, `GET ${FLEET_SIZE_CAP_ENDPOINT}` ] );
  assert.deepEqual( store.sizeCap(), CAP_6_OF_18, "snaps back to what the server enforces" );
  assert.equal( store.sizeCapSaving(), null );
} );

test( "a refusal without a JSON detail keeps the status; a network failure says so", async () => {
  const plain = makeStore( makeApi( { putCap: async () => { throw apiError( 500, "Internal Server Error" ); } } ) );
  await plain.store.setSizeCap( 4 );
  assert.deepEqual( plain.errors, [ "Fleet cap not saved: HTTP 500" ] );

  const noDetail = makeStore( makeApi( { putCap: async () => { throw apiError( 422, JSON.stringify( { other: 1 } ) ); } } ) );
  await noDetail.store.setSizeCap( 4 );
  assert.deepEqual( noDetail.errors, [ "Fleet cap not saved: HTTP 422" ] );

  const net = makeStore( makeApi( { putCap: async () => { throw new Error( "offline" ); } } ) );
  await net.store.setSizeCap( 4 );
  assert.deepEqual( net.errors, [ "Fleet cap save failed: Error: offline" ] );

  // A thrown value with a status but no message at all still reports the status.
  const bare = makeStore( makeApi( { putCap: async () => { throw { status: 502 }; } } ) );
  await bare.store.setSizeCap( 4 );
  assert.deepEqual( bare.errors, [ "Fleet cap not saved: HTTP 502" ] );
} );

// ---------------------------------------------------------------------------
// Renderer — the dial itself
// ---------------------------------------------------------------------------

interface FakeFleet extends FleetStoreLike {
  cap      : FleetSizeCap | null;
  saving   : number | null;
  setCalls : number[];
}

function mountDial() {
  const bus = createEventBusForTesting();
  const fleet: FakeFleet = {
    cap               : null,
    saving            : null,
    setCalls          : [],
    composite         : () => COMPOSITE,
    showOfflineFlag   : () => false,
    refresh           : async () => {},
    toggleShowOffline : () => {},
    sizeCap           : () => fleet.cap,
    sizeCapSaving     : () => fleet.saving,
    setSizeCap        : async ( cap ) => { fleet.setCalls.push( cap ); },
  };
  const renderer = createFleetStatusRenderer( { eventBus: bus, stores: { fleet } } );
  const root = document.createElement( "section" );
  renderer.mount( root );
  const q = ( id: string ) => root.querySelector( `[data-testid="${id}"]` ) as HTMLElement;
  const els = {
    controls : q( "multiplexer-fleet-size-cap-controls" ),
    slider   : q( "multiplexer-fleet-size-cap" ) as HTMLInputElement,
    value    : q( "multiplexer-fleet-size-cap-value" ),
    status   : q( "multiplexer-fleet-size-cap-status" ),
  };
  const capChanged = ( saving: boolean ): void => {
    bus.emit<StoreFleetSizeCapChangedPayload>( { type: "store_fleet_size_cap_changed", payload: { saving }, source: "test", ts: 0 } );
  };
  const tableChanged = (): void => {
    bus.emit<StoreFleetStatusChangedPayload>( { type: "store_fleet_status_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } );
  };
  return { root, renderer, fleet, els, capChanged, tableChanged };
}

test( "the dial is hidden, with no max and no value, until a real payload arrives (legacy html:731-736, :9273-9276)", () => {
  const { els, fleet, capChanged } = mountDial();
  assert.ok( els.controls, "the cluster exists" );
  assert.equal( els.controls.hidden, true );
  assert.equal( els.slider.getAttribute( "max" ), null, "the ceiling is never baked into markup" );

  fleet.cap = { cap: 6 };                       // no ceiling → still unusable
  capChanged( false );
  assert.equal( els.controls.hidden, true );

  fleet.cap = CAP_6_OF_18;
  capChanged( false );
  assert.equal( els.controls.hidden, false );

  fleet.cap = null;                             // a later failed read hides it again
  capChanged( false );
  assert.equal( els.controls.hidden, true );
} );

test( "a paint sets min 1, max = the ceiling verbatim, the value, the readout and the live line (legacy :9278-9291)", () => {
  const { els, fleet, capChanged } = mountDial();
  fleet.cap = CAP_6_OF_18;
  capChanged( false );
  assert.equal( els.slider.min, "1" );
  assert.equal( els.slider.max, "18" );
  assert.equal( els.slider.value, "6" );
  assert.equal( els.value.textContent, "6 / 18" );
  assert.equal( els.slider.disabled, false );
  assert.equal( els.status.textContent, "5 live — 2 manager(s), 3 worker(s)" );

  fleet.cap = { cap: 6, ceiling: 18, live: null };
  capChanged( false );
  assert.equal( els.status.textContent, "", "no census, no line" );
} );

test( "input moves the readout only; change saves once with the requested number (legacy :9372-9381)", () => {
  const { els, fleet, capChanged } = mountDial();
  fleet.cap = CAP_6_OF_18;
  capChanged( false );
  capChanged( false );                          // repeated paints must not re-bind

  els.slider.value = "11";
  els.slider.dispatchEvent( new Event( "input" ) );
  assert.equal( els.value.textContent, "11 / 18" );
  assert.deepEqual( fleet.setCalls, [], "input never writes" );

  els.slider.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( fleet.setCalls, [ 11 ], "one write per release, however many paints came before" );
} );

test( "while saving the slider is disabled and the status says so in text (legacy :9379-9380)", () => {
  const { els, fleet, capChanged } = mountDial();
  fleet.cap = CAP_6_OF_18;
  capChanged( false );

  fleet.saving = 11;
  capChanged( true );
  assert.equal( els.slider.disabled, true );
  assert.equal( els.status.textContent, "saving 11…" );

  fleet.saving = null;
  fleet.cap = { ...CAP_6_OF_18, cap: 7 };       // the server's answer
  capChanged( false );
  assert.equal( els.slider.disabled, false );
  assert.equal( els.slider.value, "7" );
  assert.equal( els.value.textContent, "7 / 18" );
} );

test( "the dial sits in the collapsible body above the table, and a table repaint leaves it in place", () => {
  const { root, els, fleet, capChanged, tableChanged } = mountDial();
  fleet.cap = CAP_6_OF_18;
  capChanged( false );
  const container = root.querySelector( '[data-testid="multiplexer-fleet-status-container"]' )!;
  assert.ok( els.controls.classList.contains( "section-content" ), "collapse hides it with the body" );
  assert.ok( els.controls.parentElement === root, "a direct child, so the collapse rule reaches it" );
  assert.ok( els.controls.nextElementSibling === container, "directly above the table" );

  tableChanged();
  assert.ok( root.querySelector( '[data-testid="multiplexer-fleet-size-cap-controls"]' ) === els.controls, "the same node, not rebuilt" );
  assert.equal( els.slider.value, "6" );
} );

test( "unmount stops painting the dial", () => {
  const { renderer, fleet, els, capChanged } = mountDial();
  renderer.unmount();
  fleet.cap = CAP_6_OF_18;
  capChanged( false );
  assert.equal( els.controls.hidden, true, "an unmounted renderer ignores the event" );
} );
