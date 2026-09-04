// 🔴 THE SAME ROW, THE SAME SHAPE, IN ALL THREE PANES — AND THE SPLIT IS DATA.
//
// Rick, by voice 2026-09-03: he must never have to re-parse the left-to-right layout
// when moving between the task list, the holding area and the epic board. So the three
// panes carry ONE schema — same fields, same order, same disclosure behaviour — and this
// file is what makes that a fact rather than an intention.
//
// Spec: src/rnd/2026.09.04-row-display-progressive-disclosure.md · row af0e5ea0, under P0 8af64f5a.
//
// WHAT THIS FILE PINS, and each arm exists because the opposite shipped or nearly did:
//
//   1. Line 1 carries exactly five FIELDS — id · title · class · status · priority —
//      plus ONE control cell for the disclosure toggle. Six cells, that order, all three
//      panes. The toggle is a control and not a field; it cannot live behind the
//      disclosure it opens, which is why it gets its own cell instead of being counted
//      among the five.
//
//   2. NO line-2 or line-3 field creeps back onto line 1. That is the arm the spec asks
//      for by name, and it is the one most likely to fail six months from now when
//      somebody adds "just one more" column.
//
//   3. THE TITLE IS EMITTED IN FULL. Measured 2026-09-03 in the real browser: the title
//      was cut to 60 characters IN JAVASCRIPT, before it ever reached the DOM, by
//      TASK_TITLE_TRUNCATE_LEN. So widening the cell revealed ZERO extra characters —
//      the whole change would have shipped cosmetic, and we would have watched Rick
//      hover and been baffled. The cap is gone; the cell wraps to two lines in CSS.
//      ⚠️ This arm asserts about the STRING the renderer emits. It says nothing about
//      how many lines the browser draws — that is Pocholo's clamp and is measured in
//      the real browser, not here. A green here is not a claim about pixels.
//
//   4. ONE RENDERER. `_renderTaskRow` and `_renderEpicRow` must agree cell-for-cell,
//      because the markup exists once and they are thin wrappers over it. A second copy
//      would drift invisibly — the trap already documented for `.task-priority-select`
//      in two_renderers_one_class_name.test.ts, which is a DIFFERENT pair (classic vs
//      multiplexer) and does not cover this one.
//
//   5. THE SPLIT IS DATA. `ROW_SCHEMA` declares the three lines; the renderer walks it.
//      Rick's line-2/line-3 ruling drops in by editing an array, and this guard reads
//      the same array the renderer does, so the two cannot disagree.
//      ⚠️ Arm 5b deliberately pins the LITERAL field names as well. Deriving both sides
//      of a comparison from ROW_SCHEMA alone would be a tautology — the walk and the
//      expectation would move together and agree about anything. One side has to be
//      nailed to something the renderer cannot move.
//
//   6. The disclosed rows' colspan equals the number of line-1 cells, COMPUTED from the
//      rendered row rather than pinned to a literal. Six colspans carried the old column
//      count (12 · 12 · 11 · 5 · 5 · 5 · 5); a stale one still renders perfectly while
//      failing to span the table, which is why nobody catches it by looking.
//
// Run: npx tsx --test src/tests/unit/notifications_js/the_row_is_one_shape_in_all_three_panes.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

// The five fields Rick ruled onto the always-visible line, in his order, plus the
// control cell. Pinned as a LITERAL on purpose — see the note on arm 5b above.
const LINE_1_FIELDS  = [ "id", "title", "class", "status", "priority" ];
const DISCLOSE_CELL  = "task-col-disclose";
const LINE_1_CELLS   = [ ...LINE_1_FIELDS.map( f => `task-col-${f}` ), DISCLOSE_CELL ];
const LINE_2_FIELDS  = [ "blocked", "chase", "accountable", "filer", "project" ];
const LINE_3_FIELDS  = [ "detail", "actions" ];

// A title longer than the retired 60-char cap AND longer than one rendered line, so the
// "emitted in full" arm cannot pass by accident on a short string.
const LONG_TITLE =
  "[LUPIN] self_respin is DOWN fleet-wide — the cosa-voice MCP process serves a module older than 13014bd1";

