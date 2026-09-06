// Row 87812328 — the guard for IMPLEMENTED-BUT-NOT-INSTALLED.
//
// 🔴 A COMPONENT CAN BE COMPLETE, CORRECT, FULLY COVERED AND ENTIRELY ABSENT
// FROM THE RUNNING PAGE, and every test that builds the component itself stays
// green. The holding area and the epic board each sat at 100% coverage for an
// hour while no page carried a mount id and boot.ts wired neither — the suites
// were reporting on two components, and said nothing about the product.
//
// ⇒ So this file asks a different question from every other test on this
// surface: not "does the renderer work" but "does the APP reach it". Its two
// halves are deliberately different in kind:
//
//   1. A SOURCE-LEVEL sweep with the denominator the right way round — every
//      id boot.ts looks up must EXIST in the page. That catches any pane whose
//      id drifts, not only the two added today, and it fails on a mount that is
//      deleted as loudly as on one that is misspelled.
//   2. A BEHAVIOURAL check — the real renderers mounted into the REAL section
//      elements parsed out of multiplexer.html. A renderer that mounts fine
//      into a hand-built <div> and not into the page's own markup would pass
//      every other test in the tier.
//
// ⚠️ THE TWO SIDES COME FROM DIFFERENT FILES ON PURPOSE. Asserting boot.ts's
// ids against a list retyped here would share a provenance with nothing and
// prove only that I can copy. boot.ts is the actual consumer; the HTML is the
// actual supplier; the comparison can fail.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createHoldingAreaRenderer } from "../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { createEpicBoardRenderer } from "../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import type { TaskListComposite } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const HERE = dirname( fileURLToPath( import.meta.url ) );
const BOOT_PATH = resolve( HERE, "../../../lupin_app/static/js/multiplexer/boot.ts" );
const HTML_PATH = resolve( HERE, "../../../lupin_app/static/html/multiplexer.html" );

const bootSource = (): string => readFileSync( BOOT_PATH, "utf8" );
const htmlSource = (): string => readFileSync( HTML_PATH, "utf8" );

/**
 * Every id boot.ts resolves with getElementById, in source order.
 *
 * 🔴 COMMENT LINES ARE DROPPED, AND THAT IS NOT TIDYING. boot.ts carries an
 * 8-line copy-verbatim handshake in a comment block whose placeholder reads
 * `getElementById("<#mount-id>")`. The first cut of this sweep matched it and
 * reported a mount the page does not declare — a real-looking finding about a
 * line that never executes. § A HIT IS NOT A USE: the grep found the NAME, and
 * the question was about the USE.
 *
 * ⚠️ Line-level, not block-level: `/* … *\/` comments would slip past this. It
 * is enough for boot.ts, which uses `//` throughout, and the placeholder test
 * below is what would catch it if that ever stops being true.
 */
