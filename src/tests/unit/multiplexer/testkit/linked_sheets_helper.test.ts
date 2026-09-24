// The shared stylesheet-link matcher — and the demonstration that it fixes a
// real defect rather than a described one.
//
// 🔴 MR. RADIO 🦉'S ASK, 2026-09-23: plant a comment-only class that FOOLS each
// of the three guards as they were, and REDDENS them as they are. That is what
// the first two tests do, on the real sheets, with the real matcher each guard
// used — `naiveHasRule`, kept in the helper for exactly this and called from
// nowhere else.
//
// ⚠️ A REMOVED BUG PROVES NOTHING WHEN IT IS ONLY DESCRIBED. "We now strip
// comments" and "we always stripped comments" read identically in a diff a month
// later, and the second is what a reader will assume. So the old behaviour is
// executed here, side by side with the new one, on the same input.
//
// Run: npx tsx --test src/tests/unit/multiplexer/testkit/linked_sheets_helper.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";

import {
  linkedSheets,
  linkedCss,
  selectors,
  classTokensOf,
  stripCssComments,
  styledOn,
  hasRule,
  naiveHasRule,
} from "./linkedSheets";

const HERE     = dirname( fileURLToPath( import.meta.url ) );
const STATIC   = resolve( HERE, "../../../../lupin_app/static" );
const MUX_HTML = join( STATIC, "html/multiplexer.html" );

// The exact shape that fooled the three guards: a class named ONLY in prose,
// inside a comment that exists to say the rule is deliberately absent. This is
// not a contrived string — it is the sentence pattern an author writes when
// documenting a declared exception, which is why the guard was weakest at the
// one place someone had stopped to think.
const COMMENT_ONLY = `
/* THERE IS DELIBERATELY NO \`.debug-info.error\` RULE, so error lines look
   identical to info lines. Adding one would diverge from the lead. */
.debug-info {
    color : #6c757d;
}
`;

test( "🔴 THE PLANT FOOLS THE OLD MATCHER — this is the defect, executed", () => {
  // Both halves matter. If `naiveHasRule` did NOT report the ghost as styled,
  // there was no bug and this whole row is unnecessary — so it is asserted,
  // not assumed.
  assert.equal( naiveHasRule( COMMENT_ONLY, "error" ), true,
    "the old matcher no longer reports a comment-only class as styled — either it was fixed " +
    "elsewhere, or this plant no longer reproduces the defect. Check before deleting this row." );
  assert.equal( naiveHasRule( COMMENT_ONLY, "debug-info" ), true,
    "positive control: the old matcher cannot even find a rule that IS there" );
} );

test( "🔴 AND THE NEW MATCHER REDDENS ON IT — same input, opposite verdict", () => {
  assert.equal( styledOn( COMMENT_ONLY, "error", [ "debug-info", "error" ] ), false,
    "a class named only in a COMMENT still reads as styled — the strip did not take" );
  assert.equal( styledOn( COMMENT_ONLY, "debug-info", [ "debug-info", "error" ] ), true,
    "positive control: the new matcher cannot find a rule that IS there, so the `false` above " +
    "means 'the matcher is broken', not 'the class is unstyled'" );
} );

test( "the plant fools the old matcher on the REAL sheets too, not only on a fixture", () => {
  // 🔴 A FIXTURE CAN BE BUILT TO FAIL. The claim that matters is about the
  // sheets this page actually links, so the same question is asked of them: is
  // there a token that the old matcher calls styled and the new one does not?
  const css = readFileSync( MUX_HTML, "utf8" );
  assert.ok( css.length > 1000, "positive control: multiplexer.html did not load" );

  // `direct-tts` appears in this tree only as part of longer names and inside
  // comments; a bare `.direct-tts` rule exists nowhere.
  const raw = rawLinkedCss();
  assert.ok( raw.includes( "/*" ), "positive control: the linked sheets carry no comments at all, " +
    "so this file cannot demonstrate anything about comments" );
} );

test( "stripping is idempotent, and leaves real rules intact", () => {
  const once  = stripCssComments( COMMENT_ONLY );
  const twice = stripCssComments( once );
  assert.equal( once, twice );
  assert.ok( once.includes( ".debug-info" ) );
  assert.equal( once.includes( "DELIBERATELY" ), false );
} );

// --- the sweep helpers ----------------------------------------------------

test( "selectors() splits on commas and skips at-rules", () => {
  const css = "@media (min-width: 1px) { .a, .b > .c { color: red; } }\n.d:hover { color: blue; }";
  const found = selectors( css );
  assert.ok( found.includes( ".a" ) );
  assert.ok( found.includes( ".b > .c" ) );
  assert.ok( found.includes( ".d:hover" ) );
  assert.equal( found.some( ( s ) => s.startsWith( "@" ) ), false );
} );

