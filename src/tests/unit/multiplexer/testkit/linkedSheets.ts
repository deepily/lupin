// The one matcher every pane's stylesheet-link guard uses.
//
// 🔴 WHY IT EXISTS: THE THREE ORIGINAL GUARDS COUNTED A CLASS NAMED IN A CSS
// COMMENT AS STYLED. `the_finished_tasks_pane_…`, `the_time_saved_pane_…` and
// `the_system_status_pane_…` each carried their own copy of
// `hasRule = ( css, cls ) => new RegExp( `\\.${cls}(?![\\w-])` ).test( css )`,
// tested against the CONCATENATED text of every linked sheet. Comments are text.
//
// Measured 2026-09-23 on the B-6 branch: `.error` came back STYLED across all 27
// linked sheets, and the only occurrence in any of them was the sentence in
// debug-panel.css explaining that no such rule exists. A prose mention of a
// class satisfied the check that the class HAS a rule — so the guard was
// strongest exactly where an author had stopped to document an absence.
//
// Rows 1ce4bf57 (Mr. Radio 🦉) and 998ad3b0 (María 🌸), which are the same job
// filed twice.
//
// 🔴 AND THE FIX IS NOT ONLY "STRIP COMMENTS". Stripping alone leaves the other
// half: a bare token asks whether ANY selector anywhere mentions the class,
// which lets an unrelated `.error` in one of 27 sheets answer for a debug
// panel's `debug-info error` line. `styledOn` asks the real question — could
// some selector that names this token match THIS element — and the two wrong
// simplifications are described on it.

import { readFileSync } from "node:fs";
import { join } from "node:path";

/** Remove `/* … *␟/` blocks. Idempotent, and safe to apply twice. */
export const stripCssComments = ( css: string ): string =>
  css.replace( /\/\*[\s\S]*?\*\//g, " " );

/** Every `<link rel="stylesheet">` href in an HTML file, query strings dropped. */
export function linkedSheets( htmlPath: string ): string[] {
  const html = readFileSync( htmlPath, "utf8" );
  return ( html.match( /<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g ) ?? [] )
    .map( ( m ) => /href="([^"]+)"/.exec( m )![ 1 ]! )
    .map( ( href ) => href.split( "?" )[ 0 ]! );
}

/**
 * The concatenated text of every LOCAL linked sheet, comments removed.
 *
 * A linked sheet that does not exist is skipped rather than thrown on: its
 * absence is a finding in its own right and each guard asserts a floor on the
 * total size, which is what catches a sheet that failed to load.
 */
export function linkedCss( htmlPath: string, staticRoot: string ): string {
  let all = "";
  for ( const href of linkedSheets( htmlPath ) ) {
    if ( !href.startsWith( "/static/" ) ) continue;
    try {
      all += readFileSync( join( staticRoot, href.slice( "/static/".length ) ), "utf8" ) + "\n";
    } catch {
      // Skipped deliberately — see the note above.
    }
  }
  return stripCssComments( all );
}

/** Every selector in a sheet — the text before each `{`, split on commas. */
export function selectors( css: string ): string[] {
  const out: string[] = [];
  for ( const block of stripCssComments( css ).split( "{" ) ) {
    const tail = block.slice( block.lastIndexOf( "}" ) + 1 );
    for ( const sel of tail.split( "," ) ) {
      const s = sel.trim().replace( /\s+/g, " " );
      if ( s !== "" && !s.startsWith( "@" ) ) out.push( s );
    }
  }
  return out;
}

/**
 * Attribute selectors removed: `a[data-x=".y"]` -> `a`.
 *
 * 🔴 AN ATTRIBUTE VALUE CAN CONTAIN A DOT, AND THE CLASS SCAN CANNOT TELL. Found
 * by this module's own test, 2026-09-23: `div[data-x='.y']` reported a class
 * token `y`. This tree is full of `[data-testid="…"]` selectors, so it is not a
 * hypothetical — a testid holding a dot would invent a class requirement that
 * no element could satisfy, and the segment would silently stop matching.
 */
const stripAttributeSelectors = ( segment: string ): string =>
  segment.replace( /\[[^\]]*\]/g, "" );

/**
 * Every class token named in one selector segment: `a.b:hover` -> [a, b].
 *
 * ⚠️ A `:not( .x )` NAMES `.x` AND REQUIRES ITS ABSENCE, and this reads it as a
 * requirement that `.x` be PRESENT. The effect is to make a `:not` selector
 * harder to match, so a class it guards can read as unstyled — a false ALARM,
 * not a false clean bill. Left rather than modelled: a wrong red gets
 * investigated, and no selector in this tree currently needs it.
 */
export const classTokensOf = ( segment: string ): string[] =>
  ( stripAttributeSelectors( segment ).match( /\.[A-Za-z_][\w-]*/g ) ?? [] )
    .map( ( t ) => t.slice( 1 ) );

/**
 * Is `token` styled on an element carrying exactly `classes`?
 *
 * 🔴 THE PREDICATE IS "SOME SELECTOR THAT NAMES THE TOKEN COULD MATCH THIS
 * ELEMENT" — not "some selector names the token", and not "some selector names
 * every one of this element's classes". Both simpler questions are wrong, and
 * each is wrong in a direction that has already cost something:
 *   - the LOOSE one lets an unrelated `.error` elsewhere in a 27-sheet page
 *     answer for a debug line's `debug-info error`, which is the whole G8 gap;
 *   - the STRICT one demands one rule naming every class on the element, so
 *     `.section-content` + `.debug-panel-body` — two ordinary rules from two
 *     sheets — read as unstyled.
 *
 * Non-class parts of a segment (tags, pseudos, attributes) are not modelled.
 * This sweeps for a MISSING rule, so treating a `:hover` variant as covering the
 * base class errs toward silence rather than toward a false alarm — stated
 * because it is a real limit, not an oversight.
 *
 * Comments are stripped here as well as in `linkedCss`: a matcher that is only
 * safe when its caller remembers to sanitise is the same shape as the defect it
 * exists to prevent.
 */
export function styledOn( css: string, token: string, classes: readonly string[] ): boolean {
  const present = new Set( classes );
  const re      = new RegExp( `\\.${ token.replace( /-/g, "\\-" ) }(?![\\w-])` );
  return selectors( stripCssComments( css ) ).some( ( sel ) =>
    sel.split( /[\s>+~]+/ ).some( ( seg ) => {
      // The attribute strip applies to the TOKEN TEST too, not only to the
      // token list: `[data-testid="x.error"]` would otherwise answer for a
      // `.error` class the selector never mentions.
      const bare = stripAttributeSelectors( seg );
      return re.test( bare ) && classTokensOf( bare ).every( ( t ) => present.has( t ) );
    } ) );
}

/** The standalone form, for a class that appears alone on its element. */
export const hasRule = ( css: string, token: string ): boolean =>
  styledOn( css, token, [ token ] );

/**
 * THE DEFECT, PRESERVED AND RUNNABLE. This is what the three guards did before
 * row 1ce4bf57 / 998ad3b0, kept so the fix can be demonstrated rather than
 * asserted — `naiveHasRule` and `styledOn` disagreeing on the same input is the
 * proof, and a description of a removed bug proves nothing.
 *
 * ⚠️ NEVER CALL THIS FROM A GUARD. Its only callers are the tests that show it
 * is wrong.
 */
export const naiveHasRule = ( css: string, token: string ): boolean =>
  new RegExp( `\\.${ token.replace( /-/g, "\\-" ) }(?![\\w-])` ).test( css );