function bootMountIds(): string[] {
  return bootSource()
    .split( "\n" )
    .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
    .flatMap( ( line ) => ( line.match( /getElementById\(\s*"([^"]+)"\s*\)/g ) ?? [] ) )
    .map( ( m ) => /"([^"]+)"/.exec( m )![ 1 ] );
}

/** Every id the page declares. */
function pageIds(): Set<string> {
  return new Set( ( htmlSource().match( /\bid="([^"]+)"/g ) ?? [] )
    .map( ( m ) => /"([^"]+)"/.exec( m )![ 1 ] ) );
}

test( "the two sweeps reach real populations before anything is concluded from them", () => {
  // 🔴 POSITIVE CONTROLS FIRST. An extraction that matched nothing would make
  // the sweep below pass over an empty set — a loop over nothing is green, and
  // that is how an absence and a clean bill of health print the same page.
  const ids   = bootMountIds();
  const page  = pageIds();

  assert.ok( ids.length >= 8, `boot.ts sweep found only ${ ids.length } getElementById calls — the regex is not reaching the mounts` );
  assert.ok( page.size >= 8,  `the page sweep found only ${ page.size } ids — the regex is not reaching the markup` );

  // And a known member of each, so a sweep that returns the wrong KIND of thing
  // in the right QUANTITY cannot pass either.
  assert.ok( ids.includes( "task-list-pane" ), "boot.ts no longer mounts the task list — or the sweep is reading the wrong file" );
  assert.ok( page.has( "task-list-pane" ),     "the page no longer declares the task-list pane" );

  // 🔴 AND THE FILTER IS PROVEN, not assumed: boot.ts's copy-verbatim comment
  // block contains a literal `getElementById("<#mount-id>")` placeholder. It
  // must be IN the file (or this control is vacuous) and OUT of the sweep.
  assert.ok( bootSource().includes( 'getElementById("<#mount-id>")' ),
    "the placeholder is gone from boot.ts — this control no longer proves the comment filter does anything" );
  assert.ok( !ids.includes( "<#mount-id>" ),
    "the sweep is reading commented-out code as a live mount" );
} );

test( "EVERY id boot.ts mounts into is declared by the page", () => {
  // ⚠️ THE DENOMINATOR RUNS THE RIGHT WAY ROUND. This asks whether anything
  // boot REACHES FOR is missing, rather than whether a list I wrote is present
  // — a list satisfies itself by being short, and would not have caught a pane
  // I forgot to add.
  const page    = pageIds();
  const missing = bootMountIds().filter( ( id ) => !page.has( id ) );

  assert.deepEqual( missing, [],
    `boot.ts mounts into ids the page does not declare: ${ JSON.stringify( missing ) } — each of these throws at boot` );
} );

test( "the page declares the holding-area and epic-board panes, and boot mounts BOTH", () => {
  // 🔴 THE MUTATION THIS FILE EXISTS FOR. Delete either mount block from
  // boot.ts and the renderer's own 17 or 32 tests stay green, its coverage
  // stays at 100%, and the pane is simply gone from the product.
  const ids  = bootMountIds();
  const page = pageIds();

  for ( const id of [ "holding-area-pane", "epic-board-pane" ] ) {
    assert.ok( page.has( id ), `the page does not declare #${ id }` );
    assert.ok( ids.includes( id ), `boot.ts never mounts #${ id } — the pane is implemented and not installed` );
  }
} );

test( "the epic board takes NO poll of its own, and the holding area DOES", () => {
  // ⚠️ NOT STYLE. The epic board reads the task list's composite so the two
  // panes cannot show different clocks; a startPolling() on it would reintroduce
  // exactly the drift the shared composite prevents. The holding area's query
  // is a SECOND one — not_approved rows are invisible to the task list's — so
  // it must have its own.
  const src = bootSource();
  assert.ok( src.includes( "stores.holdingArea.startPolling()" ),
    "the holding area does not poll — its pane would never populate" );
  assert.ok( !/stores\.epicBoard/.test( src ),
    "the epic board grew a store of its own — it must read the task list's composite" );
  assert.ok( !/epicBoardRenderer[\s\S]{0,400}?startPolling/.test( src ),
    "the epic board grew a timer of its own — two clocks read as a bug the first time they disagree" );
} );

// ---------------------------------------------------------------------------
// The behavioural half — the real renderers into the REAL page markup
// ---------------------------------------------------------------------------

function sectionFromPage( id: string ): HTMLElement {
  const host = document.createElement( "div" );
  host.innerHTML = htmlSource();
  const el = host.querySelector( `#${ id }` );
  assert.ok( el, `#${ id } is not in multiplexer.html` );
  return el as HTMLElement;
}

function stubStore( composite: TaskListComposite | null ) {
  return { composite: () => composite, async refresh() { /* no-op */ } };
}

test( "the holding-area renderer mounts into the PAGE'S OWN section element", () => {
  const section = sectionFromPage( "holding-area-pane" );
  assert.equal( section.childNodes.length, 0, "the page's section is not empty — this test would not prove the mount filled it" );

  createHoldingAreaRenderer( {
    eventBus  : createEventBusForTesting(),
    store     : stubStore( { tasks: [] } ),
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } ).mount( section );

  assert.ok( section.querySelector( ".holding-area-container" ), "the pane painted no container into the page's section" );
} );

test( "the epic-board renderer mounts into the PAGE'S OWN section element", () => {
  const section = sectionFromPage( "epic-board-pane" );
  assert.equal( section.childNodes.length, 0 );

  createEpicBoardRenderer( {
    eventBus  : createEventBusForTesting(),
    store     : stubStore( { tasks: [] } ),
    storiesFn : () => ( {} ),
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } ).mount( section );

  assert.ok( section.querySelector( ".epic-board-container" ), "the pane painted no container into the page's section" );
} );

test( "the page keeps the legacy pane ORDER — task list, then holding area, then epic board", () => {
  // Carbon copy of notifications.html, where the three sit in that order. A
  // reader moving between the two clients should not have to re-find them.
  const html = htmlSource();
  const at = ( id: string ): number => {
    const i = html.indexOf( `id="${ id }"` );
    assert.ok( i !== -1, `#${ id } is not in the page` );
    return i;
  };
  assert.ok( at( "task-list-pane" ) < at( "holding-area-pane" ), "the holding area sits above the task list" );
  assert.ok( at( "holding-area-pane" ) < at( "epic-board-pane" ), "the epic board sits above the holding area" );
} );
