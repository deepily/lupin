/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Row disclosure — the ellipsis toggle, the controls row and the error stripe.
//
// Reproduces the in-service JS card's _disclosureToggle (notifications.js:10175)
// and the three-row emission of _renderRow (:10092) as OBSERVATIONAL
// EQUIVALENCE, not shared code.
//
// ⭐ RICK'S SPEC, quoted in the JS source: "an ellipsis right-justified ON THE
// TITLE LINE indicating hidden functionality; clicking it discloses the
// controls as ONE narrow row spanning the full width of the item; that second
// row is NOT displayed by default."
//
// 🔴 THE STATE LIVES IN `aria-expanded`, NOT IN A CSS CLASS. The JS docstring:
// "A disclosure that only exists in CSS is invisible to a keyboard user, who
// then has no way to reach any of these verbs at all." The `hidden` attribute
// on the controls row carries the VISUAL half. BOTH ARE REQUIRED, and a port
// that keeps only one of them looks correct to a sighted mouse user while
// being unreachable by keyboard, or reachable but never painted.
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §5a

import { ownLookup } from "../../shared/ownLookup";

import { ROW_SCHEMA, rowWidth, rowFieldLabel, disclosedFields, type RowField } from "../rowSchema";

/** The ellipsis character the toggle renders. Verbatim from the JS card. */
export const DISCLOSE_GLYPH = "⋯";   // ⋯ MIDLINE HORIZONTAL ELLIPSIS

/** The toggle's title attribute. Verbatim from the JS card. */
export const DISCLOSE_TITLE = "Show row controls";

/**
 * The disclosure toggle button. Pure (creates, does not attach).
 *
 * Ensures:
 *   - class `task-disclose-button`, `data-task-id` (or "" when absent)
 *   - `aria-expanded="false"` — the accessible half of the state
 *   - `type="button"` so it never submits an enclosing form
 */
export function renderDiscloseToggle( taskId: string | null | undefined ): HTMLButtonElement {
  const btn = document.createElement( "button" );
  btn.type      = "button";
  btn.className = "task-disclose-button";
  btn.setAttribute( "data-task-id", taskId ?? "" );
  btn.setAttribute( "aria-expanded", "false" );
  btn.setAttribute( "title", DISCLOSE_TITLE );
  btn.textContent = DISCLOSE_GLYPH;
  return btn;
}

/**
 * The cell that carries the toggle, right-justified on the title line.
 *
 * Ensures:
 *   - class `task-col-disclose`, holding exactly the toggle
 */
export function renderDiscloseCell( taskId: string | null | undefined ): HTMLTableCellElement {
  const td = document.createElement( "td" );
  td.className = "task-col-disclose";
  td.appendChild( renderDiscloseToggle( taskId ) );
  return td;
}

/** One label/value pair inside a disclosed line. */
export interface DisclosedValue {
  field : RowField;
  value : string | Node;
}

/**
 * One disclosed field: label + value, both in their own spans so the CSS can
 * lay them out without parsing text. Pure.
 *
 * 🔴 A VALUE MAY BE A NODE, AND THAT IS NOT A CONVENIENCE. Line 3 of the schema
 * is `detail` and `actions`, and in the JS card both are MARKUP — an
 * interactive 📄 affordance and the nine-control action group
 * (notifications.js:10086-10089, where `parts.detail.html` and
 * `parts.actions.html` are spliced in as html). A string-only field renders the
 * word "—" where the legacy card renders controls, and NOTHING ABOUT THE ROW
 * LOOKS WRONG when it does — same shape, same labels, no controls.
 *
 * Ensures:
 *   - a string value is written with textContent (safe-write, never parsed)
 *   - a Node value is APPENDED, so its listeners, datasets and disabled state
 *     survive intact
 */
function renderDisclosedField( field: RowField, value: string | Node ): HTMLDivElement {
  const wrap = document.createElement( "div" );
  wrap.className = `task-disclosed-field task-col-${ field }`;
  const label = document.createElement( "span" );
  label.className   = "task-disclosed-label";
  label.textContent = rowFieldLabel( field );
  const val = document.createElement( "span" );
  val.className   = "task-disclosed-value";
  if ( typeof value === "string" ) {
    val.textContent = value;
  } else {
    val.appendChild( value );
  }
  wrap.appendChild( label );
  wrap.appendChild( val );
  return wrap;
}

