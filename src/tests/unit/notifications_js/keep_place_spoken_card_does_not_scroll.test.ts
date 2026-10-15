// Legacy notifications.js: Keep place on, a spoken card does not move the view.
//
// startTTSPlayingIndicator expands what hides the card and scrolls it into view. Keep place keeps the
// expansion and drops the scroll. The test enters through startTTSPlayingIndicator, where speech enters.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/keep_place_spoken_card_does_not_scroll.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type UI = Record<string, unknown> & {
  startTTSPlayingIndicator : ( id: string ) => void;
  keepPlace                : boolean;
};

let scrolls = 0;
let expands = 0;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

function makeUI( keepPlace: boolean ): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  const noop = (): void => {};
  Object.assign( ui, {
    debug: false, log: noop, warn: noop, error: noop,
    senderGroups     : new Map( [ [ "s1", {} ] ] ),
    expandSenderCard : (): void => { expands += 1; },
    expandDateAccordion: noop,
  } );
  ui.keepPlace = keepPlace;
  return ui;
}

beforeEach( () => {
  scrolls = 0;
  expands = 0;
  document.body.replaceChildren();
  const card = document.createElement( "div" );
  card.id    = "sender-card-s1";
  card.className = "sender-card";
  const note = document.createElement( "div" );
  note.id    = "n1";
  note.getBoundingClientRect = () => ( {
    top: window.innerHeight + 100, bottom: window.innerHeight + 400,
    left: 0, right: 0, width: 0, height: 300, x: 0, y: 0, toJSON: () => ( {} ),
  } ) as DOMRect;
  note.scrollIntoView = (): void => { scrolls += 1; };
  card.appendChild( note );
  document.body.appendChild( card );
} );

test( "instrument check: with Keep place off a spoken card is expanded and scrolled into view", () => {
  makeUI( false ).startTTSPlayingIndicator( "n1" );
  assert.equal( expands, 1 );
  assert.equal( scrolls, 1 );
} );

test( "🔴 with Keep place on, a spoken card is expanded but the view does not move", () => {
  makeUI( true ).startTTSPlayingIndicator( "n1" );
  assert.equal( expands, 1, "the card was not expanded" );
  assert.equal( scrolls, 0, "the spoken card moved the view while Keep place was on" );
} );
