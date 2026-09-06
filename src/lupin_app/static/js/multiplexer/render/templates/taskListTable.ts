/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — table template (Step 4, store-canonical task mgmt).
//
// The DOM half of the task-list card, mirroring fleetStatusTable.ts. Built
// entirely via document.createElement + .textContent / .setAttribute — NO
// innerHTML — because table-section parsing rules drop stray <tr>/<td> when a
// fragment is parsed outside a <table> ancestor, AND createElement is inherently
// safe-write (no markup-injection surface for store-sourced strings).
//
// 🔴 THE ROW IS PROGRESSIVE-DISCLOSURE, NOT ELEVEN FLAT CELLS (Rick's keypress
// ruling 2026-09-05: re-shape the TS row FIRST, then build the two new panes).
// The visible line is ROW_SCHEMA.line1 — ID · Title · Class · Status · Priority
// — plus the ⋯ toggle's own cell; Blocked by · Next chase · Accountable · Filed
// by · Project and the nine controls live behind that toggle. The ELEVEN-column
// flat row this file used to emit was a PRE-DISCLOSURE GENERATION, not an
// incomplete copy of the JS card.
//
// ⚠️ THE ROW ITSELF LIVES IN templates/taskRowDisclosed.ts AND IS SHARED BY ALL
// THREE PANES. The JS card shares _renderRow between the task list, the holding
// area and the epic board with Rick's reason in its docstring — "moving between
// the epic board and the task list meant re-parsing the layout" — so cell-for-
// cell row identity is a BEHAVIOURAL requirement. Do not give this pane a row of
// its own.
//
// ⚠️ NO COLSPAN LITERAL SURVIVES HERE. Every span derives from rowWidth(); a
// stale colspan does not look broken (the table renders perfectly while the
// controls row quietly stops spanning it).
//
// The owner_persona is the GROUP HEADER (not a per-row column), so a row never
// repeats its owner.

import type { TaskGroup, TaskListModel } from "../taskListModel";
import { ownerKeyForGroup, taskGroupIdSlug } from "../taskListCollapse";
import { rowWidth } from "../rowSchema";
import { renderRowTableHead } from "./rowDisclosure";
import { renderDisclosedRow } from "./taskRowDisclosed";

function renderGroupHeader( group: TaskGroup, isCollapsed: boolean, idSlug: string ): HTMLTableRowElement {
  // Non-unassigned groups always carry a non-null ownerPersona (groupTasksByOwner
  // invariant); the Unassigned bucket takes the literal label.
  const label = group.isUnassigned
    ? "(Unassigned)"
    : `${group.ownerPersona} · ${group.tasks.length}`;

  // The header doubles as the per-persona ACCORDION bar: a chevron + the label,
  // keyboard-activatable (role/tabindex/aria). The chevron is decorative
  // (aria-hidden); collapse state lives on the parent <tbody> (toggled by class).
  const headerRow = document.createElement( "tr" );
  headerRow.className = "task-group-header" + ( group.isUnassigned ? " task-group-unassigned" : "" );
  headerRow.setAttribute( "role", "button" );
  headerRow.setAttribute( "tabindex", "0" );
  headerRow.setAttribute( "aria-expanded", String( !isCollapsed ) );
  headerRow.setAttribute( "aria-controls", idSlug );

  const cell = document.createElement( "td" );
  cell.colSpan = rowWidth();
  const chevron = document.createElement( "span" );
  chevron.className = "task-group-chevron";
  chevron.setAttribute( "aria-hidden", "true" );
  chevron.textContent = isCollapsed ? "▸" : "▾";
  cell.appendChild( chevron );
  cell.appendChild( document.createTextNode( label ) );
  headerRow.appendChild( cell );
  return headerRow;
}

/**
 * Render the owner-grouped model as a read-only `<table>`. Each owner is a
 * group-header row; its tasks render beneath; the Unassigned group renders last.
 *
 * Requires:
 *   - model is the { totalCount, groups } shape from groupTasksByOwner
 *   - ianaZone is the IANA zone for next-chase cells, or null/undefined
 * Ensures:
 *   - Returns a `.task-list-table` <table> element
 *   - each owner group is its OWN <tbody class="task-group" data-owner> (the
 *     accordion seam): a group whose owner key ∈ collapsedOwners gets the
 *     `collapsed` class (CSS hides its rows; the header bar stays), chevron ▸,
 *     aria-expanded="false"; otherwise chevron ▾, aria-expanded="true"
 *   - the <thead> is the SHARED ROW_SCHEMA header — five field columns plus the
 *     blank disclosure column, so its cell count equals rowWidth()
 *   - each task emits THREE rows (visible · hidden controls · hidden error
 *     stripe) via the row renderer all three panes share; the nine controls live
 *     behind the ⋯ toggle, and reassignTargets (active personas, Sam included —
 *     Q5) populates the owner selects inside them
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the multi-line exported function-declaration line; all internal branches are exercised by tests.
export function renderTaskListTable(
  model           : TaskListModel,
  ianaZone        : string | null | undefined,
  collapsedOwners : ReadonlySet<string> = new Set(),
  reassignTargets : ReadonlyArray<string> = [],
): HTMLTableElement {
  const table = document.createElement( "table" );
  table.className = "task-list-table";

  // The <thead> is SHARED with the other two row panes (rowDisclosure) so it
  // walks the same ROW_SCHEMA array the rows walk and cannot drift from them.
  table.appendChild( renderRowTableHead() );

  // Each owner group is its OWN <tbody class="task-group" data-owner> so a
  // collapse is a single class flip on that tbody (CSS hides its .task-row).
  for ( const group of model.groups ) {
    const ownerKey    = ownerKeyForGroup( group );
    const isCollapsed = collapsedOwners.has( ownerKey );
    const idSlug      = taskGroupIdSlug( ownerKey );

    const tbody = document.createElement( "tbody" );
    tbody.className = "task-group" + ( isCollapsed ? " collapsed" : "" );
    tbody.id = idSlug;
    tbody.dataset.owner = ownerKey;

    tbody.appendChild( renderGroupHeader( group, isCollapsed, idSlug ) );
    for ( const task of group.tasks ) {
      // THREE <tr> per task — visible line, hidden controls row, hidden error
      // stripe — all appended into this group's own <tbody> so a collapse hides
      // the disclosed row with its parent.
      tbody.appendChild( renderDisclosedRow( task, "task-list", ianaZone, reassignTargets ) );
    }
    table.appendChild( tbody );
  }

  return table;
}
