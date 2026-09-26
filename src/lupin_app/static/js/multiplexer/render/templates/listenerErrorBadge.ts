/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Row 8033756c — the on-page "something broke" indicator.
//
// Rick's ruling 2026-09-26: "Log it and keep going but do make sure that the
// user is apprised of the error in some place on the UI that there was an
// error. Otherwise they might not know to report it."
//
// ONE INDICATOR, A COUNT, AND A DISMISS — not a stack and not a dialog. A bus
// error usually arrives in bursts (one bad payload reaches four renderers), so
// an element per error would bury the page in the failure mode it is reporting.
// The count is what distinguishes "one glitch" from "this is happening
// constantly", which is what the user would actually put in a report.
//
// NO BROWSER DIALOG, per the ruling. An alert() would block every subsequent
// browser event, which for an error indicator means the page stops working
// harder than the error made it.
//
// Safe-write invariant (mirrors missedBadge.ts / ttsChrome.ts): ALL DOM writes
// go through the `html` tagged template + `.textContent`. NEVER `.innerHTML =`,
// `rawHTML(`, or `.outerHTML =` — an error message can carry attacker-shaped
// text from a payload, and this is the one template guaranteed to be handed
// hostile input eventually.

import { html } from "../html";

export interface ListenerErrorBadgeHandlers {
  /** Dismiss click — the renderer clears the count and empties its root. */
  onDismiss(): void;
}

export interface ListenerErrorBadgeOpts {
  /** How many listener errors since the last dismiss. Caller guarantees >= 1. */
  count     : number;
  /** The most recent error's message, shown in the title attribute. */
  lastError : string;
  /** The `type` of the event whose listener threw — the single most useful
   *  thing for a bug report, so it is on the face of the badge, not hidden. */
  lastEventType : string;
}

/**
 * Build the listener-error indicator.
 *
 * Requires:
 *   - `opts.count` is a positive integer
 *   - `handlers.onDismiss` is a function
 *
 * Ensures:
 *   - returns an HTMLElement carrying `.listener-error-badge` and
 *     `data-testid="multiplexer-listener-error-badge"`
 *   - `.listener-error-count` reads the count; at 1 the text is singular
 *   - the originating event type is in `.listener-error-detail`
 *   - `.listener-error-dismiss` is wired to `handlers.onDismiss`
 *   - `role="status"` + `aria-live="polite"`: announced, never focus-stealing
 *   - all writes are safe (no .innerHTML / rawHTML / .outerHTML)
 */
export function renderListenerErrorBadge(
  opts     : ListenerErrorBadgeOpts,
  handlers : ListenerErrorBadgeHandlers,
): HTMLElement {
  const root = document.createElement( "div" );
  root.className = "listener-error-badge";
  root.setAttribute( "data-testid", "multiplexer-listener-error-badge" );
  // polite, not assertive: this reports a background failure, and interrupting
  // a screen-reader mid-sentence is the dialog behaviour the ruling excludes.
  root.setAttribute( "role", "status" );
  root.setAttribute( "aria-live", "polite" );
  root.setAttribute( "data-error-count", String( opts.count ) );
  root.title = opts.lastError;

  const label = opts.count === 1
    ? "1 display error"
    : `${ opts.count } display errors`;

  /* c8 ignore next 6 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders the badge (missedBadge.ts:50 precedent).
  const frag = html`
    <span class="listener-error-icon" aria-hidden="true">⚠️</span>
    <span class="listener-error-count">${label}</span>
    <span class="listener-error-detail">while handling ${opts.lastEventType}</span>
    <button type="button" class="listener-error-dismiss" title="Dismiss">Dismiss</button>
  ` as DocumentFragment;
  root.appendChild( frag );

  const dismissBtn = root.querySelector<HTMLButtonElement>( ".listener-error-dismiss" );
  /* c8 ignore next */ // defensive: html`` always produces the dismiss button.
  if ( dismissBtn !== null ) {
    dismissBtn.addEventListener( "click", () => handlers.onDismiss() );
  }

  return root;
}
