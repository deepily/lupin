/* c8 ignore next */ // tsx phantom-branch artifact, file header.
// One-click ticket approval in the multiplexer.
//
// A manager asking Rick to approve rows writes each as a bullet with an ordinary markdown link:
// `[approve ☐](/app/tasks/approve?row=<full uuid>) [📋](/app/tasks/view?row=<full uuid>)`.
// Both links are actions, not destinations. The approve click sends the approve move and draws "approved ✅"
// where the link was. The 📋 click reads the row and shows it the way the abstract 📋 shows text.
// A card drawn after a reload is checked once per row id: a row that has left the holding area
// shows "approved ✅" (or its plain status when it was dropped), not a live link.
//
// The sender is `HoldingAreaStore.transitionTask`, not `TaskListStore.transitionTask`.
// The task-list store edits its cached open list first. When the row is missing from that cache
// it resolves as done without sending anything, so the link would say "approved ✅" for a request
// never made. The holding-area sender always posts, never throws, and reports a refusal as a value.

import type { HoldingAreaStore } from "../stores/HoldingAreaStore";
import { normalizeDocLinkHref } from "./docLink";
import type { TaskItem } from "./taskListModel";
import type { TransitionExtras } from "./taskVerbs";

/** Every approve link starts here, after loopback normalization. */
export const APPROVE_LINK_PREFIX = "/app/tasks/approve?row=";

// A full lowercase hyphenated row id, the only thing sent to the server.
const ROW_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** A priority link ends with this and a level. The server honours it for Rick's login only. */
export const PRIORITY_LINK_PARAM = "&priority=";

const PRIORITY_RE = /^P[0-5]$/;

/** Every 📋 view link starts here, after loopback normalization. */
export const VIEW_LINK_PREFIX = "/app/tasks/view?row=";

/** Shows text the way the abstract 📋 does: in the Reading Pane or the tooltip, by layout. */
export type AbstractShower = ( anchor: Element, abstract: string, title: string ) => void;

/** Reads one row for the 📋 link and the redraw check; null when the read failed. */
export type TaskReader = ( id: string ) => Promise<TaskItem | null>;

/** The one call this module needs, taken from the holding-area store so the two cannot drift. */
export type ApproveSender = Pick<HoldingAreaStore, "transitionTask">;

/**
 * The row id an approve-link href names, or null when the href is not an approve link.
 *
 * Requires: nothing (null and empty are "not an approve link").
 * Ensures: a malformed or short id is null, so nothing is ever sent for it.
 */
export function approveRowId( href: string | null ): string | null {
  return rowIdAfter( APPROVE_LINK_PREFIX, href );
}

/** What a priority link names: the row and the level it admits the row at. */
export interface PriorityLink { rowId: string; priority: string }

/**
 * The row and level a priority-link href names, or null.
 *
 * The href is `/app/tasks/approve?row=<id>&priority=P0`.
 * Ensures: the plain approve link is null here, and a priority link is null for `approveRowId`, so each click has one handler.
 */
export function approvePriorityLink( href: string | null ): PriorityLink | null {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null ) return null;
  const at = normalized.lastIndexOf( PRIORITY_LINK_PARAM );
  if ( at < 0 ) return null;
  const priority = normalized.slice( at + PRIORITY_LINK_PARAM.length );
  const rowId    = rowIdAfter( APPROVE_LINK_PREFIX, normalized.slice( 0, at ) );
  return rowId !== null && PRIORITY_RE.test( priority ) ? { rowId, priority } : null;
}

/** The row id a 📋 view-link href names, or null when the href is not a view link. */
export function viewRowId( href: string | null ): string | null {
  return rowIdAfter( VIEW_LINK_PREFIX, href );
}

/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
function rowIdAfter( prefix: string, href: string | null ): string | null {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null || !normalized.startsWith( prefix ) ) return null;
  const id = normalized.slice( prefix.length );
  return ROW_ID_RE.test( id ) ? id : null;
}

