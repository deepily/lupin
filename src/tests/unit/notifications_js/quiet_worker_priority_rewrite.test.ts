// The legacy client's quiet-mode rewrite for a quiet worker (row 92076977).
//
// A spawned worker's notifications carry `worker_quiet: true`. The legacy client lowers its `high` to
// `medium` and keeps the ding, but a worker's `urgent` still speaks, by Rick's design.
// A manager that Rick quieted by hand has no stamp, so its `urgent` is lowered as before.
// The tests run the real handleNotificationUpdate from notifications.js and replace only its outputs
// (the ding, the card and the speech queue) with recorders.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/quiet_worker_priority_rewrite.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const WORKER  = "claude.code@lupin.deepily.ai#quietwk1";
const MANAGER = "claude.code@lupin.deepily.ai#quietmg1";
const LOUD    = "claude.code@lupin.deepily.ai#loudwk01";

type RewriteUI = Record<string, unknown> & {
  conversationModes        : Record<string, boolean>;
  handleNotificationUpdate : ( envelope: unknown ) => Promise<void>;
};

let UI     : RewriteUI;
let dings  : string[];
let spoken : string[];
let cards  : string[];

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

beforeEach( () => {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  UI = Object.create( Ctor.prototype ) as RewriteUI;
  UI.debug             = false;
  UI.log               = (): void => {};
  UI.conversationModes = {};
  UI.notificationState = { notifications: [] };
  UI.CONVERSATION_MODES_KEY = "test-conversation-modes";
  dings  = [];
  spoken = [];
  cards  = [];
  Object.assign( UI, {
    _maybeAutoPlayPodcast         : (): void => {},
    _setStripIconConvMode         : (): void => {},
    playNotificationSoundByPriority: async ( p: string ): Promise<void> => { dings.push( p ); },
    formatNotificationTTSMessage  : ( n: { message: string } ): string => n.message,
    addNotificationToSenderGroup  : ( n: { priority: string } ): void => { cards.push( n.priority ); },
    updateTotalNotificationsCount : (): void => {},
    addToTTSQueue                 : ( item: { notification: { priority: string } } ): void => { spoken.push( item.notification.priority ); },
  } );
} );

async function send( sender: string, priority: string, quiet: boolean ): Promise<void> {
  await UI.handleNotificationUpdate( { notification: {
    id_hash   : `${sender}-${priority}`,
    type      : "task",
    sender_id : sender,
    message   : "hello",
    priority,
    ...( quiet ? { worker_quiet: true } : {} ),
  } } );
  await new Promise( ( r ) => setTimeout( r, 350 ) );   // the speech queue is fed after a 300 ms settle
}

test("a quiet worker's high is lowered to medium: the ding is kept and nothing is spoken", async () => {
  await send( WORKER, "high", true );
  assert.deepEqual( dings,  [ "medium" ] );
  assert.deepEqual( spoken, [] );
  assert.deepEqual( cards,  [ "medium" ], "the card is still filed, at medium" );
});

test("a quiet worker's urgent is spared: it dings as urgent and is spoken", async () => {
  await send( WORKER, "urgent", true );
  assert.deepEqual( dings,  [ "urgent" ] );
  assert.deepEqual( spoken, [ "urgent" ] );
});

test("the stamp quiets the session, and a worker's medium stays unspoken", async () => {
  await send( WORKER, "medium", true );
  assert.equal( UI.conversationModes[ "quietwk1" ], false );
  assert.deepEqual( spoken, [] );
});

test("a manager Rick quieted by hand has no stamp, so its urgent is lowered to medium as before", async () => {
  UI.conversationModes[ "quietmg1" ] = false;
  await send( MANAGER, "urgent", false );
  assert.deepEqual( dings,  [ "medium" ] );
  assert.deepEqual( spoken, [] );
});

test("a manager Rick quieted by hand has its high lowered too", async () => {
  UI.conversationModes[ "quietmg1" ] = false;
  await send( MANAGER, "high", false );
  assert.deepEqual( spoken, [] );
});

test("with no stamp and no stored quiet, high and urgent speak as before", async () => {
  await send( LOUD, "high", false );
  await send( LOUD, "urgent", false );
  assert.deepEqual( spoken, [ "high", "urgent" ] );
});
