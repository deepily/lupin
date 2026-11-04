/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// alreadyAtTarget — the answer to "the server refused my transition; is the row already where I asked?"
//
// Row 71a11ed7: Rick approved a held row and read `Approve refused: no-op transition
// 'queued'->'queued'` for an approve that had taken effect. A second approve request reached the
// server after the first had committed; the server correctly wrote nothing and said so, and the page
// painted that answer as a refusal.
//
// ⚠️ THE SERVER'S NO-OP MESSAGE IS NOT CHANGED. Other callers (the MCP tools) read it as written.
// The page takes the message's own advice instead: "Re-read the row rather than retrying."
//
// 🔴 THE TEST IS THE ROW'S STATUS, NOT THE MESSAGE TEXT. Matching the sentence would break on any
// rewording; the status is the fact the operator cares about.

/**
 * The sentence both clients show when a click found the row already at the target.
 *
 * It claims only what was measured (the row's status) and not that this click moved it: the server's
 * no-op message says it cannot tell WHO moved the row, so the page must not either. The legacy page
 * (notifications.js, `_alreadyThereNote`) holds an identical copy; a parity test pins the two.
 */
export function alreadyThereMessage( label: string, status: string ): string {
  return `${ label }: this row is already ${ status } — this click changed nothing.`;
}

/** The one read this needs. Both stores' api clients satisfy it structurally. */
export interface RowReader {
  get<T>( path: string ): Promise<T>;
}

/** The HTTP status the store's rules answer a rejected transition with, no-op included. */
export const TRANSITION_REJECTED_STATUS = 422;

/**
 * True when a rejected transition left the row already at the status it was sent to.
 *
 * Requires:
 *   - err is whatever the api client threw for the POST /transition (any shape)
 *
 * Ensures:
 *   - false for any rejection that is not a 422 (a 403 is a real refusal), with NO read made
 *   - otherwise one GET /api/tasks/<encoded id>; true iff its `status` equals `toStatus`
 *   - false when that read itself fails: the original refusal is then the honest thing to show
 *   - never throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export async function alreadyAtTarget( api: RowReader, id: string, toStatus: string, err: unknown ): Promise<boolean> {
  if ( ( err as { status?: unknown } | null | undefined )?.status !== TRANSITION_REJECTED_STATUS ) return false;
  try {
    const row = await api.get<{ status?: unknown } | null>( `/api/tasks/${ encodeURIComponent( id ) }` );
    return row?.status === toStatus;
  } catch {
    return false;
  }
}
