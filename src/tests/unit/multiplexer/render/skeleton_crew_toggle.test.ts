// Row 6f72dc83 — the skeleton crew toggle in the multiplexer's Fleet Status pane.
//
// Design: src/rnd/v0.2.2/2026.10.10-skeleton-crew-toggle-design.md §5 (the clients) and §9 (build row 8).
// Wire contract (note section 5): the GET body gains `skeleton_crew` { on, since, set_by,
// settings_mute_while_off }; PUT /api/arbiter/skeleton-crew takes { "on": bool }, admin only,
// and answers the same body, re-read from the file.
//
// Store behaviour and renderer behaviour are both here, because the claim is the pair: a store
// that saves correctly behind a switch that never disables is not the feature.
//
// Run via:
//   npx tsx --test src/tests/unit/multiplexer/render/skeleton_crew_toggle.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFleetStatusStore,
  FLEET_SIZE_CAP_ENDPOINT,
  FLEET_SKELETON_CREW_ENDPOINT,
  type FleetApiClient,
  type FleetSizeCap,
  type FleetSkeletonCrew,
} from "../../../../lupin_app/static/js/multiplexer/stores/FleetStatusStore";
import {
  createFleetStatusRenderer,
  type FleetStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/FleetStatusRenderer";
import type { FleetComposite } from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";
import type { StoreFleetSizeCapChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const nowFn = (): number => 0;

const crew = ( on: boolean, mute: boolean | null = false ): FleetSkeletonCrew =>
  ( { on, since: "2026-10-10T13:20:00-04:00", set_by: "rick", settings_mute_while_off: mute } );

const CREW_OFF: FleetSizeCap = { cap: 6, ceiling: 18, live: { total: 5, managers: 2, workers: 3 }, skeleton_crew: crew( false ) };
const CREW_ON : FleetSizeCap = { ...CREW_OFF, skeleton_crew: crew( true ) };
const COMPOSITE: FleetComposite = { app_timezone: "America/New_York", fleet_arbiter: { sessions: [] } };

function apiError( status: number, text: string ): Error & { status: number } {
  const e = new Error( `HTTP ${status} ${FLEET_SKELETON_CREW_ENDPOINT}: ${text}` ) as Error & { status: number };
  e.status = status;
  return e;
}

interface ApiCtx {
  api    : FleetApiClient;
  calls  : string[];
  getCap : () => Promise<FleetSizeCap>;
  putCrew: ( body: unknown ) => Promise<FleetSizeCap>;
}

function makeApi( overrides: Partial<Pick<ApiCtx, "getCap" | "putCrew">> = {} ): ApiCtx {
  const ctx: ApiCtx = {
    calls   : [],
    getCap  : async () => CREW_OFF,
    putCrew : async ( body ) => ( { ...CREW_OFF, skeleton_crew: crew( ( body as { on: boolean } ).on ) } ),
    ...overrides,
    api     : null as unknown as FleetApiClient,
  };
  ctx.api = {
    get: async <T,>( path: string ): Promise<T> => {
      ctx.calls.push( `GET ${path}` );
      if ( path === FLEET_SIZE_CAP_ENDPOINT ) return ( await ctx.getCap() ) as unknown as T;
      return COMPOSITE as unknown as T;
    },
    put: async <T,>( path: string, body: unknown ): Promise<T> => {
      ctx.calls.push( `PUT ${path} ${JSON.stringify( body )}` );
      return ( await ctx.putCrew( body ) ) as unknown as T;
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
// Store
// ---------------------------------------------------------------------------

test( "the endpoint is PUT /api/arbiter/skeleton-crew", () => {
  assert.equal( FLEET_SKELETON_CREW_ENDPOINT, "/api/arbiter/skeleton-crew" );
} );

test( "the state is read from the `skeleton_crew` field of the fleet-size-cap GET", async () => {
  const ctx = makeApi( { getCap: async () => CREW_ON } );
  const { store } = makeStore( ctx );
  assert.equal( store.skeletonCrewSaving(), null, "nothing in flight before a write" );
  await store.refreshSizeCap();
  assert.equal( store.sizeCap()!.skeleton_crew!.on, true );
  assert.deepEqual( ctx.calls, [ `GET ${FLEET_SIZE_CAP_ENDPOINT}` ] );
} );

test( "a flip PUTs { on }, reports saving while in flight, and keeps the SERVER's answer", async () => {
  let release!: ( v: FleetSizeCap ) => void;
  // The server read back "off" although "on" was asked: the store must hold "off".
  const ctx = makeApi( { putCrew: () => new Promise( ( r ) => { release = r; } ) } );
  const { store, events } = makeStore( ctx );

  const saving = store.setSkeletonCrew( true );
  assert.equal( store.skeletonCrewSaving(), true, "saving names the requested state" );
  assert.equal( store.sizeCapSaving(), null, "the cap is not the thing being saved" );
  assert.deepEqual( events, [ { saving: true } ], "the pane repaints on the existing cap event" );
  assert.deepEqual( ctx.calls, [ `PUT ${FLEET_SKELETON_CREW_ENDPOINT} {"on":true}` ] );

  release( { ...CREW_OFF, skeleton_crew: crew( false ) } );
  await saving;
  assert.equal( store.skeletonCrewSaving(), null );
  assert.equal( store.sizeCap()!.skeleton_crew!.on, false, "the server's re-read, not the value sent" );
  assert.deepEqual( events, [ { saving: true }, { saving: false } ] );
} );

test( "a refused flip reports the server's detail, then re-reads the enforced state", async () => {
  const ctx = makeApi( {
    getCap  : async () => CREW_OFF,
    putCrew : async () => { throw apiError( 403, JSON.stringify( { detail: "admin role required" } ) ); },
  } );
  const { store, errors } = makeStore( ctx );
  await store.setSkeletonCrew( true );
  assert.deepEqual( errors, [ "Skeleton crew not saved: admin role required" ] );
  assert.deepEqual( ctx.calls, [ `PUT ${FLEET_SKELETON_CREW_ENDPOINT} {"on":true}`, `GET ${FLEET_SIZE_CAP_ENDPOINT}` ] );
  assert.equal( store.sizeCap()!.skeleton_crew!.on, false, "snaps back to what the server holds" );
  assert.equal( store.skeletonCrewSaving(), null );
} );

test( "a refusal without a JSON detail keeps the status; a network failure says so", async () => {
  const plain = makeStore( makeApi( { putCrew: async () => { throw apiError( 500, "Internal Server Error" ); } } ) );
  await plain.store.setSkeletonCrew( false );
  assert.deepEqual( plain.errors, [ "Skeleton crew not saved: HTTP 500" ] );

  const net = makeStore( makeApi( { putCrew: async () => { throw new Error( "offline" ); } } ) );
  await net.store.setSkeletonCrew( false );
  assert.deepEqual( net.errors, [ "Skeleton crew save failed: Error: offline" ] );
} );

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

interface FakeFleet extends FleetStoreLike {
  cap       : FleetSizeCap | null;
  saving    : boolean | null;
  setCalls  : boolean[];
}

function mountToggle() {
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
    sizeCapSaving     : () => null,
    setSizeCap        : async () => {},
    skeletonCrewSaving: () => fleet.saving,
    setSkeletonCrew   : async ( on ) => { fleet.setCalls.push( on ); },
  };
  const renderer = createFleetStatusRenderer( { eventBus: bus, stores: { fleet } } );
  const root = document.createElement( "section" );
  renderer.mount( root );
  const q = ( id: string ) => root.querySelector( `[data-testid="${id}"]` ) as HTMLElement;
  const els = {
    controls : q( "multiplexer-fleet-size-cap-controls" ),
    field    : q( "multiplexer-skeleton-crew-field" ),
    toggle   : q( "multiplexer-skeleton-crew-toggle" ) as HTMLInputElement,
    state    : q( "multiplexer-skeleton-crew-state" ),
    warning  : q( "multiplexer-skeleton-crew-warning" ),
  };
  const capChanged = ( saving: boolean ): void => {
    bus.emit<StoreFleetSizeCapChangedPayload>( { type: "store_fleet_size_cap_changed", payload: { saving }, source: "test", ts: 0 } );
  };
  return { root, renderer, fleet, els, capChanged };
}

test( "the switch is a real checkbox with role=switch, inside the cap controls beside the dial", () => {
  const { els } = mountToggle();
  assert.equal( els.toggle.type, "checkbox" );
  assert.equal( els.toggle.getAttribute( "role" ), "switch" );
  assert.equal( els.field.parentElement!.getAttribute( "data-testid" ), "multiplexer-fleet-size-cap-controls" );
  assert.equal( els.toggle.getAttribute( "aria-labelledby" ), els.state.id, "the visible text names the control" );
} );

test( "it stays hidden until the server sends a `skeleton_crew` object with a boolean `on`", () => {
  const { els, fleet, capChanged } = mountToggle();
  assert.equal( els.field.hidden, true );

  fleet.cap = { cap: 6, ceiling: 18 };           // an older server: no field, no switch that does nothing
  capChanged( false );
  assert.equal( els.field.hidden, true );

  fleet.cap = { ...CREW_OFF, skeleton_crew: { ...crew( false ), on: "yes" as unknown as boolean } };
  capChanged( false );
  assert.equal( els.field.hidden, true, "only a real boolean counts" );

  fleet.cap = CREW_OFF;
  capChanged( false );
  assert.equal( els.field.hidden, false );

  fleet.cap = null;                              // a failed read hides the whole cluster, switch included
  capChanged( false );
  assert.equal( els.controls.hidden, true );
} );

test( "the state is said in TEXT and the checkbox agrees: OFF, then ON", () => {
  const { els, fleet, capChanged } = mountToggle();
  fleet.cap = CREW_OFF;
  capChanged( false );
  assert.equal( els.state.textContent, "Skeleton crew: OFF" );
  assert.equal( els.toggle.checked, false );
  assert.equal( els.toggle.disabled, false );
  assert.equal( els.toggle.getAttribute( "aria-checked" ), "false" );

  fleet.cap = CREW_ON;
  capChanged( false );
  assert.equal( els.state.textContent, "Skeleton crew: ON" );
  assert.equal( els.toggle.checked, true );
  assert.equal( els.toggle.getAttribute( "aria-checked" ), "true" );
} );

test( "a warning line appears only when the settings mute is set while the toggle is off", () => {
  const { els, fleet, capChanged } = mountToggle();
  assert.equal( els.warning.hidden, true, "nothing before a payload" );

  fleet.cap = { ...CREW_OFF, skeleton_crew: crew( false, true ) };
  capChanged( false );
  assert.equal( els.warning.hidden, false );
  assert.match( els.warning.textContent!, /settings\.json/ );
  assert.match( els.warning.textContent!, /skeleton crew is off/i );

  fleet.cap = { ...CREW_OFF, skeleton_crew: crew( false, null ) };   // the server could not read the file
  capChanged( false );
  assert.equal( els.warning.hidden, true, "null means no warning" );

  fleet.cap = { ...CREW_OFF, skeleton_crew: crew( false, false ) };
  capChanged( false );
  assert.equal( els.warning.hidden, true );

  fleet.cap = { ...CREW_ON, skeleton_crew: crew( true, true ) };     // on already mutes the poke
  capChanged( false );
  assert.equal( els.warning.hidden, true, "the warning is for the OFF case only" );
} );

test( "change saves once with the requested state", () => {
  const { els, fleet, capChanged } = mountToggle();
  fleet.cap = CREW_OFF;
  capChanged( false );
  capChanged( false );                           // repeated paints must not re-bind

  els.toggle.checked = true;
  els.toggle.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( fleet.setCalls, [ true ] );

  els.toggle.checked = false;
  els.toggle.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( fleet.setCalls, [ true, false ] );
} );

test( "while saving the switch is disabled and the text says so, not colour alone", () => {
  const { els, fleet, capChanged } = mountToggle();
  fleet.cap = CREW_OFF;
  capChanged( false );

  fleet.saving = true;
  capChanged( true );
  assert.equal( els.toggle.disabled, true );
  assert.equal( els.state.textContent, "Skeleton crew: turning ON…" );

  fleet.saving = false;
  capChanged( true );
  assert.equal( els.state.textContent, "Skeleton crew: turning OFF…" );

  fleet.saving = null;
  fleet.cap = CREW_ON;                           // the server's answer
  capChanged( false );
  assert.equal( els.toggle.disabled, false );
  assert.equal( els.toggle.checked, true );
  assert.equal( els.state.textContent, "Skeleton crew: ON" );
} );

test( "a refused flip snaps the switch back to what the server holds", () => {
  const { els, fleet, capChanged } = mountToggle();
  fleet.cap = CREW_OFF;
  capChanged( false );

  els.toggle.checked = true;                     // the operator clicked; the PUT was refused
  els.toggle.dispatchEvent( new Event( "change" ) );
  assert.equal( els.toggle.checked, true, "optimistic until the store answers" );

  capChanged( false );                           // the store re-read the file: still off
  assert.equal( els.toggle.checked, false );
  assert.equal( els.state.textContent, "Skeleton crew: OFF" );
} );

test( "unmount stops painting the switch", () => {
  const { renderer, fleet, els, capChanged } = mountToggle();
  fleet.cap = CREW_OFF;
  capChanged( false );
  renderer.unmount();
  fleet.cap = CREW_ON;
  capChanged( false );
  assert.equal( els.state.textContent, "Skeleton crew: OFF", "an unmounted renderer ignores the event" );
} );
