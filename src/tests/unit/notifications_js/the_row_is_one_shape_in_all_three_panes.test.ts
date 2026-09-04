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
