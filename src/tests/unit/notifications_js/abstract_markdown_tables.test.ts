// Markdown TABLES inside a notification abstract — Rick's question, 2026-09-05:
// "Is it possible to force markdown rendering of a table within a notification bubble?"
//
// 🔴 WHAT THIS FILE PINS, AND WHY IT IS NOT WHERE THE ROW EXPECTED. The row asked
// whether the defect was a PARSER gap (GFM off) or a SANITISER gap (tables stripped).
// Measured: NEITHER. `renderMarkdown` already sets `gfm: true`, and all six table tags
// are already in its DOMPurify ALLOWED_TAGS. The table was always being built and always
// surviving — nothing styled it, so it rendered as bare borderless text.
//
// ⇒ So these tests guard the layer that WAS already correct, because that is the layer a
// future edit could silently break: someone tightening ALLOWED_TAGS, or swapping the
// renderer, or turning `gfm` off, would return the bug with no other test noticing. The
// CSS half cannot be asserted here (happy-dom does no cascade) and is called out below.
//
// FIXTURE: Rick's own table, verbatim from row 6e2e2b93 — long prose cells, a branch
// name, shas, snake_case-ish tokens, an em dash, and cells far wider than a bubble.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/abstract_markdown_tables.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const STATIC           = resolve( HERE, "../../../lupin_app/static" );
const NOTIFICATIONS_JS = resolve( STATIC, "js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  // The REAL vendored libraries the page loads — not npm copies, which could differ in
  // version and would make this test report on software the browser never runs.
  vm.runInThisContext( readFileSync( resolve( STATIC, "js/vendor/marked.min.js" ), "utf8" ) );
  vm.runInThisContext( readFileSync( resolve( STATIC, "js/vendor/purify.min.js" ), "utf8" ) );

  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type MdUI = Record<string, unknown> & {
  renderMarkdown       : ( text: string ) => string;
  renderAbstractSection: ( abstract: string ) => string;
};

function newUI(): MdUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as MdUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  return ui;
}

// Rick's table, verbatim from the row.
const RICKS_TABLE = [
  "| Row | State |",
  "|---|---|",
  "| Land maya's eight commits (947f3c45) | Landed — land-maya-88f4dfdb @ 907b9a32, 8 commits, a3f45e6d ancestor, scanner present at tip. Verified in-tree, not from his summary. Not yet merged to a shared branch. |",
  "| Memento mirror keyed by worktree (bfcea79d) | Waiting on your ->done from your own account — the only path that exists. |",
  "| Tiberius | Re-spun at 51.2%: memento verified fresh, retained_unmatched empty, persona allocated, same seat. |",
].join( "\n" );

// ---------------------------------------------------------------------------
// The structural claim.
// ---------------------------------------------------------------------------

test( "Rick's table survives renderMarkdown as real table elements", () => {
  const html = newUI().renderMarkdown( RICKS_TABLE );
  for ( const tag of [ "<table", "<thead", "<tbody", "<tr", "<th", "<td" ] ) {
    assert.ok( html.includes( tag ), `${tag} must survive parse + sanitise` );
  }
} );

test( "the table has the right SHAPE — 2 headers, 3 body rows, 6 cells", () => {
  // Counting, not just presence: a renderer that emitted one mangled row would pass a
  // presence check and fail a human looking at the card.
  const el = document.createElement( "div" );
  el.innerHTML = newUI().renderMarkdown( RICKS_TABLE );

  assert.equal( el.querySelectorAll( "th" ).length,          2, "two headers" );
  assert.equal( el.querySelectorAll( "tbody tr" ).length,    3, "three body rows" );
  assert.equal( el.querySelectorAll( "tbody td" ).length,    6, "six body cells" );
  assert.equal( el.querySelector( "th" )?.textContent,  "Row" );
} );

test( "the awkward content in Rick's cells survives intact", () => {
  const el = document.createElement( "div" );
  el.innerHTML = newUI().renderMarkdown( RICKS_TABLE );
  const text = el.textContent ?? "";

  // Each of these is a token the row named as what actually breaks.
  assert.ok( text.includes( "947f3c45" ),             "a sha" );
  assert.ok( text.includes( "land-maya-88f4dfdb" ),   "a branch name" );
  assert.ok( text.includes( "retained_unmatched" ),   "a snake_case identifier" );
  assert.ok( text.includes( "—" ),                    "an em dash" );
  assert.ok( text.includes( "51.2%" ),                "a percentage" );
  // `->done` contains a character the sanitiser escapes; assert the TEXT, which is what
  // the reader sees, rather than the raw HTML entity.
  assert.ok( text.includes( "->done" ),               "an arrow token" );
} );

test( "a table nested in a real abstract section still renders", () => {
  // renderAbstractSection is the actual call site (notifications.js), so this exercises
  // the path rather than the helper — a helper-level pass would not prove the wrapper
  // keeps the table.
  const html = newUI().renderAbstractSection( "Board state:\n\n" + RICKS_TABLE );
  assert.ok( html.includes( "abstract-content" ), "the wrapper is present" );
  assert.ok( html.includes( "<table" ),           "and the table survives inside it" );
} );

// ---------------------------------------------------------------------------
// Negative controls — prove the assertions above can fail.
// ---------------------------------------------------------------------------

test( "POSITIVE CONTROL: prose without a table produces NO table", () => {
  // Without this, every assertion above could be passing because the renderer emits
  // table tags for everything, and the suite would be measuring nothing.
  const html = newUI().renderMarkdown( "Just a sentence with | a pipe | in it." );
  assert.ok( !html.includes( "<table" ), "a lone pipe must not become a table" );
} );

test( "the sanitiser is genuinely running — a forbidden tag is stripped", () => {
  // Proves the ALLOWED_TAGS path is live, so "tables survive" means survived a real
  // sanitise rather than bypassed one.
  const html = newUI().renderMarkdown( "text <img src=x> more" );
  assert.ok( !html.includes( "<img" ), "img is in FORBID_TAGS and must be removed" );
} );

// ⚠️ NOT TESTED HERE, DELIBERATELY, AND SAID SO RATHER THAN LEFT IMPLIED:
//
// 1. THE CSS. happy-dom applies no cascade and does no layout, so the rules that make
//    this LOOK like a table — borders, header shading, and the `display:block;
//    overflow-x:auto` that keeps a wide table scrolling inside itself instead of
//    widening the card — cannot be asserted in this tier. They are in
//    css/notifications.css under `.abstract-content table`. A browser check is the only
//    honest verification and it has not been run.
//
// 2. SCRIPT SANITISING. Measured 2026-09-05: under happy-dom, DOMPurify does NOT strip
//    <script> even though it strips <img>. That is an artifact of happy-dom's parsing,
//    not a statement about the browser — so no test here asserts script behaviour, and
//    nobody should add one to this tier and believe it.
