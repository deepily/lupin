/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-0 (row 52daee86, 2026-09-16, John 🏄🏽) — the shared scroll-reveal helper.
//
// A port of legacy `scrollIntoViewIfNeeded` (notifications.js:25386-25408), built
// once so every reveal path uses the same rule: the toolbar's show (A-2 #1),
// Action Required's auto-reveal (A-2 #2b), TTS playback (A-2 #4), the filter
// badges (A-2 #11) and Queue Filter Settings (B-3).
//
// Not a bare `scrollIntoView`:
//   - an element already fully in view is left alone and resolves at once;
//   - otherwise it scrolls `{ behavior: "smooth", block: "start" }` and resolves
//     on a 300 ms timer, so a caller can sequence work after the scroll.
// Expanding a collapsed ancestor before the scroll is the caller's job.

/** How long legacy waits for a smooth scroll to settle before resolving. */
export const SCROLL_REVEAL_SETTLE_MS = 300;

/**
 * Scroll `el` into view unless it is already fully visible.
 *
 * Requires:
 *   - `el` is an Element attached to the document, or null
 *
 * Ensures:
 *   - null → resolves at once, scrolls nothing (legacy's guard)
 *   - top >= 0 and bottom <= window.innerHeight → resolves at once, scrolls nothing
 *   - otherwise → calls scrollIntoView( { behavior: "smooth", block: "start" } )
 *     once, and resolves after SCROLL_REVEAL_SETTLE_MS
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function scrollRevealElement( el: Element | null ): Promise<void> {
  return new Promise<void>( ( resolve ) => {
    if ( el === null ) {
      resolve();
      return;
    }
    const rect      = el.getBoundingClientRect();
    const isVisible = rect.top >= 0 && rect.bottom <= window.innerHeight;
    if ( isVisible ) {
      resolve();
      return;
    }
    el.scrollIntoView( { behavior: "smooth", block: "start" } );
    setTimeout( resolve, SCROLL_REVEAL_SETTLE_MS );
  } );
}