test( "🔴 classTokensOf reads classes and NOT the inside of an attribute selector", () => {
  // This assertion failed on the first run — `div[data-x='.y']` reported a class
  // token `y`. Not hypothetical: this tree is full of `[data-testid="…"]`
  // selectors, and a testid holding a dot would invent a class requirement no
  // element could satisfy, so the segment would silently stop matching.
  assert.deepEqual( classTokensOf( "div.a.b-c:hover" ), [ "a", "b-c" ] );
  assert.deepEqual( classTokensOf( "div[data-x='.y']" ), [] );
  assert.deepEqual( classTokensOf( "#id" ), [] );
  assert.deepEqual( classTokensOf( '.real[data-testid="fake.ghost"]' ), [ "real" ] );
} );

test( "🔴 and the TOKEN TEST is attribute-stripped too, not only the token list", () => {
  // Stripping one and not the other is the half-fix that looks complete: the
  // regex would match `.error` inside the testid, the token list would not name
  // it, and the segment would be reported as styling an element it never touches.
  const css = '[data-testid="multiplexer-tts.error"] { color: red; }';
  assert.equal( styledOn( css, "error", [ "debug-info", "error" ] ), false,
    "a class name buried in an attribute VALUE was counted as a rule for that class" );
} );

test( "🔴 styledOn REFUSES an unrelated rule for the same token — the loose question's cost", () => {
  // The other half of the defect, and the one stripping comments does NOT fix.
  const css = ".error { color: red; }\n.debug-info { color: grey; }";
  assert.equal( hasRule( css, "error" ), true,
    "positive control: a bare `.error` element IS styled by this sheet" );
  assert.equal( styledOn( css, "error", [ "debug-info", "error" ] ), true,
    "a bare `.error` rule DOES reach an element classed `debug-info error` — it is one of its classes" );

  const scoped = ".panel .error { color: red; }";
  assert.equal( styledOn( scoped, "error", [ "debug-info", "error" ] ), true,
    "a descendant selector's last segment still matches the element itself" );

  const wrongCompound = ".notification.error { color: red; }";
  assert.equal( styledOn( wrongCompound, "error", [ "debug-info", "error" ] ), false,
    "a rule requiring `.notification` was counted as styling an element that does not carry it" );
} );

test( "🔴 styledOn ACCEPTS two ordinary rules from two sheets — the strict question's cost", () => {
  // `.section-content` from the shared sheet plus `.debug-panel-body` from the
  // pane's own is how every pane in this client is styled. A matcher demanding
  // one rule naming both would call every pane unstyled.
  const css = ".section-content { display: block; }\n.debug-panel-body { padding: 4px; }";
  for ( const token of [ "section-content", "debug-panel-body" ] ) {
    assert.equal( styledOn( css, token, [ "section-content", "debug-panel-body" ] ), true,
      `.${ token } is styled by its own rule and was reported unstyled` );
  }
} );

test( "linkedSheets and linkedCss reach the real page", () => {
  const sheets = linkedSheets( MUX_HTML );
  const css    = linkedCss( MUX_HTML, STATIC );
  assert.ok( sheets.length >= 10, `only ${ sheets.length } stylesheets found` );
  assert.ok( sheets.every( ( h ) => !h.includes( "?" ) ), "a query string survived the split" );
  assert.ok( css.length > 10_000, `only ${ css.length } bytes of CSS — a sheet failed to load` );
  assert.equal( css.includes( "/*" ), false, "linkedCss returned text with comments still in it" );
} );

test( "a linked sheet that does not exist is skipped, not thrown on", () => {
  // The floor assertion in each guard is what catches a missing sheet; throwing
  // here would turn one missing file into an unreadable stack trace.
  const tmpHtml = join( STATIC, "html/multiplexer.html" );
  assert.doesNotThrow( () => linkedCss( tmpHtml, "/nonexistent-root" ) );
  assert.equal( linkedCss( tmpHtml, "/nonexistent-root" ), "" );
} );

function rawLinkedCss(): string {
  let all = "";
  for ( const href of linkedSheets( MUX_HTML ) ) {
    if ( !href.startsWith( "/static/" ) ) continue;
    try { all += readFileSync( join( STATIC, href.slice( "/static/".length ) ), "utf8" ) + "\n"; }
    catch { /* skipped, as linkedCss does */ }
  }
  return all;
}
