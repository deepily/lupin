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

/** The stored suffix: whitespace then exactly 8 hex characters, at the very end. */
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
 *     visibly odd and sends the reader to the row.
 *   - absent, blank, or a value that is nothing BUT a session id → `fallback`
 *   - pure: no DOM, never throws
 */
export function personaLabel( value: string | null | undefined, fallback: string ): string {
  if ( typeof value !== "string" ) return fallback;
  const raw = value.trim();
  if ( raw === "" ) return fallback;

  const stripped = raw.replace( TRAILING_SESSION_ID, "" ).trim();
  return stripped === "" ? fallback : stripped;
}
