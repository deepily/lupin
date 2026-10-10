// THE STOP POKE SWITCH in the multiplexer's notifications bar (row 3526fb95).
//
// Rick's ruling: a plain on/off toggle with a simple indicator; only an admin can flip it.
// The server enforces the admin rule. What these tests hold the client to:
//
//   1. the indicator shows what the server said — a failed read paints "unknown", and a
//      flip paints the state the server read back, not the one that was asked for
//   2. a non-admin gets the indicator on a disabled button
//   3. the flip PUTs the opposite of what is shown to the one endpoint
//   4. the header mounts the switch beside the bounce button and paints it on mount
//
// Run via:
//   npx tsx --test src/tests/unit/multiplexer/render/poke_mute_switch.test.ts

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsHeaderRenderer } from "../../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type {
  NotificationDeleteApiLike,
  NotificationsHeaderStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import {
  POKE_MUTE_PATH,
  createPokeMuteSwitch,
  type PokeMuteApiLike,
  type PokeMuteState,
} from "../../../../lupin_app/static/js/multiplexer/render/pokeMuteSwitch";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
afterEach( () => {
  if ( globalThis.document !== undefined ) document.body.replaceChildren();
} );

const ON : PokeMuteState = { muted: false, set_by: null, set_at: null };
const OFF: PokeMuteState = { muted: true,  set_by: "rick@example.com", set_at: "2026-10-02T15:00:00+00:00" };

type Call = { verb: "GET" | "PUT"; path: string; body?: unknown };

// Each queued reply is a value to resolve with, or an Error to reject with.
function fakeApi( replies: unknown[] ): { api: PokeMuteApiLike; calls: Call[] } {
  const calls: Call[] = [];
  const next = <T>(): Promise<T> => {
    assert.ok( replies.length > 0, "unexpected extra api call" );
    const reply = replies.shift();
    return reply instanceof Error ? Promise.reject( reply ) : Promise.resolve( reply as T );
  };
  const api: PokeMuteApiLike = {
    get<T>( path: string ): Promise<T> { calls.push( { verb: "GET", path } ); return next<T>(); },
    put<T>( path: string, body: unknown ): Promise<T> { calls.push( { verb: "PUT", path, body } ); return next<T>(); },
  };
  return { api, calls };
}

test( "it starts unknown and disabled, before anything has been read", () => {
  const { api, calls } = fakeApi( [] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );

  assert.equal( sw.element.dataset.muted, "unknown" );
  assert.equal( sw.element.disabled, true );
  assert.equal( sw.element.textContent, "❔ Poke" );
  assert.equal( sw.element.getAttribute( "data-testid" ), "multiplexer-poke-mute" );
  assert.equal( calls.length, 0 );
} );

