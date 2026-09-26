// Legacy broadcast-panel.js — the @mention chip inserts EXACTLY `@name`
// (row 319c57a3, Rick's ruling 2026-09-26 13:35).
//
// WHY THIS FILE EXISTS. The multiplexer and the legacy client carry a
// byte-identical `injectMentionAtCursor`, and row 319c57a3 changes BOTH. The
// multiplexer half is covered by broadcast_card_renderer.test.ts through the
// real renderer; this half had no executing test of any kind, so a fix landed
// there would have been unwitnessed. The row says "both clients", and a claim
// about the legacy client needs a legacy-client witness.
//
// HOW IT LOADS. broadcast-panel.js is plain browser JS wrapped in an IIFE with
// no exports and is in no tsconfig, so it cannot be imported. It is loaded the
// way src/tests/unit/notifications_js/ loads its subject: slice the function's
// own source out of the file and run it through vm.runInThisContext. That means
// the REAL bytes are under test — edit the file and this test sees the edit.
//
// ⚠️ The slice is anchored on text, and the anchor is checked to match EXACTLY
// ONCE. A second match, or none, aborts the load rather than silently testing
// the wrong function or an empty string.
//
// ⚠️ THIS FILE HAS NO c8 NUMBER, AND THAT IS NOT A GAP. broadcast-panel.js is in
// no tsconfig, so it is outside the TypeScript gate's denominator by
// construction — the same documented position as notifications.js. These
// behavioural assertions are its gate.
//
// Run via:
//   npx tsx --test src/tests/unit/broadcast_panel_js/mention_insert_is_exactly_at_name.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE               = dirname( fileURLToPath( import.meta.url ) );
const BROADCAST_PANEL_JS = resolve( HERE, "../../../lupin_app/static/js/broadcast-panel.js" );

const FN_OPEN  = "    function injectMentionAtCursor( token ) {";
const FN_CLOSE = "\n    }\n";

type Inject = ( token: string ) => void;

function inject(): Inject {
  return ( globalThis as unknown as { __injectMentionAtCursor: Inject } ).__injectMentionAtCursor;
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }

  const source = readFileSync( BROADCAST_PANEL_JS, "utf8" );

  // The anchor must be present, and present ONCE. Either failure aborts loudly
  // — a slice that silently grabs the wrong region is a test that passes while
  // measuring nothing.
  const open = source.indexOf( FN_OPEN );
  assert.ok( open >= 0, `anchor not found in broadcast-panel.js: ${FN_OPEN}` );
  assert.equal(
    source.indexOf( FN_OPEN, open + 1 ), -1,
    "anchor must match EXACTLY once — it matched twice, so the slice is ambiguous",
  );

  const close = source.indexOf( FN_CLOSE, open );
  assert.ok( close > open, "closing brace at function indent not found after the anchor" );
  const fnSource = source.slice( open, close + FN_CLOSE.length - 1 );

  // Prove the slice actually carries the logic under test before running it.
  assert.ok( fnSource.includes( "setSelectionRange" ), "slice must contain the caret write" );
  assert.ok( fnSource.includes( '"@" + token' ),       "slice must contain the mention build" );

  vm.runInThisContext( fnSource + "\n;globalThis.__injectMentionAtCursor = injectMentionAtCursor;" );
  assert.equal( typeof inject(), "function", "injectMentionAtCursor loaded into the global scope" );
} );

beforeEach( () => {
  document.body.replaceChildren();
  const ta = document.createElement( "textarea" );
  ta.id = "broadcast-textarea";
  document.body.appendChild( ta );
} );

function ta(): HTMLTextAreaElement {
  return document.getElementById( "broadcast-textarea" ) as HTMLTextAreaElement;
}

function seed( text: string, caret: number ): void {
  const t = ta();
  t.value = text;
  t.setSelectionRange( caret, caret );
}

// ---------------------------------------------------------------------------
// The same contract the multiplexer half asserts, against the legacy bytes.
//
// The cases deliberately cover the positions a boundary rule WOULD have treated
// specially — mid-word, before a colon, after a space, back-to-back, a newline
// neighbour — so re-introducing any of that logic reddens one of them by name.
// The caret is asserted every time: `value` alone cannot see a caret regression.
// ---------------------------------------------------------------------------

test( "insert 1: empty box → `@maria`, no trailing space", () => {
  seed( "", 0 );
  inject()( "maria" );
  assert.equal( ta().value, "@maria" );
  assert.equal( ta().selectionStart, "@maria".length );
} );

test( "insert 2: caret after `hi` → `hi@maria` — NO space is inserted for us", () => {
  seed( "hi", 2 );
  inject()( "maria" );
  assert.equal( ta().value, "hi@maria" );
  assert.equal( ta().selectionStart, "hi@maria".length );
} );

test( "insert 3: two clicks in a row → `@maria@mr radio`, verbatim and adjacent", () => {
  seed( "", 0 );
  inject()( "maria" );
  inject()( "mr radio" );
  assert.equal( ta().value, "@maria@mr radio" );
  assert.equal( ta().selectionStart, "@maria@mr radio".length );
} );

test( "insert 4: caret mid-text `hello|world` → `hello@mariaworld`, fused on purpose", () => {
  // The operator types their own spaces. This is the position a boundary rule
  // would have separated, and Rick ruled it does not.
  seed( "helloworld", 5 );
  inject()( "maria" );
  assert.equal( ta().value, "hello@mariaworld" );
  assert.equal( ta().selectionStart, "hello@maria".length );
} );

test( "insert 5: caret before a colon → `@maria:`, no special case needed", () => {
  seed( ":", 0 );
  inject()( "maria" );
  assert.equal( ta().value, "@maria:" );
  assert.equal( ta().selectionStart, "@maria".length );
} );

test( "insert 6: caret after a space the operator typed → `hi @maria`, still exactly one", () => {
  seed( "hi ", 3 );
  inject()( "maria" );
  assert.equal( ta().value, "hi @maria" );
  assert.equal( ta().selectionStart, "hi @maria".length );
} );

test( "insert 7: a newline neighbour gets no space either", () => {
  seed( "hi\n\nbye", 4 );
  inject()( "maria" );
  assert.equal( ta().value, "hi\n\n@mariabye" );
  assert.equal( ta().selectionStart, "hi\n\n@maria".length );
} );

test( "insert 8: a selection is REPLACED by the mention, nothing added around it", () => {
  // `before`/`after` slice at selectionStart/selectionEnd, so the selection is
  // what the mention displaces.
  seed( "aXXXb", 0 );
  ta().setSelectionRange( 1, 4 );
  inject()( "maria" );
  assert.equal( ta().value, "a@mariab" );
  assert.equal( ta().selectionStart, "a@maria".length );
} );
