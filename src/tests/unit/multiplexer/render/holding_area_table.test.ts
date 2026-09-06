// Holding-area card — holdingAreaTable template unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE TOOLTIPS ARE COMPARED AGAINST notifications.js, NOT AGAINST A LITERAL
// TYPED HERE. María's condition, 2026-09-05: if a string must match something
// else exactly, assert BOTH sides in one test. A literal retyped in this file
// shares its provenance with the one in the template — the two would move
// together on any copy-paste error and the comparison could never fail, which
// is the tautology CLAUDE.md § A COMPARISON WHOSE TWO SIDES COME FROM ONE
// SOURCE forbids.
//
// ⚠️ AND THE EXTRACTION CARRIES THREE CONTROLS, BECAUSE ONE IS NOT ENOUGH.
// A regex slice that matches nothing yields "", and two empty strings compare
// equal — § AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE. So
// before any comparison: each slice is non-empty, each still carries the
// `${label}` hole, and the function contains EXACTLY TWO title attributes.
// The count is the one the other two cannot supply — non-empty and
// carries-the-hole both pass on a slice that found the right string for the
// WRONG button.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderHoldingAreaGroup,
  renderHoldingAreaGroups,
  holdingApproveAllTitle,
  holdingWontFixAllTitle,
  HOLDING_WONT_FIX_REASON_PLACEHOLDER,
  HOLDING_WONT_FIX_REASON_ARIA_LABEL,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/holdingAreaTable";
import { groupHeldRowsByFiler } from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import { rowWidth } from "../../../../lupin_app/static/js/multiplexer/render/rowSchema";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// The legacy side of every string comparison in this file.
// ---------------------------------------------------------------------------

const HERE = dirname( fileURLToPath( import.meta.url ) );
const LEGACY_PATH = resolve( HERE, "../../../../lupin_app/static/js/notifications.js" );

/** The body of `_renderHoldingAreaGroup`, sliced out of the legacy client. */
function legacyGroupSource(): string {
  const src   = readFileSync( LEGACY_PATH, "utf8" );
  const start = src.indexOf( "_renderHoldingAreaGroup( filer, tasks ) {" );
  assert.ok( start !== -1, "legacy _renderHoldingAreaGroup not found — the extraction is pointing at nothing" );
  const end   = src.indexOf( "_wireHoldingAreaControls()", start );
  assert.ok( end > start,  "legacy _wireHoldingAreaControls not found after the group renderer" );
  return src.slice( start, end );
}

/** The `title="…"` that follows `marker` in the legacy group renderer. */
function legacyTitleAfter( marker: string ): string {
  const body = legacyGroupSource();
  const at   = body.indexOf( marker );
  assert.ok( at !== -1, `legacy marker ${ marker } not found in the group renderer` );
  const match = /title="([^"]*)"/.exec( body.slice( at ) );
  assert.ok( match, `no title attribute after ${ marker } in the legacy group renderer` );
  return match[ 1 ];
}

