/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Holding-area card — group template (row 87812328).
//
// The DOM half of the holding-area pane: rows filed but not yet cleared to
// start, grouped by FILER, each group carrying batch approve / batch won't-fix.
// Built via document.createElement + .textContent / .setAttribute — NO
// innerHTML — for the same two reasons taskListTable.ts gives: table-section
// parsing rules drop stray <tr>/<td> outside a <table> ancestor, and
// createElement is safe-write for store-sourced strings.
//
// ⚠️ THIS PANE IS DIV-PER-GROUP, NOT TBODY-PER-GROUP, AND THAT DIVERGENCE IS
// DELIBERATE. The task list and the epic board group rows into <tbody
// class="task-group"> because a click on their group header toggles a collapse;
// this pane HAS NO ACCORDION — notifications.js:12787 says so in as many words,
// "IT IS NOT AN ACCORDION LISTENER" — so each filer gets its own <div> wrapping
// its own <table>. Normalising this to the sibling panes' shape would invent a
// collapse seam the legacy pane does not have.
//
// ⚠️ THE ROW IS THE SHARED ONE. renderDisclosedRow is used verbatim with pane
// "holding-area"; the JS card shares _renderRow across all three panes because
// cell-for-cell row identity between panes is a behavioural requirement Rick
// asked for, not a convenience. Do not give this pane a row of its own.
//
// 🔴 THE TWO BATCH TOOLTIPS ARE CARBON-COPIED FROM notifications.js AND ARE
// PINNED AGAINST THAT FILE, NOT AGAINST A LITERAL. Both EMBED the filer label,
// so they are templates rather than constants — a renderer that dropped the
// name would still satisfy a prefix check. See
// src/tests/unit/multiplexer/render/holding_area_table.test.ts, which slices
// both strings out of the legacy source and compares the substituted result.

import type { HeldFilerGroup } from "../holdingAreaModel";
import { renderRowTableHead } from "./rowDisclosure";
import { renderDisclosedRow } from "./taskRowDisclosed";

/**
 * The batch-approve tooltip for one filer. Carbon copy of
 * notifications.js `_renderHoldingAreaGroup`.
 *
 * ⚠️ BATCH APPROVE CARRIES NO CONFIRM, and the tooltip is where that is
 * justified to the operator: it is the non-destructive direction, so an
 * over-approved row can be demoted straight back.
 */
export function holdingApproveAllTitle( filer: string ): string {
  return `Approve every row ${ filer } filed — reversible, a row approved by mistake can be demoted straight back`;
}

/**
 * The batch won't-fix tooltip for one filer. Carbon copy of
 * notifications.js `_renderHoldingAreaGroup`.
 *
 * 🔴 THE REASON IS PER GROUP, NOT PER ROW, AND THE TOOLTIP SAYS SO. Every row
 * closed by one press gets the SAME justification — honest for the case the
 * batch exists to serve, dishonest for a mixed group. The per-row control is
 * the right tool whenever the reasons differ; this one is deliberately the
 * blunt instrument and is labelled as such.
 */
export function holdingWontFixAllTitle( filer: string ): string {
  return `Close every row ${ filer } filed as won't-fix. TERMINAL, and every row gets the SAME reason — use the per-row control when the reasons differ`;
}

/** The batch reason box's placeholder. Carbon copy. */
export const HOLDING_WONT_FIX_REASON_PLACEHOLDER = "one reason, applied to every row below…";

/** The batch reason box's accessible name. Carbon copy. */
export const HOLDING_WONT_FIX_REASON_ARIA_LABEL = "Batch won't-fix reason";

function batchButton( cls: string, filer: string, label: string, title: string ): HTMLButtonElement {
  const btn = document.createElement( "button" );
  btn.type      = "button";
  btn.className = `task-action-btn ${ cls }`;
  btn.dataset.filer = filer;
  btn.title     = title;
  btn.textContent = label;
  return btn;
}

