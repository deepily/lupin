/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The disclosed task row — the THREE <tr> elements the JS card emits per task.
//
// Reproduces _renderRow (notifications.js:10092) as OBSERVATIONAL EQUIVALENCE.
//
// 🔴 ONE RENDERER, ALL THREE ROW PANES. The JS card shares _renderRow between
// the task list, the holding area and the epic board deliberately, and Rick's
// reason is in its docstring: "moving between the epic board and the task list
// meant re-parsing the layout." So CELL-FOR-CELL ROW IDENTITY IS A BEHAVIOURAL
// REQUIREMENT, not a refactoring convenience — and this file is where the TS
// side keeps that promise. Do NOT give a pane its own row renderer.
//
// ⚠️ Sharing this INSIDE the TS client is not a breach of Rick's no-code-reuse
// ruling. That ruling separates the two CLIENTS (JS from TS); three copies of
// a row inside one client is the exact drift the legacy card already killed.
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §2.2, §5a

import {
  taskIdLabel,
  taskTitleLabel,
  taskCellOrDash,
  taskClassSlug,
  taskIsParked,
  taskStatusClass,
  taskPriorityClass,
  formatTaskBlockedBy,
  formatChaseTime,
  type TaskItem,
} from "../taskListModel";
import { ROW_SCHEMA, type RowField } from "../rowSchema";
import { renderDiscloseCell, renderControlsRow, renderErrorStripe } from "./rowDisclosure";
import { taskFilerLabel } from "../holdingAreaModel";
import { renderActionsContent, renderDetailContent } from "./taskRowControls";

/** The pane a row is rendered into — decides only the row's own extra class. */
export type RowPane = "task-list" | "holding-area" | "epic-board";

/**
 * The VISIBLE cell for one line-1 field. Pure.
 *
 * ⚠️ The title cell alone also carries a `title=` attribute holding the FULL
 * title, because the visible text is truncated.
 */
function renderVisibleCell( field: RowField, task: TaskItem ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = `task-col-${ field }`;

  if ( field === "title" ) {
    // 🔴 THE WHOLE TITLE, NEVER A CHARACTER CAP. The JS card renders the full
    // title and bounds it VISUALLY with a two-line clamp; `_taskTitleLabel`
    // truncates nothing, and its ROW_SCHEMA note says so in as many words: "the
    // title is the WHOLE title — no cap, no ellipsis". A character cap loses text
    // the clamp merely hides.
    //
    // 🔴 THE SPAN IS LOAD-BEARING — DO NOT UNWRAP IT. `-webkit-line-clamp` does
    // not bind on a `<td>` (`display: table-cell`), and neither does `max-height`.
    // Measured by the JS authors on the live page 2026-09-03: the cell carried
    // computed `max-height: 39px` and `overflow: hidden` and still RENDERED 90px,
    // with clientHeight == scrollHeight (51/51) proving nothing was clamped; the
    // span, same declarations, bound at 39px against 78px of content.
    // ⚠️ Do NOT re-derive that from the computed `display` value — both compute
    // `flow-root`, two people already reasoned from it, and it is a red herring.
    //
    // ⚠️ THE `title=` TOOLTIP STAYS ON THE `<td>`, so a clamped title is still
    // recoverable on hover. A clamp that hides text with no way back would be the
    // character cap again wearing a different mechanism.
    const full = taskTitleLabel( task );
    const span = document.createElement( "span" );
    span.className   = "task-title";
    span.textContent = full;
    cell.appendChild( span );
    cell.setAttribute( "title", full );
    return cell;
  }
  if ( field === "status" ) {
    const dot = document.createElement( "span" );
    dot.className = "task-status-dot";
    cell.appendChild( dot );
    cell.appendChild( document.createTextNode( task.status || "unknown" ) );
    // 🔴 PARKED ROWS ARE SHOWN, DIMMED AND BADGED — NEVER DROPPED (Rick 2026-07-22).
    // The badge is what stops a deferred row reading as an ordinary open one.
    if ( taskIsParked( task ) ) {
      const badge = document.createElement( "span" );
      badge.className   = "task-parked-badge";
      badge.setAttribute( "title", task.park_reason ?? "" );
      badge.textContent = "parked";
      cell.appendChild( badge );
    }
    return cell;
  }
  if ( field === "class" ) {
    const badge = document.createElement( "span" );
    // ⚠️ The TEXT is the raw value; the CLASS NAME is the stripped slug. An
    // item_class with a space would otherwise split into two class names.
    badge.className   = `task-class-badge task-class-${ taskClassSlug( task.item_class ) }`;
    badge.textContent = task.item_class || "task";
    cell.appendChild( badge );
    return cell;
  }
  if ( field === "priority" ) {
    cell.className   = `task-col-priority ${ taskPriorityClass( task.priority ) }`.trim();
    cell.textContent = taskCellOrDash( task.priority );
    return cell;
  }
  // id — CLICK-TO-COPY. The cell shows 8 chars and the clipboard gets the full
  // 36: copying the RENDERED text hands back a string that looks right and fails
  // at the paste, silently, in whatever tool it was pasted into (Rick, dbb4c187:
  // "I want the ID to be copy upon click... Want it to be 1 click").
  //
  // ⚠️ THE AFFORDANCE SITS ON THE CELL, NOT ON A SPAN. The JS card wraps it in
  // `.task-id-copy` with `data-task-full-id` because it writes via innerHTML;
  // TaskListRenderer's delegated handler instead matches
  // `.task-col-id[role="button"]` and reads the FULL id off the row's
  // `data-task-id`. Same observable behaviour, existing tested wiring — and
  // Rick's ruling is observational equivalence, not identical markup.
  //
  // An idless row (label "—") gets NO affordance: there is nothing to copy.
  cell.textContent = taskIdLabel( task );
  if ( task.id != null && String( task.id ) !== "" ) {
    cell.setAttribute( "role", "button" );
    cell.setAttribute( "tabindex", "0" );
    cell.setAttribute( "title", "Click to copy ID" );
  }
  return cell;
}

