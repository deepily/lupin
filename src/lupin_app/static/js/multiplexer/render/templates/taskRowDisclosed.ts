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
  truncateTaskTitle,
  taskCellOrDash,
  taskStatusClass,
  taskPriorityClass,
  formatTaskBlockedBy,
  formatChaseTime,
  type TaskItem,
} from "../taskListModel";
import { ROW_SCHEMA, type RowField } from "../rowSchema";
import { renderDiscloseCell, renderControlsRow, renderErrorStripe } from "./rowDisclosure";
import { taskFilerLabel } from "../holdingAreaModel";

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
    const full = taskTitleLabel( task );
    cell.textContent = truncateTaskTitle( full );
    cell.setAttribute( "title", full );
    return cell;
  }
  if ( field === "status" ) {
    const dot = document.createElement( "span" );
    dot.className = "task-status-dot";
    cell.appendChild( dot );
    cell.appendChild( document.createTextNode( task.status || "unknown" ) );
    return cell;
  }
  if ( field === "class" ) {
    const badge = document.createElement( "span" );
    badge.className   = `task-class-badge task-class-${ task.item_class || "task" }`;
    badge.textContent = task.item_class || "task";
    cell.appendChild( badge );
    return cell;
  }
  if ( field === "priority" ) {
    cell.className   = `task-col-priority ${ taskPriorityClass( task.priority ) }`.trim();
    cell.textContent = taskCellOrDash( task.priority );
    return cell;
  }
  cell.textContent = taskIdLabel( task );   // id
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
  task     : TaskItem,
  ianaZone : string | null | undefined,
): Partial<Record<RowField, string>> {
  return {
    blocked     : taskCellOrDash( formatTaskBlockedBy( task.blocked_by ) ),
    chase       : formatChaseTime( task.next_chase_ts, ianaZone ),
    accountable : taskCellOrDash( task.accountable_manager ),
    filer       : taskFilerLabel( task ),
    project     : taskCellOrDash( task.project ),
    detail      : task.body ? "📄" : "—",
    actions     : "",
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
  task     : TaskItem,
  pane     : RowPane,
  ianaZone : string | null | undefined,
): DocumentFragment {
  const statusClass = taskStatusClass( task.status );
  const taskId      = task.id ?? "";
  const frag        = document.createDocumentFragment();

  const tr = document.createElement( "tr" );
  // The epic board's rows carry `epic-row` in the JS card; the other two panes
  // carry no extra class.
  const paneClass = pane === "epic-board" ? " epic-row" : "";
  tr.className = `task-row${ paneClass } ${ statusClass }`.trim();
  tr.setAttribute( "data-task-id", taskId );

  ROW_SCHEMA.line1.forEach( ( field ) => tr.appendChild( renderVisibleCell( field, task ) ) );
  tr.appendChild( renderDiscloseCell( taskId ) );

  frag.appendChild( tr );
  frag.appendChild( renderControlsRow( taskId, statusClass, disclosedValues( task, ianaZone ) ) );
  frag.appendChild( renderErrorStripe( taskId ) );
  return frag;
}
