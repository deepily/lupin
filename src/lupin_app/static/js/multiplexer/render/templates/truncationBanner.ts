/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-2 #8 (row c1bb2be7) — the truncation banner: a query that came back short
// says so, instead of a pane that silently shows 500 of 1,912 rows.
//
// Ported from legacy notifications.js _renderTaskListTruncationBanner, with
// _holdingAreaWarningCount and _taskListQueryLimit. Pure: it returns the lines and the
// caller places them. The Holding Area passes ITS OWN query string, so the limit it
// reads is the pane's own rather than the task board's (io/phase2/A9.md H12).
//
// ⚠️ A row-cap page prints BOTH the ✂️ line and the server's "row-cap truncation"
// warning, as legacy does today (filed as legacy defect 7 and left by ruling: the
// server's line carries the reason the ✂️ line does not).

import type { TaskListComposite } from "../taskListModel";

const HELD_NOTE_MARKER = "matching your filters are in the HOLDING AREA";

function line( text: string, extraClass: string = "" ): HTMLParagraphElement {
  const p = document.createElement( "p" );
  p.className = `task-list-message task-list-truncated${extraClass}`;
  p.textContent = text;
  return p;
}

/** The `limit=` a query string asks for, or NaN when it names none. */
export function queryLimit( queryString: string ): number {
  const match = /[?&]limit=(\d+)/.exec( queryString );
  return match ? Number( match[ 1 ] ) : Number.NaN;
}

/** The held-row count in the server's holding-area note, or null for any other warning. */
export function heldWarningCount( warning: unknown ): number | null {
  if ( typeof warning !== "string" || !warning.includes( HELD_NOTE_MARKER ) ) return null;
  const match = /^⚠️\s*(\d+) row\(s\) /.exec( warning );
  return match ? Number( match[ 1 ] ) : null;
}

/**
 * The banner's lines, possibly none.
 *
 * Triggers, as legacy: `has_more`, a `total` above what was shown, or a page exactly
 * `limit` long with no total at all (completeness unknown). The server's warnings follow
 * verbatim, except the holding-area note, which becomes "N waiting for your approval"
 * and is dropped when it repeats `headerCount`.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line: the never-run CJS export annotation `0&&(module.exports=…)` maps onto the last function.
export function renderTruncationBanner(
  composite: TaskListComposite | null, queryString: string, headerCount: number | null,
): HTMLParagraphElement[] {
  if ( composite === null ) return [];
  const total = Number( composite.total );
  const shown = Number.isFinite( Number( composite.count ) )
    ? Number( composite.count )
    : ( Array.isArray( composite.tasks ) ? composite.tasks.length : Number.NaN );
  const claimsMore   = composite.has_more === true;
  const countsShort  = Number.isFinite( total ) && Number.isFinite( shown ) && total > shown;
  const limit        = queryLimit( queryString );
  const pageIsFull   = Number.isFinite( limit ) && Number.isFinite( shown ) && shown === limit;
  const totalUnknown = !Number.isFinite( total );
  const warnings     = Array.isArray( composite.warnings ) ? composite.warnings : [];

  const warningLines: HTMLParagraphElement[] = [];
  const verbatim: unknown[] = [];
  for ( const w of warnings ) {
    const held = heldWarningCount( w );
    if ( held === null ) verbatim.push( w );
    else if ( held !== headerCount ) warningLines.push( line( `${held} waiting for your approval`, " task-list-holding-note" ) );
  }
  if ( verbatim.length > 0 ) warningLines.push( line( `⚠️ Server: ${verbatim.map( String ).join( " · " )}` ) );

  if ( !claimsMore && !countsShort && !( pageIsFull && totalUnknown ) ) return warningLines;

  let detail: string;
  if ( countsShort ) {
    detail = `showing ${shown} of ${total} — ${total - shown} not displayed`;
  } else if ( pageIsFull && totalUnknown ) {
    detail = `the page came back exactly full (${shown}) and the server reported no total — completeness UNKNOWN`;
  } else {
    detail = "the server held rows back — some work is not displayed";
  }
  return [ line( `✂️ Board truncated: ${detail}.` ), ...warningLines ];
}
