// THE STOP POKE SWITCH in the legacy client's toolbar (row 3526fb95).
//
// Rick's ruling: a plain on/off toggle with a simple indicator; only an admin can flip it.
// The server enforces the admin rule. What these tests hold the CLIENT to:
//
//   1. the indicator shows what the server said, never a guess — a failed read paints
//      "unknown", and a flip paints the state the server read back, not the one asked for
//   2. a non-admin sees the indicator on a disabled button
//   3. the flip sends the opposite of what is shown, to the one endpoint
//
// Harness copied from fleet_size_cap_dial.test.ts.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/poke_mute_switch.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
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

type State = { muted: boolean; set_by: string | null; set_at: string | null };
type Call  = { url: string; init?: { method?: string; body?: string } };
type PokeUI = Record<string, unknown> & {
  isAdmin: boolean;
  _paintPokeMute: ( state: unknown ) => boolean;
  refreshPokeMute: () => Promise<State | null>;
  togglePokeMute: () => Promise<State | null>;
  authedFetch: ( url: string, init?: Call[ "init" ] ) => Promise<unknown>;
  error: ( ...args: unknown[] ) => void;
  log: ( ...args: unknown[] ) => void;
};

const ON : State = { muted: false, set_by: null, set_at: null };
const OFF: State = { muted: true,  set_by: "rick@example.com", set_at: "2026-10-02T15:00:00+00:00" };

let errors: string[];

function newUI( isAdmin: boolean ): PokeUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as PokeUI;
  ui.isAdmin = isAdmin;
  ui.log     = (): void => {};
  ui.error   = ( ...args: unknown[] ): void => { errors.push( String( args[ 0 ] ) ); };
  return ui;
}

// The button exactly as the page ships it, cut out of the real HTML.
function shippedButton(): string {
  const page  = readFileSync( NOTIFICATIONS_HTML, "utf8" );
  const found = page.match( /<button[^>]*id="poke-mute-btn"[^>]*>[^<]*<\/button>/g ) ?? [];
  assert.equal( found.length, 1, "the page must carry exactly one poke-mute button" );
  return found[ 0 ];
}

// Row 6f72dc83: one skeleton crew toggle now controls the stop poke, so the separate
// button is hidden in the page as shipped (not deleted: its handlers and paint stay).
test( "the shipped poke-mute button carries `hidden`, and a paint does not lift it", () => {
  const ui = newUI( true );
  document.body.innerHTML = shippedButton();
  assert.equal( button().hidden, true );
  ui._paintPokeMute( ON );
  assert.equal( button().hidden, true );
  assert.equal( button().dataset.muted, "false", "it still paints, so a revert is one attribute" );
} );

function button(): HTMLButtonElement {
  return document.getElementById( "poke-mute-btn" ) as HTMLButtonElement;
}

function answering( ui: PokeUI, replies: Array<{ ok: boolean; status?: number; body?: unknown } | Error> ): Call[] {
  const calls: Call[] = [];
  ui.authedFetch = async ( url, init ): Promise<unknown> => {
    calls.push( { url, init } );
    const reply = replies.shift();
    assert.ok( reply !== undefined, `unexpected extra call to ${ url }` );
    if ( reply instanceof Error ) throw reply;
    return { ok: reply.ok, status: reply.status ?? ( reply.ok ? 200 : 500 ), json: async () => reply.body };
  };
  return calls;
}

beforeEach( () => {
  errors = [];
  document.body.innerHTML = shippedButton();
} );

test( "the button ships disabled and unknown, inside the action class the section dispatcher ignores", () => {
  const btn = button();
  assert.equal( btn.disabled, true );
  assert.equal( btn.dataset.muted, "unknown" );
  assert.equal( btn.className, "bounce-server-btn" );
  assert.equal( btn.hasAttribute( "data-section" ), false );
} );

test( "an admin sees a working bell when the poke is on and a working muted bell when it is off", () => {
  const ui = newUI( true );

  assert.equal( ui._paintPokeMute( ON ), true );
  assert.equal( button().textContent, "🔔" );
  assert.equal( button().dataset.muted, "false" );
  assert.equal( button().disabled, false );
  assert.equal( button().title, "Heartbeat stop poke: ON. Click to mute it for the whole fleet." );

  ui._paintPokeMute( OFF );
  assert.equal( button().textContent, "🔕" );
  assert.equal( button().dataset.muted, "true" );
  assert.equal( button().disabled, false );
  assert.equal( button().title, "Heartbeat stop poke: MUTED by rick@example.com. Click to turn it back on." );
} );

test( "a non-admin sees the same indicator on a button that cannot be pressed", () => {
  const ui = newUI( false );

  ui._paintPokeMute( OFF );
  assert.equal( button().textContent, "🔕" );
  assert.equal( button().disabled, true );
  assert.equal( button().title, "Heartbeat stop poke: MUTED by rick@example.com. Only an admin can change it." );

  ui._paintPokeMute( ON );
  assert.equal( button().textContent, "🔔" );
  assert.equal( button().disabled, true );
} );