/**
 * Handle a click that may be on an approve link. Returns true when the click was claimed.
 *
 * Ensures:
 *   - a non-approve click is untouched and reports false
 *   - the browser does not follow the link (preventDefault), wherever the link sits
 *   - one request per link: a second click while it is out sends nothing
 *   - success replaces the link with a disabled "approved ✅"; a refusal or pending answer replaces it with
 *     the server's message, word for word
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as docLink.ts isPaneResidentAnchor).
export function handleApproveLinkClick( ev: Event, target: Element, sender: ApproveSender ): boolean {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const rowId = approveRowId( anchor.getAttribute( "href" ) );
  if ( rowId === null ) return false;
  ev.preventDefault();
  if ( anchor.getAttribute( "data-approve-state" ) === "pending" ) return true;
  anchor.setAttribute( "data-approve-state", "pending" );
  anchor.setAttribute( "aria-disabled", "true" );
  ( anchor as HTMLElement ).style.opacity = "0.5";
  void sender.transitionTask( rowId, "queued", {} ).then( ( result ) => {
    const outcome = anchor.ownerDocument.createElement( "span" );
    outcome.className   = result.ok ? "approve-link-result approve-link-approved" : "approve-link-result approve-link-refused";
    outcome.textContent = result.ok ? APPROVED_TEXT : result.message;
    if ( result.ok ) outcome.setAttribute( "aria-disabled", "true" );
    anchor.replaceWith( outcome );
  } );
  return true;
}

/**
 * Handle a click that may be on a priority link. Returns true when the click was claimed.
 *
 * Ensures:
 *   - a non-priority click is untouched and reports false
 *   - the browser does not follow the link
 *   - one request per link: a second click while it is out sends nothing
 *   - the request is the approve move plus `promote_priority`; the server decides who may
 *   - success replaces the link with a disabled "approved at <level> ✅"; a refusal or pending answer with the server's words
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleApprovePriorityLinkClick( ev: Event, target: Element, sender: ApproveSender ): boolean {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const link = approvePriorityLink( anchor.getAttribute( "href" ) );
  if ( link === null ) return false;
  ev.preventDefault();
  if ( anchor.getAttribute( "data-approve-state" ) === "pending" ) return true;
  anchor.setAttribute( "data-approve-state", "pending" );
  anchor.setAttribute( "aria-disabled", "true" );
  ( anchor as HTMLElement ).style.opacity = "0.5";
  void sender.transitionTask( link.rowId, "queued", { promote_priority: link.priority } ).then( ( result ) => {
    const outcome = anchor.ownerDocument.createElement( "span" );
    outcome.className   = result.ok ? "approve-link-result approve-link-approved" : "approve-link-result approve-link-refused";
    outcome.textContent = result.ok ? `approved at ${ link.priority } ✅` : result.message;
    if ( result.ok ) outcome.setAttribute( "aria-disabled", "true" );
    anchor.replaceWith( outcome );
  } );
  return true;
}

/**
 * The reader the 📋 link and the redraw check share, built on the api client.
 *
 * Requires: api.get sends a GET and resolves with the parsed body.
 * Ensures:
 *   - the request is `GET /api/tasks/<id>` with the id percent-encoded, as the legacy card sends it
 *   - any failure reads as null, so the caller leaves the live link or says the read failed
 */
export function taskReaderFor( api: { get<T>( path: string ): Promise<T> } ): TaskReader {
  return async ( id ) => {
    try { return await api.get<TaskItem>( `/api/tasks/${ encodeURIComponent( id ) }` ); }
    catch { return null; }
  };
}

/** What a disabled, already-approved link reads. */
export const APPROVED_TEXT = "approved ✅";

/** Statuses that mean the row was turned down, shown as plain text and never as approved. */
const CLOSED_STATUSES = new Set( [ "dropped", "wont_fix" ] );

/**
 * One block of text: a row's title, priority, owner, status and body.
 *
 * Requires: row is a task row as the server sent it.
 * Ensures: a missing field reads as a dash, "unowned" or "(no body)", never as "undefined".
 */
export function taskOverlayText( row: TaskItem ): string {
  const facts = `Priority: ${ row.priority ?? "—" } · Owner: ${ row.owner_persona ?? "unowned" } · Status: ${ row.status ?? "—" }`;
  return `${ row.title ?? "(no title)" }\n${ facts }\n\n${ row.body ?? "(no body)" }`;
}

/**
 * Handle a click that may be on a 📋 view link. Returns true when the click was claimed.
 *
 * Ensures:
 *   - a non-view click is untouched and reports false
 *   - the browser does not follow the link
 *   - the row is read and handed to `show` (the abstract 📋's own display code); a failed read says so there
 *   - no overlay and no tab opens
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleViewLinkClick( ev: Event, target: Element, reader: TaskReader, show: AbstractShower ): boolean {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const rowId = viewRowId( anchor.getAttribute( "href" ) );
  if ( rowId === null ) return false;
  ev.preventDefault();
  void reader( rowId ).then( ( row ) => {
    show( anchor, row === null ? "Could not read this ticket." : taskOverlayText( row ), `Ticket ${ rowId.slice( 0, 8 ) }` );
  } );
  return true;
}

/**
 * Check every unchecked approve link under the given roots, one read per distinct row id.
 *
 * Ensures:
 *   - a link is checked once; one already clicked (pending) is left alone
 *   - not_approved, or a failed read, leaves the live link as it is
 *   - a row that left not_approved for a live or done status becomes a disabled "approved ✅"
 *   - a dropped or wont_fix row becomes plain text naming that status, never "approved"
 */
