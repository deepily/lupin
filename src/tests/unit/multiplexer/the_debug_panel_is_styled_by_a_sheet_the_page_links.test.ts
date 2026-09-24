// 🔴 A CORRECT RENDERER WHOSE STYLESHEET NOTHING LOADS IS A BROKEN PAGE, AND
// EVERY TEST STAYS GREEN — gap G2. B-6 adds a new sheet
// (css/multiplexer/debug-panel.css) and therefore a new <link> line, which is
// exactly the shape that failed before. Both halves are held here.
//
// 🔴 AND THE MATCHER HERE STRIPS COMMENTS, WHICH ITS SIBLINGS DO NOT. The
// sibling guards for the Finished Tasks, Time Saved and System Status panes ask
// `/\.<class>(?![\w-])/` of the CONCATENATED sheet text. Measured on this branch
// 2026-09-23: that test reports `.error` as STYLED across all 27 linked sheets,
// and the only occurrence in any of them is the sentence in debug-panel.css
// explaining that no such rule exists. A prose mention of a class satisfies the
// check that the class has a rule. So this file parses selectors instead, and
// proves the difference with a control below rather than asserting it in a
// comment. (Reported to María 🌸 as a defect in those three files; not repaired
// here, because repairing them is not this branch's work.)
//
// 🔴 THIS PANE CARRIES TWO DECLARED EXCEPTIONS — THE TYPE TOKENS, `.info` AND
// `.error`. Legacy's `addDebugMessage` (notifications.js:21174) writes
// `debug-info info` or `debug-info error` onto every line it builds, and legacy
// defines exactly ONE rule for any of it: `.debug-info` (notifications.css:352).
// Neither type token is styled in any sheet the legacy page links, so all three
// kinds of line render in the same #6c757d grey. The multiplexer emits the same
// classes for parity of shape and deliberately ships no rules for them.
//
// ⚠️ `.info` IS ON THIS LIST BECAUSE A RULE FOR IT WAS REMOVED, NOT BECAUSE ONE
// WAS NEVER WRITTEN. debug-panel.css carried `.debug-info.info { color: inherit }`,
// added to make the class attribute's shape match — which it already did — and
// `inherit` OVERRODE `.debug-info`'s #6c757d, so every info line in the
// multiplexer rendered in the body colour where legacy's renders grey. A rule
// added for parity that broke parity, caught by María 🌸 in review rather than
// by this guard, which the rule satisfied. That is the argument for sweeping
// for a MISSING rule and for checking the exception is still earned: a present
// rule is not evidence of a correct one.
//
// The last test asserts both exceptions are still EARNED — if legacy ever gains
// either rule, that test fails and this list should SHRINK, not grow.
//
// ⚠️ THE EXCEPTION IS A COMPOUND, NOT A BARE TOKEN. `.error` on its own is not
// the question: the panel's error line is `class="debug-info error"`, and a rule
// for some unrelated `.error` elsewhere would style it by accident. What is
// asked below is whether the compound the panel actually emits is styled.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_debug_panel_is_styled_by_a_sheet_the_page_links.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createDebugPanelRenderer } from "../../../lupin_app/static/js/multiplexer/render/DebugPanelRenderer";

import {
  linkedSheets,
  linkedCss as sharedLinkedCss,
  selectors,
  styledOn,
  hasRule,
  stripCssComments,
} from "./testkit/linkedSheets";
import { log, error, wsDiag, setDebugPanel } from "../../../lupin_app/static/js/multiplexer/shared/debugSink";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const HERE        = dirname( fileURLToPath( import.meta.url ) );
const STATIC      = resolve( HERE, "../../../lupin_app/static" );
const MUX_HTML    = join( STATIC, "html/multiplexer.html" );
const LEGACY_HTML = join( STATIC, "html/notifications.html" );
const SHEET       = "/static/css/multiplexer/debug-panel.css";

/**
 * `"<the element's classes>" -> "<the token with no rule>"` — emitted ON PURPOSE
 * with nothing styling it, legacy's own defect inherited rather than fixed.
 * Shrink this list when legacy gains the rule; never grow it to silence a sweep.
 */
const UNSTYLED_BY_LEGACY = [
  "debug-info info » .info",
  "debug-info error » .error",
];

// --- the shared matcher (testkit/linkedSheets.ts) --------------------------
// This file carried its own copy of every function below until row 998ad3b0.
// Four guards held four copies, and the copy is how the comment defect spread:
// a fix to one of them left the other three saying a commented-out class was
// styled. The helper's `classTokensOf` also strips ATTRIBUTE SELECTORS, which
// this copy did not — `[data-testid="a.b"]` used to report a class token `b`.
// The local names are kept as thin aliases so the assertions below read the
// same as when they were written.
const linkedCss      = ( htmlPath: string ): string => sharedLinkedCss( htmlPath, STATIC );
const stripComments  = stripCssComments;


