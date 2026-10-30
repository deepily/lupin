// The page takes its time zone from /api/config/client and from nowhere else (row 43286adc).
//
// Pins three behaviours of notifications.js:
//   · a failed config fetch leaves appTimezone null, not a literal zone;

//   · every time display shows UTC, labelled, when no zone is configured, and honours a configured zone;
//
// Harness as in fleet_status_panel.test.ts: vm.runInThisContext the class, Object.create the prototype.
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/the_page_zone_comes_from_the_server_only.test.ts

import { test, before } from "node:test";
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
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type ZoneUI = Record<string, unknown> & {
  appTimezone: string | null | undefined;
  fetchClientConfig: () => Promise<void>;
  formatJobTimestamp: ( timestamp: string ) => string;
  extractDateFromTimestamp: ( iso: string | null ) => string;
  getLocalTimeDisplay: () => string;
  getLocalDateDisplay: () => string;
  getDateString: ( date: Date ) => string;
  renderJobCard: ( job: Record<string, unknown>, queueName: string ) => string;
};

function makeUI( appTimezone: string | null | undefined ): ZoneUI {
  const proto = ( globalThis as unknown as { NotificationsUI: { prototype: object } } ).NotificationsUI.prototype;
  const ui    = Object.create( proto ) as ZoneUI;
  const noop  = (): void => {};
  Object.assign( ui, {
    debug: false, log: noop, warn: noop, error: noop,
    isAdmin: false, queueFilterMode: "own", appTimezone,
    truncateText: ( text: string ) => text,
    escapeHtml:   ( text: string ) => text,
  } );
  return ui;
}

const SERVER_STAMP = "2026-01-14 @ 10:30:45 EST";
const NIGHT_UTC    = "2026-01-14T23:30:00Z";
const SCHEDULED_AT = "2026-01-14T15:30:00+00:00";

test( "a failed config fetch leaves the zone null, not a literal zone", async () => {
  const ui = makeUI( "Asia/Tokyo" );
  ui.authedFetch = async () => { throw new Error( "network down" ); };
  await ui.fetchClientConfig();
  assert.equal( ui.appTimezone, null );
} );

test( "a config answer carrying app_timezone sets the zone", async () => {
  const ui = makeUI( null );
  ui.authedFetch = async () => ( { ok: true, json: async () => ( { app_timezone: "America/Los_Angeles" } ) } );
  await ui.fetchClientConfig();
  assert.equal( ui.appTimezone, "America/Los_Angeles" );
} );

test( "a config answer without app_timezone leaves the zone null and logs one console error", async () => {
  const ui     = makeUI( "Asia/Tokyo" );
  const errors: unknown[][] = [];
  ui.error     = ( ...args: unknown[] ) => { errors.push( args ); };
  ui.authedFetch = async () => ( { ok: true, json: async () => ( { env_label: "TEST" } ) } );
  await ui.fetchClientConfig();
  assert.equal( ui.appTimezone, null );
  assert.equal( errors.length, 1 );
  assert.match( String( errors[ 0 ][ 0 ] ), /app_timezone/ );
} );

test( "a config answer with an empty app_timezone is treated as missing", async () => {
  const ui = makeUI( "Asia/Tokyo" );
  ui.authedFetch = async () => ( { ok: true, json: async () => ( { app_timezone: "" } ) } );
  await ui.fetchClientConfig();
  assert.equal( ui.appTimezone, null );
} );

test( "formatJobTimestamp shows the server's own text when no zone is configured and the text carries no offset", () => {
  assert.equal( makeUI( null ).formatJobTimestamp( SERVER_STAMP ), SERVER_STAMP );
} );

test( "formatJobTimestamp renders a no-zone instant in UTC, labelled", () => {
  const out = makeUI( null ).formatJobTimestamp( "2026-01-14T10:30:45Z" );
  assert.match( out, /10:30 AM UTC$/ );
} );

test( "formatJobTimestamp renders in the configured zone, with no UTC label", () => {
  const tokyo = makeUI( "Asia/Tokyo" ).formatJobTimestamp( "2026-01-14T10:30:45Z" );
  const la    = makeUI( "America/Los_Angeles" ).formatJobTimestamp( "2026-01-14T10:30:45Z" );
  assert.match( tokyo, /7:30 PM$/ );
  assert.match( la,    /2:30 AM$/ );
} );

test( "formatJobTimestamp keeps its empty and unparseable answers", () => {
  const ui = makeUI( "Asia/Tokyo" );
  assert.equal( ui.formatJobTimestamp( "" ), "" );
  assert.equal( ui.formatJobTimestamp( "not a date" ), "Invalid Date" );
} );

test( "formatJobTimestamp returns the text unchanged when the browser rejects the configured zone", () => {
  assert.equal( makeUI( "Not/AZone" ).formatJobTimestamp( "2026-01-14T10:30:45Z" ), "2026-01-14T10:30:45Z" );
} );

test( "the scheduled badge shows a UTC time labelled UTC when no zone is configured", () => {
  const html = makeUI( null ).renderJobCard( { job_id: "j1", question_text: "q", scheduled_at: SCHEDULED_AT }, "todo" );
  assert.match( html, /🕐 Jan 14 03:30 PM UTC/ );
} );

test( "the scheduled badge honours the configured zone", () => {
  const html = makeUI( "Asia/Tokyo" ).renderJobCard( { job_id: "j1", question_text: "q", scheduled_at: SCHEDULED_AT }, "todo" );
  assert.match( html, /Jan 15/ );
  assert.match( html, /12:30 AM(?! UTC)/ );
} );

test( "the date helpers use the configured zone, and UTC when none is configured", () => {
  const when = new Date( NIGHT_UTC );
  const tokyo = makeUI( "Asia/Tokyo" );
  const none  = makeUI( null );
  assert.equal( tokyo.extractDateFromTimestamp( NIGHT_UTC ), "2026-01-15" );
  assert.equal( none.extractDateFromTimestamp( NIGHT_UTC ), "2026-01-14" );
  assert.equal( tokyo.getDateString( when ), "2026-01-15" );
  assert.equal( none.getDateString( when ), "2026-01-14" );
  assert.match( none.getLocalDateDisplay(), /^\d{4}-\d\d-\d\d$/ );
  assert.match( none.getLocalTimeDisplay(), /^\d\d:\d\d UTC$/ );
  assert.doesNotMatch( tokyo.getLocalTimeDisplay(), /UTC$/ );
  assert.equal( none.extractDateFromTimestamp( null ), none.getLocalDateDisplay() );
} );

test( "a browser set to Tokyo does not leak its zone into a no-zone display", () => {
  const saved = process.env.TZ;
  process.env.TZ = "Asia/Tokyo";
  try {
    const none = makeUI( null );
    assert.equal( none.getDateString( new Date( NIGHT_UTC ) ), "2026-01-14" );
    assert.match( none.formatJobTimestamp( "2026-01-14T10:30:45Z" ), /10:30 AM UTC$/ );
    assert.match( none.renderJobCard( { job_id: "j1", question_text: "q", scheduled_at: SCHEDULED_AT }, "todo" ), /03:30 PM UTC/ );
  } finally {
    if ( saved === undefined ) delete process.env.TZ; else process.env.TZ = saved;
  }
} );
