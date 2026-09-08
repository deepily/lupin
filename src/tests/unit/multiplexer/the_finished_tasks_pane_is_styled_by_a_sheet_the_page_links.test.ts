// 🔴 A CORRECT RENDERER WHOSE STYLESHEET NOTHING LOADS IS A BROKEN PAGE, AND
// EVERY TEST STAYS GREEN — gap G2 of the accordion build spec.
//
// The precedent is on this branch: epic-board.css held a correct collapse rule
// that no page linked, so a correct renderer produced a broken pane for a day
// and the suite never noticed. The legacy Finished Tasks pane (ba4bb92c) shipped
// with a guard asserting BOTH halves — the sheet is linked AND the pane's rules
// are in that sheet. This is the multiplexer's own.
//
// 🔨 CLASS NAMES ARE SHARED WITH THE LEGACY PANE AND THAT IS RULED, NOT
// OVERSIGHT. Rick, 2026-09-06, scopes CSS OUT of the no-code-reuse rule
// (87812328) — the ruling is quoted in the sheet itself at task-list.css:1375:
// "Rick's 2026-09-06 ruling scopes CSS OUT of the no-reuse rule — a new sheet
// would need a new <link> line, which is the exact gap (G2) that left the
// accordion work invisible in a browser for a day." Both clients already link
// this sheet, and matching class names are how the Layout-Parity Oracle
// measures ONE shape across the two.
//
// ⚠️ THE CLASS LIST IS TAKEN FROM THE RENDERED DOM, NOT HAND-WRITTEN. A
// hand-list would be a fourth hand-maintained population of the same kind this
// branch keeps finding drifted; taking it from the actual output means a class
// added to the template is covered on the day it lands.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_finished_tasks_pane_is_styled_by_a_sheet_the_page_links.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createFinishedTasksRenderer } from "../../../lupin_app/static/js/multiplexer/render/FinishedTasksRenderer";
import type { FinishedTaskEvent } from "../../../lupin_app/static/js/multiplexer/render/finishedTasksModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const STATIC    = resolve( HERE, "../../../lupin_app/static" );
const HTML_PATH = join( STATIC, "html/multiplexer.html" );

/** Every stylesheet href multiplexer.html actually links. */
function linkedSheets(): string[] {
  const html = readFileSync( HTML_PATH, "utf8" );
  return ( html.match( /<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g ) ?? [] )
    .map( ( m ) => /href="([^"]+)"/.exec( m )![ 1 ]! )
    .map( ( href ) => href.split( "?" )[ 0 ]! );
}

/** The concatenated text of every linked sheet — what a browser would have. */
function linkedCss(): string {
  let all = "";
  for ( const href of linkedSheets() ) {
    if ( !href.startsWith( "/static/" ) ) continue;
    try {
      all += readFileSync( join( STATIC, href.slice( "/static/".length ) ), "utf8" ) + "\n";
    } catch {
      // A linked sheet that does not exist is its own finding, asserted below.
    }
  }
  return all;
}

/** Mount the pane with rows, so every state's classes are actually emitted. */
function paneClasses(): Set<string> {
  const events: Record<string, ReadonlyArray<FinishedTaskEvent>> = {
    done     : [ { id: 1, item_id: "i", ts: "2026-09-07T19:00:00Z", actor: "rio c1",
                   transition: "in_progress->done", reason: "r", title: "t" } ],
    dropped  : [],
    wont_fix : [],
  };
  const root = document.createElement( "div" );
  const r = createFinishedTasksRenderer( {
    eventBus  : createEventBusForTesting(),
    store     : {
      eventsByStatus   : () => events,
      measuredStatuses : () => [ "done", "dropped", "wont_fix" ],
      error            : () => null,
      windowDays       : () => 1,
      setWindowDays    : () => {},
      refresh          : async () => {},
    },
    nowDateFn : () => new Date( "2026-09-07T20:00:00Z" ),
    storage   : { getItem: () => null, setItem: () => {} },
  } );
  r.mount( root );
  r.forceRenderForTesting();

  const found = new Set<string>();
  for ( const el of [ root, ...Array.from( root.querySelectorAll( "*" ) ) ] ) {
    for ( const cls of Array.from( ( el as HTMLElement ).classList ) ) found.add( cls );
  }
  r.unmount();
  return found;
}

test( "the sweeps reach real populations before anything is concluded from them", () => {
  // 🔴 POSITIVE CONTROLS FIRST. A sheet list that matched nothing, or a class
  // sweep over an unmounted pane, would make every check below pass over an
  // empty set — and an absence prints exactly like a clean bill of health.
  const sheets = linkedSheets();
  const css    = linkedCss();
  const cls    = paneClasses();

  assert.ok( sheets.length >= 10, `the link sweep found only ${ sheets.length } stylesheets` );
  assert.ok( css.length > 10_000, `the concatenated CSS is only ${ css.length } bytes — a sheet failed to load` );
  assert.ok( cls.size >= 8, `the pane emitted only ${ cls.size } classes — it did not render` );
  assert.ok( cls.has( "finished-tasks-table" ),
    "the class sweep found no table — the fixture rendered a sentinel, so the row classes are untested" );
} );

test( "🔴 THE SHEET CARRYING THIS PANE'S RULES IS LINKED BY THE PAGE", () => {
  // Half one of G2. The sheet existing is not the same as the page loading it.
  assert.ok( linkedSheets().includes( "/static/css/task-list.css" ),
    "multiplexer.html no longer links task-list.css — every finished-* rule is now dead, " +
    "and so is every task-status-* tint the rows carry" );
} );

test( "🔴 EVERY CLASS THE PANE EMITS HAS A RULE IN A SHEET THE PAGE LINKS", () => {
  // Half two. This is the direction that fires when somebody adds a class to
  // the template and puts its rule in a sheet only the legacy page loads.
  const css     = linkedCss();
  const missing = [ ...paneClasses() ]
    .filter( ( cls ) => !new RegExp( `\\.${ cls.replace( /[-]/g, "\\-" ) }(?![\\w-])` ).test( css ) )
    .sort();

  assert.deepEqual( missing, [],
    `these classes are emitted by the finished-tasks pane and styled by NO sheet the page links: ` +
    `${ missing.join( ", " ) }. Either add the rule to a LINKED sheet, or add a <link> line — ` +
    `a rule in an unlinked sheet is gap G2, and it renders a correct renderer as a broken pane ` +
    `while every test stays green` );
} );

test( "the row TINTS resolve too — they come from the task list's taxonomy, not this pane's", () => {
  // Named separately because they are the one family this pane borrows from
  // another feature: a `task-status-*` class that lost its rule would leave
  // terminal rows untinted, and the class-sweep above would not say WHY.
  const css = linkedCss();
  for ( const cls of [ "task-status-done", "task-status-dropped", "task-status-wont-fix" ] ) {
    assert.match( css, new RegExp( `\\.${ cls.replace( /[-]/g, "\\-" ) }(?![\\w-])` ),
      `${ cls } has no rule in any linked sheet` );
  }
} );
