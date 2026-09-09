// 🔴 27 METHODS ARE REACHABLE ONLY THROUGH TEXT INSIDE AN HTML ATTRIBUTE, AND NOTHING CHECKED THEM.
//
// Measured 2026-09-09 (María 🌸), on row `464ea71e`, at HEAD `9810232c`:
//
//     total `window.notificationsUI` references          36
//     of those, inside inline onclick=/onchange= STRINGS 26
//     distinct METHODS reachable ONLY that way           27
//
// Every one lives inside a template literal that becomes an HTML attribute:
//
//     onclick="window.notificationsUI.toggleJobPause('${jobId}', ${!job.paused})"
//
// ⚠️ A TYPESCRIPT CHECKER CANNOT SEE INSIDE A STRING LITERAL. That is the whole reason this
// file exists, and it is the reason the obvious fix for `464ea71e` is not the fix. Adding
// notifications.js to a tsconfig — the action that row's "1,492 errors" number prices — buys
// the annotation debt and does NOT buy this surface. Rename `toggleJobPause` and the button
// dies at click time with the typecheck, the tier and the merge gate all green.
//
// 🔴 THIS FILE READS THE REAL PROTOTYPE. It does not pattern-match method definitions.
// The first cut of the measurement DID use a regex over definitions, and that regex was loose
// enough to match nested functions and object-literal methods — so its "0 unresolved" would
// have been indistinguishable from a matcher that matches everything. A guard whose green
// cannot fail is not a guard. References are extracted from source (they ARE source text,
// there is nowhere else they live); resolution is checked against the constructed class.
//
// WHAT MAKES THIS FILE FAIL, and each is a decision somebody should make on purpose:
//   · a method reached from an inline handler is renamed or deleted without updating the HTML
//   · a new inline handler is written against a method that does not exist
//   · the class stops exposing its methods on the prototype (e.g. moved to instance fields)
//
// Run: npx tsx --test src/tests/unit/notifications_js/every_inline_onclick_reaches_a_real_method.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

/** Every `window.notificationsUI.<name>` in the file — the optional-chaining form included. */
const REFERENCE_PATTERN = /window\.notificationsUI\??\.([A-Za-z_][A-Za-z0-9_]*)/g;

let source    = "";
let Ctor: { prototype: Record<string, unknown> };
let referenced: string[] = [];

/** Resolution as the browser would do it: walk the real prototype chain. */
function resolves( name: string ): boolean {
  return typeof ( Ctor.prototype as Record<string, unknown> )[ name ] === "function";
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();

  source = readFileSync( NOTIFICATIONS_JS, "utf8" );

  // Same seam every other file in this directory uses: evaluate the class body, stop before
  // the bottom-of-file init so nothing boots, then hand the constructor out.
  const initIdx = source.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    source.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );

  Ctor       = ( globalThis as Record<string, unknown> ).NotificationsUI as typeof Ctor;
  referenced = [ ...new Set( [ ...source.matchAll( REFERENCE_PATTERN ) ].map( m => m[ 1 ] ) ) ].sort();
} );

test( "POSITIVE CONTROL: the extractor finds the surface at all", () => {
  assert.ok( referenced.length >= 20,
    `expected the inline-handler surface to be substantial, found ${referenced.length} names. ` +
    `A near-empty result means the extraction broke, not that the coupling went away — ` +
    `check REFERENCE_PATTERN against how handlers are written today` );

  // A name nobody would invent, taken from a real inline handler in the file.
  assert.ok( referenced.includes( "toggleJobPause" ),
    "toggleJobPause is written into a real inline onclick in this file; if it is gone, " +
    "confirm the handler was removed on purpose before relaxing this control" );
} );

test( "POSITIVE CONTROL: resolution can actually FAIL — a fabricated name does not resolve", () => {
  assert.equal( resolves( "thisMethodDoesNotExistAnywhere" ), false,
    "the resolver reports a fabricated method as present, so a green result below would " +
    "prove nothing — this is the check that stops this file being a guard that cannot fail" );
} );

test( "POSITIVE CONTROL: resolution finds a method that IS there", () => {
  assert.equal( resolves( "toggleJobPause" ), true,
    "toggleJobPause is not on the prototype — if the class moved its methods to instance " +
    "fields, this file's resolution model is wrong and must be re-pointed, not deleted" );
} );

test( "THE GUARD: every method named in an inline handler exists on the class", () => {
  const missing = referenced.filter( n => !resolves( n ) );

  assert.deepEqual( missing, [],
    `these methods are called from inline HTML handlers and do NOT exist on ` +
    `NotificationsUI.prototype:\n\n    ${missing.join( "\n    " )}\n\n` +
    `Each one is a button that throws at click time. Nothing else in this repo catches ` +
    `this: the reference lives inside a string literal, so no typecheck can see it.\n` +
    `Fix the handler text or restore the method — do not delete this assertion.` );
} );
