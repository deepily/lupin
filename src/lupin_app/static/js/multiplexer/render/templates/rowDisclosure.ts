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

import { rowWidth, rowFieldLabel, disclosedFields, type RowField } from "../rowSchema";

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
  value : string;
}

/**
 * One disclosed field: label + value, both in their own spans so the CSS can
 * lay them out without parsing text. Pure.
 */
function renderDisclosedField( field: RowField, value: string ): HTMLDivElement {
  const wrap = document.createElement( "div" );
  wrap.className = `task-disclosed-field task-col-${ field }`;
  const label = document.createElement( "span" );
  label.className   = "task-disclosed-label";
  label.textContent = rowFieldLabel( field );
  const val = document.createElement( "span" );
  val.className   = "task-disclosed-value";
  val.textContent = value;
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
  values      : Partial<Record<RowField, string>>,
): HTMLTableRowElement {
  const tr = document.createElement( "tr" );
  tr.className = `task-controls-row ${ statusClass }`.trim();
  tr.setAttribute( "data-controls-for", taskId ?? "" );
  tr.hidden = true;

  const cell = document.createElement( "td" );
  cell.setAttribute( "colspan", String( rowWidth() ) );

  disclosedFields().forEach( ( line, idx ) => {
    const lineEl = document.createElement( "div" );
    lineEl.className = `task-disclosed-line task-disclosed-line--${ idx === 0 ? "fields" : "actions" }`;
    line.forEach( ( field ) => {
      lineEl.appendChild( renderDisclosedField( field, values[ field ] ?? "—" ) );
    } );
    cell.appendChild( lineEl );
  } );

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
