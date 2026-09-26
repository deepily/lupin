/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The read a pane takes after a row write — and the one rule about it.
//
// 🔴 HARDENING, NOT A BUG FIX. Read this before citing it: as of 2026-09-26 no read in
// this codebase can reject, so none of what follows has been observed in production and
// nothing here repairs a live symptom. Rachel 🕊️ and Sam 🎙️ measured the closure
// independently (row 93ca4268); `a_store_refresh_cannot_reject_today.test.ts` is the
// tripwire that reddens if it ever reopens. What this module removes is the COUPLING
// that would turn such a rejection into a wrong answer — the same class of change as
// row 8105670f.
//
// WHAT THE COUPLING IS. Every pane re-reads the board after a mutation so the operator
// sees what the server stored, and every one of those re-reads was CHAINED onto the
// write's own settle:
//
//     const done = mutation.done.then( () => this.store.refreshAfterWrite() );
//
// `.then` ADOPTS the read's promise, so from that point `done` reports the READ. The
// write's outcome — the only thing anyone actually asked about — is no longer what
// `done` carries. Three different wrong answers fall out of that one shape, depending
// on what each caller does with a rejection:
//
//   - `TaskRowController.commitMutation` treats a rejected `done` as a refused write:
//     `restoreState()` plus a refusal stripe. The operator's edit would come off the
//     screen while the server held the new value, with nothing saying the write had
//     succeeded, so nobody would retry.
//   - a caller with a no-op restorer keeps the value but still paints the stripe — a
//     false refusal over a write that landed.
//   - a caller that `await`s it mid-sequence abandons the statements after it: the
//     holding area's batch would never paint its tally, and a verdict chip would sit
//     on "Sending…" over a verdict the server had recorded.
//
// ⚠️ AND THE REJECTION WOULD OFTEN NOT BE THIS WRITER'S. `refreshAfterWrite()` awaits
// `inFlightRun` — a poll that started BEFORE this write — precisely so the read it then
// takes can see the write. Joining that poll also inherits its rejection, so a poll tick
// failing would roll back an edit made by someone who never saw it. No per-shape patch
// at the read reaches that; the coupling itself is the thing, so it is cut here.
//
// 🔴 WHY BOTHER WITH A PATH NOTHING CAN TAKE. Because the closure is not local. The
// stores are closed at their own seam (`fetchState` catches every shape); the JOIN is
// closed only DOWNSTREAM, for exactly as long as they stay closed — Rachel's precision,
// and the sharpest fact on the row. Narrowing one catch would reopen the whole chain
// silently, in a file that mentions none of this. 138976e2 is that narrowing having
// already happened once.
//
// THE CONTRACT: the returned promise NEVER rejects. The write's outcome has already been
// decided by the time this runs. A failed read is a STALENESS fact, not a write failure,
// and it goes to `onStale` — which must SURFACE it. A `.catch(() => {})` in place of a
// real `onStale` would trade a visibly wrong value for an invisibly stale one, which is
// the worse of the two; every call site passes a painter.

/**
 * The stamp text a pane shows when the write landed but the board could not be re-read.
 *
 * It replaces the `updated HH:MM:SS` stamp rather than sitting beside it, because the
 * two make exactly one claim between them — "what you are looking at is current as of
 * T" versus "what you are looking at may be behind". The next successful read re-stamps
 * the time and the warning goes away on its own, which is correct: the staleness ended.
 */
export const READ_BACK_FAILED_STAMP = "⚠ saved — board not re-read";

/** Marks the stamp element while it carries READ_BACK_FAILED_STAMP. Styled in multiplexer/task-list.css. */
export const READ_BACK_FAILED_CLASS = "multiplexer-read-back-failed";

/**
 * Run a post-write read whose failure can never be mistaken for a failed write.
 *
 * Requires:
 *   - `read` takes the after-write read (in this codebase, a store's `refreshAfterWrite`)
 *   - `onStale` SURFACES the failure somewhere the operator can see it
 *
 * Ensures:
 *   - resolves whatever `read` does — it never rejects, so no caller's error path fires
 *   - `onStale` is called exactly once, with the rejection value, iff `read` rejected
 *   - statements after an `await` of this call always run
 */
export async function readBackAfterWrite(
  read    : () => Promise<void>,
  onStale : ( err: unknown ) => void
): Promise<void> {
  try {
    await read();
  } catch ( err ) {
    onStale( err );
  }
}

/**
 * Paint `READ_BACK_FAILED_STAMP` into a pane's updated-stamp element.
 *
 * Shared by the three panes because their stamps are the same element under three
 * class names (`.task-list-updated` · `.holding-area-updated` · `.epic-board-updated`),
 * and a fourth pane adding its own copy of these two lines is how they would drift.
 *
 * Ensures:
 *   - a null element is a no-op (the pane is unmounted; there is nothing to tell)
 *   - the element carries READ_BACK_FAILED_CLASS afterwards
 */
export function stampReadBackFailed( el: HTMLElement | null ): void {
  if ( el === null ) return;
  el.textContent = READ_BACK_FAILED_STAMP;
  el.classList.add( READ_BACK_FAILED_CLASS );
}

/**
 * Drop the read-back-failed marking, for a pane that has just re-read successfully.
 *
 * ⚠️ TAKES A NON-NULL ELEMENT, unlike its sibling above, and the asymmetry is real
 * rather than an oversight. Every caller is a `stampUpdated()` that has ALREADY
 * returned on a null stamp before reaching this line, so a null check here would be a
 * branch no test could take — and a dead branch bought with a coverage pragma is worse
 * than no branch, because the pragma is what a later reader trusts.
 *
 * ⚠️ THE PRAGMA BELOW IS NOT THAT, and the distinction is the whole point of the
 * sentence above. It covers a branch that does not exist in the source at all — the
 * tsx phantom on an exported function-declaration line. VERIFIED, not assumed, against
 * `coverage-final.json`: `type=branch`, `counts=[0]`, and a SINGLE location spanning
 * line 117 columns 16-37, which is the identifier itself. A real conditional carries
 * two locations. Every statement in the body is exercised.
 *
 * Ensures:
 *   - the class is gone; the caller writes the fresh `updated …` text itself
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line — see the note above for the coverage-final.json evidence.
export function clearReadBackFailed( el: HTMLElement ): void {
  el.classList.remove( READ_BACK_FAILED_CLASS );
}
