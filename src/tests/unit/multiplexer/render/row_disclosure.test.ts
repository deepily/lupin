// Row disclosure — rowDisclosure unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// THREE DEFECTS THESE PIN, each of which renders a plausible row:
//   1. keeping only ONE half of the state. The JS card holds it in BOTH
//      `aria-expanded` (the accessible half) and `hidden` (the visual half).
//      Drop aria and a sighted mouse user sees nothing wrong while the row is
//      unreachable by keyboard; drop hidden and it is announced open and never
//      painted.
//   2. an UNSCOPED lookup. A row rendered in two panes has two controls rows
//      with the same data-controls-for, so document.querySelector opens the
//      wrong pane's copy — and it looks like the right one until you notice
//      the other pane moved.
//   3. a HARD-CODED colspan. The table still renders perfectly while the
//      controls row quietly stops spanning it.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const M = () => import( "../../../../lupin_app/static/js/multiplexer/render/templates/rowDisclosure" );
const S = () => import( "../../../../lupin_app/static/js/multiplexer/render/rowSchema" );

// ---------------------------------------------------------------- toggle

test( "the toggle carries type=button, the class, and the task id", async () => {
  const { renderDiscloseToggle } = await M();
  const b = renderDiscloseToggle( "abc" );
  assert.equal( b.tagName.toLowerCase(), "button" );
  assert.equal( b.getAttribute( "type" ), "button" );
  assert.equal( b.className, "task-disclose-button" );
  assert.equal( b.getAttribute( "data-task-id" ), "abc" );
} );

test( "🔴 the toggle starts aria-expanded=false — the ACCESSIBLE half of the state", async () => {
  const { renderDiscloseToggle } = await M();
  assert.equal( renderDiscloseToggle( "abc" ).getAttribute( "aria-expanded" ), "false" );
} );

test( "the toggle renders the ellipsis and the JS card's title verbatim", async () => {
  const { renderDiscloseToggle, DISCLOSE_GLYPH, DISCLOSE_TITLE } = await M();
  const b = renderDiscloseToggle( "abc" );
  assert.equal( DISCLOSE_GLYPH, "⋯" );
  assert.equal( DISCLOSE_TITLE, "Show row controls" );
  assert.equal( b.textContent, DISCLOSE_GLYPH );
  assert.equal( b.getAttribute( "title" ), DISCLOSE_TITLE );
} );

test( "an absent task id becomes empty string, never the literal 'null'", async () => {
  const { renderDiscloseToggle } = await M();
  assert.equal( renderDiscloseToggle( null ).getAttribute( "data-task-id" ), "" );
  assert.equal( renderDiscloseToggle( undefined ).getAttribute( "data-task-id" ), "" );
} );

test( "the disclose CELL carries the class and exactly the toggle", async () => {
  const { renderDiscloseCell } = await M();
  const td = renderDiscloseCell( "abc" );
  assert.equal( td.className, "task-col-disclose" );
  assert.equal( td.children.length, 1 );
  assert.equal( ( td.children[ 0 ] as HTMLElement ).className, "task-disclose-button" );
} );

// ---------------------------------------------------------------- controls row

test( "🔴 the controls row is HIDDEN by default — Rick's 'NOT displayed by default'", async () => {
  const { renderControlsRow } = await M();
  assert.equal( renderControlsRow( "abc", "task-status-queued", {} ).hidden, true );
} );

test( "the controls row carries its class, status class and data-controls-for", async () => {
  const { renderControlsRow } = await M();
  const tr = renderControlsRow( "abc", "task-status-queued", {} );
  assert.ok( tr.className.includes( "task-controls-row" ) );
  assert.ok( tr.className.includes( "task-status-queued" ) );
  assert.equal( tr.getAttribute( "data-controls-for" ), "abc" );
} );

test( "an empty status class leaves no trailing space in the class list", async () => {
  const { renderControlsRow } = await M();
  assert.equal( renderControlsRow( "abc", "", {} ).className, "task-controls-row" );
} );