function legacyAttr( pattern: RegExp ): string {
  const match = pattern.exec( legacyGroupSource() );
  assert.ok( match, `legacy attribute ${ pattern } not found in the group renderer` );
  return match[ 1 ];
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function heldTask( id: string, filer: string, title = "a held row" ): TaskItem {
  return {
    id,
    title,
    status     : "todo",
    priority   : "P2",
    created_by : filer,
  } as unknown as TaskItem;
}

// ---------------------------------------------------------------------------
// The extraction's own positive control — every string assertion below is
// worthless if this one does not hold.
// ---------------------------------------------------------------------------

test( "the legacy extraction reaches real strings, and they still carry the filer hole", () => {
  const approve = legacyTitleAfter( "holding-approve-all" );
  const wontFix = legacyTitleAfter( "holding-wont-fix-all\"" );

  assert.ok( approve.length > 40, `approve tooltip came back too short to be the real one: ${ JSON.stringify( approve ) }` );
  assert.ok( wontFix.length > 40, `won't-fix tooltip came back too short to be the real one: ${ JSON.stringify( wontFix ) }` );

  // 🔴 THE HOLE IS THE POINT. Both tooltips INTERPOLATE the filer, so they are
  // templates rather than constants — a renderer that dropped the name would
  // still satisfy a check against the constant prefix.
  assert.ok( approve.includes( "${label}" ), "the approve tooltip no longer interpolates the filer — the comparison below would be testing a constant" );
  assert.ok( wontFix.includes( "${label}" ), "the won't-fix tooltip no longer interpolates the filer" );

  assert.notEqual( approve, wontFix, "the two tooltips extracted identical — the slice is picking up one button twice" );

  // 🔴 COUNT THE MATCHES. Non-empty and carries-the-hole both pass on a slice
  // that found the RIGHT string for the WRONG button; only the count catches a
  // boundary that has moved to swallow a neighbouring function.
  const allTitles = legacyGroupSource().match( /title="[^"]*"/g ) ?? [];
  assert.equal( allTitles.length, 2,
    `expected exactly two title attributes in the legacy group renderer, found ${ allTitles.length } — the slice boundaries have moved` );
} );

// ---------------------------------------------------------------------------
// The carbon copy itself
// ---------------------------------------------------------------------------

test( "the batch tooltips are byte-identical to the legacy client's, filer substituted", () => {
  const filer = "Mr Radio";

  assert.equal(
    holdingApproveAllTitle( filer ),
    legacyTitleAfter( "holding-approve-all" ).replace( "${label}", filer ),
  );
  assert.equal(
    holdingWontFixAllTitle( filer ),
    legacyTitleAfter( "holding-wont-fix-all\"" ).replace( "${label}", filer ),
  );
} );

test( "the batch reason box's placeholder and accessible name match the legacy client's", () => {
  assert.equal( HOLDING_WONT_FIX_REASON_PLACEHOLDER, legacyAttr( /placeholder="([^"]*)"/ ) );
  assert.equal( HOLDING_WONT_FIX_REASON_ARIA_LABEL,  legacyAttr( /aria-label="([^"]*)"/ ) );
} );

test( "a rendered group carries both tooltips with THIS group's filer in them", () => {
  const group = { filer: "Mr Radio", tasks: [ heldTask( "t1", "mr radio 0e61abe3" ) ] };
  const el    = renderHoldingAreaGroup( group, null );

  const approve = el.querySelector( "button.holding-approve-all" ) as HTMLButtonElement;
  const wontFix = el.querySelector( "button.holding-wont-fix-all" ) as HTMLButtonElement;

  assert.ok( approve, "batch approve button is not rendered" );
  assert.ok( wontFix, "batch won't-fix button is not rendered" );

  assert.equal( approve.getAttribute( "title" ), holdingApproveAllTitle( "Mr Radio" ) );
  assert.equal( wontFix.getAttribute( "title" ), holdingWontFixAllTitle( "Mr Radio" ) );

  // The filer must actually appear — the whole reason the tooltip is a template.
  assert.ok( approve.getAttribute( "title" )!.includes( "Mr Radio" ) );
  assert.ok( wontFix.getAttribute( "title" )!.includes( "Mr Radio" ) );

  assert.equal( approve.textContent, "Approve all" );
  assert.equal( wontFix.textContent, "Won't fix all" );
} );

// ---------------------------------------------------------------------------
// Structure
// ---------------------------------------------------------------------------

test( "every keyed element in the header carries this group's data-filer", () => {
  const group = { filer: "Krishna", tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] };
  const el    = renderHoldingAreaGroup( group, null );

  assert.equal( el.getAttribute( "data-filer" ), "Krishna" );

  // ⚠️ THE DENOMINATOR RUNS THE RIGHT WAY ROUND. This sweeps the header for
  // everything the handler could key on and asserts none of them is MISSING the
  // attribute — rather than asserting a list I wrote is present, which a short
  // list satisfies by being short. The floor stops an empty sweep passing.
  const header = el.querySelector( ".holding-area-group-header" ) as HTMLElement;
  assert.ok( header, "the group header is not rendered" );

  const keyed = Array.from( header.querySelectorAll( "button, input, .holding-area-group-status" ) );
  assert.ok( keyed.length >= 4, `header sweep found only ${ keyed.length } keyed elements — expected the two buttons, the reason box and the status span` );
  for ( const node of keyed ) {
    assert.equal( node.getAttribute( "data-filer" ), "Krishna",
      `${ node.tagName }.${ node.className } is missing this group's data-filer` );
  }
} );

test( "the group's table uses the SHARED row head, so its width cannot drift from the row's", () => {
  const group = { filer: "Krishna", tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] };
  const el    = renderHoldingAreaGroup( group, null );

  const table = el.querySelector( "table" ) as HTMLTableElement;
  assert.ok( table.classList.contains( "task-list-table" ), "the pane's table lost the shared task-list-table class" );
  assert.ok( table.classList.contains( "holding-area-table" ), "the pane's table lost its own holding-area-table class" );

  assert.equal( table.querySelectorAll( "thead th" ).length, rowWidth() );
} );

