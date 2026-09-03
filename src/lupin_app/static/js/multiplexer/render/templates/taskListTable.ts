/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — table template (Step 4, store-canonical task mgmt).
//
// The DOM half of the task-list card, mirroring fleetStatusTable.ts. Built
// entirely via document.createElement + .textContent / .setAttribute — NO
// innerHTML — because table-section parsing rules drop stray <tr>/<td> when a
// fragment is parsed outside a <table> ancestor, AND createElement is inherently
// safe-write (no markup-injection surface for store-sourced strings).
//
// Columns (row redesign 2026.06.29 + Detail reposition F2 2026.07.01): ID ·
// Title · Detail · Class · Status · Blocked by · Next chase · Accountable ·
// Priority · Project · Actions. The leading ID column + the Detail 📄 column
// (body-overlay affordance, now directly after Title) augment the original
// eight; Actions stays the trailing edit column. The owner_persona is the GROUP
// HEADER (not a per-row column), so a row never repeats its owner.

import {
  EDITABLE_PRIORITIES,
  formatChaseTime,
  formatTaskBlockedBy,
  taskBodyIsEmpty,
  taskCellOrDash,
  taskIdLabel,
  taskPriorityClass,
  taskStatusClass,
  taskTitleLabel,
  truncateTaskTitle,
  type TaskGroup,
  type TaskItem,
  type TaskListModel,
} from "../taskListModel";
import { ownerKeyForGroup, taskGroupIdSlug } from "../taskListCollapse";
import { verbLegality } from "../taskVerbs";

// Eleven columns post-row-redesign: ID + the eight read-only data columns +
// Detail (📄 body overlay) + the Actions column (priority select · owner-reassign
// select · drop button + inline reason input).
const TASK_COLSPAN = 11;

function td( className: string, text: string ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = className;
  cell.textContent = text;
  return cell;
}

/**
 * Build the leftmost ID cell (row redesign 2026.06.29 + F1 2026.07.01). Displays
 * the compact 8-char id label; the FULL id rides the row's `data-task-id`. When
 * the row carries a real id the cell is a click-to-copy affordance: role=button
 * + tabindex + title, and `.task-col-id` gets cursor:pointer via CSS (gated on
 * [role="button"]). A row with no id (label "—") gets NO affordance — there is
 * nothing to copy — so an em-dash cell is inert.
 *
 * Ensures:
 *   - text = taskIdLabel(task) (8-char prefix, or "—" when the id is absent)
 *   - task has a non-empty id → role="button", tabindex="0", title set
 *   - task has no id → a plain cell (no interactive attributes)
 */
function renderIdCell( task: TaskItem ): HTMLTableCellElement {
  const cell = td( "task-col-id", taskIdLabel( task ) );
  if ( task.id != null && String( task.id ) !== "" ) {
    cell.setAttribute( "role", "button" );
    cell.setAttribute( "tabindex", "0" );
    cell.setAttribute( "title", "Click to copy ID" );
  }
  return cell;
}

/**
 * Build the Detail cell (row redesign 2026.06.29): a 📄 affordance opening the
 * body overlay. createElement + dataset (NO innerHTML — safe-write for the
 * store-sourced body). When the body is empty the emoji is DIMMED in place
 * (disabled / non-clickable, ruling #3) and carries no body payload.
 *
 * Ensures:
 *   - body present → `.task-detail-emoji` (role=button, tabindex=0) carrying
 *     data-task-body (the full body) + data-task-id (the 8-char id)
 *   - body empty → `.task-detail-emoji.task-detail-empty` (aria-disabled), no dataset
 */
function renderDetailCell( task: TaskItem ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = "task-col-detail";
  const emoji = document.createElement( "span" );
  emoji.textContent = "📄";
  if ( taskBodyIsEmpty( task ) ) {
    emoji.className = "task-detail-emoji task-detail-empty";
    emoji.setAttribute( "aria-disabled", "true" );
    emoji.setAttribute( "title", "No detail" );
  } else {
    emoji.className = "task-detail-emoji";
    emoji.setAttribute( "role", "button" );
    emoji.setAttribute( "tabindex", "0" );
    emoji.setAttribute( "title", "View detail" );
    // In this branch taskBodyIsEmpty(task) is false → body is a non-empty string.
    emoji.dataset.taskBody = task.body as string;
    emoji.dataset.taskId   = taskIdLabel( task );
  }
  cell.appendChild( emoji );
  return cell;
}

/**
 * Build the per-row Actions cell (Phase 2 — D2/D3 editing controls). All DOM via
 * createElement + textContent/setAttribute — NO innerHTML (table-section parse
 * safety + safe-write for store-sourced persona/priority strings). The controls
 * carry NO inline listeners: TaskListRenderer delegates `change` (selects) and
 * `click` (Submit) at the persistent container, surviving every re-render.
 *
 * Ensures:
 *   - `.task-priority-select` — P0–P3 options (EDITABLE_PRIORITIES), current
 *     priority pre-selected; reuses taskPriorityClass for the heat tint
 *   - `.task-owner-select` — reassignment roster (active personas, INCLUDING the
 *     'Sam' overflow persona — Q5); the current owner is pre-selected (prepended
 *     if not already a target so the select reflects reality); an unassigned task
 *     leads with a disabled "(unassigned)" placeholder
 *   - `.task-verb-select` + `.task-reason-input` + `.task-submit-button` — the
 *     one-select row control (2026.09.02), replacing the single Drop button
 */