/**
 * Mount the pane, drive EVERY writer, and collect every class that appears.
 *
 * 🔴 ONE MOUNT WOULD MISS THE TYPES. A freshly-mounted panel holds the seeded
 * line and nothing else, and the seeded line's class is bare `debug-info` — so
 * a sweep over an unwritten panel would never see `info` or `error` at all and
 * would report a clean bill of health over the two classes in question.
 */
function paneClassSpecs(): string[][] {
  const realLog   = console.log;
  const realError = console.error;
  console.log   = () => {};
  console.error = () => {};

  const root = document.createElement( "div" );
  const r    = createDebugPanelRenderer( {} );
  r.mount( root );
  log( "an info line" );
  error( "an error line" );
  wsDiag( "a diagnostic" );

  const found: string[][] = [];
  for ( const el of [ root, ...Array.from( root.querySelectorAll( "*" ) ) ] ) {
    // 🔴 THE WHOLE CLASS LIST PER ELEMENT, NOT EACH TOKEN LOOSE IN A SET. An
    // error line is `debug-info error`; asking about `error` with no idea what
    // it sits beside invites an unrelated `.error` elsewhere to answer for it.
    const classes = Array.from( ( el as HTMLElement ).classList );
    if ( classes.length > 0 ) found.push( classes );
  }

  r.unmount();
  setDebugPanel( null );
  console.log   = realLog;
  console.error = realError;
  return found;
}

/** `"<classes> » .<token>"` for every token the sweep saw, deduplicated. */
function paneTokenClaims(): string[] {
  const out = new Set<string>();
  for ( const classes of paneClassSpecs() ) {
    for ( const token of classes ) out.add( `${ classes.join( " " ) } » .${ token }` );
  }
  return [ ...out ].sort();
}

const parseClaim = ( claim: string ): { classes: string[]; token: string } => {
  const [ lhs, rhs ] = claim.split( " » ." ) as [ string, string ];
  return { classes: lhs.split( " " ), token: rhs };
};

// --------------------------------------------------------------------------

test( "the sweeps reach real populations before anything is concluded from them", () => {
  // 🔴 POSITIVE CONTROLS FIRST. An empty sheet list or an unpainted pane makes
  // every check below pass over nothing, and an absence prints exactly like a
  // clean bill of health.
  const sheets = linkedSheets( MUX_HTML );
  const css    = linkedCss( MUX_HTML );
  const claims = paneTokenClaims();

  assert.ok( sheets.length >= 10, `the link sweep found only ${ sheets.length } stylesheets` );
  assert.ok( css.length > 10_000, `the concatenated CSS is only ${ css.length } bytes — a sheet failed to load` );
  assert.ok( selectors( css ).length > 500, `the selector parse found only ${ selectors( css ).length } selectors` );
  for ( const needed of [
    "debug-info » .debug-info",
    "debug-info info » .info",
    "debug-info error » .error",
    "debug-log-scrollable » .debug-log-scrollable",
  ] ) {
    assert.ok( claims.includes( needed ),
      `the sweep never produced \`${ needed }\` — a writer did not run, so that class is untested` );
  }
} );

test( "🔴 THE MATCHER IGNORES COMMENTS — the control its three sibling guards do not have", () => {
  // This is the defect named in the header, held as a runnable fact. The naive
  // matcher those files use answers TRUE for `.debug-info.error` today, purely
  // on the sentence in debug-panel.css saying the rule does not exist.
  const commentOnly = "/* .ghost-class is deliberately not defined */\n.real-class { color: red; }\n";
  assert.equal( hasRule( commentOnly, "ghost-class" ), false,
    "the matcher counts a class named in a COMMENT as styled — a prose mention would satisfy the sweep" );
  assert.equal( hasRule( commentOnly, "real-class" ), true,
    "positive control: the matcher cannot find a rule that IS there" );
  assert.equal( /\.ghost-class(?![\w-])/.test( commentOnly ), true,
    "the naive matcher no longer over-matches, so this file's extra work is no longer needed — " +
    "check whether the sibling guards were repaired and simplify here if so" );
} );

test( "🔴 THE SHEET CARRYING THIS PANE'S RULES IS LINKED BY THE PAGE", () => {
  assert.ok( linkedSheets( MUX_HTML ).includes( SHEET ),
    `multiplexer.html does not link ${ SHEET } — every rule in it is dead, the Debug panel renders ` +
    `unstyled, and no other test is red` );
} );