const ROW = {
  id:                  "af0e5ea0-c662-4216-830d-1c41341dbe2c",
  title:               LONG_TITLE,
  item_class:          "task",
  status:              "blocked",
  priority:            "P0",
  project:             "lupin",
  blocked_by:          [ { kind: "user", id: "rick" } ],
  next_chase_ts:       "2026-09-04T15:00:00+00:00",
  accountable_manager: "maria",
  created_by:          "maya 9f278071",
  body:                "a body, so the detail affordance is live rather than dimmed",
};

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

function newUI(): any {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui: any = Object.create( Ctor.prototype );
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.queueSessionId = "test-session";
  return ui;
}

/** Parse a renderer's HTML into a real table body and hand back its rows. */
function rowsOf( html: string ): HTMLTableRowElement[] {
  const host = document.createElement( "table" );
  host.innerHTML = `<tbody>${html}</tbody>`;
  const rows = [ ...host.querySelectorAll( "tr" ) ] as HTMLTableRowElement[];
  // POSITIVE CONTROL. An empty parse satisfies every per-cell assertion in every loop
  // below, and would report a perfect green over nothing at all.
  assert.ok( rows.length >= 1, "the renderer must have produced at least one <tr>" );
  return rows;
}

/** The class name each <td> on the visible line carries, in document order. */
function line1Cells( html: string ): string[] {
  const cells = [ ...rowsOf( html )[ 0 ].querySelectorAll( "td" ) ];
  assert.ok( cells.length >= 1, "the visible line must have produced at least one <td>" );
  return cells.map( td => [ ...td.classList ].find( c => c.startsWith( "task-col-" ) ) ?? `??(${td.className})` );
}

/** Every pane that renders a row, driven for real — never grepped. */
function panes(): Array<{ name: string; html: string }> {
  const ui = newUI();
  return [
    { name: "task list / holding area", html: ui._renderTaskRow( ROW, "America/New_York" ) },
    { name: "epic board",               html: ui._renderEpicRow( ROW ) },
  ];
}

test( "1. line 1 is the five ruled fields plus the disclosure control, in order, in every pane", () => {
  for ( const pane of panes() ) {
    assert.deepEqual( line1Cells( pane.html ), LINE_1_CELLS,
      `${pane.name}: the visible line must carry exactly ${LINE_1_CELLS.join( " · " )}` );
  }
} );

test( "2. no line-2 or line-3 field creeps back onto the visible line", () => {
  const banned = [ ...LINE_2_FIELDS, ...LINE_3_FIELDS ].map( f => `task-col-${f}` );
  for ( const pane of panes() ) {
    const present = line1Cells( pane.html ).filter( c => banned.includes( c ) );
    assert.deepEqual( present, [],
      `${pane.name}: these belong behind the disclosure, not on the visible line: ${present.join( ", " )}` );
  }
} );

test( "3. the title is emitted in FULL — no character cap, no ellipsis in the markup", () => {
  for ( const pane of panes() ) {
    const cell = rowsOf( pane.html )[ 0 ].querySelector( "td.task-col-title" );
    assert.ok( cell, `${pane.name}: a title cell must exist` );
    assert.equal( cell!.textContent, LONG_TITLE,
      `${pane.name}: the renderer must emit the whole title — a JS cap makes a wider cell show the same text` );
    assert.equal( cell!.getAttribute( "title" ), LONG_TITLE,
      `${pane.name}: the hover tooltip must still carry the full title` );
  }
} );

