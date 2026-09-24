// 🔴 A CORRECT RENDERER WHOSE STYLESHEET NOTHING LOADS IS A BROKEN PAGE, AND
// EVERY TEST STAYS GREEN — gap G2. B-7 adds a new sheet
// (css/multiplexer/direct-tts.css) and therefore a new <link> line, which is
// exactly the shape that failed before. Both halves are held here.
//
// 🔴 THIS FILE'S MATCHER STRIPS COMMENTS AND PARSES SELECTORS, WHICH THREE OF
// ITS SIBLINGS DO NOT. `the_finished_tasks_pane_…`, `the_time_saved_pane_…` and
// `the_system_status_pane_…` test `/\.<class>(?![\w-])/` against the
// CONCATENATED sheet text, so a class named in a CSS COMMENT reads as STYLED —
// measured 2026-09-23 on the B-6 branch, where `.error` came back styled across
// all 27 linked sheets on the strength of a sentence saying no such rule exists.
// Filed twice: Mr. Radio 🦉's row 1ce4bf57 and María 🌸's row 998ad3b0, whose
// shape is to extract ONE shared helper and switch all of these onto it. Until
// that lands this file carries its own copy rather than inherit the defect.
//
// ⚠️ AND A COLOUR TEST IS NOT OWED HERE, WHICH IS WORTH SAYING BECAUSE B-6 GAINED
// ONE. B-6's pane had a rule that was PRESENT AND WRONG (`.debug-info.info`
// overrode legacy's grey), which a has-a-rule sweep cannot see. This pane's
// rules are geometry — flex, gap, padding, border — and the one deliberate
// difference from legacy is named in the sheet's own header rather than hidden:
// legacy carries the flex trio INLINE, this carries it in a rule. If this pane
// ever gains a colour that legacy sets differently, it needs B-6's treatment.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_direct_tts_pane_is_styled_by_a_sheet_the_page_links.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createDirectTtsRenderer } from "../../../lupin_app/static/js/multiplexer/render/DirectTtsRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const HERE        = dirname( fileURLToPath( import.meta.url ) );
const STATIC      = resolve( HERE, "../../../lupin_app/static" );
const MUX_HTML    = join( STATIC, "html/multiplexer.html" );
const LEGACY_CSS  = join( STATIC, "css/notifications.css" );
const SHEET       = "/static/css/multiplexer/direct-tts.css";

/** `"<classes> » .<token>"` emitted on purpose with no rule. Empty is the goal. */
const UNSTYLED_BY_LEGACY: string[] = [];

const stripComments = ( css: string ): string => css.replace( /\/\*[\s\S]*?\*\//g, " " );

function linkedSheets( htmlPath: string ): string[] {
  const html = readFileSync( htmlPath, "utf8" );
  return ( html.match( /<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g ) ?? [] )
    .map( ( m ) => /href="([^"]+)"/.exec( m )![ 1 ]! )
    .map( ( href ) => href.split( "?" )[ 0 ]! );
}

function linkedCss( htmlPath: string ): string {
  let all = "";
  for ( const href of linkedSheets( htmlPath ) ) {
    if ( !href.startsWith( "/static/" ) ) continue;
    try {
      all += readFileSync( join( STATIC, href.slice( "/static/".length ) ), "utf8" ) + "\n";
    } catch {
      // A linked sheet that does not exist is its own finding, asserted below.
    }
  }
  return stripComments( all );
}

/** Every selector in a sheet — the text before each `{`, split on commas. */
function selectors( css: string ): string[] {
  const out: string[] = [];
  for ( const block of stripComments( css ).split( "{" ) ) {
    const tail = block.slice( block.lastIndexOf( "}" ) + 1 );
    for ( const sel of tail.split( "," ) ) {
      const s = sel.trim().replace( /\s+/g, " " );
      if ( s !== "" && !s.startsWith( "@" ) ) out.push( s );
    }
  }
  return out;
}

const tokensOf = ( segment: string ): string[] =>
  ( segment.match( /\.[A-Za-z_][\w-]*/g ) ?? [] ).map( ( t ) => t.slice( 1 ) );

