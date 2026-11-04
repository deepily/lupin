// Every time display in notifications.js shows the server zone or labelled UTC.
//
// Each test drives one display method and reads the time text it wrote. Two zones are checked:
// Asia/Tokyo must give a Tokyo clock with no UTC label, and no zone must give a UTC clock with the label.
// Methods that are not under test are stubbed by a proxy that answers every unknown name with a no-op.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/every_time_display_site_shows_the_zone.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
} );

beforeEach( () => {
  document.body.replaceChildren();
  Element.prototype.scrollIntoView = (): void => {};
} );

type UI = Record<string, any>;   // eslint-disable-line @typescript-eslint/no-explicit-any

const AT = "2026-01-14T10:30:45Z";   // 19:30 in Tokyo, 10:30 in UTC

/** Build a display object whose unknown methods are no-ops and whose zone is `zone`. */
function makeUI( zone: string | null ): UI {
  const proto = ( globalThis as unknown as { NotificationsUI: { prototype: object } } ).NotificationsUI.prototype;
  const noop  = (): void => {};
  const loose = new Proxy( proto, { get: ( t, k, r ) => ( k in t ? Reflect.get( t, k, r ) : ( typeof k === "string" ? noop : undefined ) ) } );
  const ui    = Object.create( loose ) as UI;
  Object.assign( ui, {
    debug: false, log: noop, warn: noop, error: noop, appTimezone: zone,
    escapeHtml:          ( t: string ) => t,
    renderMarkdownInline: ( t: string ) => t,
    createProxyRatifyLink: () => null,
    expandedJobCards:    new Set<string>( [ "j1" ] ),
    senderGroups:        new Map(),
  } );
  return ui;
}

/** Put an element with the given id into the page and return it. */
function addEl( id: string, tag = "div" ): HTMLElement {
  const el = document.createElement( tag );
  el.id = id;
  document.body.appendChild( el );
  return el;
}

/** Assert a Tokyo clock for the Tokyo zone and a labelled UTC clock for none. */
function expectZone( zone: string | null, text: string | null | undefined, tokyoPattern: RegExp, utcPattern: RegExp ): void {
  if ( zone === null ) { assert.match( String( text ), utcPattern ); assert.match( String( text ), /UTC/ ); }
  else                 { assert.match( String( text ), tokyoPattern ); assert.doesNotMatch( String( text ), /UTC/ ); }
}

const ZONES: ( string | null )[] = [ "Asia/Tokyo", null ];