test( "it is hidden, not removed: the skeleton crew toggle is the one control now (row 6f72dc83)", async () => {
  const { api } = fakeApi( [ ON ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
  assert.equal( sw.element.hidden, true, "hidden from the first paint" );

  await sw.refresh();
  assert.equal( sw.element.hidden, true, "a repaint does not bring it back" );
  assert.equal( sw.element.textContent, "🔔 Poke on", "the handlers and paint are intact, so a revert is one line" );
} );

test( "an admin gets a working button showing the state the server reported", async () => {
  const { api, calls } = fakeApi( [ ON, OFF ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );

  assert.deepEqual( await sw.refresh(), ON );
  assert.deepEqual( calls, [ { verb: "GET", path: POKE_MUTE_PATH } ] );
  assert.equal( POKE_MUTE_PATH, "/api/heartbeat/poke-mute" );
  assert.equal( sw.element.textContent, "🔔 Poke on" );
  assert.equal( sw.element.dataset.muted, "false" );
  assert.equal( sw.element.disabled, false );
  assert.equal( sw.element.title, "Heartbeat stop poke: ON. Click to mute it for the whole fleet." );

  assert.deepEqual( await sw.refresh(), OFF );
  assert.equal( sw.element.textContent, "🔕 Poke muted" );
  assert.equal( sw.element.dataset.muted, "true" );
  assert.equal( sw.element.title, "Heartbeat stop poke: MUTED by rick@example.com. Click to turn it back on." );
} );

test( "a non-admin gets the same indicator on a disabled button", async () => {
  const { api } = fakeApi( [ OFF, ON ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => false } );

  await sw.refresh();
  assert.equal( sw.element.textContent, "🔕 Poke muted" );
  assert.equal( sw.element.disabled, true );
  assert.equal( sw.element.title, "Heartbeat stop poke: MUTED by rick@example.com. Only an admin can change it." );

  await sw.refresh();
  assert.equal( sw.element.textContent, "🔔 Poke on" );
  assert.equal( sw.element.disabled, true );
} );

for ( const bad of [ null, "muted", {}, { muted: "true" }, { muted: 1 } ] ) {
  test( `a reply that is not a clean boolean state paints unknown: ${ JSON.stringify( bad ) }`, async () => {
    const { api } = fakeApi( [ ON, bad ] );
    const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
    await sw.refresh();

    assert.equal( await sw.refresh(), null );
    assert.equal( sw.element.dataset.muted, "unknown" );
    assert.equal( sw.element.disabled, true );
  } );
}

test( "a failed read paints unknown and reports the error", async () => {
  const boom = new Error( "network down" );
  const { api } = fakeApi( [ ON, boom ] );
  const seen: Array<[ string, unknown ]> = [];
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true, onError: ( m, e ) => seen.push( [ m, e ] ) } );
  await sw.refresh();

  assert.equal( await sw.refresh(), null );
  assert.equal( sw.element.dataset.muted, "unknown" );
  assert.deepEqual( seen, [ [ "[poke-mute] read failed", boom ] ] );
} );

test( "a failed read with no error sink still paints unknown", async () => {
  const { api } = fakeApi( [ new Error( "network down" ) ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
  assert.equal( await sw.refresh(), null );
  assert.equal( sw.element.dataset.muted, "unknown" );
} );

test( "a click sends the opposite of what is shown and paints the server's read-back", async () => {
  const { api, calls } = fakeApi( [ ON, OFF, ON ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
  await sw.refresh();

  sw.element.click();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( calls[ 1 ], { verb: "PUT", path: POKE_MUTE_PATH, body: { muted: true } } );
  assert.equal( sw.element.dataset.muted, "true" );

  assert.deepEqual( await sw.toggle(), ON );
  assert.deepEqual( calls[ 2 ], { verb: "PUT", path: POKE_MUTE_PATH, body: { muted: false } } );
  assert.equal( sw.element.dataset.muted, "false" );
} );

test( "the indicator follows the read-back, not the request, and a malformed read-back paints unknown", async () => {
  const { api } = fakeApi( [ ON, ON, { nonsense: true } ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
  await sw.refresh();

  await sw.toggle();                                   // asked to mute; the server says still on
  assert.equal( sw.element.dataset.muted, "false" );
  assert.equal( sw.element.textContent, "🔔 Poke on" );

  assert.equal( await sw.toggle(), null );
  assert.equal( sw.element.dataset.muted, "unknown" );
} );

test( "a refused flip reports the error and re-reads the real state", async () => {
  const refused = Object.assign( new Error( "HTTP 403" ), { status: 403 } );
  const { api, calls } = fakeApi( [ ON, refused, ON ] );
  const seen: string[] = [];
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true, onError: ( m ) => seen.push( m ) } );
  await sw.refresh();

  assert.deepEqual( await sw.toggle(), ON );
  assert.deepEqual( calls.map( ( c ) => c.verb ), [ "GET", "PUT", "GET" ] );
  assert.deepEqual( seen, [ "[poke-mute] flip refused or failed" ] );
  assert.equal( sw.element.dataset.muted, "false" );
  assert.equal( sw.element.disabled, false );
} );

test( "a flip does nothing while the state is unknown", async () => {
  const { api, calls } = fakeApi( [] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
  assert.equal( await sw.toggle(), null );
  assert.equal( calls.length, 0 );
} );

// ── the header mounts it ─────────────────────────────────────────────────────

function makeStore(): NotificationsHeaderStoreLike {
  return {
    list             : () => [],
    history          : () => [],
    visibleEntries   : () => [],
    removeByIdHashes : () => { /* not exercised here */ },
    historyWindow    : () => 48,
    setHistoryWindow : () => { /* not exercised here */ },
    filterMode       : () => "own",
    setFilterMode    : () => { /* not exercised here */ },
  };
}

const headerApi: NotificationDeleteApiLike = {
  delete<T>(): Promise<T> { return Promise.resolve( undefined as T ); },
  bounceDevServer() { return Promise.resolve( { status: "accepted", timestamp: "t" } ); },
};

test( "the header puts the switch right after the bounce button and paints it on mount", async () => {
  const { api, calls } = fakeApi( [ OFF ] );
  const sw = createPokeMuteSwitch( { api, isAdmin: () => true } );
  const renderer = createNotificationsHeaderRenderer( {
    eventBus : createEventBusForTesting(), store: makeStore(), api: headerApi, pokeMuteSwitch: sw,
  } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  renderer.mount( root );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  const bounce = root.querySelector( '[data-testid="multiplexer-bounce-dev-server"]' ) as HTMLElement;
  assert.ok( bounce.nextElementSibling === sw.element, "the switch must be the element right after the bounce button" );
  assert.deepEqual( calls, [ { verb: "GET", path: POKE_MUTE_PATH } ] );
  assert.equal( sw.element.dataset.muted, "true" );
  renderer.unmount();
} );

test( "a header built without the switch has none", () => {
  const renderer = createNotificationsHeaderRenderer( {
    eventBus : createEventBusForTesting(), store: makeStore(), api: headerApi,
  } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  renderer.mount( root );

  assert.equal( root.querySelectorAll( '[data-testid="multiplexer-poke-mute"]' ).length, 0 );
  const bounce = root.querySelector( '[data-testid="multiplexer-bounce-dev-server"]' ) as HTMLElement;
  assert.equal( bounce.nextElementSibling?.getAttribute( "data-testid" ), "multiplexer-notifications-header-status" );
  renderer.unmount();
} );
