/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line, same as approve-link.js.
/**
 * The ↗ "open in a new tab" link beside a file in the doc viewer's folder listing.
 *
 * The listing is drawn by document-viewer.html, which both clients show in their Reading Pane iframe.
 * Each client's pane intercepts a click on any `/app/docs?path=` link inside that iframe and renders
 * the document in the pane. The ↗ link must escape that interception, so it carries `data-doc-new-tab`
 * and both interceptors leave an anchor with that attribute alone.
 *
 * The URL is the one the pane's "bust out" button opens: `normalizeDocLinkHref( view_url )`, from the
 * same function. Both read the server's `view_url`, so the two cannot disagree.
 *
 * Plain JS, because the document viewer page and notifications.js have no build step.
 */

import { normalizeDocLinkHref } from "./approve-link.js";

/** The attribute that marks a ↗ anchor, so the clients' iframe interception skips it. */
export const NEW_TAB_ATTR = "data-doc-new-tab";

/** The glyph: the north-east arrow. */
export const NEW_TAB_GLYPH = "↗";

// A pptx entry's view_url ends in this: the server sends it as a download, which no tab renders.
const DOWNLOAD_PARAM = "&download=true";

/**
 * The href the ↗ link opens, or null when the entry has none.
 *
 * Requires: `entry` is a directory-listing entry `{ kind, view_url }`.
 * Ensures:
 *   - null for a directory, an entry with no view_url, and a download-only file type
 *   - otherwise `normalizeDocLinkHref( entry.view_url )`, the same call the pane's bust-out button makes
 *
 * @param {{ kind: string, view_url?: string | null }} entry
 * @returns {string | null}
 */
export function newTabHrefFor( entry ) {
  if ( entry.kind !== "file" ) return null;
  const href = normalizeDocLinkHref( entry.view_url ?? null );
  if ( href === null || href.includes( DOWNLOAD_PARAM ) ) return null;
  return href;
}

/**
 * Escape a string for a double-quoted HTML attribute or text node.
 *
 * @param {string} text
 * @returns {string}
 */
export function escapeHtml( text ) {
  return text.replace( /&/g, "&amp;" ).replace( /</g, "&lt;" ).replace( />/g, "&gt;" ).replace( /"/g, "&quot;" );
}

/**
 * The ↗ anchor's HTML for one listing entry, or "" when the entry gets no glyph.
 *
 * Ensures:
 *   - target="_blank" rel="noopener", a title and an aria-label "Open <name> in a new tab"
 *   - the NEW_TAB_ATTR marker; the anchor is a sibling of the name link, never inside it
 *
 * @param {{ kind: string, name: string, view_url?: string | null }} entry
 * @returns {string}
 */
export function newTabLinkHtml( entry ) {
  const href = newTabHrefFor( entry );
  if ( href === null ) return "";
  const label = escapeHtml( "Open " + entry.name + " in a new tab" );
  return "<a class=\"doc-dir-newtab\" " + NEW_TAB_ATTR + "=\"1\" href=\"" + escapeHtml( href ) + "\" target=\"_blank\" rel=\"noopener\""
    + " title=\"" + label + "\" aria-label=\"" + label + "\">" + NEW_TAB_GLYPH + "</a>";
}

/**
 * True when this anchor carries the ↗ marker. The clients' iframe interceptors call it.
 *
 * @param {Element | null} anchor
 * @returns {boolean}
 */
export function isNewTabAnchor( anchor ) {
  return anchor !== null && anchor.hasAttribute( NEW_TAB_ATTR );
}