export async function markApproveLinks( roots: Iterable<Element>, reader: TaskReader ): Promise<void> {
  const byRow = new Map<string, Element[]>();
  for ( const root of roots ) {
    const found = root.matches( "a[href]" ) ? [ root ] : Array.from( root.querySelectorAll( "a[href]" ) );
    for ( const anchor of found ) {
      const id = approveRowId( anchor.getAttribute( "href" ) ) ?? approvePriorityLink( anchor.getAttribute( "href" ) )?.rowId ?? null;
      if ( id === null || anchor.hasAttribute( "data-approve-checked" ) ) continue;
      anchor.setAttribute( "data-approve-checked", "1" );
      byRow.set( id, [ ...( byRow.get( id ) ?? [] ), anchor ] );
    }
  }
  await Promise.all( Array.from( byRow, async ( [ id, anchors ] ) => {
    const row = await reader( id );
    if ( row === null || row.status === undefined || row.status === "not_approved" ) return;
    for ( const anchor of anchors ) {
      if ( !anchor.isConnected || anchor.getAttribute( "data-approve-state" ) === "pending" ) continue;
      const verdict = anchor.ownerDocument.createElement( "span" );
      const closed  = CLOSED_STATUSES.has( row.status );
      verdict.className   = closed ? "approve-link-result approve-link-closed" : "approve-link-result approve-link-approved";
      verdict.textContent = closed ? row.status : APPROVED_TEXT;
      if ( !closed ) verdict.setAttribute( "aria-disabled", "true" );
      anchor.replaceWith( verdict );
    }
  } ) );
}

/**
 * Watch a root for newly drawn approve links and check each batch once.
 *
 * Ensures: the links already under root are checked now; the returned function stops the watch.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function observeApproveLinks( root: Element, reader: TaskReader ): () => void {
  void markApproveLinks( [ root ], reader );
  const observer = new MutationObserver( ( records ) => {
    const added: Element[] = [];
    for ( const rec of records ) rec.addedNodes.forEach( ( n ) => { if ( n.nodeType === 1 ) added.push( n as Element ); } );
    if ( added.length > 0 ) void markApproveLinks( added, reader );
  } );
  observer.observe( root, { childList: true, subtree: true } );
  return (): void => observer.disconnect();
}

// ---------------------------------------------------------------------------
// Batch links: one click applies one move to a whole list of held rows
// ---------------------------------------------------------------------------
//
// `/app/tasks/approve?rows=<id>,<id>&move=queued|dropped[&reason=...]` and its 📋 partner
// `/app/tasks/view?rows=<id>,<id>`. The click is the same user_direct move the single link sends,
// once per row, and the answer names every row: a refusal of one never hides the others.

/** Every batch approve link starts here, after loopback normalization. */
export const BATCH_APPROVE_PREFIX = "/app/tasks/approve?rows=";

/** Every batch view link starts here, after loopback normalization. */
export const BATCH_VIEW_PREFIX = "/app/tasks/view?rows=";

/** What a batch link asks for: the ids, the move, and the reason a drop carries. */
export interface BatchLink { ids: string[]; move: "queued" | "dropped"; reason: string | null }

/**
 * A comma list of full row ids as an array, or null when the list cannot be trusted.
 *
 * Ensures: null for an empty list, a short or malformed id, or the same id twice, so nothing is sent for it.
 */
export function parseBatchIds( list: string | null ): string[] | null {
  if ( list === null || list === "" ) return null;
  const ids = list.split( "," );
  if ( ids.some( ( id ) => !ROW_ID_RE.test( id ) ) ) return null;
  if ( new Set( ids ).size !== ids.length ) return null;
  return ids;
}

/** The query of a link whose normalized href starts with `prefix`, or null. */
function batchParams( prefix: string, href: string | null ): URLSearchParams | null {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null || !normalized.startsWith( prefix ) ) return null;
  return new URLSearchParams( normalized.slice( prefix.indexOf( "?" ) + 1 ) );
}

/**
 * What a batch approve-link href asks for, or null when it is not one or cannot be trusted.
 *
 * Ensures: null for a bad id list, a move other than queued or dropped, or a drop with a blank reason.
 */
