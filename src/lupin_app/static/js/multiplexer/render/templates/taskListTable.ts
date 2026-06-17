/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — table template (Step 4, store-canonical task mgmt).
//
// The DOM half of the task-list card, mirroring fleetStatusTable.ts. Built
// entirely via document.createElement + .textContent / .setAttribute — NO
// innerHTML — because table-section parsing rules drop stray <tr>/<td> when a
// fragment is parsed outside a <table> ancestor, AND createElement is inherently
// safe-write (no markup-injection surface for store-sourced strings).
//
// Eight columns: Title · Class · Status · Blocked by · Next chase · Accountable
// · Priority · Project. The owner_persona is the GROUP HEADER (not a per-row
// column), so a row never repeats its owner.

import {
  formatChaseTime,
  formatTaskBlockedBy,
  taskCellOrDash,
  taskPriorityClass,
  taskStatusClass,
  taskTitleLabel,
  type TaskGroup,
  type TaskItem,
  type TaskListModel,
} from "../taskListModel";
import { ownerKeyForGroup, taskGroupIdSlug } from "../taskListCollapse";

const TASK_COLSPAN = 8;

function td( className: string, text: string ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = className;
  cell.textContent = text;
  return cell;
}

/**
 * Render a single task row (<tr>) with the eight columns.
 *
 * Requires:
 *   - task is a TaskItem (fields rendered defensively — falsy → "—")
 *   - ianaZone is the IANA zone for the next-chase cell, or null/undefined
 * Ensures:
 *   - Status cell carries a `.task-status-dot` color-keyed span + the status word
 *   - Blocked-by / Accountable / Project: falsy/"none" → "—"
 *   - Next-chase: ISO → "MM-DD HH:MM" in zone; absent → "—"
 *   - the row carries a `task-status-*` class (status→accent); the Priority cell
 *     carries a `task-prio-*` heat class when recognized. Color is redundant
 *     with the status WORD / priority text (WCAG 1.4.1).
 */
export function renderTaskRow(
  task     : TaskItem,
  ianaZone : string | null | undefined,
): HTMLTableRowElement {
  const status      = task.status || "unknown";
  const statusClass = taskStatusClass( task.status );
  const prioClass   = taskPriorityClass( task.priority );

  const tr = document.createElement( "tr" );
  tr.className = `task-row ${statusClass}`;

  tr.appendChild( td( "task-col-title", taskTitleLabel( task ) ) );

  const classCell = document.createElement( "td" );
  classCell.className = "task-col-class";
  const classBadge = document.createElement( "span" );
  classBadge.className = `task-class-badge task-class-${task.item_class || "task"}`;
  classBadge.textContent = task.item_class || "task";
  classCell.appendChild( classBadge );
  tr.appendChild( classCell );

  // Status-dot prepended in the Status cell — color-keyed via the row's
  // `task-status-*` class (createElement keeps it safe-write; no innerHTML).
  const statusCell = document.createElement( "td" );
  statusCell.className = "task-col-status";
  const dot = document.createElement( "span" );
  dot.className = "task-status-dot";
  statusCell.appendChild( dot );
  statusCell.appendChild( document.createTextNode( status ) );
  tr.appendChild( statusCell );

  tr.appendChild( td( "task-col-blocked", taskCellOrDash( formatTaskBlockedBy( task.blocked_by ) ) ) );
  tr.appendChild( td( "task-col-chase", formatChaseTime( task.next_chase_ts, ianaZone ) ) );
  tr.appendChild( td( "task-col-accountable", taskCellOrDash( task.accountable_manager ) ) );

  tr.appendChild( td(
    "task-col-priority" + ( prioClass ? ` ${prioClass}` : "" ),
    taskCellOrDash( task.priority ),
  ) );
  tr.appendChild( td( "task-col-project", taskCellOrDash( task.project ) ) );

  return tr;
}

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
  cell.colSpan = TASK_COLSPAN;
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
 *   - Read-only: no action column, no mutating controls
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the multi-line exported function-declaration line; all internal branches are exercised by tests.
export function renderTaskListTable(
  model           : TaskListModel,
  ianaZone        : string | null | undefined,
  collapsedOwners : ReadonlySet<string> = new Set(),
): HTMLTableElement {
  const table = document.createElement( "table" );
  table.className = "task-list-table";

  const thead = document.createElement( "thead" );
  const headRow = document.createElement( "tr" );
  const headers: ReadonlyArray<[string, string]> = [
    [ "task-col-title", "Title" ],
    [ "task-col-class", "Class" ],
    [ "task-col-status", "Status" ],
    [ "task-col-blocked", "Blocked by" ],
    [ "task-col-chase", "Next chase" ],
    [ "task-col-accountable", "Accountable" ],
    [ "task-col-priority", "Priority" ],
    [ "task-col-project", "Project" ],
  ];
  for ( const [ cls, label ] of headers ) {
    const th = document.createElement( "th" );
    th.className = cls;
    th.textContent = label;
    headRow.appendChild( th );
  }
  thead.appendChild( headRow );
  table.appendChild( thead );

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
      tbody.appendChild( renderTaskRow( task, ianaZone ) );
    }
    table.appendChild( tbody );
  }

  return table;
}
