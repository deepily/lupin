// Legacy notifications.js: a card arriving at the top keeps the reader's place.
//
// Rick's report: "an update inevitably arrives and the Notifications History is scrolled once again to the
// top of the notification list." An update moves the sender's card to the top of #notifications-list, or
// creates a new card there, so every card the reader can see shifts down by that card's height. The
// "Keep place" toggle (on by default) pins the card the reader is looking at across that move.
//
// happy-dom has no layout, so each card gets a rect from a small model: cards are stacked in DOM order,
// CARD_HEIGHT apart, and the window's scroll offset moves them up. The only scroll call the client may
// use is window.scrollBy, which the stub applies to that same offset.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/a_card_arriving_keeps_the_readers_place.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const CARD_HEIGHT = 200;
const NAV_OFFSET  = 100;     // the strip above the list; the client's anchor skips cards above it
const SENDERS     = [ "s1", "s2", "s3", "s4", "s5" ];

type UI = Record<string, unknown> & {
  moveSenderCardToTop : ( senderId: string, options?: Record<string, unknown> ) => void;
  keepPlace           : boolean;
};

let scrollY = 0;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

function cardId( senderId: string ): string {
  return `sender-card-${ senderId }`;
}

/** Give every card a rect from its place in the list and the current scroll offset. */
function installLayout(): void {
  for ( const card of Array.from( document.querySelectorAll( "#notifications-list > .sender-card" ) ) ) {
    ( card as HTMLElement ).getBoundingClientRect = (): DOMRect => {
      const list  = document.getElementById( "notifications-list" ) as HTMLElement;
      const index = Array.from( list.children ).indexOf( card );
      const top   = NAV_OFFSET + index * CARD_HEIGHT - scrollY;
      return { top, bottom: top + CARD_HEIGHT, left: 0, right: 800, width: 800, height: CARD_HEIGHT, x: 0, y: top, toJSON: () => ( {} ) } as DOMRect;
    };
  }
}

function topOf( senderId: string ): number {
  return ( document.getElementById( cardId( senderId ) ) as HTMLElement ).getBoundingClientRect().top;
}

function makeUI( keepPlace: boolean = false ): UI {     // the constructor sets the flag from storage; off is its default
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  const noop = (): void => {};
  Object.assign( ui, {
    debug                 : false,
    log                   : noop,
    warn                  : noop,
    error                 : noop,
    _markStripIconActivity: noop,
    _layoutMode           : "vertical",
  } );
  ui.keepPlace = keepPlace;
  return ui;
}

beforeEach( () => {
  scrollY = 0;
  localStorage.clear();
  document.body.replaceChildren();
  const column    = document.createElement( "div" );
  column.className = "left-column";
  const container = document.createElement( "div" );
  container.className = "container";
  const list = document.createElement( "div" );
  list.id = "notifications-list";
  for ( const s of SENDERS ) {
    const card = document.createElement( "div" );
    card.id        = cardId( s );
    card.className = "sender-card";
    list.appendChild( card );
  }
  container.appendChild( list );
  column.appendChild( container );
  document.body.appendChild( column );
  installLayout();
  Object.defineProperty( window, "scrollY", { get: () => scrollY, configurable: true } );
  ( window as unknown as { scrollBy: ( x: number, y: number ) => void } ).scrollBy = ( _x: number, y: number ): void => { scrollY += y; };
} );

test( "an update from a card below the view moves it to the top and the reader keeps their place", () => {
  scrollY = 450;                          // cards s3 and s4 are on screen
  const before3 = topOf( "s3" );
  const before4 = topOf( "s4" );
  makeUI( true ).moveSenderCardToTop( "s5" );
  const list = document.getElementById( "notifications-list" ) as HTMLElement;
  assert.equal( ( list.firstElementChild as HTMLElement ).id, cardId( "s5" ), "the card did move to the top" );
  assert.equal( topOf( "s3" ), before3 );
  assert.equal( topOf( "s4" ), before4 );
} );

test( "an update from the card the reader is looking at leaves the cards that stayed below it where they were", () => {
  scrollY = 450;                          // s3 is at 50 and s4 at 250; s4 is the one that moves
  const before5 = topOf( "s5" );
  makeUI( true ).moveSenderCardToTop( "s4" );
  const list = document.getElementById( "notifications-list" ) as HTMLElement;
  assert.equal( ( list.firstElementChild as HTMLElement ).id, cardId( "s4" ) );
  assert.equal( topOf( "s5" ), before5, "the first card that did not move is the anchor" );
} );

test( "a card the reader never scrolled to does not turn into an anchor: the moved card is skipped", () => {
  scrollY = 1;                            // the reader barely left the top: s1 sits at 99, s2 at 299
  const before2 = topOf( "s2" );
  makeUI( true ).moveSenderCardToTop( "s2" );   // s2 is the first card at or below the strip, and it is the one that moves
  assert.equal( topOf( "s3" ), 100 + 2 * CARD_HEIGHT - 1, "s3 is the anchor and stays put" );
  assert.ok( before2 > 0 );
} );

test( "at the top of the list nothing is compensated, so the new card is simply there", () => {
  scrollY = 0;
  makeUI( true ).moveSenderCardToTop( "s5" );
  assert.equal( scrollY, 0 );
  assert.equal( topOf( "s5" ), NAV_OFFSET );
} );

test( "by default the old behaviour stays: the view is left to shift", () => {
  scrollY = 450;
  const before3 = topOf( "s3" );
  makeUI().moveSenderCardToTop( "s5" );
  assert.equal( scrollY, 450 );
  assert.equal( topOf( "s3" ), before3 + CARD_HEIGHT );
} );

test( "Keep place is off when nothing was ever stored, on only for the stored word true", () => {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: Record<string, unknown> };
  assert.equal( typeof Ctor.prototype._readKeepPlace, "function" );
  const read = (): boolean => ( Ctor.prototype._readKeepPlace as () => boolean ).call( { KEEP_PLACE_KEY: "notifications_keep_place" } );
  assert.equal( read(), false );
  localStorage.setItem( "notifications_keep_place", "false" );
  assert.equal( read(), false );
  localStorage.setItem( "notifications_keep_place", "true" );
  assert.equal( read(), true );
} );
