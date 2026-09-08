/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// ONE rule for turning a stored actor/filer string into the name a reader sees.
//
// 🔴 WHY THIS IS A SHARED FUNCTION AND NOT A THIRD COPY OF THE REGEX.
// The store holds `<persona> <8-hex session>`, and a persona CAN BE TWO WORDS. The
// obvious implementation — `value.split( /\s+/ )[ 0 ]` — renders "mr radio 8353ea70"
// as "mr". Measured by María 2026-09-02: WRONG ON 6 OF 13 LIVE ROWS, and those six
// are exactly the ones Rick asked about, so the naive form fails hardest precisely
// where the feature is for.
//
// ⚠️ AND IT HAS ALREADY BEEN RE-DERIVED ONCE. `holdingAreaModel.taskFilerLabel` got
// it right and carried a docstring saying so; `finishedTasksModel.actorPersona`, in a
// neighbouring file in the same client, was written months later with the naive split
// and shipped it to the WHO column (row 4a06ded1). A warning in a docstring is not a
// control — the next author has no reason to read a file they are not editing.
//
// 🔨 MARÍA'S RULING (2026-09-07): "Export taskFilerLabel's regex helper or extract a
// shared one to avoid three implementations of the same rule." Same shape as her
// 2026-09-05 ruling that produced `ownLookup`: once a rule has been written twice and
// got it wrong once, the SHAPE is the defect and the SITE is not.
//
// ⇒ THE PREDICATE, NOT A LIST OF PLACES THAT NEED IT: strip a TRAILING session id;
// never keep a leading word.
//
// ⚠️ SCOPE — MULTIPLEXER ONLY. The legacy client has its own copy and that is
// deliberate: Rick's no-shared-code ruling (87812328) means the two clients reproduce
// behaviour independently. This is one rule for THIS client, not for both.

/**
 * The stored suffix: whitespace then exactly 8 hex characters, at the very end.
 *
 * 🔴 THE `\s+` IS LOAD-BEARING AND A BARE ID IS DELIBERATELY NOT A MATCH. `"0e61abe3"`
 * with no name in front of it renders WHOLE, not as the fallback — pinned by
 * `holding_area_model.test.ts` ("a bare session id with no name is shown WHOLE — visibly
 * odd, by design") and by the JS-PARITY corpus in the same file, entry
 * `[ "0e61abe3", "0e61abe3" ]`, which locks this client to the legacy card under Rick's
 * no-shared-code ruling `87812328`.
 *
 * ⚠️ DO NOT "FIX" THIS TO `/(?:^|\s+)[0-9a-f]{8}$/i`. It looks like the obvious repair —
 * it makes the unreachable arm below reachable and closes a coverage hole — and it was
 * tried on 2026-09-08 and REVERTED. Measured: it reddens those two named tests, and it
 * diverges the two clients, which is the one thing the parity corpus exists to prevent.
 */
const TRAILING_SESSION_ID = /\s+[0-9a-f]{8}$/i;

/**
 * The display name inside a stored `<persona> <8-hex session>` value.
 *
 * Requires:
 *   - `value` is the raw stored string, or null/undefined
 *
 * Ensures:
 *   - "mr radio 8353ea70" → "mr radio"   (a TWO-WORD persona survives)
 *   - "krishna 420f5ec9"  → "krishna"
 *   - no trailing session id → the WHOLE string, untouched. A truncated name is a
 *     WRONG name wearing a right one's clothes; an unexpected format shown in full is
 *     visibly odd and sends the reader to the row. A BARE session id is this case, not
 *     an exception to it — see the regex note above.
 *   - absent or blank → `fallback`
 *   - pure: no DOM, never throws
 *
 * 🔴 THIS CONTRACT USED TO CARRY A FOURTH CLAUSE — "or a value that is nothing BUT a
 * session id → `fallback`" — AND IT WAS NEVER TRUE. It contradicted the clause above it,
 * no code implemented it, and two tests named for `taskFilerLabel` assert the opposite.
 * Removed 2026-09-08 rather than implemented: the code and the tests already agreed with
 * each other, and the docstring was the outlier.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function personaLabel( value: string | null | undefined, fallback: string ): string {
  if ( typeof value !== "string" ) return fallback;
  const raw = value.trim();
  if ( raw === "" ) return fallback;

  const stripped = raw.replace( TRAILING_SESSION_ID, "" ).trim();

  // 🔴 THE `fallback` ARM IS UNREACHABLE BY CONSTRUCTION, AND IT IS KEPT ON PURPOSE.
  // `raw` is trimmed, so `raw[ 0 ]` is never whitespace; `TRAILING_SESSION_ID` requires
  // whitespace before the id, so a match can never start at index 0; so the unmatched
  // prefix always survives and always begins with a non-whitespace character; so
  // `stripped` is never "". Measured 2026-09-08 against this module through tsx: 628
  // inputs — every JS whitespace character crossed with five session-id shapes — reached
  // it ZERO times, while `personaLabel( null )` and `personaLabel( "   " )` DID reach the
  // fallback through the two guards above, so the probe could see a hit and found none.
  //
  // ⚠️ IT IS NOT DELETED BECAUSE IT GUARDS THE REGEX, NOT THE INPUT. Widen
  // `TRAILING_SESSION_ID` to match at index 0 and `stripped` becomes reachable-empty the
  // same day; without this arm that renders an EMPTY cell instead of the fallback. The
  // arm costs one branch and removes a whole failure mode from a future edit.
  /* c8 ignore next */ // unreachable while the regex requires leading whitespace — argued and measured above; no test can reach it.
  return stripped === "" ? fallback : stripped;
}
