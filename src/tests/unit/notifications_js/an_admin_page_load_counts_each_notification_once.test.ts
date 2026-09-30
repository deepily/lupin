// Legacy notifications.js — an admin page load counts each notification ONCE (row b670b76c).
//
// Measured 2026-09-10 (io/2026.09.10-mux-count-gap-root-cause.md, C2): on an admin login the
// legacy client showed about twice the multiplexer's count for every sender (489 vs 1026).
// Cause: startup calls initializeFilterUI(), which calls setFilterMode(), which fired an
// UN-awaited loadConversationHistory(); startup then awaited a second one. Two overlapping
// loads, and addNotificationToSenderGroup() had no dedupe, so every row was pushed and
// counted twice. The server log showed the conversation-by-date calls arriving in pairs.
// Rick ruled ~15:57 EDT: fix legacy.
//
// Two fixes, each pinned by its own test so each revert arm reddens on its own:
//   1. initializeFilterUI() sets the mode WITHOUT reloading history; startup's own load does it.
//   2. addNotificationToSenderGroup() skips a row whose id it already holds in that direction,
//      like the multiplexer's NotificationStore ("live-first wins"). A reply echo shares the
//      question's id on the live answer path, so direction is part of the key.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/an_admin_page_load_counts_each_notification_once.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

const SENDER = "claude.code@lupin.deepily.ai#abc12345";
const DAY    = "2026-09-10";

// Three rows; the third was answered, so each history load also adds its reply echo -> 4 entries.
const ROWS = [
  { id: "n1", sender_id: SENDER, message: "one",   timestamp: `${DAY}T15:00:00Z`, state: "delivered" },
  { id: "n2", sender_id: SENDER, message: "two",   timestamp: `${DAY}T15:01:00Z`, state: "delivered" },
  { id: "n3", sender_id: SENDER, message: "three", timestamp: `${DAY}T15:02:00Z`, state: "responded",
    response_value: { value: "yes" }, responded_at: `${DAY}T15:03:00Z` },
];
const ENTRIES_PER_LOAD = 4;

type Group = { totalCount: number; dateGroups: Map<string, unknown[]> };
type UI = Record<string, unknown> & {
  senderGroups                 : Map<string, Group>;
  initializeFilterUI           : () => void;
  setFilterMode                : ( mode: string ) => void;
  loadConversationHistory      : () => Promise<void>;
  addNotificationToSenderGroup : ( notification: unknown, isResponse?: boolean ) => void;
};

let fetchUrls: string[] = [];

function conversationFetches(): number {
  return fetchUrls.filter( u => u.includes( "/conversation-by-date/" ) ).length;
}

function installFetch(): void {
  fetchUrls = [];
  ( globalThis as Record<string, unknown> ).fetch = async ( url: string ) => {
    fetchUrls.push( url );
    await new Promise( r => setTimeout( r, 2 ) );   // real network yields, so two loads interleave
    const body = url.includes( "/senders-visible/" )
      ? [ { sender_id: SENDER, last_activity: `${DAY}T15:02:00Z` } ]
      : { [ DAY ]: ROWS };
    return { ok: true, status: 200, json: async () => body };
  };
}

function makeUI(): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  const noop = (): void => {};

  Object.assign( ui, {
    debug                     : false,
    log                       : noop,
    warn                      : noop,
    error                     : noop,
    isAdmin                   : true,
    currentUserEmail          : "rick@example.com",
    historyWindowHours        : 24,
    appTimezone               : "America/New_York",
    senderGroups              : new Map(),
    senderPersonaMap          : new Map(),
    managerPersonaMap         : new Map(),
    isInitialLoad             : false,
    QUEUE_FILTER_PREF_KEY     : "notifications_filter_preference",
    UNKNOWN_SENDER            : "unknown",
    ensureValidToken          : async (): Promise<void> => {},
    getAuthHeader             : () => "Bearer test-token",
    refreshAllQueues          : noop,
    createSenderCard          : noop,
    createDateAccordion       : noop,
    addMessageToDateAccordion : noop,
    updateSenderCardHeader    : noop,
    moveSenderCardToTop       : noop,
    saveSessionName           : noop,
    _clearAllStripIcons       : noop,
    updateClearButtonState    : noop,
  } );

  for ( const id of [ "filter-settings-section", "filter-own-jobs", "filter-others-jobs",
                      "filter-all-jobs", "filter-mode-display", "notifications-list", "notifications-count" ] ) {
    const el = document.createElement( "div" );
    el.id = id;
    document.body.appendChild( el );
  }
  return ui;
}

const settle = (): Promise<void> => new Promise( r => setTimeout( r, 40 ) );

beforeEach( () => {
  document.body.replaceChildren();
  localStorage.clear();
  installFetch();
} );

test( "an admin page load fetches each sender's history once, not twice", async () => {
  const ui = makeUI();

  // The startup order in init(): filter UI first, then the awaited history load.
  ui.initializeFilterUI();
  await ui.loadConversationHistory();
  await settle();

  assert.equal( conversationFetches(), 1, `conversation-by-date fetched ${conversationFetches()} times on one page load` );
} );

test( "an admin page load shows each notification once in the sender's count and the total", async () => {
  const ui = makeUI();

  ui.initializeFilterUI();
  await ui.loadConversationHistory();
  await settle();

  assert.equal( ui.senderGroups.get( SENDER )?.totalCount, ENTRIES_PER_LOAD );
  assert.equal( document.getElementById( "notifications-count" )?.textContent, String( ENTRIES_PER_LOAD ) );
} );

test( "two history loads that overlap still count each notification once", async () => {
  const ui = makeUI();

  await Promise.all( [ ui.loadConversationHistory(), ui.loadConversationHistory() ] );

  const group = ui.senderGroups.get( SENDER );
  assert.equal( group?.totalCount, ENTRIES_PER_LOAD, "overlapping loads double-counted" );
  assert.equal( group?.dateGroups.get( DAY )?.length, ENTRIES_PER_LOAD, "overlapping loads pushed rows twice" );
} );

test( "clicking a filter button still reloads history (control: only the startup call skips it)", async () => {
  const ui = makeUI();
  ui.initializeFilterUI();
  await ui.loadConversationHistory();
  await settle();
  const before = conversationFetches();

  ui.setFilterMode( "all" );
  await settle();

  assert.equal( conversationFetches(), before + 1, "a filter click must reload history" );
  assert.equal( ui.senderGroups.get( SENDER )?.totalCount, ENTRIES_PER_LOAD, "the reload replaces the cards, it does not add to them" );
} );

test( "a reply echo that shares the question's id is a second entry, not a duplicate", () => {
  const ui       = makeUI();
  const question = { id: "q1", sender_id: SENDER, message: "Promote it?", timestamp: `${DAY}T16:00:00Z`, state: "delivered" };

  // The live answer path re-adds the question object, with its own id, as the outgoing reply.
  ui.addNotificationToSenderGroup( question, false );
  ui.addNotificationToSenderGroup( { ...question, message: "Response: yes", response_value: "yes" }, true );

  assert.equal( ui.senderGroups.get( SENDER )?.totalCount, 2 );
} );

test( "a row with no id is counted every time, because it cannot be recognised as a repeat", () => {
  const ui  = makeUI();
  const row = { sender_id: SENDER, message: "no id", timestamp: `${DAY}T16:05:00Z`, state: "delivered" };

  ui.addNotificationToSenderGroup( row, false );
  ui.addNotificationToSenderGroup( row, false );

  assert.equal( ui.senderGroups.get( SENDER )?.totalCount, 2 );
} );
