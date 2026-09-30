// Markdown TABLES inside a legacy notification BUBBLE — row 5ae3ce90, Step 2.
//
// Bubbles render through `renderMarkdownInline` → `marked.parseInline`, which cannot build a
// table, so a table showed as raw pipes. Rick's ruling, 2026-09-10: legacy stays minimal until
// it is deleted — messages keep parseInline, and only a message that contains a GFM table goes to
// the block renderer, the way a ``` fence already does.
//
// ⚠️ WHAT THIS FILE CAN AND CANNOT SEE. It pins the ROUTING with the real vendored marked: which
// messages take the block path. DOMPurify does not sanitize under happy-dom and happy-dom does no
// cascade, so the allowlist and the styling are pinned in Chromium by
// src/tests/e2e_ui/test_a_legacy_bubble_renders_a_markdown_table.py.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/bubble_markdown_tables.test.ts

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

type BubbleUI = Record<string, unknown> & {
  renderMarkdownInline  : ( text: string ) => string;
  containsMarkdownTable : ( text: string ) => boolean;
};

function newUI(): BubbleUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as BubbleUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  return ui;
}

const TABLE = "| a | b |\n|---|:-:|\n| 1 | 2 |";

test( "a message containing a table takes the block path and renders a table", () => {
  const html = newUI().renderMarkdownInline( `Board state:\n\n${TABLE}` );
  for ( const tag of [ "<table", "<thead", "<tbody", "<th", "<td" ] ) {
    assert.ok( html.includes( tag ), `${tag} missing — the message went down parseInline` );
  }
} );

test( "a message without a table keeps the inline path: no <p> wrap", () => {
  const html = newUI().renderMarkdownInline( "hello **world**" );
  assert.equal( html, "hello <strong>world</strong>" );
} );

test( "containsMarkdownTable asks marked's lexer, so only a real table qualifies", () => {
  const ui = newUI();
  const cases: Array<[ string, boolean ]> = [
    [ TABLE,                                 true  ],
    [ "a | b\n--|--\n1 | 2",                 true  ],   // GFM allows a table with no outer pipes
    [ "> | a |\n> |---|\n> | 1 |",           true  ],   // nested in a blockquote
    [ "a | b | c",                           false ],   // pipes in prose
    [ "| a | b |\n| 1 | 2 |",                false ],   // header row with no delimiter row
    [ "cost | time\n--- then more",          false ],
  ];
  for ( const [ text, expected ] of cases ) {
    assert.equal( ui.containsMarkdownTable( text ), expected, JSON.stringify( text ) );
  }
} );
