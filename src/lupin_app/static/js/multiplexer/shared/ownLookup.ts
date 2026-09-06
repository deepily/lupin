// ONE refusal for every table lookup in the multiplexer client.
//
// 🔴 WHY THIS IS A SHARED FUNCTION AND NOT A THIRD `Object.hasOwn`.
// `TABLE[ key ] ?? fallback` walks the PROTOTYPE CHAIN. Ask any such table for
// `"toString"` and you get `Object.prototype.toString` — a FUNCTION, and truthy,
// so it sails past every `=== null` guard downstream and arrives where a spec or
// a sentence was expected. Measured on the verb table: `verbNeeds( "toString" )`
// returned the function, and its `.status` is `undefined`, so the caller would
// have POSTed a transition with NO TARGET STATUS rather than refusing.
//
// ⚠️ A FALSY wrong answer would have been caught by guards that already existed.
// This hole returns a TRUTHY wrong answer, which is why four ordinary
// unknown-verb cases all passed and only asking for `"toString"` caught it.
//
// 🔨 MARÍA'S RULING (2026-09-05, on Clayton 😎's F4 finding a THIRD copy):
// "A THIRD copy of the prototype-chain hole changes the fix shape — do not let
// it be patched in place a third time." Three instances is the tell that the
// SHAPE is the defect and the SITE is not, and this repo's own
// § WHEN THE FIX FOR AN ENUMERATION DEFECT IS ITSELF AN ENUMERATION says the
// third hand-written repair inherits the whole defect while looking like a fix.
//
// ⇒ THE PREDICATE, NOT A LIST OF PLACES THAT NEED IT: a table lookup answers
// only for keys the table OWNS.
//
// ⚠️ AND THE GUARD THAT KEEPS A FOURTH SITE FROM ARRIVING UNGUARDED IS NOT THIS
// FILE — a helper nobody is obliged to call prevents nothing. It is
// `src/tests/unit/multiplexer/no_lookup_walks_the_prototype_chain.test.ts`,
// which sweeps the client for the index-and-coalesce SHAPE and reddens on any
// occurrence outside this module. Named here so that deleting the guard is a
// visible act rather than a quiet one.

/**
 * Read `key` from `table`, answering ONLY for keys the table owns.
 *
 * Requires:
 *   - `table` is a plain object used as a lookup table
 *
 * Ensures:
 *   - an OWN key → its value
 *   - anything else → `fallback`, including every inherited `Object.prototype`
 *     member (`toString`, `constructor`, `valueOf`, `hasOwnProperty`, …)
 *   - never returns an inherited value, so a caller's `=== null` / falsy guard
 *     cannot be defeated by a truthy function arriving from the prototype
 *   - pure: reads only, never throws for a missing key
 */
export function ownLookup<T>(
  table    : Readonly<Record<string, T>>,
  key      : string,
  fallback : T,
): T {
  // ⚠️ THE CAST IS THE POINT OF THE GUARD, NOT A HOLE IN IT. Under
  // `noUncheckedIndexedAccess` an index read is typed `T | undefined` because
  // the compiler cannot know the key is present — `Object.hasOwn` is exactly the
  // proof it is asking for, and this is the ONE place in the client that has to
  // make that argument. Every call site gets `T` with no cast of its own.
  return Object.hasOwn( table, key ) ? ( table[ key ] as T ) : fallback;
}
