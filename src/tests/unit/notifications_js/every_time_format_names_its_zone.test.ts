// Every time formatting call in the web client names its zone (row 43286adc).
//
// A bare toLocaleTimeString() or getHours() answers in the browser's zone, which is the defect the
// server-zone-or-labelled-UTC rule exists to remove. This guard reads the source and fails on:
//   · toLocale{Time,Date,}String and Intl.DateTimeFormat calls whose arguments do not contain `timeZone`;
//   · the host-zone getters getHours, getMinutes, getDate, getDay, getMonth, getFullYear, getTimezoneOffset.
// It reads every tracked .ts file under src/lupin_app/static/js and every tracked .js and .html file under
// src/lupin_app/static (the mobile test build, dist and minified files are left out). A .ts file that
// still reads the browser zone must be on the owed list with a reason, and an owed file with no finding left fails as stale.
// It states its denominator (how many calls it checked) and proves itself on a planted site.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/every_time_format_names_its_zone.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const FORMAT_CALL  = /(?:\.toLocale(?:Time|Date)?String|\bIntl\.DateTimeFormat)\s*\(/g;
const HOST_GETTER  = /\.(?:getHours|getMinutes|getDate|getDay|getMonth|getFullYear|getTimezoneOffset)\s*\(/g;
// Number formatting, not time formatting: the one call that carries no date.
const NUMBER_CALLS = [ "tokens.toLocaleString()", "data.total_replays.toLocaleString()" ];

type Finding = { line: number; text: string };

/** Blank out comments, keeping every newline so line numbers stay true. */
function stripComments( source: string ): string {
  const blank = ( m: string ) => m.replace( /[^\n]/g, " " );
  return source.replace( /\/\*[\s\S]*?\*\//g, blank ).replace( /(^|\s)\/\/[^\n]*/g, blank );
}

/** Return the text between the parenthesis that opens at `open` and its match. */
function balancedArgs( source: string, open: number ): string {
  let depth = 0;
  for ( let i = open; i < source.length; i++ ) {
    if ( source[ i ] === "(" ) depth++;
    if ( source[ i ] === ")" && --depth === 0 ) return source.slice( open + 1, i );
  }
  throw new Error( `unbalanced parenthesis at offset ${open}` );
}

function lineOf( source: string, offset: number ): number {
  return source.slice( 0, offset ).split( "\n" ).length;
}

function scan( rawSource: string ): { checked: number; findings: Finding[] } {
  const source   = stripComments( rawSource );
  const findings: Finding[] = [];
  let checked    = 0;
  for ( const m of source.matchAll( FORMAT_CALL ) ) {
    const open = m.index! + m[ 0 ].length - 1;
    const call = source.slice( source.lastIndexOf( "\n", m.index! ) + 1, open + 1 );
    if ( NUMBER_CALLS.some( n => source.slice( Math.max( 0, m.index! - 20 ), open + 2 ).includes( n ) ) ) continue;
    checked++;
    if ( !/\btimeZone\b/.test( balancedArgs( source, open ) ) ) findings.push( { line: lineOf( source, m.index! ), text: call.trim() } );
  }
  for ( const m of source.matchAll( HOST_GETTER ) ) {
    checked++;
    findings.push( { line: lineOf( source, m.index! ), text: m[ 0 ] } );
  }
  return { checked, findings };
}

const SOURCE = readFileSync( NOTIFICATIONS_JS, "utf8" );
const ROOT   = resolve( HERE, "../../../.." );

/** Files that still read the browser zone, each with the reason it is owed. */
const OWED: Record<string, string> = {};

/** Every tracked non-test .ts file under the web client, as repo-relative paths. */
function trackedTsFiles(): string[] {
  const out = execFileSync( "git", [ "ls-files", "--", "src/lupin_app/static/js/*.ts" ], { cwd: ROOT, encoding: "utf8" } );
  return out.split( "\n" ).filter( f => f && !f.endsWith( ".test.ts" ) && !f.endsWith( ".d.ts" ) );
}

test( "no time formatting in notifications.js answers in the browser's zone", () => {
  const { findings } = scan( SOURCE );
  assert.deepEqual( findings, [], `time formatting without an explicit timeZone:\n${findings.map( f => `  line ${f.line}: ${f.text}` ).join( "\n" )}` );
} );

test( "no tracked .ts file reads the browser zone unless it is owed", () => {
  const bad = trackedTsFiles().filter( f => !( f in OWED ) ).flatMap( f => scan( readFileSync( resolve( ROOT, f ), "utf8" ) ).findings.map( x => `${f}:${x.line}: ${x.text}` ) );
  assert.deepEqual( bad, [], `time formatting without an explicit timeZone:\n  ${bad.join( "\n  " )}` );
} );

test( "every owed .ts file still has a finding, so the list cannot go stale", () => {
  const stale = Object.keys( OWED ).filter( f => scan( readFileSync( resolve( ROOT, f ), "utf8" ) ).findings.length === 0 );
  assert.deepEqual( stale, [] );
} );

test( "the .ts scan reaches a real population of files and calls", () => {
  const files = trackedTsFiles();
  assert.ok( files.length >= 100, `only ${files.length} .ts files were walked` );
  assert.ok( files.includes( "src/lupin_app/static/js/multiplexer/render/fleetModel.ts" ) && files.includes( "src/lupin_app/static/js/multiplexer/render/taskListModel.ts" ) );
  const checked = files.reduce( ( n, f ) => n + scan( readFileSync( resolve( ROOT, f ), "utf8" ) ).checked, 0 );
  assert.ok( checked >= 8, `only ${checked} calls were checked in .ts files` );
} );

test( "a planted bare call in a real .ts file reddens the guard", () => {
  const file    = readFileSync( resolve( ROOT, "src/lupin_app/static/js/multiplexer/render/fleetModel.ts" ), "utf8" );
  const planted = file.replace( "return new Intl.DateTimeFormat( undefined, { ...opts, timeZone: \"UTC\" } ).format( date );", "return new Intl.DateTimeFormat( undefined, opts ).format( date );" );
  assert.notEqual( planted, file, "the planting anchor must match" );
  assert.equal( scan( planted ).findings.length, 1 );
} );

const STATIC = "src/lupin_app/static";

/** Every tracked .js and .html file the web client serves, as repo-relative paths. */
function trackedPageFiles(): string[] {
  const out = execFileSync( "git", [ "ls-files", "--", `${STATIC}/*.js`, `${STATIC}/*.html` ], { cwd: ROOT, encoding: "utf8" } );
  return out.split( "\n" ).filter( f => f && !f.includes( "/lupin-mobile-test/" ) && !f.includes( "/dist/" ) && !f.endsWith( ".min.js" ) );
}

test( "no tracked .js or .html page reads the browser zone", () => {
  const bad = trackedPageFiles().flatMap( f => scan( readFileSync( resolve( ROOT, f ), "utf8" ) ).findings.map( x => `${f}:${x.line}: ${x.text}` ) );
  assert.deepEqual( bad, [], `time formatting without an explicit timeZone:\n  ${bad.join( "\n  " )}` );
} );

test( "the .js and .html scan reaches a real population of files", () => {
  const files = trackedPageFiles();
  assert.ok( files.length >= 55, `only ${files.length} .js and .html files were walked` );
  for ( const known of [ `${STATIC}/js/notifications.js`, `${STATIC}/js/chunk-sequencer.js`, `${STATIC}/html/document-viewer.html`, `${STATIC}/html/admin/js/peer-queue-watch.js` ] ) {
    assert.ok( files.includes( known ), `${known} was not walked` );
  }
} );

test( "a planted bare call in a real admin page script reddens the guard", () => {
  const file    = readFileSync( resolve( ROOT, `${STATIC}/html/admin/js/peer-queue-watch.js` ), "utf8" );
  const planted = file.replace( "LupinAppZone.time( new Date() )", "new Date().toLocaleTimeString()" );
  assert.notEqual( planted, file, "the planting anchor must match" );
  assert.equal( scan( planted ).findings.length, 1 );
} );

test( "every page that uses LupinAppZone loads app-zone.js first", () => {
  const pages = trackedPageFiles().filter( f => f.endsWith( ".html" ) );
  let users   = 0;
  for ( const page of pages ) {
    const html    = readFileSync( resolve( ROOT, page ), "utf8" );
    const scripts = [ ...html.matchAll( /<script[^>]*\ssrc="([^"]+)"/g ) ].map( m => m[ 1 ]! );
    const usesAt  = scripts.findIndex( src => src.startsWith( "/static/" ) && src !== "/static/js/app-zone.js"
                                         && existsSync( resolve( ROOT, "src/lupin_app", src.slice( 1 ) ) )   // built bundles are not tracked
                                         && readFileSync( resolve( ROOT, "src/lupin_app", src.slice( 1 ) ), "utf8" ).includes( "LupinAppZone." ) );
    if ( usesAt < 0 && !html.includes( "LupinAppZone." ) ) continue;
    users++;
    const loadAt = scripts.indexOf( "/static/js/app-zone.js" );
    assert.ok( loadAt >= 0, `${page} uses LupinAppZone but does not load app-zone.js` );
    if ( usesAt >= 0 ) assert.ok( loadAt < usesAt, `${page} loads app-zone.js after a script that uses it` );
  }
  assert.ok( users >= 8, `only ${users} pages were found using LupinAppZone` );
} );

test( "the scan reaches a real population of formatting calls", () => {
  const { checked } = scan( SOURCE );
  assert.ok( checked >= 12,
     `only ${checked} time-formatting calls were checked` );
} );

test( "a planted bare toLocaleTimeString in the real source reddens the guard", () => {
  const planted = SOURCE.replace( "this._zonedTime( now )", "now.toLocaleTimeString()" );
  assert.notEqual( planted, SOURCE, "the planting anchor must match" );
  assert.equal( scan( planted ).findings.length, 1 );
} );

test( "each kind of unzoned call is flagged, and a zoned or commented one is not", () => {
  const bad  = [ "d.toLocaleTimeString()", "d.toLocaleDateString( 'en-CA' )", "d.toLocaleString( [], { hour: 'numeric' } )",
                 "new Intl.DateTimeFormat( undefined, { hour: 'numeric' } )", "d.getHours()", "d.getFullYear()" ];
  for ( const call of bad ) assert.equal( scan( `x = ${call};` ).findings.length, 1, call );
  const good = [ "d.toLocaleTimeString( [], { timeZone: z } )", "new Intl.DateTimeFormat( 'en-GB', { timeZone: z, hour: 'numeric' } )",
                 "// d.getHours()", "/* d.toLocaleTimeString() */", "x = tokens.toLocaleString();" ];
  for ( const call of good ) assert.equal( scan( call ).findings.length, 0, call );
} );
