/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Console tee — the standalone console page's URL (row 27760534, Rick's ruling 2026-09-28).
//
// The live console opens in its OWN tab, the way documents do, and that tab is a real page:
// `/app/console?seat=<full cc session id>&title=<title>`. It survives a reload and can be
// bookmarked, so everything the page needs travels in the query string — never in the opener.
//
// 🔴 ONE MODULE BUILDS THE URL AND THE SAME MODULE READS IT. The reading pane's pop-out writes
// it and the console page parses it; two hand-written copies of "which key is the seat" would
// agree until someone renamed one. The legacy notifications client will later open the same
// URL, and should import nothing but this contract: path, `seat`, `title`.

export const CONSOLE_PAGE_PATH    = "/app/console";
export const CONSOLE_DEFAULT_TITLE = "Console";

/**
 * A seat's FULL stable id: a Claude Code session UUID, 8-4-4-4-12 hex.
 *
 * 🔴 THE 8-HEX CHIP PREFIX IS NOT A SEAT ID, AND IT IS THE LIKELIEST WRONG VALUE. A sender id
 * carries only the first 8 hex of the seat (`claude.code@lupin#e14bd712`), prefixes are not
 * unique, and the server matches the exact id only — so a page handed a prefix would watch
 * nothing, silently. It is refused up front with a message instead.
 */
export const SEAT_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ConsolePageQuery {
  /** The seat to watch, or null when the query does not name a usable one. */
  seat  : string | null;
  title : string;
  /** Why `seat` is null, in words the page can show; null when the seat is usable. */
  error : string | null;
}

/**
 * The console page's URL for one seat.
 *
 * Requires:
 *   - seat is the seat's FULL stable id
 *
 * Ensures:
 *   - both values are percent-encoded, so a title carrying `&`, `#` or an emoji round-trips
 *     through parseConsolePageQuery unchanged
 */
export function buildConsolePageHref( seat: string, title: string ): string {
  return `${ CONSOLE_PAGE_PATH }?seat=${ encodeURIComponent( seat ) }&title=${ encodeURIComponent( title ) }`;
}

/**
 * Read the console page's query string.
 *
 * Requires:
 *   - search is `location.search` (a leading "?" is optional)
 *
 * Ensures:
 *   - title falls back to CONSOLE_DEFAULT_TITLE when absent or blank
 *   - a missing, blank or malformed seat yields seat === null and a non-null error
 *   - a well-formed seat is returned trimmed, with error === null
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation maps onto the last function.
export function parseConsolePageQuery( search: string ): ConsolePageQuery {
  const params = new URLSearchParams( search );
  const title  = ( params.get( "title" ) ?? "" ).trim() || CONSOLE_DEFAULT_TITLE;
  const seat   = ( params.get( "seat" ) ?? "" ).trim();

  if ( seat === "" ) {
    return { seat : null, title, error : "No seat was named. This page needs ?seat=<the seat's full session id>." };
  }
  if ( !SEAT_ID_PATTERN.test( seat ) ) {
    return { seat : null, title, error : `"${ seat }" is not a full seat id. A console link needs the whole session id, not the 8-character chip prefix.` };
  }
  return { seat, title, error : null };
}
