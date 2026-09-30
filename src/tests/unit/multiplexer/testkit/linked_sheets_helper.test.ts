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

// ===========================================================================
// 🔴 THE PLANT, ON THE REAL SHEETS, FOR EACH OF THE THREE GUARDS.
//
// A fixture can be built to fail. The claim that matters is about the sheets
// this page actually links, so the plant is applied to them: every rule naming
// the class is removed, every comment naming it is scrubbed, and ONE comment
// naming it is left. The old matcher must then call it STYLED and the new one
// must not.
//
// ⚠️ MY FIRST ATTEMPT AT THIS SCORED ZERO AND I NEARLY REPORTED IT AS A PASS.
// It deleted the class's standalone block and left the `:hover`, `:last-child`
// and descendant rules — `.top-solution-item` is named by SIX selectors in
// time-saved.css. The class was still genuinely styled by the survivors, so
// BOTH matchers correctly said so. A demonstration that scores zero has two
// explanations and "the fix is unnecessary" is the less likely one; the other
// is that the arm did not land. `rulesRemoved` is asserted below for exactly
// that reason — an arm that removes nothing proves nothing.
// ===========================================================================

const PLANTS = [
  { sheet: "css/multiplexer/finished-tasks.css", cls: "finished-task-row"  },
  { sheet: "css/multiplexer/time-saved.css",     cls: "top-solution-item"  },
  { sheet: "css/multiplexer/system-status.css",  cls: "refresh-link"       },
] as const;

/** Remove every rule naming `cls`, scrub comments naming it, plant one comment. */
function plant( css: string, cls: string ): { text: string; rulesRemoved: number } {
  const rule = new RegExp( `^[^\n{}]*\.${ cls }(?![\w-])[^\n{}]*\{[^}]*\}\n`, "gm" );
  const rulesRemoved = ( css.match( rule ) ?? [] ).length;
  let text = css.replace( rule, "" );
  text = text.replace( /\/\*[\s\S]*?\*\//g, ( m ) => ( m.includes( cls ) ? " " : m ) );
  text += `\n/* THERE IS DELIBERATELY NO .${ cls } RULE — it inherits from the row above. */\n`;
  return { text, rulesRemoved };
}

for ( const { sheet, cls } of PLANTS ) {
  test( `🔴 PLANT .${ cls } into ${ sheet.split( "/" ).pop() }: the old matcher is fooled, the new one is not`, () => {
    const original = readFileSync( join( STATIC, sheet ), "utf8" );
    const { text, rulesRemoved } = plant( original, cls );

    assert.ok( rulesRemoved >= 1,
      `the plant removed NO rules for .${ cls } — the arm did not land, so neither verdict below ` +
      `means anything. This is exactly how the first attempt scored a misleading zero.` );
    assert.equal( new RegExp( `\\.${ cls }(?![\\w-])` ).test( text ), true,
      "positive control: the planted comment does not name the class, so there is nothing to be fooled by" );

    // Every OTHER linked sheet, unchanged, plus the planted one — the real corpus.
    const others = linkedSheets( MUX_HTML )
      .filter( ( h ) => h.startsWith( "/static/" ) && !h.endsWith( sheet.split( "/" ).pop()! ) )
      .map( ( h ) => { try { return readFileSync( join( STATIC, h.slice( "/static/".length ) ), "utf8" ); } catch { return ""; } } )
      .join( "\n" );
    assert.ok( others.length > 10_000, "positive control: the rest of the page's CSS did not load" );

    const corpus = others + "\n" + text;
    assert.equal( naiveHasRule( corpus, cls ), true,
      `the OLD matcher no longer reports .${ cls } as styled. Either it was fixed elsewhere, or ` +
      `another sheet still defines it and this plant is not isolating what it claims to.` );
    assert.equal( hasRule( corpus, cls ), false,
      `the NEW matcher still reports .${ cls } as styled with every rule for it removed — the ` +
      `comment strip did not take, or another linked sheet defines it after all` );
  } );
}

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

