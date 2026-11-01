/* c8 ignore next */ // tsx phantom-branch artifact, file header.
// One-click ticket approval in the multiplexer.
//
// A manager asking Rick to approve rows writes each as a bullet with an ordinary markdown link:
// `[✅ approve](/app/tasks/approve?row=<full uuid>)`. The link is an action, not a destination.
// The click handler claims it, sends the approve move, and draws the result where the link was.
//
// The sender is `HoldingAreaStore.transitionTask`, not `TaskListStore.transitionTask`.
// The task-list store edits its cached open list first. When the row is missing from that cache
// it resolves as done without sending anything, so the link would say "Approved ✓" for a request
// never made. The holding-area sender always posts, never throws, and reports a refusal as a value.

import type { HoldingAreaStore } from "../stores/HoldingAreaStore";
import { normalizeDocLinkHref } from "./docLink";

/** Every approve link starts here, after loopback normalization. */
export const APPROVE_LINK_PREFIX = "/app/tasks/approve?row=";

// A full lowercase hyphenated row id, the only thing sent to the server.
const ROW_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The one call this module needs, taken from the holding-area store so the two cannot drift. */
export type ApproveSender = Pick<HoldingAreaStore, "transitionTask">;

/**
 * The row id an approve-link href names, or null when the href is not an approve link.
 *
 * Requires: nothing (null and empty are "not an approve link").
 * Ensures: a malformed or short id is null, so nothing is ever sent for it.
 */
export function approveRowId( href: string | null ): string | null {
  const normalized = normalizeDocLinkHref( href );
  if ( normalized === null || !normalized.startsWith( APPROVE_LINK_PREFIX ) ) return null;
  const id = normalized.slice( APPROVE_LINK_PREFIX.length );
  return ROW_ID_RE.test( id ) ? id : null;
}

/**
 * Handle a click that may be on an approve link. Returns true when the click was claimed.
 *
 * Ensures:
 *   - a non-approve click is untouched and reports false
 *   - the browser does not follow the link (preventDefault), wherever the link sits
 *   - one request per link: a second click while it is out sends nothing
 *   - success replaces the link with "Approved ✓"; a refusal or pending answer replaces it with
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
    outcome.textContent = result.ok ? "Approved ✓" : result.message;
    anchor.replaceWith( outcome );
  } );
  return true;
}