test( "🔴 the colspan is DERIVED from rowWidth(), not written", async () => {
  const { renderControlsRow } = await M();
  const { rowWidth } = await S();
  const cell = renderControlsRow( "abc", "", {} ).querySelector( "td" )!;
  assert.equal( cell.getAttribute( "colspan" ), String( rowWidth() ) );
} );

test( "the disclosed fields render as TWO lines, in schema order", async () => {
  const { renderControlsRow } = await M();
  const { ROW_SCHEMA } = await S();
  const tr    = renderControlsRow( "abc", "", {} );
  const lines = tr.querySelectorAll( ".task-disclosed-line" );
  assert.equal( lines.length, 2 );
  const first = [ ...lines[ 0 ].querySelectorAll( ".task-disclosed-field" ) ]
    .map( ( el ) => el.className.replace( "task-disclosed-field task-col-", "" ) );
  assert.deepEqual( first, [ ...ROW_SCHEMA.line2 ] );
} );

test( "each disclosed field carries a LABEL span and a VALUE span", async () => {
  const { renderControlsRow } = await M();
  const tr = renderControlsRow( "abc", "", { filer: "Maria" } );
  const filer = tr.querySelector( ".task-col-filer" )!;
  assert.equal( filer.querySelector( ".task-disclosed-label" )!.textContent, "Filed by" );
  assert.equal( filer.querySelector( ".task-disclosed-value" )!.textContent, "Maria" );
} );

test( "a field with no supplied value renders an em-dash, never 'undefined'", async () => {
  const { renderControlsRow } = await M();
  const tr = renderControlsRow( "abc", "", {} );
  assert.equal( tr.querySelector( ".task-col-project .task-disclosed-value" )!.textContent, "—" );
} );

// ---------------------------------------------------------------- error stripe

test( "the error stripe is hidden, keyed to the row, and spans the full width", async () => {
  const { renderErrorStripe } = await M();
  const { rowWidth } = await S();
  const tr = renderErrorStripe( "abc" );
  assert.equal( tr.className, "task-row-error-stripe" );
  assert.equal( tr.getAttribute( "data-error-for" ), "abc" );
  assert.equal( tr.hidden, true );
  assert.equal( tr.querySelector( "td" )!.getAttribute( "colspan" ), String( rowWidth() ) );
} );

// ---------------------------------------------------------------- toggling

function pane( ids: string[] ): HTMLElement {
  const div = document.createElement( "div" );
  const tbl = document.createElement( "table" );
  for ( const id of ids ) {
    const tr = document.createElement( "tr" );
    tr.className = "task-controls-row";
    tr.setAttribute( "data-controls-for", id );
    ( tr as HTMLElement ).hidden = true;
    tbl.appendChild( tr );
  }
  div.appendChild( tbl );
  return div;
}

test( "🔴 BOTH HALVES MOVE TOGETHER and stay opposite", async () => {
  const { renderDiscloseToggle, toggleDisclosure } = await M();
  const p   = pane( [ "a" ] );
  const btn = renderDiscloseToggle( "a" );
  p.appendChild( btn );
  const row = p.querySelector<HTMLElement>( '[data-controls-for="a"]' )!;

  assert.equal( toggleDisclosure( p, btn ), true );
  assert.equal( btn.getAttribute( "aria-expanded" ), "true" );
  assert.equal( row.hidden, false );

  assert.equal( toggleDisclosure( p, btn ), false );
  assert.equal( btn.getAttribute( "aria-expanded" ), "false" );
  assert.equal( row.hidden, true );
} );

test( "🔴 PANE-SCOPED: a second pane's identical row is NOT touched", async () => {
  const { renderDiscloseToggle, toggleDisclosure } = await M();
  // The exact situation the JS docstring names: one row in two panes, same id.
  const mine   = pane( [ "shared" ] );
  const theirs = pane( [ "shared" ] );
  const host   = document.createElement( "div" );
  host.appendChild( theirs );          // the OTHER pane is earlier in the document
  host.appendChild( mine );
  document.body.appendChild( host );

  const btn = renderDiscloseToggle( "shared" );
  mine.appendChild( btn );
  toggleDisclosure( mine, btn );

  assert.equal( mine.querySelector<HTMLElement>( '[data-controls-for="shared"]' )!.hidden, false );
  assert.equal( theirs.querySelector<HTMLElement>( '[data-controls-for="shared"]' )!.hidden, true,
    "an unscoped query would have opened the other pane's copy" );
  host.remove();
} );

