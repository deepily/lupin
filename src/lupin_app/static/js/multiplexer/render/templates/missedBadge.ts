/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP15 — "N missed while away" badge template (F7).
//
// Ports the legacy `#missed-status` + `#missed-reset-button` DOM
// (notifications.js:14708-14722) to a safe-write template. Only rendered when
// count > 0 (the renderer paints an empty root otherwise), so this template
// never has to express the hidden state.
//
// Safe-write invariant (mirrors ttsChrome.ts): ALL DOM writes go through the
// `html` tagged template + `.textContent` only. NEVER `.innerHTML =`,
// `rawHTML(`, or `.outerHTML =`. Verified by the grep guard in
// templates_missed_badge.test.ts.

import { html } from "../html";

export interface MissedBadgeHandlers {
  /** Reset (soft-dismiss) click. */
  onReset(): void;
}

export interface MissedBadgeOpts {
  /** Missed count — caller guarantees > 0 (renderer hides at 0). */
  count : number;
}

/**
 * Build the missed-while-away badge (status text + Reset button).
 *
 * Requires:
 *   - `opts.count` is a positive integer
 *   - `handlers.onReset` is a function
 *
 * Ensures:
 *   - Returned HTMLElement carries `.missed-badge` + `.missed-visible`
 *   - `.missed-status` text reads `${count} missed while away`
 *   - `.missed-reset-button` is wired to `handlers.onReset`
 *   - All writes are safe (no .innerHTML / rawHTML / .outerHTML)
 */
export function renderMissedBadge(
  opts     : MissedBadgeOpts,
  handlers : MissedBadgeHandlers,
): HTMLElement {
  const root = document.createElement( "div" );
  root.className = "missed-badge missed-visible";
  root.setAttribute( "data-testid", "multiplexer-missed-badge" );

  const countStr = String( opts.count );
  /* c8 ignore next 6 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders the badge (ttsChrome.ts:105 precedent).
  const frag = html`
    <span class="missed-status" id="missed-status">${countStr} missed while away</span>
    <button type="button" class="missed-reset-button" id="missed-reset-button">Reset</button>
  ` as DocumentFragment;
  root.appendChild( frag );

  const resetBtn = root.querySelector<HTMLButtonElement>( ".missed-reset-button" );
  /* c8 ignore next */ // defensive: html`` always produces the reset button.
  if ( resetBtn !== null ) {
    resetBtn.addEventListener( "click", () => handlers.onReset() );
  }

  return root;
}
