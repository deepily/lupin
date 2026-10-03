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
// ⚠️ THIS PANE IS DIV-PER-GROUP, NOT TBODY-PER-GROUP. Each filer gets its own
// <div> wrapping its own <table>, because the group header carries batch
// controls a <tr> header could not hold cleanly.
//
// 🔴 EACH GROUP IS AN ACCORDION, COLLAPSED BY DEFAULT (Rick, row 52142a84,
// 2026-09-24): "when the holding area task list loads I want each individual
// persona to have all of their tasks hidden, yet displayable by a click on the
// bar containing the persona name". The collapse is a `.collapsed` class on the
// group <div> plus aria-expanded on the header; legacy renders the same markup.
// Which groups are open is the RENDERER's state, passed in here — this template
// only paints it.
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

import { holdingPlanId, type HeldFilerGroup, type HeldPlan } from "../holdingAreaModel";
import type { TaskItem } from "../taskListModel";
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

/** The group header's tooltip. Carbon copy of notifications.js `_renderHoldingAreaGroup`. */
export const HOLDING_GROUP_TOGGLE_TITLE = "Click to show or hide this filer's held rows";

/** The chevron glyph for a group's open state — ▼ open, ▶ closed, as the task list's. */
export function holdingGroupChevron( expanded: boolean ): string {
  return expanded ? "▼" : "▶";
}

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
function renderGroupHeader( group: HeldFilerGroup, expanded: boolean ): HTMLDivElement {
  const header = document.createElement( "div" );
  header.className = "holding-area-group-header";
  header.setAttribute( "role", "button" );
  header.setAttribute( "tabindex", "0" );
  header.setAttribute( "aria-expanded", expanded ? "true" : "false" );
  header.title = HOLDING_GROUP_TOGGLE_TITLE;

  const chevron = document.createElement( "span" );
  chevron.className   = "holding-area-group-chevron";
  chevron.setAttribute( "aria-hidden", "true" );
  chevron.textContent = holdingGroupChevron( expanded );
  header.appendChild( chevron );

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

/** A table of held rows in the shared row shape — the filer's own, or one plan's. */
function renderRowTable(
  tasks           : ReadonlyArray<TaskItem>,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string>,
): HTMLTableElement {
  const table = document.createElement( "table" );
  table.className = "task-list-table holding-area-table";
  table.appendChild( renderRowTableHead() );

  const tbody = document.createElement( "tbody" );
  for ( const task of tasks ) {
    tbody.appendChild( renderDisclosedRow( task, "holding-area", ianaZone, reassignTargets ) );
  }
  table.appendChild( tbody );
  return table;
}

/** The plan group header's tooltip. Carbon copy of notifications.js `_renderHoldingPlanGroup`. */
export const HOLDING_PLAN_TOGGLE_TITLE = "Click to show or hide the rows of this plan";

/** The plan approve button's label. Carbon copy of notifications.js `_renderHoldingPlanGroup`. */
export function holdingPlanApproveLabel( n: number ): string {
  return `Approve all ${ n }`;
}

/** The plan approve button's tooltip. Carbon copy of notifications.js `_renderHoldingPlanGroup`. */
export function holdingPlanApproveTitle( n: number ): string {
  return `Approve the ${ n } rows listed under this plan — reversible, a row approved by mistake can be demoted straight back`;
}

/** The plan group's chevron glyph — ▼ open, ▶ closed, as the filer group's. */
export function holdingPlanChevron( expanded: boolean ): string {
  return holdingGroupChevron( expanded );
}

/**
 * One plan sub-group inside a filer's group: a header (chevron, "Plan: <title>", count,
 * ONE approve control, status span) and a table of exactly the plan's rows.
 *
 * ⚠️ THE IDS RIDE ON THE BUTTON (`data-task-ids`), built from the same rows as the table
 * beneath it. The press acts on what the operator was shown, and a row a peer has since
 * moved is refused by the server and counted as refused, never skipped.
 *
 * Ensures:
 *   - returns a `.holding-plan-group` <div> carrying data-filer and data-plan, and carrying
 *     `.collapsed` exactly when expanded is false
 *   - the label reads "Plan: <title>"; the raw key is only the tooltip and a data attribute
 *   - the header is a keyboard-reachable button whose aria-expanded and chevron agree with expanded
 *   - the button, the label and the status span carry the plan's identity; the button's label
 *     and its data-task-ids carry the same N, the number of rows in the table
 */
export function renderHoldingPlanGroup(
  filer           : string,
  plan            : HeldPlan,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string>,
  expanded        : boolean,
): HTMLDivElement {
  const wrapper = document.createElement( "div" );
  wrapper.className     = expanded ? "holding-plan-group" : "holding-plan-group collapsed";
  wrapper.dataset.filer = filer;
  wrapper.dataset.plan  = plan.key;

  const header = document.createElement( "div" );
  header.className = "holding-plan-header";
  header.setAttribute( "role", "button" );
  header.setAttribute( "tabindex", "0" );
  header.setAttribute( "aria-expanded", expanded ? "true" : "false" );
  header.title = HOLDING_PLAN_TOGGLE_TITLE;

  const chevron = document.createElement( "span" );
  chevron.className   = "holding-plan-chevron";
  chevron.setAttribute( "aria-hidden", "true" );
  chevron.textContent = holdingPlanChevron( expanded );
  header.appendChild( chevron );

  const label = document.createElement( "span" );
  label.className   = "holding-plan-label";
  label.textContent = `Plan: ${ plan.title }`;
  label.title       = plan.key;
  header.appendChild( label );

  const countEl = document.createElement( "span" );
  countEl.className   = "holding-plan-count";
  countEl.textContent = String( plan.ids.length );
  header.appendChild( countEl );

  const btn = document.createElement( "button" );
  btn.type      = "button";
  btn.className = "task-action-btn holding-plan-approve-all";
  btn.dataset.filer   = filer;
  btn.dataset.plan    = plan.key;
  btn.dataset.taskIds = plan.ids.join( "," );
  btn.title       = holdingPlanApproveTitle( plan.ids.length );
  btn.textContent = holdingPlanApproveLabel( plan.ids.length );
  header.appendChild( btn );

  const status = document.createElement( "span" );
  status.className = "holding-plan-status";
  status.dataset.filer = filer;
  status.dataset.plan  = plan.key;
  header.appendChild( status );

  wrapper.appendChild( header );
  wrapper.appendChild( renderRowTable( plan.tasks, ianaZone, reassignTargets ) );
  return wrapper;
}

/**
 * One filer's group: the header bar carrying the batch controls, then that
 * filer's held rows in their own table.
 *
 * Requires:
 *   - group is one entry from groupHeldRowsByFiler
 *   - ianaZone is the IANA zone for next-chase cells, or null/undefined
 *   - expanded says whether this filer's rows are shown; false by default
 * Ensures:
 *   - returns a `.holding-area-group` <div> carrying data-filer, and carrying
 *     `.collapsed` exactly when expanded is false
 *   - the header is a keyboard-reachable button whose aria-expanded and chevron
 *     agree with expanded
 *   - the header carries the filer label, the group count, batch approve,
 *     batch won't-fix, the batch reason box and the status span — all five
 *     interactive/keyed elements carrying data-filer
 *   - the table is `.task-list-table.holding-area-table` with the SHARED
 *     ROW_SCHEMA head, so its column count cannot drift from the row's
 *   - each plan sub-group (see renderHoldingPlanGroup) is listed first, then the
 *     filer's ungrouped rows in the filer's own table, which is omitted when there
 *     are none
 *   - each task emits the shared three-row disclosed row with pane
 *     "holding-area"
 */
export function renderHoldingAreaGroup(
  group           : HeldFilerGroup,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
  expanded        : boolean = false,
  expandedPlans   : ReadonlySet<string> = new Set(),
): HTMLDivElement {
  const wrapper = document.createElement( "div" );
  wrapper.className = expanded ? "holding-area-group" : "holding-area-group collapsed";
  wrapper.dataset.filer = group.filer;

  wrapper.appendChild( renderGroupHeader( group, expanded ) );

  for ( const plan of group.plans ) {
    wrapper.appendChild( renderHoldingPlanGroup(
      group.filer, plan, ianaZone, reassignTargets, expandedPlans.has( holdingPlanId( group.filer, plan.key ) ) ) );
  }
  if ( group.ungrouped.length > 0 ) {
    wrapper.appendChild( renderRowTable( group.ungrouped, ianaZone, reassignTargets ) );
  }

  return wrapper;
}

/**
 * Every filer group, in the model's order, as a fragment the renderer drops
 * into the pane container.
 *
 * Ensures:
 *   - one `.holding-area-group` per input group, in order
 *   - a group is open exactly when its filer is in expandedFilers — every
 *     group starts collapsed (row 52142a84)
 *   - an empty model yields an EMPTY fragment — the "nothing waiting" message
 *     is the renderer's job, not this template's, because an empty holding
 *     area is a real state that must say so rather than paint blank
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the multi-line exported function-declaration line — c8 reports ONE location (173:16-40, the identifier itself), not the two a real conditional carries; every internal branch is exercised.
export function renderHoldingAreaGroups(
  groups          : ReadonlyArray<HeldFilerGroup>,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string> = [],
  expandedFilers  : ReadonlySet<string> = new Set(),
  expandedPlans   : ReadonlySet<string> = new Set(),
): DocumentFragment {
  const frag = document.createDocumentFragment();
  for ( const group of groups ) {
    frag.appendChild( renderHoldingAreaGroup( group, ianaZone, reassignTargets, expandedFilers.has( group.filer ), expandedPlans ) );
  }
  return frag;
}