// 🔴 THE TITLE TEXT LIVES IN A SPAN, AND THE SPAN IS THE WHOLE POINT.
//
// Measured on the live page 2026-09-03. `-webkit-line-clamp` and `max-height` both REACH
// the title cell and both do nothing there; inside a span the identical declarations bind:
//
//     cell  declared max-height 39px, overflow hidden -> rendered 90px;
//           clientHeight == scrollHeight (51/51) — nothing clamped
//     span  same declarations -> bounds at 39px against 78px, clipped, two lines
//
// So the fix is MARKUP, not styling: the stylesheet cannot reach this from its own side,
// which is why the element is asserted here instead of trusted to a CSS file.
//
// ⚠️ THE MECHANISM IS NOT THE COMPUTED `display` VALUE, and this comment used to say it
// was. Two of us explained it as "the cell computes flow-root so the clamp cannot apply";
// Pocholo disproved it — the SPAN computes `flow-root` too and the clamp binds on it
// anyway. Only the geometry discriminates. Recorded because a wrong mechanism sends the
// next reader hunting innocent code, and this one points at a property that was never
// involved.
//
// ⚠️ WHAT THIS ARM CANNOT DO: it asserts the span EXISTS, never that the clamp BINDS. The
// unit tier has no layout engine — under happy-dom every geometry value is 0 while
// computed styles read back fine — which is exactly how 574 green tests sat over a
// visibly broken page. A guard here can pin DECLARATIONS and never GEOMETRY; the binding
// is provable only in a real browser.
test( "3c. the title text is wrapped in a span the clamp can bind to", () => {
  for ( const pane of panes() ) {
    const cell = rowsOf( pane.html )[ 0 ].querySelector( "td.task-col-title" );
    const span = cell!.querySelector( "span.task-title" );
    assert.ok( span, `${pane.name}: the title needs a span — a clamp on a table-cell is inert` );
    assert.equal( span!.textContent, LONG_TITLE,
      `${pane.name}: the span carries the whole title, not a fragment of it` );
    assert.equal( cell!.children.length, 1,
      `${pane.name}: the span is the cell's only child, so the clamp governs all of the text` );
    assert.equal( cell!.getAttribute( "title" ), LONG_TITLE,
      `${pane.name}: the tooltip stays on the cell` );
  }
} );

test( "3b. the retired character cap is gone from the class, not merely unused", () => {
  const ui = newUI();
  assert.equal( ui.TASK_TITLE_TRUNCATE_LEN, undefined,
    "TASK_TITLE_TRUNCATE_LEN must be removed — a constant left behind is a constant somebody re-wires" );
  assert.equal( typeof ui._truncateTaskTitle, "undefined",
    "_truncateTaskTitle must be removed with it" );
} );

test( "4. one renderer — the two entry points agree cell-for-cell", () => {
  const ui = newUI();
  assert.deepEqual(
    line1Cells( ui._renderEpicRow( ROW ) ),
    line1Cells( ui._renderTaskRow( ROW, "America/New_York" ) ),
    "the epic board and the task list must be the same markup, not two copies of it" );
} );

test( "5. the line split is DATA — ROW_SCHEMA declares it and the renderer walks it", () => {
  const ui = newUI();
  assert.ok( ui.ROW_SCHEMA, "ROW_SCHEMA must exist so Rick's ruling drops in by editing an array" );
  const walked = ui.ROW_SCHEMA.line1.map( ( f: string ) => `task-col-${f}` ).concat( DISCLOSE_CELL );
  for ( const pane of panes() ) {
    assert.deepEqual( line1Cells( pane.html ), walked,
      `${pane.name}: the rendered line must be the one ROW_SCHEMA declares` );
  }
} );

test( "5b. ROW_SCHEMA carries Rick's ruled membership — pinned to literals, not to itself", () => {
  const ui = newUI();
  assert.deepEqual( ui.ROW_SCHEMA.line1, LINE_1_FIELDS, "line 1: id · title · class · status · priority" );
  assert.deepEqual( ui.ROW_SCHEMA.line2, LINE_2_FIELDS, "line 2: blocked-by · next chase · accountable · filed-by · project" );
  assert.deepEqual( ui.ROW_SCHEMA.line3, LINE_3_FIELDS, "line 3: detail · actions" );
} );

test( "6. every line-2 and line-3 field is present behind the disclosure, in every pane", () => {
  for ( const pane of panes() ) {
    const disclosed = rowsOf( pane.html ).find( r => r.classList.contains( "task-controls-row" ) );
    assert.ok( disclosed, `${pane.name}: a disclosed row must follow the visible line` );
    for ( const field of [ ...LINE_2_FIELDS, ...LINE_3_FIELDS ] ) {
      assert.ok( disclosed!.querySelector( `.task-col-${field}` ),
        `${pane.name}: ${field} was taken off the visible line and must appear behind the disclosure` );
    }
  }
} );

