// A switch-changed frame on the queue socket reaches the scheduled-jobs section.
//
// Legacy notifications.js, row 063fc1a8: the `cron_job_switch_changed` frame goes to
// window.cronJobs.applyEvent, and the name is subscribed on the queue socket only.
//
// Like its siblings, notifications.js is loaded by slicing the source through vm.runInThisContext,
// so c8 cannot see it; this behavioural test is its gate.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/a_cron_switch_frame_reaches_the_scheduled_jobs_section.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const EVENT            = "cron_job_switch_changed";

type UI = Record<string, unknown> & {
  handleQueueMessage: ( event: { data: string } ) => void;
  _buildQueueAuthMessage: () => { subscribed_events: string[] };
  _buildAudioAuthMessage: () => { subscribed_events: string[] };
};

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
} );

function makeUI(): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.authToken      = "<test-double-token-placeholder>";
  ui.queueSessionId = "calm dolphin";
  ui.audioSessionId = "wise owl";
  return ui;
}

const frame = () => ( { data: JSON.stringify( { type: EVENT, timestamp: "t", job: "duplicate-check", enabled: false } ) } );

test( "the frame reaches applyEvent whole", () => {
  const seen: unknown[] = [];
  ( globalThis as Record<string, unknown> ).cronJobs = { applyEvent: ( f: unknown ) => seen.push( f ) };
  ( window as unknown as Record<string, unknown> ).cronJobs = ( globalThis as Record<string, unknown> ).cronJobs;
  makeUI().handleQueueMessage( frame() );
  assert.deepEqual( seen, [ { type: EVENT, timestamp: "t", job: "duplicate-check", enabled: false } ] );
} );

test( "a frame arriving before the section script has loaded is ignored", () => {
  delete ( window as unknown as Record<string, unknown> ).cronJobs;
  makeUI().handleQueueMessage( frame() );
} );

test( "the name is on the queue socket's subscription list and not on the audio socket's", () => {
  const ui = makeUI();
  assert.ok( ui._buildQueueAuthMessage().subscribed_events.includes( EVENT ) );
  assert.ok( !ui._buildAudioAuthMessage().subscribed_events.includes( EVENT ) );
} );