export function batchLinkOf( href: string | null ): BatchLink | null {
  const params = batchParams( BATCH_APPROVE_PREFIX, href );
  if ( params === null ) return null;
  const ids  = parseBatchIds( params.get( "rows" ) );
  const move = params.get( "move" );
  if ( ids === null || ( move !== "queued" && move !== "dropped" ) ) return null;
  const reason = ( params.get( "reason" ) ?? "" ).trim();
  if ( move === "dropped" && reason === "" ) return null;
  return { ids, move, reason: move === "dropped" ? reason : null };
}

/** The ids a batch 📋 view-link href names, or null when it is not one or the list is bad. */
export function batchViewIds( href: string | null ): string[] | null {
  const params = batchParams( BATCH_VIEW_PREFIX, href );
  return params === null ? null : parseBatchIds( params.get( "rows" ) );
}

/**
 * Apply one move to every listed row, all requests out together.
 *
 * Ensures: returns one line per row in the order given, `<first 8> applied ✅` or `<first 8> refused: <server words>`.
 */
export async function applyBatch( link: BatchLink, sender: ApproveSender ): Promise<string[]> {
  const extras: TransitionExtras = link.reason === null ? {} : { reason: link.reason };
  const results = await Promise.all( link.ids.map( ( id ) => sender.transitionTask( id, link.move, extras ) ) );
  return results.map( ( r, i ) => `${ link.ids[ i ]!.slice( 0, 8 ) } ${ r.ok ? "applied ✅" : `refused: ${ r.message }` }` );
}

/**
 * Handle a click that may be on a batch approve link. Returns true if it claimed it.
 *
 * Ensures:
 *   - a click on anything else is untouched and reports false
 *   - a batch link that cannot be trusted (bad, short or repeated id, empty list, odd move, drop without a reason)
 *     is claimed so the browser does not navigate, but sends nothing
 *   - one run per link: a second click while it is out sends nothing
 *   - the link is replaced by a summary line and one line per row
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleBatchApproveLinkClick( ev: Event, target: Element, sender: ApproveSender ): boolean {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const href = anchor.getAttribute( "href" );
  if ( normalizeDocLinkHref( href )?.startsWith( BATCH_APPROVE_PREFIX ) !== true ) return false;
  ev.preventDefault();
  const link = batchLinkOf( href );
  if ( link === null || anchor.getAttribute( "data-approve-state" ) === "pending" ) return true;
  anchor.setAttribute( "data-approve-state", "pending" );
  anchor.setAttribute( "aria-disabled", "true" );
  ( anchor as HTMLElement ).style.opacity = "0.5";
  void applyBatch( link, sender ).then( ( lines ) => {
    const done    = lines.filter( ( l ) => l.endsWith( "applied ✅" ) ).length;
    const outcome = anchor.ownerDocument.createElement( "span" );
    outcome.className = done === lines.length ? "approve-link-result approve-link-approved" : "approve-link-result approve-link-refused";
    outcome.textContent = [ `${ done } of ${ lines.length } applied`, ...lines ].join( "\n" );
    ( outcome as HTMLElement ).style.whiteSpace = "pre-line";
    anchor.replaceWith( outcome );
  } );
  return true;
}

/**
 * Handle a click that may be on a batch 📋 view link. Returns true when it claimed the click.
 *
 * Ensures:
 *   - a click on anything else is untouched and reports false
 *   - the browser does not follow the link
 *   - every row is read and `show` gets one line per row, its status and title, in the order given;
 *     a row that could not be read says so, and the rest still show
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function handleBatchViewLinkClick( ev: Event, target: Element, reader: TaskReader, show: AbstractShower ): boolean {
  const anchor = target.closest( "a[href]" );
  if ( anchor === null ) return false;
  const href = anchor.getAttribute( "href" );
  if ( normalizeDocLinkHref( href )?.startsWith( BATCH_VIEW_PREFIX ) !== true ) return false;
  ev.preventDefault();
  const ids = batchViewIds( href );
  if ( ids === null ) { show( anchor, "This link does not name a clean list of full ticket ids.", "Held rows" ); return true; }
  void Promise.all( ids.map( reader ) ).then( ( rows ) => {
    const lines = rows.map( ( row, i ) => `${ ids[ i ]!.slice( 0, 8 ) } · ${ row === null ? "could not be read" : `${ row.status ?? "—" } · ${ row.title ?? "(no title)" }` }` );
    show( anchor, lines.join( "\n" ), `${ ids.length } held rows` );
  } );
  return true;
}
