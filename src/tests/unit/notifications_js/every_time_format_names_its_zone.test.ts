// Every time formatting call in notifications.js names its zone (row 43286adc).
//
// A bare toLocaleTimeString() or getHours() answers in the browser's zone, which is the defect the
// server-zone-or-labelled-UTC rule exists to remove. This guard reads the source and fails on:
//   · toLocale{Time,Date,}String and Intl.DateTimeFormat calls whose arguments do not contain `timeZone`;
//   · the host-zone getters getHours, getMinutes, getDate, getDay, getMonth, getFullYear, getTimezoneOffset.
// It states its denominator (how many calls it checked) and proves itself on a planted site.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/every_time_format_names_its_zone.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const FORMAT_CALL  = /(?:\.toLocale(?:Time|Date)?String|\bIntl\.DateTimeFormat)\s*\(/g;
const HOST_GETTER  = /\.(?:getHours|getMinutes|getDate|getDay|getMonth|getFullYear|getTimezoneOffset)\s*\(/g;
// Number formatting, not time formatting: the one call that carries no date.
const NUMBER_CALLS = [ "tokens.toLocaleString()" ];

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

test( "no time formatting in notifications.js answers in the browser's zone", () => {
  const { findings } = scan( SOURCE );
  assert.deepEqual( findings, [], `time formatting without an explicit timeZone:\n${findings.map( f => `  line ${f.line}: ${f.text}` ).join( "\n" )}` );
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
