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
  EDITABLE_PRIORITIES,
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

// Nine columns post-Phase-2: the eight read-only data columns + an Actions
// column carrying the per-row editing controls (priority select · owner-reassign
// select · drop button + inline reason input).
const TASK_COLSPAN = 9;

function td( className: string, text: string ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = className;
  cell.textContent = text;
  return cell;
}

/**
 * Build the per-row Actions cell (Phase 2 — D2/D3 editing controls). All DOM via
 * createElement + textContent/setAttribute — NO innerHTML (table-section parse
 * safety + safe-write for store-sourced persona/priority strings). The controls
 * carry NO inline listeners: TaskListRenderer delegates `change` (selects) and
 * `click` (drop button) at the persistent container, surviving every re-render.
 *
 * Ensures:
 *   - `.task-priority-select` — P0–P3 options (EDITABLE_PRIORITIES), current
 *     priority pre-selected; reuses taskPriorityClass for the heat tint
 *   - `.task-owner-select` — reassignment roster (active personas, INCLUDING the
 *     'Sam' overflow persona — Q5); the current owner is pre-selected (prepended
 *     if not already a target so the select reflects reality); an unassigned task
 *     leads with a disabled "(unassigned)" placeholder
 *   - `.task-drop-reason` text input + `.task-drop-button` — the inline
 *     drop-with-reason affordance (Q4: inline row input, not a modal)
 */
function renderActionsCell( task: TaskItem, reassignTargets: ReadonlyArray<string> ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = "task-col-actions";

  // Priority select (P0–P3). The heat class makes the current urgency legible
  // even before the user opens the dropdown (color is redundant with the text).
  const prioSelect = document.createElement( "select" );
  const prioClass  = taskPriorityClass( task.priority );
  prioSelect.className = "task-priority-select" + ( prioClass ? ` ${prioClass}` : "" );
  prioSelect.setAttribute( "aria-label", "Set priority" );
  for ( const p of EDITABLE_PRIORITIES ) {
    const opt = document.createElement( "option" );
    opt.value = p;
    opt.textContent = p;
    if ( ( task.priority ?? "" ) === p ) opt.selected = true;
    prioSelect.appendChild( opt );
  }
  cell.appendChild( prioSelect );

  // Owner-reassignment select. The current owner is pre-selected; an unassigned
  // task gets a disabled placeholder so the control isn't blank.
  const ownerSelect = document.createElement( "select" );
  ownerSelect.className = "task-owner-select";
  ownerSelect.setAttribute( "aria-label", "Reassign owner" );
  const currentOwner = task.owner_persona ?? "";
  if ( !currentOwner ) {
    const placeholder = document.createElement( "option" );
    placeholder.value = "";
    placeholder.textContent = "(unassigned)";
    placeholder.disabled = true;
    placeholder.selected = true;
    ownerSelect.appendChild( placeholder );
  }
  const seen = new Set<string>();
  const ordered = currentOwner ? [ currentOwner, ...reassignTargets ] : reassignTargets;
  for ( const persona of ordered ) {
    if ( !persona || seen.has( persona ) ) continue;
    seen.add( persona );
    const opt = document.createElement( "option" );
    opt.value = persona;
    opt.textContent = persona;
    if ( persona === currentOwner ) opt.selected = true;
    ownerSelect.appendChild( opt );
  }
  cell.appendChild( ownerSelect );

  // Drop-with-reason: inline reason input + Drop button (Q4 — inline row input,
  // not a modal). The renderer reads the sibling input's value on click and
  // enforces the non-blank reason the `→dropped` transition requires.
  const reasonInput = document.createElement( "input" );
  reasonInput.type = "text";
  reasonInput.className = "task-drop-reason";
  reasonInput.setAttribute( "placeholder", "drop reason…" );
  reasonInput.setAttribute( "aria-label", "Drop reason" );
  cell.appendChild( reasonInput );

  const dropBtn = document.createElement( "button" );
  dropBtn.type = "button";
  dropBtn.className = "task-drop-button";
  dropBtn.textContent = "Drop";
  cell.appendChild( dropBtn );

  return cell;
}

/**
 * Render a single task row (<tr>) with the eight data columns + the Actions cell.
 *
 * Requires:
 *   - task is a TaskItem (fields rendered defensively — falsy → "—")
 *   - ianaZone is the IANA zone for the next-chase cell, or null/undefined
 *   - reassignTargets is the active-persona roster (Sam INCLUDED — Q5) for the
 *     owner select; defaults to [] (e.g. read-only callers / fleet unavailable)
 * Ensures:
 *   - Status cell carries a `.task-status-dot` color-keyed span + the status word
 *   - Blocked-by / Accountable / Project: falsy/"none" → "—"
 *   - Next-chase: ISO → "MM-DD HH:MM" in zone; absent → "—"
 *   - the row carries a `task-status-*` class (status→accent); the Priority cell
 *     carries a `task-prio-*` heat class when recognized. Color is redundant
 *     with the status WORD / priority text (WCAG 1.4.1).
 *   - the row carries `data-task-id` (the row's id, or "" when absent) so the
 *     renderer's delegated handlers can resolve the target task from any control
 *   - the trailing Actions cell carries the priority/owner selects + drop affordance
 */
export function renderTaskRow(
  task            : TaskItem,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
): HTMLTableRowElement {
  const status      = task.status || "unknown";
  const statusClass = taskStatusClass( task.status );
  const prioClass   = taskPriorityClass( task.priority );

  const tr = document.createElement( "tr" );
  tr.className = `task-row ${statusClass}`;
  tr.setAttribute( "data-task-id", task.id ?? "" );

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

  tr.appendChild( renderActionsCell( task, reassignTargets ) );

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
 *   - each row carries the trailing Actions cell (priority/owner edit + drop);
 *     reassignTargets (active personas, Sam included — Q5) populates the owner selects
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
    [ "task-col-actions", "Actions" ],
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
      tbody.appendChild( renderTaskRow( task, ianaZone, reassignTargets ) );
    }
    table.appendChild( tbody );
  }

  return table;
}