test( "7. the disclosed rows span the visible line — colspan COMPUTED, never a literal", () => {
  for ( const pane of panes() ) {
    const rows  = rowsOf( pane.html );
    const width = rows[ 0 ].querySelectorAll( "td" ).length;
    const spanners = rows.filter( r => r.classList.contains( "task-controls-row" )
                                    || r.classList.contains( "task-row-error-stripe" ) );
    assert.ok( spanners.length >= 2, `${pane.name}: expected a controls row and an error stripe` );
    for ( const r of spanners ) {
      const cell = r.querySelector( "td" );
      assert.equal( Number( cell!.getAttribute( "colspan" ) ), width,
        `${pane.name}: .${r.className} must span all ${width} cells — a stale colspan still renders perfectly` );
    }
  }
} );

test( "8. the disclosure toggle stays on the visible line, reachable without disclosing", () => {
  for ( const pane of panes() ) {
    const first  = rowsOf( pane.html )[ 0 ];
    const toggle = first.querySelector( `td.${DISCLOSE_CELL} .task-disclose-button` );
    assert.ok( toggle, `${pane.name}: the toggle cannot live behind the disclosure it opens` );
    assert.equal( toggle!.getAttribute( "aria-expanded" ), "false",
      `${pane.name}: the state is the attribute — a CSS-only disclosure is invisible to a keyboard` );
  }
} );

/**
 * The class name each <th> in the shared header carries, in document order.
 *
 * 🔴 POSITIVE CONTROL, and it is not decoration. A header that produced nothing would
 * satisfy `deepEqual( [], [] )` against a row list that produced nothing, and arm 9
 * would report a perfect green over two empty comparisons. An empty result is the one
 * finding that looks identical whether the work happened or not.
 */
function headerCells( html: string ): string[] {
  const host = document.createElement( "table" );
  host.innerHTML = html;
  const ths = [ ...host.querySelectorAll( "thead tr th" ) ];
  assert.ok( ths.length >= 1, "the header must have produced at least one <th>" );
  return ths.map( th => [ ...th.classList ].find( c => c.startsWith( "task-col-" ) ) ?? `??(${th.className})` );
}

test( "9. the header names the columns the rows emit, in the same order, in every pane", () => {
  /**
   * A cell with no header silently shifts every column right of it, and the table still
   * renders perfectly while it is wrong — which is why this is worth driving rather than
   * reading.
   *
   * 🔴 THE TEN ARMS ABOVE CANNOT SEE THIS. Every one of them drives a ROW renderer;
   * `panes()` calls `_renderTaskRow` and `_renderEpicRow` and nothing in this file ever
   * called a header builder. So a header that drifts from its rows was, until this arm,
   * unguarded everywhere except by a Python text guard that cannot render.
   *
   * ⚠️ ONE SIDE IS PINNED TO A LITERAL, DELIBERATELY. Comparing the header against the
   * rows alone would be a comparison whose two sides both walk ROW_SCHEMA — it agrees
   * with the code however wrong the code is, because a change to the schema moves both.
   * Checking the header against LINE_1_CELLS first gives this arm a side the renderer
   * cannot move; the row comparison then closes the loop. (Arm 5b pins the schema's own
   * membership the same way, for the same reason.)
   */
  const ui    = newUI();
  const heads = headerCells( ui._taskTableHeaderRow() );

  assert.deepEqual( heads, LINE_1_CELLS,
    `the header must name ${LINE_1_CELLS.join( " · " )} — it names ${heads.join( " · " )}` );

  for ( const pane of panes() ) {
    assert.deepEqual( line1Cells( pane.html ), heads,
      `${pane.name}: the rows and the shared header disagree about the columns. Every ` +
      `column right of the first disagreement is mislabelled, and the table renders ` +
      `perfectly the whole time.` );
  }
} );
