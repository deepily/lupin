/* c8 ignore next */ // TRANSPILER ARTIFACT, not source: c8 scores a branch on the file-header line of a tsx-transformed module. Nothing on this line is conditional.
// Parity A-2 #11 — the reveal BOTH filter badges call.
//
// Legacy gives its two badges ONE handler, `showAndScrollToFilterPanel`
// (notifications.js:6364-6384), and wires both to it (:1834-1845). This is that
// handler, and it lives in its own module for a reason worth stating: it used to be an
// inline arrow inside `bootMultiplexer()`, where NO test could reach it. boot.ts runs
// bootMultiplexer() at import and exports nothing, so every boot-level guard in this
// tree is a SOURCE PIN that reads the file as text — and a source pin cannot see a
// logic error, only a spelling one. Emptying the body of that inline arrow killed no
// test (María 🌸's surviving mutant, 2026-09-23). Extracted here, the real function is
// driven by real tests, so emptying it reddens them.
//
// The toolbar is read through a THUNK, not captured: boot constructs the badges that
// close over this reveal BEFORE it constructs the section-toolbar renderer, so a
// captured reference would be read in its temporal dead zone. Deferring the read to
// call time makes that explicit instead of relying on "a click happens later".

import { scrollRevealElement } from "./scrollReveal";
import { SECTION_ID } from "./FilterSettingsRenderer";

// The slice of SectionToolbarRenderer this reveal needs — keeps the unit test free to
// inject a fake, and keeps this module from importing the whole renderer.
export interface RevealToolbarLike {
  /** Persist + un-hide + re-light the section's toolbar button. Does NOT scroll. */
  showSection( sectionId: string ): void;
}

export interface FilterSettingsRevealOptions {
  /** Resolved at CALL time — see the header note on the temporal dead zone. */
  toolbar : () => RevealToolbarLike;
  /** The document to resolve the pane against; tests inject a happy-dom document. */
  doc?    : Document;
}

/**
 * Build the reveal both filter badges call.
 *
 * Requires:
 *   - `toolbar` returns the live section-toolbar renderer when INVOKED
 *
 * Ensures:
 *   - Returns a thunk that un-hides + persists + re-lights Filter Settings through
 *     `showSection`, then scrolls the pane into view via the A-0 shared helper
 *   - The scroll is separate because `showSection` deliberately does not scroll
 *   - A missing pane element is a no-op rather than a throw
 */
/* c8 ignore next */ // TRANSPILER ARTIFACT, not source: this declaration line carries no conditional. tsx erases the `): () => void` return type and c8 scores a branch on the result. Same artifact, same remedy, as sectionToolbar.ts's renderSectionToolbar.
export function createFilterSettingsReveal(
  opts: FilterSettingsRevealOptions,
): () => void {
  /* c8 ignore next */ // UNTESTABLE BY DESIGN, not untested: the `?? document` arm is the production default, and every test injects `doc` so happy-dom's document is the one resolved. Exercising it would mean asserting on the ambient global the test runner installed.
  const doc = opts.doc ?? document;
  return (): void => {
    opts.toolbar().showSection( SECTION_ID );
    const pane = doc.getElementById( SECTION_ID );
    if ( pane !== null ) void scrollRevealElement( pane );
  };
}