/**
 * One filer's group header: the label, the count, and the three batch controls
 * plus the per-group status span the handler writes into.
 *
 * ⚠️ EVERY CONTROL CARRIES data-filer, INCLUDING THE STATUS SPAN. The handler
 * finds a group's rows by that attribute — the batch reason is keyed by FILER,
 * not by task id, which is why the row-level `data-task-id` lookup the other
 * panes use does not reach these.
 */
function renderGroupHeader( group: HeldFilerGroup ): HTMLDivElement {
  const header = document.createElement( "div" );
  header.className = "holding-area-group-header";

  const filerEl = document.createElement( "span" );
  filerEl.className   = "holding-area-filer";
  filerEl.textContent = group.filer;
  header.appendChild( filerEl );

  const countEl = document.createElement( "span" );
  countEl.className   = "holding-area-group-count";
  countEl.textContent = String( group.tasks.length );
  header.appendChild( countEl );

  header.appendChild( batchButton(
    "holding-approve-all", group.filer, "Approve all", holdingApproveAllTitle( group.filer ) ) );
  header.appendChild( batchButton(
    "holding-wont-fix-all", group.filer, "Won't fix all", holdingWontFixAllTitle( group.filer ) ) );

  const reason = document.createElement( "input" );
  reason.type        = "text";
  reason.className   = "task-action-input holding-wont-fix-all-reason";
  reason.dataset.filer = group.filer;
  reason.placeholder = HOLDING_WONT_FIX_REASON_PLACEHOLDER;
  reason.setAttribute( "aria-label", HOLDING_WONT_FIX_REASON_ARIA_LABEL );
  header.appendChild( reason );

  const status = document.createElement( "span" );
  status.className = "holding-area-group-status";
  status.dataset.filer = group.filer;
  header.appendChild( status );

  return header;
}

/**
 * One filer's group: the header bar carrying the batch controls, then that
 * filer's held rows in their own table.
 *
 * Requires:
 *   - group is one entry from groupHeldRowsByFiler
 *   - ianaZone is the IANA zone for next-chase cells, or null/undefined
 * Ensures:
 *   - returns a `.holding-area-group` <div> carrying data-filer
 *   - the header carries the filer label, the group count, batch approve,
 *     batch won't-fix, the batch reason box and the status span — all five
 *     interactive/keyed elements carrying data-filer
 *   - the table is `.task-list-table.holding-area-table` with the SHARED
 *     ROW_SCHEMA head, so its column count cannot drift from the row's
 *   - each task emits the shared three-row disclosed row with pane
 *     "holding-area"
 */
export function renderHoldingAreaGroup(
  group           : HeldFilerGroup,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
): HTMLDivElement {
  const wrapper = document.createElement( "div" );
  wrapper.className = "holding-area-group";
  wrapper.dataset.filer = group.filer;

  wrapper.appendChild( renderGroupHeader( group ) );

  const table = document.createElement( "table" );
  table.className = "task-list-table holding-area-table";
  table.appendChild( renderRowTableHead() );

  const tbody = document.createElement( "tbody" );
  for ( const task of group.tasks ) {
    tbody.appendChild( renderDisclosedRow( task, "holding-area", ianaZone, reassignTargets ) );
  }
  table.appendChild( tbody );
  wrapper.appendChild( table );

  return wrapper;
}

/**
 * Every filer group, in the model's order, as a fragment the renderer drops
 * into the pane container.
 *
 * Ensures:
 *   - one `.holding-area-group` per input group, in order
 *   - an empty model yields an EMPTY fragment — the "nothing waiting" message
 *     is the renderer's job, not this template's, because an empty holding
 *     area is a real state that must say so rather than paint blank
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the multi-line exported function-declaration line — c8 reports ONE location (173:16-40, the identifier itself), not the two a real conditional carries; every internal branch is exercised.
export function renderHoldingAreaGroups(
  groups          : ReadonlyArray<HeldFilerGroup>,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
): DocumentFragment {
  const frag = document.createDocumentFragment();
  for ( const group of groups ) {
    frag.appendChild( renderHoldingAreaGroup( group, ianaZone, reassignTargets ) );
  }
  return frag;
}
