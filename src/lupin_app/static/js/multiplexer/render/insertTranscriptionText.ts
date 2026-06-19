/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer WP6 (parity bridge, 2026-06-11) — insert-at-caret splice (F5).
//
// Pure port of the legacy `notifications.js:_insertTranscriptionText`
// contract (2026-06-01, Rick): transcribed text is inserted wherever the
// caret sits, replacing ONLY a highlighted range (if any), and never
// clobbering the rest of the field. Elements that expose no caret
// (selectionStart === null/undefined) get an APPEND, and caret positioning
// is skipped (legacy parity — setSelectionRange would throw there).
//
// Kept PURE (string in, string out) so the splice arithmetic is unit-testable
// without a DOM; SenderCardRecorderRenderer owns the element-level half
// (stash-before-repaint + focus/caret restore after repaint).

export interface InsertTranscriptionResult {
  /** The field's new value after the splice. */
  value : string;
  /** Caret index to restore (after the inserted text), or null when the
   *  source element exposed no caret (append path — skip setSelectionRange). */
  caret : number | null;
}

/**
 * Splice `text` into `existing` at the selection [selStart, selEnd).
 *
 * Requires:
 *   - `existing` is the field's current value.
 *   - `selStart`/`selEnd` are the element's selection bounds, or
 *     null/undefined when the element exposes no caret.
 * Ensures:
 *   - With a caret: the selected range is replaced by `text`; the rest of
 *     `existing` is preserved; `caret` = selStart + text.length.
 *   - Without a caret: `text` is appended; `caret` is null.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function insertTranscriptionText(
  existing : string,
  selStart : number | null | undefined,
  selEnd   : number | null | undefined,
  text     : string,
): InsertTranscriptionResult {
  const hasCaret = selStart !== null && selStart !== undefined;
  const start = hasCaret ? selStart : existing.length;
  const end   = hasCaret ? (selEnd ?? start) : existing.length;

  return {
    value : existing.slice(0, start) + text + existing.slice(end),
    caret : hasCaret ? start + text.length : null,
  };
}