/**
 * Is `token` styled on an element carrying exactly `classes`? See B-6's copy for
 * the full argument: the loose question lets an unrelated rule answer for this
 * pane, and the strict one calls two ordinary rules from two sheets "unstyled".
 */
function styledOn( css: string, token: string, classes: readonly string[] ): boolean {
  const present = new Set( classes );
  const re      = new RegExp( `\\.${ token.replace( /-/g, "\\-" ) }(?![\\w-])` );
  return selectors( css ).some( ( sel ) =>
    sel.split( /[\s>+~]+/ ).some( ( seg ) =>
      re.test( seg ) && tokensOf( seg ).every( ( t ) => present.has( t ) ) ) );
}

/**
 * Mount the pane and collect every element's class list.
 *
 * ⚠️ ONE MOUNT IS ENOUGH HERE, unlike System Status or the Debug panel. This
 * pane paints no state-dependent classes — the five controls and their two
 * wrappers are all there is, from the first paint and forever (B10). Said
 * explicitly, because "one mount is enough" is the assumption that made the
 * other sweeps report clean bills over classes they never saw.
 */
function paneClassLists(): string[][] {
  const root = document.createElement( "div" );
  const r    = createDirectTtsRenderer( {
    audio    : { ttsMode: () => "instant", stop: () => {} },
    cache    : { checkCache: async () => null },
    playBlob : async () => {},
    speak    : async () => {},
    haltAll  : () => {},
    logFn    : () => {},
    errorFn  : () => {},
  } );
  r.mount( root );

  const found: string[][] = [];
  for ( const el of [ root, ...Array.from( root.querySelectorAll( "*" ) ) ] ) {
    const classes = Array.from( ( el as HTMLElement ).classList );
    if ( classes.length > 0 ) found.push( classes );
  }
  r.unmount();
  return found;
}

function paneTokenClaims(): string[] {
  const out = new Set<string>();
  for ( const classes of paneClassLists() ) {
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
  const sheets = linkedSheets( MUX_HTML );
  const css    = linkedCss( MUX_HTML );
  const claims = paneTokenClaims();

  assert.ok( sheets.length >= 10, `the link sweep found only ${ sheets.length } stylesheets` );
  assert.ok( css.length > 10_000, `the concatenated CSS is only ${ css.length } bytes — a sheet failed to load` );
  assert.ok( selectors( css ).length > 500, `the selector parse found only ${ selectors( css ).length } selectors` );
  for ( const needed of [
    "audio-controls » .audio-controls",
    "section-content direct-tts-body » .direct-tts-body",
  ] ) {
    assert.ok( claims.includes( needed ), `the sweep never produced \`${ needed }\` — the pane did not render` );
  }
} );

test( "🔴 THE MATCHER IGNORES COMMENTS — the control its three sibling guards do not have", () => {
  const commentOnly = "/* .ghost-class is deliberately not defined */\n.real-class { color: red; }\n";
  assert.equal( styledOn( commentOnly, "ghost-class", [ "ghost-class" ] ), false,
    "the matcher counts a class named in a COMMENT as styled — a prose mention satisfies the sweep" );
  assert.equal( styledOn( commentOnly, "real-class", [ "real-class" ] ), true,
    "positive control: the matcher cannot find a rule that IS there" );
} );

test( "🔴 THE SHEET CARRYING THIS PANE'S RULES IS LINKED BY THE PAGE", () => {
  assert.ok( linkedSheets( MUX_HTML ).includes( SHEET ),
    `multiplexer.html does not link ${ SHEET } — every rule in it is dead, Direct TTS renders ` +
    `unstyled, and no other test is red` );
} );

test( "🔴 EVERY CLASS THE PANE EMITS HAS A RULE IN A LINKED SHEET", () => {
  const css     = linkedCss( MUX_HTML );
  const missing = paneTokenClaims()
    .filter( ( claim ) => !UNSTYLED_BY_LEGACY.includes( claim ) )
    .filter( ( claim ) => {
      const { classes, token } = parseClaim( claim );
      return !styledOn( css, token, classes );
    } );

  assert.deepEqual( missing, [],
    `these classes are emitted by the Direct TTS pane and styled by NO sheet the page links: ` +
    `${ missing.join( ", " ) }. Either add the rule to a LINKED sheet, or add a <link> line — ` +
    `a rule in an unlinked sheet renders a correct renderer as a broken pane while every test stays green` );
} );

