// personaLabel — the shared "strip a trailing session id" rule, tested DIRECTLY.
//
// 🔴 WHY THIS FILE DID NOT EXIST, AND WHY THAT IS NOT THE SAME AS "UNTESTED".
// Before this commit, ZERO test files mentioned `personaLabel` by name, while the
// module reported 100% statements, lines and functions — all of it from CALLERS
// exercising it sideways (`holdingAreaModel.taskFilerLabel`,
// `finishedTasksModel.actorPersona`).
//
// ⚠️ I READ THAT AS "THE BEHAVIOUR IS UNGUARDED" AND IT WAS WRONG. Two tests in
// `holding_area_model.test.ts` pin this module's exact rule — "a bare session id
// with no name is shown WHOLE — visibly odd, by design" at :60, and the JS-PARITY
// corpus at :219 whose entry `[ "0e61abe3", "0e61abe3" ]` locks it to the legacy
// card. A grep for the FUNCTION NAME found nothing; the guards were one level up,
// named for the caller. § A HIT IS NOT A USE, running in the other direction: an
// empty search is not an absent guard.
//
// ⇒ WHAT THIS FILE ADDS IS DIRECTNESS, NOT COVERAGE. A rule guarded only through
// a caller reddens for reasons that name the caller, and the next author reads a
// failure in `taskFilerLabel` rather than a failure in the rule. These tests fail
// with the rule's own name on them.
//
// 🔴 AND THE ONE UNCOVERED BRANCH IS NOT HERE TO BE CLOSED BY A TEST. The
// `stripped === ""` fallback arm is unreachable by construction — `raw` is trimmed,
// the regex needs leading whitespace, so the match can never start at index 0.
// Measured: 628 inputs reached it zero times while the null/blank guards above it
// DID reach the fallback. Widening the regex to `(?:^|\s+)` makes it reachable and
// REDDENS the two tests above — tried 2026-09-08, reverted. The arm carries a
// `c8 ignore` with that argument, in the source, beside the code.

import { test } from "node:test";
import assert from "node:assert/strict";

import { personaLabel } from "../../../lupin_app/static/js/multiplexer/shared/personaLabel";

const FALLBACK = "—";

// ------------------------------------------------- the rule this file exists for

test( "a TWO-WORD persona survives the strip", () => {
  // The naive `split( /\s+/ )[ 0 ]` renders this as "mr", and it shipped to the
  // Finished-Tasks WHO column once already — wrong on 6 of 13 live rows.
  assert.equal( personaLabel( "mr radio 8353ea70", FALLBACK ), "mr radio" );
} );

test( "a one-word persona keeps its name and loses its id", () => {
  assert.equal( personaLabel( "krishna 420f5ec9", FALLBACK ), "krishna" );
} );

test( "the id match is case-insensitive", () => {
  assert.equal( personaLabel( "Rachel ABA6A819", FALLBACK ), "Rachel" );
} );

test( "the id must be at the END — an 8-hex run mid-string is part of the name", () => {
  assert.equal( personaLabel( "0e61abe3 Rio", FALLBACK ), "0e61abe3 Rio" );
  assert.equal( personaLabel( "deadbeef rides again", FALLBACK ), "deadbeef rides again" );
} );

// --------------------------------------------- the bare id: WHOLE, not fallback

test( "a BARE session id is shown WHOLE — the leading whitespace is required", () => {
  // 🔴 THE CASE THE COVERAGE GATE POINTED AT, AND THE ANSWER IS NOT THE FALLBACK.
  // Pinned at the caller by holding_area_model.test.ts:60 and by the JS-PARITY
  // corpus entry [ "0e61abe3", "0e61abe3" ]. Changing this diverges the two
  // clients, which is what the parity corpus exists to prevent.
  assert.equal( personaLabel( "0e61abe3", FALLBACK ), "0e61abe3" );
  assert.equal( personaLabel( "8353ea70", FALLBACK ), "8353ea70" );
  // Trimmed first, so padding does not turn it into a match either.
  assert.equal( personaLabel( "   8353ea70   ", FALLBACK ), "8353ea70" );
} );

test( "POSITIVE CONTROL — a NAMED value DOES lose its id, so the test above discriminates", () => {
  // Without this, a `personaLabel` that returned its input unchanged for
  // EVERYTHING would pass the test above. The pair is what makes either one mean
  // something.
  assert.equal( personaLabel( "cheech a6d0dd31", FALLBACK ), "cheech" );
  assert.notEqual( personaLabel( "cheech a6d0dd31", FALLBACK ), "cheech a6d0dd31" );
} );

test( "the id length is EXACT — eight, not seven and not nine", () => {
  // Off-by-one in either direction must leave the value whole, or the rule would
  // eat the last word of any name ending in hex-ish characters.
  assert.equal( personaLabel( "Rio 0e61abe",   FALLBACK ), "Rio 0e61abe"   );
  assert.equal( personaLabel( "sam 8353ea701", FALLBACK ), "sam 8353ea701" );
} );

// ----------------------------------------------------- absent, blank, non-string

test( "absent and blank yield the fallback", () => {
  assert.equal( personaLabel( null,      FALLBACK ), FALLBACK );
  assert.equal( personaLabel( undefined, FALLBACK ), FALLBACK );
  assert.equal( personaLabel( "",        FALLBACK ), FALLBACK );
  assert.equal( personaLabel( "   ",     FALLBACK ), FALLBACK );
} );

test( "a non-string yields the fallback rather than throwing", () => {
  // The store hands this a value read off JSON; a number or an object there is a
  // torn row, and a torn row must not take the pane down.
  assert.equal( personaLabel( 42 as unknown as string, FALLBACK ), FALLBACK );
  assert.equal( personaLabel( {} as unknown as string, FALLBACK ), FALLBACK );
} );

test( "the fallback is the CALLER's string, not a hard-coded em dash", () => {
  // Two callers pass two different fallbacks — "—" for the holding area and the
  // Finished-Tasks sentinel — so a literal here would be wrong for one of them.
  assert.equal( personaLabel( null, "unmeasured" ), "unmeasured" );
  assert.equal( personaLabel( "  ", "unmeasured" ), "unmeasured" );
} );

// ------------------------------------------------------------ shape and purity

test( "a value with no session id at all comes back untouched", () => {
  // Rick's rule: an unexpected format shown IN FULL is visibly odd and sends the
  // reader to the row; a truncated one would look like a name.
  assert.equal( personaLabel( "operator foolish goat", FALLBACK ), "operator foolish goat" );
  assert.equal( personaLabel( "reap-reconcile maya",   FALLBACK ), "reap-reconcile maya" );
} );

test( "the same input twice gives the same answer — the regex carries no state", () => {
  // A `/g` flag on the module-level regex would make `lastIndex` persist and the
  // second call would answer differently. This pins that it does not.
  assert.equal( personaLabel( "maria 3f74b922", FALLBACK ), "maria" );
  assert.equal( personaLabel( "maria 3f74b922", FALLBACK ), "maria" );
} );
