// Legacy notifications.js: Keep place on, an arriving notification does not scroll the view.
//
// Rick's report (row 2958799a): the next notification to arrive scrolled the list away from where he was
// reading. Four automatic scrolls ran without asking Keep place: the action-required card arriving,
// a job-card entry arriving, a timed-out question settling onto its card, and an answered question
// settling onto its job card. A scroll the reader asked for with a click is not one of them.
// Each test enters where the arrival enters and counts scrollIntoView calls with Keep place off, then on.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/keep_place_arrival_does_not_scroll.test.ts

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

let scrolls: string[] = [];

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  ( HTMLElement.prototype as unknown as Record<string, unknown> ).scrollIntoView = function ( this: HTMLElement ): void {
    scrolls.push( this.id || this.className );
  };
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

/** A real NotificationsUI whose helpers outside this test's path are no-ops. */
function makeUI( keepPlace: boolean, extra: Record<string, unknown> = {} ): UI {
  const Ctor   = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const noop   = (): void => {};
  const target = Object.create( Ctor.prototype ) as Record<string, unknown>;
  Object.assign( target, {
    debug: false, log: noop, warn: noop, error: noop,
    keepPlace,
    expandedJobCards         : new Set( [ "j1" ] ),
    actionRequiredNotifications: new Map(),
    UNKNOWN_SENDER           : "unknown",
    appTimezone              : "UTC",
    senderGroups             : new Map(),
    managerPersonaMap        : new Map(),
    senderPersonaMap         : new Map(),
    ...extra,
  } );
  return new Proxy( target, { get: ( t, prop ) => ( prop in t ? t[ prop as string ] : noop ) } ) as unknown as UI;
}

function element( id: string, tag: string = "div" ): HTMLElement {
  const el = document.createElement( tag );
  el.id    = id;
  document.body.appendChild( el );
  return el;
}

beforeEach( () => {
  scrolls = [];
  document.body.replaceChildren();
} );

const ACTION = { id: "a1", sender_id: "claude.code@lupin.deepily.ai#00000001", message: "Proceed?", response_type: "yes_no" };

test( "instrument check: an action-required card arriving with Keep place off scrolls to its section", async () => {
  element( "action-required-active-slot" );
  element( "action-required-section" );
  makeUI( false ).renderActionRequiredNotification( ACTION );
  await new Promise( r => setTimeout( r, 80 ) );
  assert.deepEqual( scrolls, [ "action-required-section" ] );
} );

test( "🔴 with Keep place on, an action-required card arrives and the view does not move", async () => {
  element( "action-required-active-slot" );
  element( "action-required-section" );
  makeUI( true ).renderActionRequiredNotification( ACTION );
  await new Promise( r => setTimeout( r, 80 ) );
  assert.ok( document.getElementById( "action-required-a1" ), "the card did not arrive" );
  assert.deepEqual( scrolls, [], "the arrival scrolled the view while Keep place was on" );
} );

for ( const [ keep, expected ] of [ [ false, 1 ], [ true, 0 ] ] as const ) {
  const word = keep ? "on" : "off";

  test( `a job-card entry arriving with Keep place ${ word } scrolls ${ expected } time(s)`, () => {
    const content = element( "interactions-content-j1" );
    makeUI( keep ).appendNotificationToJobCard( "j1", { message: "hi", priority: "low", timestamp: new Date().toISOString() } );
    assert.equal( content.children.length, 1, "the entry did not arrive" );
    assert.equal( scrolls.length, expected );
  } );

  test( `a question timing out with Keep place ${ word } scrolls ${ expected } time(s) to its card`, () => {
    element( "action-required-t1" );
    element( "sender-card-s1" );
    const ui = makeUI( keep, {
      calculateDestination : () => ( { cardId: "sender-card-s1", senderId: "s1", rect: {} } ),
      startGenieAnimation  : ( _id: string, _card: unknown, _dest: unknown, done: () => void ) => done(),
    } );
    ( ui.actionRequiredNotifications as unknown as Map<string, unknown> ).set( "t1", {
      notification: { id: "t1", sender_id: "s1", response_type: "yes_no", response_default: "yes" },
      isResponded : false,
    } );
    ui.handleLocalTimeout( "t1" );
    assert.equal( scrolls.filter( id => id === "sender-card-s1" ).length, expected );
  } );

  test( `a question settling onto its job card with Keep place ${ word } scrolls ${ expected } time(s)`, () => {
    element( "interactions-content-j1" );
    element( "job-card-j1" );
    makeUI( keep ).routeCompletedNotification(
      { job_id: "j1", sender_id: "s1", message: "Proceed?", response_type: "yes_no", timestamp: new Date().toISOString() },
      "yes", false, "10:00", "2026-10-31"
    );
    assert.equal( scrolls.filter( id => id === "job-card-j1" ).length, expected );
  } );
}