test( "the sheet carries the rule families it was ported to carry", () => {
  const sheet = stripComments( readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" ) );
  for ( const selector of [
    ".direct-tts-body", ".audio-controls",
    ".audio-controls button", ".audio-controls button:hover",
  ] ) {
    assert.ok( sheet.includes( selector ), `direct-tts.css lost its rule for ${ selector }` );
  }
} );

test( "the ported button values match legacy's own, not merely some value", () => {
  // A copied rule that drifted is indistinguishable from a correct one by
  // selector name alone. These are legacy's `.audio-controls button`
  // (notifications.css:374) — the declarations that make the four buttons read
  // as one control strip rather than as browser defaults.
  const mine   = stripComments( readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" ) );
  const legacy = stripComments( readFileSync( LEGACY_CSS, "utf8" ) );

  const blockOf = ( css: string, sel: string ): string => {
    const m = new RegExp( `${ sel.replace( /[.\s]/g, ( c ) => ( c === "." ? "\\." : "\\s+" ) ) }\\s*\\{([^}]*)\\}` ).exec( css );
    assert.notEqual( m, null, `positive control: no block found for ${ sel }` );
    return m![ 1 ]!;
  };
  const valueOf = ( block: string, decl: string ): string | undefined =>
    new RegExp( `${ decl }\\s*:\\s*([^;]+);` ).exec( block )?.[ 1 ]?.trim();

  const mineBlock   = blockOf( mine,   ".audio-controls button" );
  const legacyBlock = blockOf( legacy, ".audio-controls button" );

  for ( const decl of [ "padding", "border", "border-radius", "background-color", "cursor", "font-size" ] ) {
    assert.ok( valueOf( legacyBlock, decl ) !== undefined, `positive control: legacy declares ${ decl }` );
    assert.equal( valueOf( mineBlock, decl ), valueOf( legacyBlock, decl ),
      `.audio-controls button's ${ decl } drifted from legacy's own .audio-controls button` );
  }

  // 🔴 ONE DECLARATION IS DELIBERATELY NOT PORTED, and it is asserted ABSENT so
  // a later "completeness" pass cannot add it back silently. Legacy spaces its
  // buttons with BOTH a right margin and a 12px gap, so its last button carries
  // a trailing margin against nothing. The gap expresses it once.
  assert.equal( valueOf( legacyBlock, "margin-right" ), "10px",
    "positive control: legacy no longer sets margin-right, so the omission below means nothing" );
  assert.equal( valueOf( mineBlock, "margin-right" ), undefined,
    "margin-right was ported in — the gap already spaces these buttons, and legacy's copy leaves " +
    "a trailing margin on the last one" );
} );

test( "the flex trio legacy writes INLINE is present here as a rule — the one named difference", () => {
  // notifications.html:1383 carries display:flex, align-items:center, gap:12px
  // on the element. This client builds its own subtree and has no markup to
  // carry them, so they live in the sheet. The computed result is identical; the
  // specificity is not, and the sheet's header says so.
  const sheet = stripComments( readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" ) );
  const block = /\.audio-controls\s*\{([^}]*)\}/.exec( sheet )![ 1 ]!;
  for ( const [ decl, value ] of [ [ "display", "flex" ], [ "align-items", "center" ], [ "gap", "12px" ] ] ) {
    assert.ok( new RegExp( `${ decl }\\s*:\\s*${ value }\\s*;` ).test( block ),
      `.audio-controls lost ${ decl }: ${ value } — legacy sets it inline and this is its only home here` );
  }
  const legacyHtml = readFileSync( join( STATIC, "html/notifications.html" ), "utf8" );
  assert.ok( /id="direct-tts-input"/.test( legacyHtml ),
    "positive control: legacy's Direct TTS markup moved, so the claim above is about nothing" );
} );
