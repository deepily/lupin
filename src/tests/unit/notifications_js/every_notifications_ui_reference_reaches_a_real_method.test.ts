// 🔴 22 METHODS ARE REACHABLE ONLY THROUGH TEXT INSIDE AN HTML ATTRIBUTE, AND NOTHING CHECKED THEM.
//
// ⚠️ THIS FILE WAS RENAMED 2026-09-09, AND THE OLD NAME WAS A CLAIM THE CODE DID NOT MAKE.
// It was `every_inline_onclick_reaches_a_real_method.test.ts`, and both the name and this header
// said "inline onclick". `REFERENCE_PATTERN` below is not scoped to attributes at all — it matches
// EVERY `window.notificationsUI.<name>` in the file, wherever it sits. Mr. Radio 🦉 caught the
// name; re-measuring to answer him showed the header numbers carried the same defect one line up.
//
// MEASURED 2026-09-09 at HEAD `371fb8fa` (María 🌸), on row `464ea71e` — each number with the
// scope it actually has, because the previous header did not:
//
//     `window.notificationsUI` references, occurrences         34
//     distinct names among them  ← THIS FILE'S CORPUS          27
//       · appearing inside an inline onclick=/onchange= string 24
//       · reachable ONLY that way, never called normally       22   ← the invisible surface
//       · never inline at all (ordinary calls, checkable)       3
//       · both inline and ordinary                              2
//
// The previous header reported `27` under the label "distinct METHODS reachable ONLY that way".
// 27 is the size of the whole corpus; the only-inline count is 22. The number was right about a
// set nobody had asked about and wrong about the set it was labelled with — which is the same
// error as the filename, and it is why the counts above name their scope explicitly.
//
// Every one of the 22 lives inside a template literal that becomes an HTML attribute:
//
//     onclick="window.notificationsUI.toggleJobPause('${jobId}', ${!job.paused})"
//
// ⚠️ A TYPESCRIPT CHECKER CANNOT SEE INSIDE A STRING LITERAL. That is the whole reason this
// file exists, and it is the reason the obvious fix for `464ea71e` is not the fix. Adding
// notifications.js to a tsconfig — the action that row's "1,492 errors" number prices — buys
// the annotation debt and does NOT buy those 22. Rename `toggleJobPause` and the button dies at
// click time with the typecheck, the tier and the merge gate all green.
//
// 🟢 GUARDING ALL 27 RATHER THAN ONLY THE 22 IS DELIBERATE. The extra five cost nothing to check
// and the inline/ordinary split is not stable — a handler moved into a real listener changes a
// name's category without changing its risk. Scoping the corpus to the split would mean
// re-deriving the split on every run and losing a name the moment somebody refactored it.
//
// ⚠️ ONE OF THE 27 IS A COMMENT, NOT A CALL — and it is named here rather than filtered out.
// `debugDumpJobCard` appears exactly once in notifications.js, inside its own usage docstring
// (`* Usage: window.notificationsUI.debugDumpJobCard( 'dr-a0ebba60' )`). It resolves on the
// prototype, so it is a real console helper whose only written reference is that line. § A hit
// is not a use applies — this extractor does not strip comments, and a corpus that cannot state
// how much of itself is commentary is telling you about its matcher.
// KEPT ON PURPOSE, with the reason: that comment is the helper's only documented entry point, so
// a rename that misses it leaves a docstring naming a method that no longer exists. Filtering
// comments out would drop the one reference most likely to rot unnoticed. It is 1 of 27; if that
// ratio ever grows, re-open this call rather than inheriting it.
//
// 🔴 THIS FILE READS THE REAL PROTOTYPE. It does not pattern-match method definitions.
// The first cut of the measurement DID use a regex over definitions, and that regex was loose
// enough to match nested functions and object-literal methods — so its "0 unresolved" would
// have been indistinguishable from a matcher that matches everything. A guard whose green
// cannot fail is not a guard. References are extracted from source (they ARE source text,
// there is nowhere else they live); resolution is checked against the constructed class.
//
// WHAT MAKES THIS FILE FAIL, and each is a decision somebody should make on purpose:
//   · a method named in a `window.notificationsUI` reference is renamed or deleted without
//     updating the reference
//   · a new reference is written against a method that does not exist
//   · the class stops exposing its methods on the prototype (e.g. moved to instance fields)
//   · the corpus SHRINKS below the ratchet below — see CORPUS_FLOOR
//
// Run: npx tsx --test src/tests/unit/notifications_js/every_notifications_ui_reference_reaches_a_real_method.test.ts

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

/**
 * 🔴 A RATCHET, NOT A SANITY CHECK — and the difference is seven names.
 *
 * This was `>= 20` against a corpus of 27, so a THIRD of the surface could disappear with the
 * whole file still green. Mr. Radio 🦉 named it 2026-09-09: a floor far below the real count
 * does not detect a shrinking corpus, it only detects total extractor failure — and total
 * failure is the one mode that was never the risk here.
 *
 * Set to the count measured at HEAD `371fb8fa`. Deleting a reference on purpose is fine and
 * this number moves DOWN with it, in the same commit, by a human who decided to. That edit is
 * the control: it forces the deletion to be stated rather than absorbed.
 */
const CORPUS_FLOOR = 27;

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

test( "POSITIVE CONTROL: the corpus has not shrunk — the extractor still sees the whole surface", () => {
  assert.ok( referenced.length >= CORPUS_FLOOR,
    `the guarded corpus is ${referenced.length} names; the floor measured at HEAD 371fb8fa is ` +
    `${CORPUS_FLOOR}. TWO DIFFERENT THINGS LOOK LIKE THIS, and they need opposite responses:\n\n` +
    `  · REFERENCES WERE REMOVED ON PURPOSE — lower CORPUS_FLOOR in the same commit that ` +
    `removes them, so the shrink is stated rather than absorbed.\n` +
    `  · THE EXTRACTOR BROKE — REFERENCE_PATTERN no longer matches how references are written ` +
    `today. Then the count below is fiction and lowering the floor hides the failure.\n\n` +
    `Read the file before choosing. Do NOT lower this number to make the suite green.` );

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

test( "THE GUARD: every method named in a window.notificationsUI reference exists on the class", () => {
  const missing = referenced.filter( n => !resolves( n ) );

  assert.deepEqual( missing, [],
    `these methods are named in window.notificationsUI references and do NOT exist on ` +
    `NotificationsUI.prototype:\n\n    ${missing.join( "\n    " )}\n\n` +
    `Each one is a button that throws at click time. Nothing else in this repo catches ` +
    `this for the 22 that live inside a string literal — no typecheck can see those at all.\n` +
    `Fix the handler text or restore the method — do not delete this assertion.` );
} );