for ( const bad of [ null, undefined, {}, { muted: "true" }, { muted: 1 } ] ) {
  test( `a state that is not a clean boolean paints unknown, even for an admin: ${ JSON.stringify( bad ) }`, () => {
    const ui = newUI( true );
    ui._paintPokeMute( ON );
    ui._paintPokeMute( bad );
    assert.equal( button().textContent, "❔" );
    assert.equal( button().dataset.muted, "unknown" );
    assert.equal( button().disabled, true );
  } );
}

test( "painting with no button in the page reports false and throws nothing", () => {
  document.body.replaceChildren();
  assert.equal( newUI( true )._paintPokeMute( ON ), false );
} );

test( "refresh reads the one endpoint and paints what it said", async () => {
  const ui    = newUI( true );
  const calls = answering( ui, [ { ok: true, body: OFF } ] );

  assert.deepEqual( await ui.refreshPokeMute(), OFF );
  assert.deepEqual( calls, [ { url: "/api/heartbeat/poke-mute", init: undefined } ] );
  assert.equal( button().dataset.muted, "true" );
} );

test( "a refused or failed read paints unknown and returns null", async () => {
  const ui = newUI( true );
  ui._paintPokeMute( ON );

  answering( ui, [ { ok: false, status: 401 } ] );
  assert.equal( await ui.refreshPokeMute(), null );
  assert.equal( button().dataset.muted, "unknown" );
  assert.deepEqual( errors, [] );

  ui._paintPokeMute( ON );
  answering( ui, [ new Error( "network down" ) ] );
  assert.equal( await ui.refreshPokeMute(), null );
  assert.equal( button().dataset.muted, "unknown" );
  assert.deepEqual( errors, [ "[POKE-MUTE] Read failed:" ] );
} );

test( "a flip sends the opposite of what is shown and paints what the server read back", async () => {
  const ui = newUI( true );
  ui._paintPokeMute( ON );
  const calls = answering( ui, [ { ok: true, body: OFF } ] );

  assert.deepEqual( await ui.togglePokeMute(), OFF );
  assert.equal( calls.length, 1 );
  assert.equal( calls[ 0 ].url, "/api/heartbeat/poke-mute" );
  assert.equal( calls[ 0 ].init?.method, "PUT" );
  assert.deepEqual( JSON.parse( calls[ 0 ].init?.body ?? "" ), { muted: true } );
  assert.equal( button().dataset.muted, "true" );

  const back = answering( ui, [ { ok: true, body: ON } ] );
  await ui.togglePokeMute();
  assert.deepEqual( JSON.parse( back[ 0 ].init?.body ?? "" ), { muted: false } );
  assert.equal( button().dataset.muted, "false" );
} );

test( "the indicator follows the server's read-back, not the request", async () => {
  const ui = newUI( true );
  ui._paintPokeMute( ON );
  answering( ui, [ { ok: true, body: ON } ] );   // asked to mute; the server says still on

  await ui.togglePokeMute();
  assert.equal( button().dataset.muted, "false" );
  assert.equal( button().textContent, "🔔" );
} );

test( "a refused flip logs the status and re-reads the real state", async () => {
  const ui = newUI( true );
  ui._paintPokeMute( ON );
  const calls = answering( ui, [ { ok: false, status: 403 }, { ok: true, body: ON } ] );

  assert.deepEqual( await ui.togglePokeMute(), ON );
  assert.deepEqual( calls.map( ( c ) => c.init?.method ?? "GET" ), [ "PUT", "GET" ] );
  assert.deepEqual( errors, [ "[POKE-MUTE] Refused: HTTP 403" ] );
  assert.equal( button().dataset.muted, "false" );
  assert.equal( button().disabled, false );
} );

test( "a flip that throws logs it and re-reads the real state", async () => {
  const ui = newUI( true );
  ui._paintPokeMute( OFF );
  answering( ui, [ new Error( "network down" ), { ok: true, body: OFF } ] );

  assert.deepEqual( await ui.togglePokeMute(), OFF );
  assert.deepEqual( errors, [ "[POKE-MUTE] Request failed:" ] );
  assert.equal( button().dataset.muted, "true" );
} );

test( "a flip does nothing while the state is unknown or the button is missing", async () => {
  const ui    = newUI( true );
  const calls = answering( ui, [] );

  assert.equal( await ui.togglePokeMute(), null );          // ships as "unknown"
  document.body.replaceChildren();
  assert.equal( await ui.togglePokeMute(), null );
  assert.equal( calls.length, 0 );
} );

test( "the click handler and the first paint are wired", () => {
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  assert.equal( ( src.match( /pokeMuteBtn\.addEventListener\( 'click', \(\) => this\.togglePokeMute\(\) \)/g ) ?? [] ).length, 1 );
  assert.equal( ( src.match( /^\s*this\.refreshPokeMute\(\);$/gm ) ?? [] ).length, 1 );
} );