/**
 * The already-formatted display strings for the DISCLOSED fields. Pure.
 *
 * ⚠️ `chase` needs the resolved IANA zone. The holding area DOES get one; the
 * epic board deliberately does NOT — its JS wrapper passes null so next-chase
 * formats exactly as it did before that pane had a zone. Not an omission; do
 * not "fix" it in the port.
 */
export function disclosedValues(
  task            : TaskItem,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
): Partial<Record<RowField, string | Node>> {
  return {
    blocked     : taskCellOrDash( formatTaskBlockedBy( task.blocked_by ) ),
    chase       : formatChaseTime( task.next_chase_ts, ianaZone ),
    accountable : taskCellOrDash( task.accountable_manager ),
    filer       : taskFilerLabel( task ),
    project     : taskCellOrDash( task.project ),
    // 🔴 LINE 3 IS CONTROLS, NOT TEXT. These two were strings — "📄" and "" —
    // which rendered the glyph as dead text and the entire nine-control action
    // group as an em-dash. Measured against notifications.js:10086-10089, where
    // `detail` takes `detailHtml` (role=button, data-task-body) and `actions`
    // takes `_taskActionsCell( task )` (priority · owner · verb · reason ·
    // Submit). A row missing them is the right shape with nothing to click.
    detail      : renderDetailContent( task ),
    actions     : renderActionsContent( task, reassignTargets ),
  };
}

/**
 * The three rows one task emits: the visible row, its hidden controls row and
 * its hidden error stripe.
 *
 * Ensures:
 *   - the visible row carries `task-row`, the pane's extra class and the
 *     status class, plus `data-task-id`
 *   - one `<td class="task-col-{field}">` per ROW_SCHEMA.line1 IN ORDER, then
 *     the disclosure cell — so the cell count always equals rowWidth()
 *   - the controls row and error stripe are both HIDDEN and both span
 *     rowWidth() columns
 *   - identical cell-for-cell across every pane; only the row's extra class
 *     differs
 */
export function renderDisclosedRow(
  task            : TaskItem,
  pane            : RowPane,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
): DocumentFragment {
  const statusClass = taskStatusClass( task.status );
  const taskId      = task.id ?? "";
  const frag        = document.createDocumentFragment();

  const tr = document.createElement( "tr" );
  // The epic board's rows carry `epic-row` in the JS card; the other two panes
  // carry no extra class.
  const paneClass   = pane === "epic-board" ? " epic-row" : "";
  const parkedClass = taskIsParked( task ) ? " task-row-parked" : "";
  tr.className = `task-row${ paneClass } ${ statusClass }${ parkedClass }`.trim();
  tr.setAttribute( "data-task-id", taskId );

  ROW_SCHEMA.line1.forEach( ( field ) => tr.appendChild( renderVisibleCell( field, task ) ) );
  tr.appendChild( renderDiscloseCell( taskId ) );

  frag.appendChild( tr );
  frag.appendChild( renderControlsRow( taskId, statusClass, disclosedValues( task, ianaZone, reassignTargets ) ) );
  frag.appendChild( renderErrorStripe( taskId ) );
  return frag;
}
