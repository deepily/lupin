// The standalone pages take their zone from app-zone.js: the server zone, else labelled UTC.
//
// The script is a plain browser script, so it is loaded through vm with a stand-in for auth.js's apiCall.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/the_standalone_pages_zone_helper.test.ts

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

const HERE   = dirname( fileURLToPath( import.meta.url ) );
const SCRIPT = resolve( HERE, "../../../lupin_app/static/js/app-zone.js" );

type Zone = {
  load: () => Promise<void>; zone: () => string; label: () => string;
  time: ( d: Date, l?: string, o?: object ) => string; day: ( d: Date, l?: string, o?: object ) => string;
  dateTime: ( d: Date, l?: string, o?: object ) => string;
};

const AT = new Date( "2026-01-14T23:30:45Z" );   // 08:30 the next day in Tokyo

/** Load a fresh copy of the script with the given apiCall, and collect console.error lines. */
function loadScript( apiCall: ( endpoint: string ) => Promise<unknown> ): { zone: Zone; errors: string[] } {
  const errors: string[] = [];
  const sandbox = { apiCall, console: { error: ( ...a: unknown[] ) => errors.push( a.map( String ).join( " " ) ) } };
  vm.createContext( sandbox );
  const zone = vm.runInContext( readFileSync( SCRIPT, "utf8" ) + "\n;LupinAppZone", sandbox, { filename: SCRIPT } ) as Zone;
  return { zone, errors };
}

let saved: string | undefined;
beforeEach( () => { saved = process.env.TZ; process.env.TZ = "America/Los_Angeles"; } );
afterEach( () => { if ( saved === undefined ) delete process.env.TZ; else process.env.TZ = saved; } );

test( "before any load, and on a page that never loads, every display is labelled UTC", () => {
  const { zone } = loadScript( async () => ( {} ) );
  assert.equal( zone.zone(), "UTC" );
  assert.equal( zone.label(), " UTC" );
  assert.equal( zone.time( AT, "en-US" ), "11:30:45 PM UTC" );
  assert.equal( zone.day( AT, "en-US" ), "1/14/2026 UTC" );
  assert.equal( zone.dateTime( AT, "en-US" ), "1/14/2026, 11:30:45 PM UTC" );
} );

test( "a loaded server zone decides every display, whatever the browser zone is, with no UTC label", async () => {
  const asked: string[] = [];
  const { zone, errors } = loadScript( async ( endpoint ) => { asked.push( endpoint ); return { app_timezone: "Asia/Tokyo" }; } );
  await zone.load();
  assert.deepEqual( asked, [ "/api/config/client" ] );
  assert.equal( zone.zone(), "Asia/Tokyo" );
  assert.equal( zone.label(), "" );
  assert.equal( zone.time( AT, "en-US" ), "8:30:45 AM" );
  assert.equal( zone.day( AT, "en-US" ), "1/15/2026" );
  assert.equal( zone.dateTime( AT, "en-US", { hour12: false } ), "1/15/2026, 08:30:45" );
  assert.deepEqual( errors, [] );
} );

test( "a config answer without app_timezone leaves UTC and logs an error naming the field", async () => {
  for ( const answer of [ {}, null, { app_timezone: "" } ] ) {
    const { zone, errors } = loadScript( async () => answer );
    await zone.load();
    assert.equal( zone.zone(), "UTC" );
    assert.equal( errors.length, 1 );
    assert.match( errors[ 0 ]!, /app_timezone/ );
  }
} );

test( "a failed config fetch leaves UTC and logs an error naming the field", async () => {
  const { zone, errors } = loadScript( async () => { throw new Error( "HTTP 500" ); } );
  await zone.load();
  assert.equal( zone.zone(), "UTC" );
  assert.equal( errors.length, 1 );
  assert.match( errors[ 0 ]!, /app_timezone.*HTTP 500/ );
} );

test( "a second load forgets the first zone when the second answer has none", async () => {
  let answer: unknown = { app_timezone: "Asia/Tokyo" };
  const { zone } = loadScript( async () => answer );
  await zone.load();
  assert.equal( zone.zone(), "Asia/Tokyo" );
  answer = {};
  await zone.load();
  assert.equal( zone.zone(), "UTC" );
} );
