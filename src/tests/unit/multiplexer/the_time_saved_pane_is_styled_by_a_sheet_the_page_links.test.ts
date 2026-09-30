// 🔴 A CORRECT RENDERER WHOSE STYLESHEET NOTHING LOADS IS A BROKEN PAGE, AND
// EVERY TEST STAYS GREEN — gap G2.
//
// The precedent is on this branch: epic-board.css held a correct collapse rule
// that no page linked, so a correct renderer produced a broken pane for a day
// and the suite never noticed. B-4 adds a NEW sheet
// (css/multiplexer/time-saved.css) and therefore a new <link> line, which is
// exactly the shape that failed before. This guard holds both halves — the page
// links the sheet, AND every class the pane emits has a rule in a LINKED sheet.
//
// 🔨 CLASS NAMES ARE SHARED WITH THE LEGACY PANE AND THAT IS RULED, NOT
// OVERSIGHT. Rick, 2026-09-06, scopes CSS OUT of the no-code-reuse rule
// (87812328); matching class names are how the Layout-Parity Oracle measures ONE
// shape across the two clients. The rules themselves are copied rather than
// shared because the multiplexer does not link notifications.css at all.
//
// ⚠️ THE CLASS LIST IS TAKEN FROM THE RENDERED DOM, NOT HAND-WRITTEN. A hand
// list is a second population to keep in step, and it drifts silently; taking it
// from the real output means a class added to the renderer is covered the day it
// lands.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_time_saved_pane_is_styled_by_a_sheet_the_page_links.test.ts

// 🔴 THIS GUARD ONCE COUNTED A CLASS NAMED IN A CSS COMMENT AS STYLED, and it
// carried its own copy of the matcher that did it. Rows 1ce4bf57 (Mr. Radio 🦉)
// and 998ad3b0 (María 🌸) — the same job filed twice. The matcher now comes from
// `testkit/linkedSheets.ts`, which strips comments before matching and ignores
// the inside of attribute selectors, and whose own test file executes the OLD
// behaviour beside the new one so the fix is demonstrated rather than described.
//
// ⚠️ THE SWEEP BELOW STILL ASKS THE BARE-TOKEN QUESTION — "does any selector
// anywhere name this class" — rather than `styledOn`'s "could a selector naming
// this token match THIS element". The stricter question is available in the
// helper and is what the B-6 and B-7 guards use; adopting it here means
// reshaping `paneClasses()` to return per-element class LISTS, and it may
// surface real gaps, as it did on B-7. That is a separate change with its own
// findings, not a silent rider on a matcher swap.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createTimeSavedRenderer } from "../../../lupin_app/static/js/multiplexer/render/TimeSavedRenderer";

import {
  linkedSheets as sharedLinkedSheets,
  linkedCss    as sharedLinkedCss,
  hasRule,
} from "./testkit/linkedSheets";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const STATIC    = resolve( HERE, "../../../lupin_app/static" );
const HTML_PATH = join( STATIC, "html/multiplexer.html" );
const SHEET     = "/static/css/multiplexer/time-saved.css";




// --- the shared matcher (testkit/linkedSheets.ts) --------------------------
const linkedSheets = (): string[] => sharedLinkedSheets( HTML_PATH );
const linkedCss    = (): string   => sharedLinkedCss( HTML_PATH, STATIC );

/**
 * Mount the pane WITH DATA, so the row classes are actually emitted.
 *
 * 🔴 AN EMPTY LEADERBOARD WOULD NOT EMIT `.top-solution-item`, `.rank`,
 * `.question` OR `.stats`, and the sweep would then report a clean bill of
 * health over four classes it never saw. The fixture carries a solution for
 * exactly that reason, and the positive control below checks it worked.
 */
async function paneClasses(): Promise<Set<string>> {
  const api = {
    get: async <T>( path: string ): Promise<T> => (
      path.endsWith( "/global" )
        ? ( { top_solutions: [ { question: "q", replays: 3, time_saved_formatted: "5m" } ] } as unknown as T )
        : ( { total_time_saved_formatted: "1h", solutions_created: 2 } as unknown as T )
    ),
  };
  const root = document.createElement( "div" );
  const r = createTimeSavedRenderer( { api, logFn: () => {} } );
  r.mount( root );
  for ( let i = 0; i < 6; i++ ) await Promise.resolve();

  const found = new Set<string>();
  for ( const el of [ root, ...Array.from( root.querySelectorAll( "*" ) ) ] ) {
    for ( const cls of Array.from( ( el as HTMLElement ).classList ) ) found.add( cls );
  }
  r.unmount();
  return found;
}

test( "the sweeps reach real populations before anything is concluded from them", async () => {
  // 🔴 POSITIVE CONTROLS FIRST. A sheet list that matched nothing, or a class
  // sweep over a pane that never painted, would make every check below pass
  // over an empty set — and an absence prints exactly like a clean bill of health.
  const sheets = linkedSheets();
  const css    = linkedCss();
  const cls    = await paneClasses();

  assert.ok( sheets.length >= 10, `the link sweep found only ${ sheets.length } stylesheets` );
  assert.ok( css.length > 10_000, `the concatenated CSS is only ${ css.length } bytes — a sheet failed to load` );
  assert.ok( cls.size >= 8, `the pane emitted only ${ cls.size } classes — it did not render` );
  assert.ok( cls.has( "top-solution-item" ),
    "the class sweep found no leaderboard row — the fixture rendered the empty state, " +
    "so .rank/.question/.stats are untested and this guard is weaker than it looks" );
} );

test( "🔴 THE SHEET CARRYING THIS PANE'S RULES IS LINKED BY THE PAGE", () => {
  // Half one of G2. The sheet existing is not the same as the page loading it,
  // and nothing else in the suite can tell the difference.
  assert.ok( linkedSheets().includes( SHEET ),
    `multiplexer.html does not link ${ SHEET } — every rule in it is dead, the Time Saved pane ` +
    `renders unstyled, and no other test is red` );
} );

test( "🔴 EVERY CLASS THE PANE EMITS HAS A RULE IN A SHEET THE PAGE LINKS", async () => {
  // Half two. This is the direction that fires when somebody adds a class to the
  // renderer and puts its rule in a sheet only the legacy page loads.
  const css     = linkedCss();
  const missing = [ ...await paneClasses() ]
    .filter( ( cls ) => !hasRule( css, cls ) )
    .sort();

  assert.deepEqual( missing, [],
    `these classes are emitted by the Time Saved pane and styled by NO sheet the page links: ` +
    `${ missing.join( ", " ) }. Either add the rule to a LINKED sheet, or add a <link> line — ` +
    `a rule in an unlinked sheet renders a correct renderer as a broken pane while every test stays green` );
} );

test( "the sheet carries the nine rule families it was ported to carry", () => {
  // ⚠️ NOT A RESTATEMENT OF THE SWEEP ABOVE. That one asks "is every emitted
  // class styled somewhere", which a single catch-all rule could satisfy. This
  // asks whether THIS sheet still holds the port — a sheet emptied to one line
  // would pass the sweep on the legacy page's rules if one were ever linked.
  const sheet = readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" );
  for ( const selector of [
    ".stats-grid", ".stat-item", ".stat-value", ".stat-label",
    ".top-solutions h4", ".top-solution-item", ".top-solution-item .rank",
    ".top-solution-item .question", ".top-solution-item .stats", ".no-data",
  ] ) {
    assert.ok( sheet.includes( selector ), `time-saved.css lost its rule for ${ selector }` );
  }
} );
