// Type declaration for the shared doc-new-tab-link module.
//
// The implementation is plain JS because the document viewer page and notifications.js have no build step.
// ReadingPaneRenderer.ts imports the same file.

/** The attribute that marks a ↗ anchor, so the clients' iframe interception skips it. */
export const NEW_TAB_ATTR: string;

/** The glyph: the north-east arrow. */
export const NEW_TAB_GLYPH: string;

/** The href the ↗ link opens, or null when the entry gets no glyph. */
export function newTabHrefFor( entry: { kind: string; view_url?: string | null } ): string | null;

/** Escape a string for a double-quoted HTML attribute or text node. */
export function escapeHtml( text: string ): string;

/** The ↗ anchor's HTML for one listing entry, or "" when the entry gets no glyph. */
export function newTabLinkHtml( entry: { kind: string; name: string; view_url?: string | null } ): string;

/** True when this anchor carries the ↗ marker. */
export function isNewTabAnchor( anchor: Element | null ): boolean;