function renderActionsCell( task: TaskItem, reassignTargets: ReadonlyArray<string> ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = "task-col-actions";

  // 🔴 `.task-priority-select` NAMES TWO DIFFERENT CONTROLS IN THIS PRODUCT, AND THEY
  // HAVE OPPOSITE SEMANTICS. This one — the multiplexer's — has NO Update button and
  // COMMITS ON CHANGE: `TaskListRenderer.handleControlChange` patches the row the moment
  // the value moves. The classic notifications page (`notifications.js`, symbol
  // `_priorityCell`) paints the same class name beside a `.task-priority-update` button
  // that stays disabled until the value differs from `data-original`, and patches only
  // on the click.
  //
  // ⚠️ SO A GUARD WRITTEN AGAINST ONE SAYS NOTHING ABOUT THE OTHER, and it will not look
  // wrong: the selector matches in both, the test goes green, and the renderer you meant
  // was never exercised. Measured 2026-09-03 while chasing a report of a dead Update
  // button — the built multiplexer bundle carries `task-priority-select` and carries
  // neither `task-priority-update` nor `.task-actions`, so a search for the class alone
  // cannot tell you which control it found. Name the renderer in the test, not just the
  // class.
  //
  // Guard: src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts
  //
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

  // The one-select row control (2026.09.02). What stood here was a single verb —
  // a bare "drop reason…" box and a Drop button — because Drop was the only
  // transition this card had ever offered. Rick's ruling brings the other four
  // with it: one select carrying all five verbs, one shared reason field, one
  // Submit. The date input is NOT built here; the renderer inserts it on the
  // verb change, for the two verbs that ask for a date, so a row shows a date
  // box only when a date is the thing being asked for.
  cell.appendChild( renderVerbControl( task ) );

  return cell;
}

/**
 * Build the verb select + shared reason input + Submit, given the row's status.
 *
 * The legality lives in `taskVerbs.verbLegality` and NOT here. Two derivations
 * of one rule agree until the day they do not, and the day they do not the cell
 * offers a move the server refuses — which reads to the operator as the board
 * being broken rather than as the move being illegal.
 *
 * Requires:
 *   - task carries `id` (possibly absent) and `status` (possibly absent)
 * Ensures:
 *   - returns a fragment of exactly three controls, each carrying `data-task-id`
 *   - the select leads with an un-chosen "Choose an action…" placeholder, then
 *     the five verbs in `TASK_VERBS` order — greyed, never removed, when illegal
 *   - a greyed option carries the reason in its OWN label plus `aria-disabled`
 *     and `task-action-disabled` (a disabled <option> has no tooltip to put it in)
 *   - a terminal row disables the select, the reason box and Submit themselves
 */
function renderVerbControl( task: TaskItem ): DocumentFragment {
  const frag = document.createDocumentFragment();
  const id   = task.id ?? "";
  const legality = verbLegality( task.status );
  // A row is terminal exactly when nothing is legal on it. Derived from the same
  // table the options are, rather than re-asking the status a second time.
  const isTerminal = legality.every( ( e ) => !e.enabled );

  const select = document.createElement( "select" );
  select.className = "task-verb-select";
  select.setAttribute( "aria-label", "Action" );
  select.dataset.taskId = id;

  const placeholder = document.createElement( "option" );
  placeholder.value = "";
  placeholder.textContent = "Choose an action…";
  placeholder.selected = true;
  select.appendChild( placeholder );

  for ( const entry of legality ) {
    const opt = document.createElement( "option" );
    opt.value = entry.verb;
    if ( entry.enabled ) {
      opt.textContent = entry.label;
    } else {
      opt.textContent = `${entry.label} — ${entry.why}`;
      opt.disabled = true;
      opt.className = "task-action-disabled";
      opt.setAttribute( "aria-disabled", "true" );
    }
    select.appendChild( opt );
  }
  frag.appendChild( select );

  const reasonInput = document.createElement( "input" );
  reasonInput.type = "text";
  reasonInput.className = "task-action-input task-reason-input";
  reasonInput.setAttribute( "placeholder", "reason…" );
  reasonInput.setAttribute( "aria-label", "Reason" );
  reasonInput.dataset.taskId = id;
  frag.appendChild( reasonInput );

  const submitBtn = document.createElement( "button" );
  submitBtn.type = "button";
  submitBtn.className = "task-action-btn task-submit-button";
  submitBtn.textContent = "Submit";
  submitBtn.dataset.taskId = id;
  frag.appendChild( submitBtn );

  if ( isTerminal ) {
    for ( const el of [ select, reasonInput, submitBtn ] ) {
      el.disabled = true;
      el.setAttribute( "aria-disabled", "true" );
    }
  }

  return frag;
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

  // NEW leftmost ID column — first 8 chars of the id, monospace (via CSS).
  // Click-to-copy affordance (F1 2026.07.01): a real-id cell copies the FULL
  // uuid (read from data-task-id) via the renderer's delegated click/keydown.
  tr.appendChild( renderIdCell( task ) );

  // Title cell: truncated text + the FULL title on a hover-tooltip (title attr).
  const titleCell = document.createElement( "td" );
  titleCell.className = "task-col-title";
  const fullTitle = taskTitleLabel( task );
  titleCell.textContent = truncateTaskTitle( fullTitle );
  titleCell.setAttribute( "title", fullTitle );
  tr.appendChild( titleCell );

  // Detail column (F2 2026.07.01: repositioned 10→3, directly after Title and
  // before Class): 📄 body-overlay affordance. renderDetailCell is unchanged.
  tr.appendChild( renderDetailCell( task ) );

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
    [ "task-col-id", "ID" ],
    [ "task-col-title", "Title" ],
    [ "task-col-detail", "Detail" ],
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
