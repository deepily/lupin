// 🔴 B2 — THE THREE PANE TABLES EMIT ONE ROW SHAPE, CELL FOR CELL.
//
// Rick asked for this personally (route doc §7.3): "moving between the epic board
// and the task list meant re-parsing the layout." Three panes share the row —
// task list and holding area via _renderTaskRow, epic board via _renderEpicRow —
// so cell-for-cell identity is a BEHAVIOURAL requirement, and it survives the
// code-reuse question being descoped. D1 removed the shared MECHANISM, not the
// requirement.
//
// 🔴 WHY THIS FILE EXISTS WHEN task_row_disclosed.test.ts ALREADY SAYS
// "all three panes emit the SAME cells in the SAME order".
// That test calls renderDisclosedRow THREE TIMES WITH THREE PANE TAGS and
// compares the outputs — three calls to ONE function. It is a statement about
// the shared row renderer, not about the panes. A pane whose TABLE stops calling
// that function, or wraps what it returns, is invisible to it. María's clause,
// verbatim: identity must hold "without relying on shared functions".
//
// MEASURED, not argued (John, 2026-09-06, sha 5434e381, tree clean):
//   Green baseline first — 108/108 rc 0 across task_row_disclosed,
//   holding_area_table, epic_board_table, templates_task_list_table and
//   holding_area_renderer.
//   Arm M-B2a — holdingAreaTable.ts hand-rolls its row and DROPS THE PRIORITY
//   CELL (sha256 c5ac14c0 -> 9e33a44f). That is exactly the cell-by-cell drift
//   §7.3 warns about.
//     -> those five suites:        108 of 108 GREEN. Survived.
//     -> the WHOLE multiplexer tier: 2383 / 2383 / 0, exit 0 — BYTE-IDENTICAL to
//        the clean baseline at the same sha.
//   So one pane rendered a five-cell row while the other two rendered six, and
//   not one of 2383 tests noticed. Restored byte-exact afterwards.
//
// Supporting reads, each with a positive control on the instrument:
//   · NO test file references two or more of the three pane TABLE templates —
//     checked in both the static `from "…"` and the dynamic `import()` forms.
//   · holding_area_table.test.ts and epic_board_table.test.ts assert only that
//     `thead th` count equals rowWidth() — the HEADER, never the emitted row.
//
// ⚠️ THE EXPECTED SHAPE BELOW IS A DELIBERATE HAND-WRITTEN LITERAL (María's
// ruling, and Krishna's constants-versus-semantics framing). Deriving it from
// ROW_SCHEMA would make both sides of the comparison move together and the
// assertion could never fail — an identity dressed as a test. Pinning it to a
// literal gives the expected value a DIFFERENT PROVENANCE from the actual one,
// which is the whole point. If Rick reorders the columns, this literal is
// SUPPOSED to go red and be updated deliberately.
//
// ⚠️ WILL NOT CATCH: this is a DOM claim. happy-dom has no layout engine, so a
// row that is structurally identical and visually wrong passes here. Whether
// these panes LOOK alike is measured in a real browser and nowhere in this file.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderTaskListTable } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskListTable";
import { renderHoldingAreaGroup } from "../../../../lupin_app/static/js/multiplexer/render/templates/holdingAreaTable";
import { renderEpicBoardTable } from "../../../../lupin_app/static/js/multiplexer/render/templates/epicBoardTable";
import { groupTasksByOwner, type TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import { groupHeldRowsByFiler } from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import { groupTasksByEpic } from "../../../../lupin_app/static/js/multiplexer/render/epicBoardModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

/**
 * CONTRACT LITERAL — ROW_SCHEMA.line1 in order, then the disclosure control.
 * Hand-written on purpose; see the header. Six cells: five FIELDS plus ONE
 * control. The toggle is a control, not a field, which is why it is not counted
 * among the five and why it cannot live behind the disclosure it opens.
 */
const EXPECTED_ROW_CELLS = [
  "task-col-id",
  "task-col-title",
  "task-col-class",
  "task-col-status",
  "task-col-priority",
  "task-col-disclose",
] as const;

const TASK = {
  id                  : "0123456789abcdef",
  title               : "a task",
  item_class          : "bug",
  status              : "blocked",
  priority            : "P1",
  blocked_by          : [],
  correlation_key     : "epic:alpha",
  next_chase_ts       : "2026-09-08T18:00:00+00:00",
  accountable_manager : "maria",
  created_by          : "mr radio 0e61abe3",
  project             : "lupin",
  body                : "some body",
} as unknown as TaskItem;

const ZONE = "UTC";

/** The three PANE TABLES, each built the way its renderer builds it. */
function paneTables(): Array<{ pane: string; el: HTMLElement }> {
  const holding = renderHoldingAreaGroup( groupHeldRowsByFiler( [ TASK ] )[ 0 ], ZONE );
  return [
    { pane: "task-list",    el: renderTaskListTable( groupTasksByOwner( [ TASK ] ), ZONE ) },
    { pane: "holding-area", el: holding },
    { pane: "epic-board",   el: renderEpicBoardTable( groupTasksByEpic( [ TASK ] ), {}, {}, ZONE ) },
  ];
}

/** The cell classes of a pane's VISIBLE row — the one carrying data-task-id. */
function visibleRowCells( el: HTMLElement ): string[] {
  const tr = el.querySelector( "tr[data-task-id]" );
  assert.ok( tr !== null, "no visible row carrying data-task-id — this pane rendered nothing to compare" );
  return Array.from( tr!.children ).map( ( c ) => ( c as HTMLElement ).className.split( " " )[ 0 ] );
}

test( "🔴 B2: every pane TABLE emits the ruled cells, in order — pinned to a literal, not to the code", () => {
  const tables = paneTables();

  // POSITIVE CONTROL. A loop over an empty list passes every assertion inside
  // it, so the corpus asserts its own size before anything is compared.
  assert.equal( tables.length, 3, "the corpus is not three panes — this test would under-report" );

  for ( const { pane, el } of tables ) {
    assert.deepEqual( visibleRowCells( el ), [ ...EXPECTED_ROW_CELLS ],
      `${ pane } does not emit the ruled row shape` );
  }
} );

test( "🔴 B2: the three pane TABLES agree with EACH OTHER, cell for cell", () => {
  // The literal above pins the shape to the RULING. This pins the panes to ONE
  // ANOTHER, so a deliberate column change that updates the literal still cannot
  // land in one pane and not the others.
  const [ first, ...rest ] = paneTables();
  const want = visibleRowCells( first.el );

  assert.ok( want.length >= 6, "positive control: the reference pane emitted no cells" );
  for ( const { pane, el } of rest ) {
    assert.deepEqual( visibleRowCells( el ), want, `${ pane } diverged from ${ first.pane }` );
  }
} );

test( "🔴 B2: every pane emits the SAME NUMBER of cells as its own header", () => {
  // The header and the row are built from one ROW_SCHEMA walk, so a pane that
  // drifts its row without drifting its header renders a table whose columns no
  // longer line up — visible to a person instantly, invisible to a shape check
  // that only ever looks at rows.
  for ( const { pane, el } of paneTables() ) {
    const ths = el.querySelectorAll( "thead th" );
    assert.ok( ths.length > 0, `${ pane } rendered no header — nothing to compare the row against` );
    assert.equal( visibleRowCells( el ).length, ths.length,
      `${ pane }'s row and header disagree about how many columns there are` );
  }
} );
