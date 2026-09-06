/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Row schema — the progressive-disclosure field split (TS multiplexer card).
//
// Reproduces the in-service JS card's ROW_SCHEMA / ROW_FIELD_LABELS /
// _rowWidth (notifications.js:43-64 and the _rowWidth method) as OBSERVATIONAL
// EQUIVALENCE, not shared code — Rick's ruling: the two clients share none.
//
// Rick ruled 2026-09-05 that the TS row must be RE-SHAPED to this design
// before the holding-area and epic-board panes are built, so the two new panes
// carbon-copy the row the legacy card actually renders.
//
// ⭐ RICK'S SPEC, quoted in the JS source: "an ellipsis right-justified ON THE
// TITLE LINE indicating hidden functionality; clicking it discloses the
// controls as ONE narrow row spanning the full width of the item; that second
// row is NOT displayed by default."
//
// ⚠️ A VERTICAL STACK OF CONTROLS IS EXPLICITLY WRONG — "Nine controls inline
// turned a dense, scannable board into a wall: the thing the board is FOR,
// seeing many rows at once, was paid away to make five verbs reachable
// without a click."
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §5a

/** Line 1 is ALWAYS VISIBLE. Lines 2 and 3 live behind the disclosure. */
import { ownLookup } from "../shared/ownLookup";

export const ROW_SCHEMA = {
  line1 : [ "id", "title", "class", "status", "priority" ],
  line2 : [ "blocked", "chase", "accountable", "filer", "project" ],
  line3 : [ "detail", "actions" ],
} as const;

export type RowField =
  | typeof ROW_SCHEMA.line1[ number ]
  | typeof ROW_SCHEMA.line2[ number ]
  | typeof ROW_SCHEMA.line3[ number ];

export const ROW_FIELD_LABELS: Readonly<Record<RowField, string>> = {
  id          : "ID",
  title       : "Title",
  class       : "Class",
  status      : "Status",
  priority    : "Priority",
  blocked     : "Blocked by",
  chase       : "Next chase",
  accountable : "Accountable",
  filer       : "Filed by",
  project     : "Project",
  detail      : "Detail",
  actions     : "Actions",
};

/**
 * The table's column count: the visible fields plus the disclosure toggle's
 * own cell. EVERY colspan in EVERY pane must derive from here.
 *
 * 🔴 THIS FUNCTION IS THE WHOLE POINT OF THE CONSTANT. The JS card's own
 * docstring names the defect it kills: the colspans "used to be hand-written
 * literals — 12, 12, 11, 5, 5, 5, 5 across seven sites — and a stale colspan
 * does not look broken: the table still renders perfectly while the controls
 * row and the error stripe quietly stop spanning it."
 *
 * ⇒ A port that hard-codes a colspan re-opens a class of defect that is
 * currently gone by construction. There is nothing left to keep in step.
 *
 * Ensures:
 *   - returns ROW_SCHEMA.line1.length + 1
 */
export function rowWidth(): number {
  return ROW_SCHEMA.line1.length + 1;
}

/**
 * The label for one row field. Pure.
 *
 * Ensures:
 *   - a known field → its display label
 *   - an unknown field → the field name itself, never undefined (a missing
 *     label must degrade to something readable rather than print "undefined"
 *     into a header cell)
 */
export function rowFieldLabel( field: string ): string {
  return ownLookup<string>( ROW_FIELD_LABELS as Record<string, string>, field, field );
}

/**
 * The fields hidden behind the disclosure, in render order. Pure.
 *
 * Ensures:
 *   - line2 followed by line3, as two separate lines
 *   - the result never includes a line1 field
 */
export function disclosedFields(): ReadonlyArray<ReadonlyArray<RowField>> {
  return [ ROW_SCHEMA.line2, ROW_SCHEMA.line3 ];
}