test( "a toggle with NO controls row in the pane is a no-op returning false", async () => {
  const { renderDiscloseToggle, toggleDisclosure } = await M();
  const p   = pane( [ "other" ] );
  const btn = renderDiscloseToggle( "missing" );
  p.appendChild( btn );
  assert.equal( toggleDisclosure( p, btn ), false );
  assert.equal( btn.getAttribute( "aria-expanded" ), "false" );
} );

test( "a toggle with no data-task-id resolves to the empty id, not a crash", async () => {
  const { toggleDisclosure } = await M();
  const p   = pane( [ "a" ] );
  const btn = document.createElement( "button" );   // no data-task-id at all
  p.appendChild( btn );
  assert.equal( toggleDisclosure( p, btn ), false );
} );

test( "an id containing CSS-special characters is matched, not escaped into a selector", async () => {
  const { renderDiscloseToggle, toggleDisclosure } = await M();
  const weird = 'a"b.c:d';
  const p     = pane( [ weird ] );
  const btn   = renderDiscloseToggle( weird );
  p.appendChild( btn );
  assert.equal( toggleDisclosure( p, btn ), true );
} );

// ---------------------------------------------------------------------------
// renderRowTableHead — ONE header for three tables
// ---------------------------------------------------------------------------

test( "the shared head walks ROW_SCHEMA.line1 in order, then the blank toggle column", async () => {
  const { renderRowTableHead } = await M();
  const { ROW_SCHEMA, rowFieldLabel, rowWidth } =
    await import( "../../../../lupin_app/static/js/multiplexer/render/rowSchema" );
  const thead = renderRowTableHead();

  assert.equal( thead.tagName, "THEAD" );
  const ths = Array.from( thead.querySelectorAll( "th" ) );

  // 🔴 DERIVED FROM THE SCHEMA, NOT TYPED OUT. A hand-written expectation here
  // would be a SECOND enumeration of the field list, and the whole reason the
  // header is generated is that a header which has drifted from its rows
  // mislabels every column to the right of the drift — silently, because the
  // table still renders perfectly.
  assert.deepEqual(
    ths.slice( 0, ROW_SCHEMA.line1.length ).map( ( th ) => th.className ),
    ROW_SCHEMA.line1.map( ( f ) => `task-col-${ f }` ),
  );
  assert.deepEqual(
    ths.slice( 0, ROW_SCHEMA.line1.length ).map( ( th ) => th.textContent ),
    ROW_SCHEMA.line1.map( ( f ) => rowFieldLabel( f ) ),
  );
  // Positive control: the loop above passes vacuously over an empty schema.
  assert.ok( ROW_SCHEMA.line1.length >= 5, "the visible line must carry its five fields" );

  // The header cell count IS the colspan every disclosed row derives from.
  assert.equal( ths.length, rowWidth() );
} );

test( "the toggle's column is headed BLANK, with its name on aria-label", async () => {
  const { renderRowTableHead } = await M();
  const th = renderRowTableHead().querySelector( "th.task-col-disclose" )!;
  assert.ok( th, "the disclosure column must have a header cell of its own" );
  // A word here would read as a SIXTH FIELD; the control still needs a name for
  // a screen reader, so it rides aria-label instead. Verbatim from the JS card.
  assert.equal( th.textContent, "" );
  assert.equal( th.getAttribute( "aria-label" ), "Row controls" );
  // ⚠️ Read LAST from the SAME head. Two calls build two element trees, so
  // comparing a node from one against a node from the other compares instances,
  // never position — it fails on a correct header and passes on nothing.
  const head = renderRowTableHead();
  assert.equal( head.querySelector( "tr" )!.lastElementChild!.className, "task-col-disclose",
    "the toggle column must be LAST — it is the right-justified control on the title line" );
} );