/**
 * The controls row — ONE narrow row spanning the full width, hidden by default.
 *
 * 🔴 THE COLSPAN COMES FROM rowWidth(), NEVER A LITERAL. A stale colspan does
 * not look broken: the table still renders perfectly while this row quietly
 * stops spanning it.
 *
 * Requires:
 *   - values maps each disclosed field to its already-formatted display string
 *
 * Ensures:
 *   - class `task-controls-row` + the row's status class
 *   - `data-controls-for` = the task id, and the `hidden` attribute SET
 *   - one `<td colspan="{rowWidth()}">` holding one
 *     `.task-disclosed-line` per disclosed line, in schema order
 *   - a field with no supplied value renders an em-dash, never "undefined"
 */
export function renderControlsRow(
  taskId      : string | null | undefined,
  statusClass : string,
  values      : Partial<Record<RowField, string | Node>>,
): HTMLTableRowElement {
  const tr = document.createElement( "tr" );
  tr.className = `task-controls-row ${ statusClass }`.trim();
  tr.setAttribute( "data-controls-for", taskId ?? "" );
  tr.hidden = true;

  const cell = document.createElement( "td" );
  cell.setAttribute( "colspan", String( rowWidth() ) );

  // The JS card wraps BOTH lines in one `.task-disclosed` container
  // (notifications.js: `<div class="task-disclosed">${discLine(line2)}${discLine(line3)}</div>`).
  // It is a layout seam, not decoration — appending the lines straight into the
  // <td> gives the same fields with nothing for a rule to bind to.
  const disclosed = document.createElement( "div" );
  disclosed.className = "task-disclosed";

  disclosedFields().forEach( ( line, idx ) => {
    const lineEl = document.createElement( "div" );
    lineEl.className = `task-disclosed-line task-disclosed-line--${ idx === 0 ? "fields" : "actions" }`;
    line.forEach( ( field ) => {
      lineEl.appendChild( renderDisclosedField(
      field, ownLookup<string | Node>( values as Record<string, string | Node>, field, "—" ) ) );
    } );
    disclosed.appendChild( lineEl );
  } );

  cell.appendChild( disclosed );

  tr.appendChild( cell );
  return tr;
}

/**
 * The per-row error stripe — hidden until a verb fails on this row.
 *
 * Ensures:
 *   - class `task-row-error-stripe`, `data-error-for` = the task id, `hidden` SET
 *   - one empty `<td colspan="{rowWidth()}">`
 */
export function renderErrorStripe( taskId: string | null | undefined ): HTMLTableRowElement {
  const tr = document.createElement( "tr" );
  tr.className = "task-row-error-stripe";
  tr.setAttribute( "data-error-for", taskId ?? "" );
  tr.hidden = true;
  const cell = document.createElement( "td" );
  cell.setAttribute( "colspan", String( rowWidth() ) );
  tr.appendChild( cell );
  return tr;
}

/**
 * Show a row's refusal stripe with `message`, or CLEAR it when `message` is empty.
 *
 * Moved out of `TaskListRenderer` (operator-state spec ruling 6) so the Task List,
 * Holding Area and Epic Board fill the stripe the shared row already paints through
 * ONE function, and operator-state restore can re-show a refusal in any of them.
 *
 * Requires:
 *   - `pane` is the pane container holding the row
 *
 * Ensures:
 *   - the stripe carrying `data-error-for === id` INSIDE `pane` gets `message` in its cell
 *   - hidden iff `message` is empty; a shown stripe carries `role="alert"`, `aria-live="polite"`
 *   - no matching stripe in `pane` is a no-op
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderRowError( pane: ParentNode, id: string, message: string ): void {
  // 🔴 THE STRIPE IS RENDERED WITH THE ROW, NOT GROWN HERE. This used to append
  // a fresh `<td class="task-row-error-stripe">` into the `.task-row`; the row
  // template now emits a hidden `<tr class="task-row-error-stripe"
  // data-error-for=…>` per task, spanning rowWidth(). Two mechanisms wearing
  // one class name is drift with a start date, so this fills the one that
  // exists rather than adding a second.
  //
  // 🔴 SCOPED TO THIS PANE, and that is load-bearing rather than tidy. The JS
  // card's own docstring: a row rendered in two panes has two stripes carrying
  // the same `data-error-for`, and an unscoped query always revealed the first
  // — "a refusal shown in a pane the operator is not looking at has not been
  // shown: from where they sit the control simply did nothing."
  //
  // ⚠️ NO SELECTOR INTERPOLATION — a task id is server data, and CSS.escape
  // produces valid escapes that happy-dom's selector parser then rejects.
  // Comparing the attribute has no escaping question at all.
  const stripe = Array.from( pane.querySelectorAll<HTMLElement>( ".task-row-error-stripe" ) )
    .find( ( el ) => el.getAttribute( "data-error-for" ) === id ) ?? null;
  if ( stripe === null ) return;

  const cell = stripe.querySelector( "td" );
  /* c8 ignore next */ // defensive: renderErrorStripe always emits exactly one <td>.
  if ( cell !== null ) cell.textContent = message;

  // An EMPTY message CLEARS rather than paints — the submit path wipes a prior
  // refusal before acting. Hiding is what clears it: a visible stripe carrying
  // no text still reads as an error that says nothing.
  stripe.hidden = message === "";
  if ( message !== "" ) {
    stripe.setAttribute( "role", "alert" );
    stripe.setAttribute( "aria-live", "polite" );
  }
}

