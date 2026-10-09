// Row 4ca5776c — the legacy page draws a Yes/No card that was filed before the page opened.
//
// A card reached this page by a live push or from the browser's own saved state, so one filed while the
// page was closed was never drawn (Pocholo's check, io/tmp/2026.10.09-pocholo-check-legacy-page-draws-no-card-at-load.md).
// hydrateAwaitingResponseCards asks the server for the waiting cards and feeds each through the same
// addActionRequiredNotification a live push uses.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/a_card_filed_while_the_page_was_closed_is_drawn_at_load.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const SOURCE           = readFileSync( NOTIFICATIONS_JS, "utf8" );

type Card = { id: string; message: string };

let Ctor: { prototype: Record<string, unknown> };

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const initIdx = SOURCE.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( SOURCE.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as typeof Ctor;
} );

type Harness = {
  ui      : Record<string, unknown> & { hydrateAwaitingResponseCards: () => Promise<number> };
  drawn   : Card[];
  errors  : unknown[][];
  urls    : string[];
};

function makeUi( answer: { ok: boolean; status?: number; statusText?: string; body?: unknown } | Error, held: string[] = [] ): Harness {
  const h: Harness = { ui: Object.create( Ctor.prototype ), drawn: [], errors: [], urls: [] };
  h.ui.actionRequiredNotifications = new Map( held.map( id => [ id, {} ] ) );
  h.ui.error                       = ( ...args: unknown[] ): void => { h.errors.push( args ); };
  h.ui.addActionRequiredNotification = ( card: Card ): void => { h.drawn.push( card ); };
  h.ui.authedFetch = async ( url: string ): Promise<unknown> => {
    h.urls.push( url );
    if ( answer instanceof Error ) throw answer;
    return { ok: answer.ok, status: answer.status, statusText: answer.statusText, json: async () => answer.body };
  };
  return h;
}

const A: Card = { id: "card-a", message: "first question" };
const B: Card = { id: "card-b", message: "second question" };

test( "every waiting card goes through the live-push path, oldest first, and the count is returned", async () => {
  const h     = makeUi( { ok: true, body: { notifications: [ A, B ] } } );
  const drawn = await h.ui.hydrateAwaitingResponseCards();
  assert.deepEqual( h.drawn, [ A, B ] );
  assert.equal( drawn, 2 );
  assert.deepEqual( h.urls, [ "/api/notifications/awaiting-response" ], "it must ask the awaiting-response route, once" );
} );

test( "a card the page already holds is not drawn twice", async () => {
  const h     = makeUi( { ok: true, body: { notifications: [ A, B ] } }, [ "card-a" ] );
  const drawn = await h.ui.hydrateAwaitingResponseCards();
  assert.deepEqual( h.drawn, [ B ] );
  assert.equal( drawn, 1 );
} );

test( "no waiting cards draws nothing and returns 0", async () => {
  const h = makeUi( { ok: true, body: { notifications: [] } } );
  assert.equal( await h.ui.hydrateAwaitingResponseCards(), 0 );
  assert.deepEqual( h.drawn, [] );
} );

test( "a refused request draws nothing, logs the status, and returns 0", async () => {
  const h = makeUi( { ok: false, status: 500, statusText: "Server Error" } );
  assert.equal( await h.ui.hydrateAwaitingResponseCards(), 0 );
  assert.deepEqual( h.drawn, [] );
  assert.deepEqual( h.errors, [ [ "Failed to load waiting response cards:", 500, "Server Error" ] ] );
} );

test( "a thrown request draws nothing, logs the error, and returns 0", async () => {
  const boom = new Error( "network down" );
  const h    = makeUi( boom );
  assert.equal( await h.ui.hydrateAwaitingResponseCards(), 0 );
  assert.deepEqual( h.drawn, [] );
  assert.deepEqual( h.errors, [ [ "Error loading waiting response cards:", boom ] ] );
} );

test( "an answer with no notifications list is an error and draws nothing", async () => {
  const h = makeUi( { ok: true, body: {} } );
  assert.equal( await h.ui.hydrateAwaitingResponseCards(), 0 );
  assert.equal( h.errors.length, 1 );
} );

test( "init draws the waiting cards AFTER it restores the saved ones, so a restored card is the one that is kept", () => {
  const restore = SOURCE.indexOf( "this.restoreActionRequiredState();" );
  const hydrate = SOURCE.indexOf( "this.hydrateAwaitingResponseCards();" );
  assert.ok( restore > 0 && hydrate > 0, "both calls must be present in init" );
  assert.ok( hydrate > restore, "the server's list must be read after the saved state is restored" );
  assert.equal( SOURCE.split( "this.hydrateAwaitingResponseCards();" ).length - 1, 1, "init must call it exactly once" );
} );
