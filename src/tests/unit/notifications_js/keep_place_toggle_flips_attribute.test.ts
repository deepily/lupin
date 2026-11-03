// Legacy notifications.js: a click on the Keep place pill flips its two state attributes.
//
// Row c278c339. The pill is bound by _bindKeepPlaceToggle and painted by _paintKeepPlaceToggle; this
// enters at the click, as the page does, and reads the pill's attributes, its label and the stored word.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/keep_place_toggle_flips_attribute.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type UI = Record<string, ( ...args: unknown[] ) => unknown> & { keepPlace: boolean };

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

beforeEach( () => {
  document.body.replaceChildren();
  globalThis.localStorage?.clear();
} );

function makeUI( keepPlace: boolean ): UI {
  const Ctor   = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const noop   = (): void => {};
  const target = Object.create( Ctor.prototype ) as Record<string, unknown>;
  Object.assign( target, { debug: false, log: noop, warn: noop, error: noop, keepPlace, KEEP_PLACE_KEY: "keep-place-test" } );
  return new Proxy( target, { get: ( t, prop ) => ( prop in t ? t[ prop as string ] : noop ) } ) as unknown as UI;
}

function pill(): HTMLElement {
  const el = document.createElement( "button" );
  el.id    = "cc-keep-place-toggle";
  document.body.appendChild( el );
  return el;
}

test( "a click turns the pill on and a second click turns it off, attribute and aria-checked together", () => {
  const ui = makeUI( false );
  const el = pill();
  ui._paintKeepPlaceToggle();
  assert.equal( el.getAttribute( "data-keep-place" ), "false" );
  assert.equal( el.getAttribute( "aria-checked" ), "false" );
  ui._bindKeepPlaceToggle();
  el.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( el.getAttribute( "data-keep-place" ), "true" );
  assert.equal( el.getAttribute( "aria-checked" ), "true" );
  assert.equal( el.textContent, "📌 Place kept" );
  assert.equal( localStorage.getItem( "keep-place-test" ), "true" );
  el.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( el.getAttribute( "data-keep-place" ), "false" );
  assert.equal( el.getAttribute( "aria-checked" ), "false" );
  assert.equal( el.textContent, "📌 Keep place" );
  assert.equal( localStorage.getItem( "keep-place-test" ), "false" );
} );

test( "a page without the pill binds and paints nothing and does not throw", () => {
  const ui = makeUI( true );
  assert.doesNotThrow( () => { ui._bindKeepPlaceToggle(); ui._paintKeepPlaceToggle(); } );
} );