test( "🔴 EVERY CLASS COMBINATION THE PANE EMITS HAS A RULE IN A LINKED SHEET, except the declared one", () => {
  const css     = linkedCss( MUX_HTML );
  const missing = paneTokenClaims()
    .filter( ( claim ) => !UNSTYLED_BY_LEGACY.includes( claim ) )
    .filter( ( claim ) => {
      const { classes, token } = parseClaim( claim );
      return !styledOn( css, token, classes );
    } );

  assert.deepEqual( missing, [],
    `these classes are emitted by the Debug panel and styled by NO sheet the page links: ` +
    `${ missing.join( ", " ) }. Either add the rule to a LINKED sheet, or add a <link> line — ` +
    `a rule in an unlinked sheet renders a correct renderer as a broken pane while every test stays green` );
} );

test( "🔴 THE DECLARED EXCEPTION IS STILL EARNED — legacy has no rule for it either", () => {
  // The whole justification for shipping one unstyled compound is that legacy
  // ships it unstyled too. If that stops being true, the exception stops being
  // parity and starts being a gap, so the claim is CHECKED rather than asserted
  // once in a comment and left to rot.
  const legacyCss = linkedCss( LEGACY_HTML );
  assert.ok( legacyCss.length > 10_000, "positive control: legacy's own sheets loaded" );
  assert.ok( hasRule( legacyCss, "debug-info" ),
    "positive control: the matcher CAN find a rule in legacy's sheets" );

  for ( const claim of UNSTYLED_BY_LEGACY ) {
    const { classes, token } = parseClaim( claim );
    assert.equal( styledOn( legacyCss, token, classes ), false,
      `legacy now styles .${ token } on an element classed \`${ classes.join( " " ) }\`. The multiplexer ` +
      `should gain the rule too — port it into debug-panel.css and REMOVE "${ claim }" from ` +
      `UNSTYLED_BY_LEGACY. Do not widen the list.` );
  }
} );

test( "the sheet carries the rule families it was ported to carry", () => {
  // ⚠️ NOT A RESTATEMENT OF THE SWEEP. That asks "is every emitted class styled
  // somewhere", which one catch-all rule could satisfy. This asks whether THIS
  // sheet still holds the port.
  const sheet = stripComments(
    readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" ) );
  for ( const selector of [ ".debug-panel-body", ".debug-info", ".debug-log-scrollable" ] ) {
    assert.ok( sheet.includes( selector ), `debug-panel.css lost its rule for ${ selector }` );
  }
  for ( const banned of [ ".debug-info.info", ".debug-info.error" ] ) {
    assert.equal( sheet.includes( banned ), false,
      `debug-panel.css gained a \`${ banned }\` rule — both type tokens are declared exceptions, ` +
      `because legacy styles neither. If legacy gained the rule too, shrink UNSTYLED_BY_LEGACY; if ` +
      `not, this is a divergence from the lead. A \`.debug-info.info\` rule has already been written ` +
      `here once and had to be removed: it overrode .debug-info's colour.` );
  }
  assert.equal( ( sheet.match( /\.debug-info(?![\w-])/g ) ?? [] ).length, 1,
    "debug-panel.css names .debug-info more than once — legacy declares it exactly once " +
    "(notifications.css:352) and a second rule is where a colour override creeps back in" );
} );

test( "the ported values match legacy's own, not merely some value", () => {
  // A copied rule that drifted is indistinguishable from a correct one by
  // selector name alone. These four are what make the panel a 300px monospace
  // box rather than a page-long one — notifications.css:352 and :359.
  const sheet = stripComments(
    readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" ) );
  const legacy = stripComments(
    readFileSync( join( STATIC, "css/notifications.css" ), "utf8" ) );

  for ( const decl of [ "max-height", "overflow-y", "font-family", "font-size" ] ) {
    const mine   = /(\.debug-log-scrollable\s*\{[^}]*\})/.exec( sheet )![ 1 ]!;
    const theirs = /(\.debug-log-scrollable\s*\{[^}]*\})/.exec( legacy )![ 1 ]!;
    const valueOf = ( block: string ) =>
      new RegExp( `${ decl }\\s*:\\s*([^;]+);` ).exec( block )?.[ 1 ]?.trim();
    assert.ok( valueOf( theirs ) !== undefined, `positive control: legacy declares ${ decl }` );
    assert.equal( valueOf( mine ), valueOf( theirs ),
      `.debug-log-scrollable's ${ decl } drifted from legacy's` );
  }
} );

