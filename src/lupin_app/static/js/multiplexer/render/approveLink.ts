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

/** Every approve link starts here, after loopback normalization. */
export const APPROVE_LINK_PREFIX = "/app/tasks/approve?row=";

// A full lowercase hyphenated row id, the only thing sent to the server.
const ROW_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

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
      const id = approveRowId( anchor.getAttribute( "href" ) );
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
