// The legacy diagnostic page's status panel updates (row c8b2d9e5)
//
// websocket-diagnostic.js kept its status elements under camelCase keys while every updateStatus
// call named them by their kebab-case page id, so no value ever reached the page. The file is plain
// browser JS in no tsconfig, so it has no c8 number. Its own bytes run through vm.runInThisContext
// against the body of the real diagnostic-websocket-test.html.
//
// Run via: npx tsx --test src/tests/unit/websocket_diagnostic_js/update_status_writes_to_the_page_elements.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE    = dirname( fileURLToPath( import.meta.url ) );
const STATIC  = resolve( HERE, "../../../lupin_app/static" );
const HTML    = readFileSync( resolve( STATIC, "html/test/diagnostic-websocket-test.html" ), "utf8" );
const JS_PATH = resolve( STATIC, "js/websocket-diagnostic.js" );
const JS_SRC  = readFileSync( JS_PATH, "utf8" );

type G = Record<string, any>;
const g = globalThis as unknown as G;

let Tool: any;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  // `class` at the top of a vm script is not a global property, so hand it out explicitly.
  vm.runInThisContext( JS_SRC + "\n;globalThis.__WebSocketDiagnosticTool = WebSocketDiagnosticTool;", { filename : JS_PATH } );
  Tool = g.__WebSocketDiagnosticTool;
} );

beforeEach( () => {
  const body = HTML.slice( HTML.indexOf( "<body>" ) + 6, HTML.indexOf( "</body>" ) );
  document.body.innerHTML = body.replace( /<script[\s\S]*?<\/script>/g, "" );
} );

/** A tool with its status elements set up, and none of the constructor's network start. */
function bare(): any {
  const tool = Object.create( Tool.prototype );
  tool.setupStatusElements();
  return tool;
}

// The ids the file passes to updateStatus, read from the file itself, never typed here.
const IDS = [ ...new Set( [ ...JS_SRC.matchAll( /updateStatus\(\s*'([^']+)'/g ) ].map( ( m ) => m[ 1 ] ) ) ];

test( "the file calls updateStatus with the eight page ids", () => {
  assert.deepEqual( [ ...IDS ].sort(), [
    "active-connections", "audio-elements", "chunks-received", "duplicate-connections",
    "first-audio-latency", "session-id", "simultaneous-play", "total-connections",
  ] );
} );

for ( const id of IDS ) {
  test( `updateStatus( '${id}' ) writes the value into #${id}`, () => {
    const el = document.getElementById( id );
    assert.ok( el, `the page has no #${id}` );
    bare().updateStatus( id, "written-by-test" );
    assert.equal( el!.textContent, "written-by-test" );
  } );
}

test( "an unknown id is ignored", () => {
  assert.doesNotThrow( () => bare().updateStatus( "no-such-id", "x" ) );
} );