/**
 * Flip one row's disclosure, PANE-SCOPED.
 *
 * 🔴 THE SCOPE IS LOAD-BEARING, NOT A TIDINESS CHOICE. The JS docstring: "A row
 * rendered in both panes has TWO controls rows carrying the same
 * `data-controls-for`, and an unscoped query would open the task list's copy
 * when the operator pressed the epic board's ellipsis." An unscoped
 * `document.querySelector` is the bug, not a simplification.
 *
 * Requires:
 *   - pane is the element containing the clicked toggle and its controls row
 *
 * Ensures:
 *   - `aria-expanded` and the controls row's `hidden` move TOGETHER and stay
 *     opposite; returns the NEW expanded boolean
 *   - a toggle with no matching controls row inside `pane` is a no-op
 *     returning false — never reaches outside the pane to find one
 */
export function toggleDisclosure( pane: ParentNode, button: HTMLElement ): boolean {
  const taskId = button.getAttribute( "data-task-id" ) ?? "";

  // ⚠️ NO SELECTOR INTERPOLATION. A task id is server data, and building a
  // selector out of it makes correctness depend on escaping it right in every
  // parser. Measured: CSS.escape produces a VALID escape that happy-dom's
  // selector parser then rejects outright — so a real-browser-correct port
  // still breaks under test, and the failure is in the parser, not the id.
  // Comparing the attribute directly has no escaping question at all and is
  // correct whatever the id contains.
  // Array.from rather than for-of: a NodeList is only iterable under the DOM
  // lib's downlevel-iteration settings, and this file must typecheck under the
  // same flags as the rest of the card.
  const rows = Array.from( pane.querySelectorAll<HTMLElement>( ".task-controls-row" ) );
  const row  = rows.find( ( c ) => c.getAttribute( "data-controls-for" ) === taskId ) ?? null;
  if ( row === null ) return false;

  const expanded = button.getAttribute( "aria-expanded" ) === "true";
  const next     = !expanded;
  button.setAttribute( "aria-expanded", String( next ) );
  ( row as HTMLElement & { hidden: boolean } ).hidden = !next;
  return next;
}

/**
 * The `<thead>` every row-rendering pane shares, built from ROW_SCHEMA.
 *
 * ⭐ ONE HEADER FOR THREE TABLES. Reproduces `_rowTableHeaderRow`
 * (notifications.js:9974), whose docstring names the defect it kills: "a header
 * that has drifted from its rows mislabels every column to the right of the
 * drift — silently, because the table still renders perfectly." Walking the
 * same array the rows walk means the two cannot disagree.
 *
 * ⚠️ THE TOGGLE'S COLUMN IS HEADED BLANK ON PURPOSE — it names a CONTROL, not a
 * field, and a word there reads as a sixth field. `aria-label` carries the name
 * for a screen reader instead, verbatim from the JS card.
 *
 * Ensures:
 *   - one `<th class="task-col-{field}">` per ROW_SCHEMA.line1 entry, IN ORDER
 *   - a trailing empty `<th class="task-col-disclose" aria-label="Row controls">`
 *   - the header cell count equals rowWidth()
 *   - pure: creates, never queries or mutates the document
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderRowTableHead(): HTMLTableSectionElement {
  const thead   = document.createElement( "thead" );
  const headRow = document.createElement( "tr" );

  ROW_SCHEMA.line1.forEach( ( field ) => {
    const th = document.createElement( "th" );
    th.className   = `task-col-${ field }`;
    th.textContent = rowFieldLabel( field );
    headRow.appendChild( th );
  } );

  const toggleTh = document.createElement( "th" );
  toggleTh.className = "task-col-disclose";
  toggleTh.setAttribute( "aria-label", "Row controls" );
  headRow.appendChild( toggleTh );

  thead.appendChild( headRow );
  return thead;
}
