// Multiplexer — the ONE place that decides what a doc link is and how it opens.
//
// Row 47759aa3. Before this module the answer lived in two places per client:
// ReadingPaneRenderer held a private `normalizeDocLinkHref` plus its own
// `DOC_LINK_PREFIX`, and markdown.ts independently stamped `target="_blank"`
// onto every anchor it emitted. Those two copies disagreed, and the
// disagreement was the bug: a doc link rendered with `_blank` opened a new tab
// whenever the renderer's interception did not claim the click first.
//
// 🔴 THE DUPLICATION *WAS* THE DEFECT, so the fix is one predicate, imported.
// Measured 2026-09-26 on :7999: in vertical layout the interception bailed and
// every one of the 5 live doc anchors fell through to its baked-in `_blank`.
// A guard that has to out-run a fallback loses eventually; removing the
// fallback is what makes the in-app path the only path.

/** Every in-app doc link starts here, after loopback normalization. */
export const DOC_LINK_PREFIX = "/app/docs?path=";

// `http://localhost:7999/app/docs?…` and `/app/docs?…` are the same document.
// Senders emit both, so the prefix test must run on a normalized href or it
// silently misses the absolute form.
const LOOPBACK_PREFIX_RE = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/;

/**
 * Strip an absolute loopback origin so an href can be compared and fetched
 * relative to whatever host is serving the page.
 *
 * Returns null for a null/empty href — callers treat that as "not a doc link"
 * rather than as an error, because an `<a>` with no href is ordinary markup.
 */
export function normalizeDocLinkHref( href: string | null ): string | null {
  if (href === null || href === "") return null;
  return href.replace(LOOPBACK_PREFIX_RE, "");
}

/**
 * True when this href addresses the in-app doc viewer, in either the relative
 * or the absolute-loopback form.
 *
 * This is the predicate `markdown.ts` consults before stamping `_blank`, and
 * the one `ReadingPaneRenderer` consults before claiming a click — so the
 * emitter and the interceptor cannot drift apart again.
 */
export function isDocLinkHref( href: string | null ): boolean {
  const normalized = normalizeDocLinkHref(href);
  return normalized !== null && normalized.startsWith(DOC_LINK_PREFIX);
}

/**
 * The two surfaces whose doc links must KEEP opening a new tab.
 *
 * Not an oversight and not a style choice — the Reading Pane is SHARED with
 * the live action-required response buttons, and opening a doc into it calls
 * `replaceChildren`, which would delete the buttons the user was mid-way
 * through pressing. Legacy paid for this twice: bug 11c01fbc for the card,
 * then 17ce50a5 for the tooltip, which is fixed-position and appended to
 * <body>, so an ancestry test against the card alone misses it.
 *
 * María ratified the carve-out 2026-09-26 and it does not contradict Rick's
 * ruling: his population is doc links in the NOTIFICATION HISTORY, and every
 * one of those now opens in-app.
 */
export const PANE_RESIDENT_SELECTOR = "#action-required-content, #action-required-section, .abstract-tooltip";

/**
 * True when this anchor lives on a pane-resident surface, so routing it into
 * the pane would destroy the surface it was clicked from.
 */
export function isPaneResidentAnchor( anchor: Element ): boolean {
  return anchor.closest(PANE_RESIDENT_SELECTOR) !== null;
}