test( "each held row renders the SHARED disclosed row, tagged for this pane and not the epic board", () => {
  const group = { filer: "Krishna", tasks: [ heldTask( "t1", "Krishna 420f5ec9" ), heldTask( "t2", "Krishna 420f5ec9" ) ] };
  const el    = renderHoldingAreaGroup( group, null );

  const rows = el.querySelectorAll( "tbody tr.task-row" );
  assert.equal( rows.length, 2 );

  // pane="holding-area" must NOT paint the epic board's extra class — that is
  // the one thing the pane argument changes about the shared row.
  for ( const row of Array.from( rows ) ) {
    assert.ok( !row.classList.contains( "epic-row" ), "a holding-area row is wearing the epic board's class" );
  }

  // Three <tr> per task: the visible line, the hidden controls row, the hidden
  // error stripe.
  assert.equal( el.querySelectorAll( "tbody tr" ).length, 6 );
  assert.equal( ( rows[ 0 ] as HTMLElement ).getAttribute( "data-task-id" ), "t1" );
} );

test( "the group count is the number of rows in THAT group, not the pane total", () => {
  const el = renderHoldingAreaGroup(
    { filer: "Krishna", tasks: [ heldTask( "t1", "k" ), heldTask( "t2", "k" ), heldTask( "t3", "k" ) ] }, null );
  assert.equal( ( el.querySelector( ".holding-area-group-count" ) as HTMLElement ).textContent, "3" );
  assert.equal( ( el.querySelector( ".holding-area-filer" ) as HTMLElement ).textContent, "Krishna" );
} );

// ---------------------------------------------------------------------------
// The fragment
// ---------------------------------------------------------------------------

test( "the fragment renders one group per model entry, in the model's order", () => {
  const groups = groupHeldRowsByFiler( [
    heldTask( "t1", "Krishna 420f5ec9" ),
    heldTask( "t2", "mr radio 0e61abe3" ),
    heldTask( "t3", "Krishna 420f5ec9" ),
  ] );

  const host = document.createElement( "div" );
  host.appendChild( renderHoldingAreaGroups( groups, null ) );

  const rendered = Array.from( host.querySelectorAll( ".holding-area-group" ) )
    .map( ( g ) => g.getAttribute( "data-filer" ) );
  assert.ok( rendered.length >= 2, "the fixture did not produce two filers — this test would pass vacuously" );
  assert.deepEqual( rendered, groups.map( ( g ) => g.filer ) );
} );

test( "the fragment forwards reassignTargets to every group it builds", () => {
  // ⚠️ NOT COVERAGE THEATRE — the fragment's own default parameter is a real
  // branch, and a fragment that took the roster and dropped it on the way down
  // would render an owner select offering nobody, in every group at once.
  const groups = groupHeldRowsByFiler( [ heldTask( "t1", "Krishna 420f5ec9" ), heldTask( "t2", "mr radio 0e61abe3" ) ] );
  const host   = document.createElement( "div" );
  host.appendChild( renderHoldingAreaGroups( groups, null, [ "rachel", "sam" ] ) );

  const rendered = host.querySelectorAll( ".holding-area-group" );
  assert.ok( rendered.length >= 2, "the fixture did not produce two groups — this test would pass vacuously" );
  for ( const group of Array.from( rendered ) ) {
    const options = Array.from( group.querySelectorAll( "select option" ) ).map( ( o ) => o.textContent );
    assert.ok( options.some( ( o ) => o === "rachel" ),
      `group ${ group.getAttribute( "data-filer" ) } never received the roster: ${ JSON.stringify( options ) }` );
  }
} );

test( "an empty model yields an EMPTY fragment — the 'nothing waiting' message is the renderer's job", () => {
  const host = document.createElement( "div" );
  host.appendChild( renderHoldingAreaGroups( [], null ) );
  assert.equal( host.childNodes.length, 0 );
} );

test( "reassignTargets reach the row's owner select through this pane too", () => {
  const el = renderHoldingAreaGroup(
    { filer: "Krishna", tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] }, null, [ "rachel", "sam" ] );
  const options = Array.from( el.querySelectorAll( "select option" ) ).map( ( o ) => o.textContent );
  assert.ok( options.some( ( o ) => o === "rachel" ), `owner select never received the roster: ${ JSON.stringify( options ) }` );
  assert.ok( options.some( ( o ) => o === "sam" ) );
} );