// ==========================================================================
// 🔴 THE GREY, PINNED. Mr. Radio 🦉's ask, 2026-09-23, after María 🌸 caught
// `.debug-info.info { color: inherit }` BY READING — every test in this file
// passed over it, because they ask whether a class HAS a rule and it had one.
//
// So this is the missing question: not "is it styled" but "styled to WHAT".
// Legacy declares `.debug-info { color: #6c757d }` once (notifications.css:352)
// and nothing else that can reach one of these lines, so all three kinds render
// in that grey. The sheets are loaded into the document and the winning
// declaration is read back off a really-mounted panel.
//
// ⚠️ WHAT THIS MEASURES, EXACTLY: happy-dom's `getComputedStyle` applies the
// cascade — a later, more specific rule does override — but it returns the
// DECLARED value and does not resolve `inherit` to a colour. So the claim here
// is "the declaration that wins for this element is #6c757d", which is the
// claim that was false, and NOT "the pixel is grey in a browser". The
// discriminator is exercised rather than assumed: the last test plants the
// removed rule and watches the value change.
// ==========================================================================

const GREY = "#6c757d";

/** Load every linked mux sheet into the document, and return the undo. */
function installSheets(): () => void {
  const added: HTMLElement[] = [];
  for ( const href of linkedSheets( MUX_HTML ) ) {
    if ( !href.startsWith( "/static/" ) ) continue;
    let text: string;
    try {
      text = readFileSync( join( STATIC, href.slice( "/static/".length ) ), "utf8" );
    } catch {
      continue;
    }
    const el = document.createElement( "style" );
    el.textContent = text;
    document.head.appendChild( el );
    added.push( el );
  }
  return () => added.forEach( ( el ) => el.remove() );
}

/** Mount a real panel INTO THE DOCUMENT, drive the writers, return the undo. */
function mountAttached(): { root: HTMLElement; undo: () => void } {
  const realLog   = console.log;
  const realError = console.error;
  console.log   = () => {};
  console.error = () => {};

  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const r = createDebugPanelRenderer( {} );
  r.mount( root );
  log( "an info line" );
  error( "an error line" );

  console.log   = realLog;
  console.error = realError;
  return { root, undo : () => { r.unmount(); setDebugPanel( null ); root.remove(); } };
}

const colourOf = ( root: HTMLElement, selector: string ): string =>
  getComputedStyle( root.querySelector<HTMLElement>( selector )! ).color;

test( "🔴 AN INFO LINE IS LEGACY'S GREY — the question no other test in this file asks", () => {
  const undoSheets = installSheets();
  const { root, undo } = mountAttached();
  try {
    // Positive control first: the sweep must have found a rule to apply at all,
    // or every assertion below is reading an unstyled element and agreeing with
    // itself about the default.
    assert.equal( colourOf( root, ".debug-info:not(.info):not(.error)" ), GREY,
      "positive control: the seeded line is not grey, so the sheets did not load into the document" );

    assert.equal( colourOf( root, ".debug-info.info" ), GREY,
      "an info line is no longer legacy's #6c757d. A `.debug-info.info` rule has been added back, " +
      "or something else now out-specifies `.debug-info`. Legacy declares that colour once " +
      "(notifications.css:352) and nothing overrides it there." );
    assert.equal( colourOf( root, ".debug-info.error" ), GREY,
      "an error line is no longer grey — that is G8, the declared exception: legacy defines no " +
      "`.debug-info.error` rule, so its error lines are the same grey as everything else" );
  } finally {
    undo();
    undoSheets();
  }
} );

test( "🔴 AND THE INSTRUMENT CAN SEE THE REGRESSION — the removed rule, planted", () => {
  // Without this arm, the test above is three assertions that could all be
  // reading a value nothing could ever have changed. This plants the exact rule
  // that was removed and watches the winning declaration move.
  const undoSheets = installSheets();
  const { root, undo } = mountAttached();
  const planted = document.createElement( "style" );
  planted.textContent = ".debug-info.info { color: inherit; }";
  document.head.appendChild( planted );
  try {
    assert.notEqual( colourOf( root, ".debug-info.info" ), GREY,
      "planting `.debug-info.info { color: inherit }` did NOT change the winning declaration — " +
      "the instrument cannot see the regression it was written for, so the test above proves nothing" );
    assert.equal( colourOf( root, ".debug-info.error" ), GREY,
      "the planted rule reached the ERROR line too — the arm is not isolating what it claims to" );
  } finally {
    planted.remove();
    undo();
    undoSheets();
  }
} );