for ( const zone of ZONES ) {
  const name = zone ?? "no zone";

  test( `[${name}] checkWebSocketHealth stamps the healthy line in the display zone`, () => {
    const ui = makeUI( zone );
    const seen: string[] = [];
    const channel = { state: "CONNECTED", _tickWatchdog: (): void => {} };
    Object.assign( ui, { queueChannel: channel, audioChannel: channel, updateHealthStatus: ( t: string ) => seen.push( t ) } );
    ui.checkWebSocketHealth();
    assert.equal( seen.length, 1 );
    expectZone( zone, seen[ 0 ], /checked [\d:]+ [AP]M\)/, /checked [\d:]+ [AP]M UTC\)/ );
  } );

  for ( const [ label, notification ] of [ [ "with a timestamp", { timestamp: AT } ], [ "without a timestamp", {} ] ] as const ) {
    test( `[${name}] appendNotificationToJobCard shows a user message time ${label}`, () => {
      const ui = makeUI( zone );
      const content = addEl( "interactions-content-j1" );
      ui.appendNotificationToJobCard( "j1", { type: "user_initiated_message", message: "hi", ...notification } );
      expectZone( zone, content.querySelector( ".message-time" )?.textContent, /[AP]M$/, /[AP]M UTC$/ );
      if ( "timestamp" in notification ) assert.match( content.querySelector( ".message-time" )!.textContent!, zone === null ? /10:30:45 AM UTC/ : /7:30:45 PM/ );
    } );

    test( `[${name}] updateProgressGroupEntry restamps the head ${label}`, () => {
      const ui = makeUI( zone );
      const element = document.createElement( "div" );
      element.innerHTML = '<div class="progress-group-head"><span class="activity-message">old</span><span class="activity-timestamp">old time</span></div>';
      ui.updateProgressGroupEntry( element, { message: "new", ...notification } );
      expectZone( zone, element.querySelector( ".progress-group-head .activity-timestamp" )?.textContent, /[AP]M$/, /[AP]M UTC$/ );
    } );

    test( `[${name}] createActivityLogEntry stamps the entry ${label}`, () => {
      const ui = makeUI( zone );
      const entry = ui.createActivityLogEntry( { message: "m", priority: "low", ...notification } );
      expectZone( zone, entry.textContent, /[AP]M/, /[AP]M UTC/ );
    } );

    test( `[${name}] addMessageToDateAccordion stamps a legacy message ${label}`, () => {
      const ui = makeUI( zone );
      const container = addEl( "date-messages-s-2026-01-14" );
      ui.addMessageToDateAccordion( "s", "2026-01-14", { message: "m", id: "n1", ...notification }, false );
      expectZone( zone, container.querySelector( ".message-time" )?.textContent, /^\d\d:\d\d$/, /^\d\d:\d\d UTC$/ );
    } );

    test( `[${name}] updateSenderProgressGroupEntry restamps the head ${label}`, () => {
      const ui = makeUI( zone );
      const element = document.createElement( "div" );
      element.innerHTML = '<div class="progress-group-head"><span class="message-time">old</span><span class="message-text">old</span></div>';
      ui.updateSenderProgressGroupEntry( element, { message: "new", ...notification } );
      expectZone( zone, element.querySelector( ".progress-group-head .message-time" )?.textContent, /^\d\d:\d\d$/, /^\d\d:\d\d UTC$/ );
    } );

    test( `[${name}] addMessageToSenderCard stamps a legacy message ${label}`, () => {
      const ui = makeUI( zone );
      const container = addEl( "sender-messages-s" );
      ui.addMessageToSenderCard( "s", { message: "m", ...notification }, false );
      expectZone( zone, container.querySelector( ".message-time" )?.textContent, /[AP]M$/, /[AP]M UTC$/ );
    } );
  }

  test( `[${name}] appendJobUserMessage stamps the bubble`, () => {
    const ui = makeUI( zone );
    const content = addEl( "interactions-content-j1" );
    ui.appendJobUserMessage( "j1", "hi", "normal" );
    expectZone( zone, content.querySelector( ".message-time" )?.textContent, /[AP]M$/, /[AP]M UTC$/ );
  } );

  test( `[${name}] renderInteractionItem stamps a user message`, () => {
    const html = makeUI( zone ).renderInteractionItem( { type: "user_initiated_message", message: "hi", timestamp: AT } );
    expectZone( zone, html.match( /message-time">([^<]*)</ )![ 1 ], /7:30:45 PM$/, /10:30:45 AM UTC$/ );
  } );

  test( `[${name}] renderFinishedTasks stamps the updated time`, () => {
    const ui = makeUI( zone );
    const updated = document.createElement( "span" );
    Object.assign( ui, { _finishedTasksEls: () => ( { pills: [], count: document.createElement( "span" ), updated, container: null } ), _finishedTasksLitStatuses: () => [] } );
    ui.renderFinishedTasks( { done: [] }, null );
    expectZone( zone, updated.textContent, /[AP]M$/, /[AP]M UTC$/ );
  } );

  test( `[${name}] renderFinishedTasks leaves the updated time blank when nothing was measured`, () => {
    const ui = makeUI( zone );
    const updated = document.createElement( "span" );
    updated.textContent = "stale";
    Object.assign( ui, { _finishedTasksEls: () => ( { pills: [], count: document.createElement( "span" ), updated, container: null } ), _finishedTasksLitStatuses: () => [] } );
    ui.renderFinishedTasks( {}, null );
    assert.equal( updated.textContent, "" );
  } );

  test( `[${name}] addDebugMessage stamps the line`, () => {
    const ui = makeUI( zone );
    const log = addEl( "debug-log" );
    ui.addDebugMessage( "hello" );
    expectZone( zone, log.textContent, /^\[[\d:]+ [AP]M\] hello$/, /^\[[\d:]+ [AP]M UTC\] hello$/ );
  } );

  for ( const [ method, slot ] of [ [ "renderActiveTTSCard", "tts-active-slot" ], [ "renderMinimizedTTSCard", "tts-pending-queue" ] ] as const ) {
    test( `[${name}] ${method} stamps a card that has no time_display`, () => {
      const ui = makeUI( zone );
      const container = addEl( slot );
      const item = { id: "t1", type: "action-required", ttsText: "speak", addedAt: AT, notification: {} };
      ui.ttsQueue = [ item ];
      ui[ method ]( item );
      expectZone( zone, container.querySelector( ".message-time" )?.textContent, /^19:30$/, /^10:30 UTC$/ );
    } );
  }
}

test( "renderInteractionItem falls back to the raw timestamp when the browser rejects the zone", () => {
  const html = makeUI( "Not/AZone" ).renderInteractionItem( { type: "user_initiated_message", message: "hi", timestamp: AT } );
  assert.match( html, new RegExp( `message-time">${AT}<` ) );
} );

test( "the today window asks for the hours counted in the display zone", async () => {
  const ui = makeUI( "Asia/Tokyo" );
  const urls: string[] = [];
  addEl( "commons-recent-activity-entries" );
  Object.assign( ui, {
    _hoursSinceZoneMidnight: () => 7,
    authedFetch: async ( url: string ) => { urls.push( url ); return { ok: true, json: async () => ( { entries: [] } ) }; },
  } );
  await ui._loadCommonsRecentActivity( "today" );
  assert.equal( urls.length, 1 );
  assert.match( urls[ 0 ], /hours=7(&|$)/ );
} );
