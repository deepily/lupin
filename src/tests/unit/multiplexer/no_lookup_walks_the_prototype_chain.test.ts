// Row 87812328 — Clayton 😎's F4, and the answer to María 🌸's condition on it.
//
// 🔴 THE FINDING WAS A THIRD COPY OF ONE DEFECT, AND THAT CHANGES THE FIX.
// `TABLE[ key ] ?? fallback` walks the prototype chain: ask for `"toString"` and
// you get `Object.prototype.toString` — truthy, so it passes every `=== null`
// guard downstream, with `.status` undefined, so the caller POSTs a transition
// with no target status instead of refusing. `7fddc864` killed it at four sites
// and left `rowSchema.ts:81` standing. Its own commit message: "leaving one of
// two identical defects standing is how it returns wearing a different call site."
//
// 🔨 MARÍA'S RULING: "A THIRD copy changes the fix shape — do not let it be
// patched in place a third time." So the repair is ONE shared refusal,
// `shared/ownLookup.ts`, and her condition was that whoever writes it must ALSO
// name how a FOURTH call site is prevented from arriving unguarded.
//
// ⇒ THIS FILE IS THAT ANSWER. A helper nobody is obliged to call prevents
// nothing; the population is derived from the TREE, not from a list of the
// sites we happen to know about — which would be the enumeration defect
// repairing itself with an enumeration, one level up.
//
// ═══════════════════════════════════════════════════════════════════════════
// ⚠️ WHAT THIS GUARD IS NOT — read before trusting it
// ═══════════════════════════════════════════════════════════════════════════
// It is a SOURCE-TEXT sweep. This repo's § A HIT IS NOT A USE says a grep finds
// the NAME and the question is almost always about the USE, and that applies
// here to the letter:
//
//   · it finds the SHAPE, so a lookup written some other way — a `Map`, a
//     destructure, a helper of someone's own — is invisible to it
//   · a coalesce over something that is NOT a lookup table is a FALSE POSITIVE,
//     and the remedy is the allow-list below, which is itself hand-maintained
//     and therefore itself a small enumeration
//
// It is mechanical prevention, not proof. It is here because the alternative on
// offer was remembering, and this fleet's own doctrine is that a rule which
// depends on remembering is not installed.
//
// Run: npx tsx --test src/tests/unit/multiplexer/no_lookup_walks_the_prototype_chain.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join, relative } from "node:path";

import { ownLookup } from "../../../lupin_app/static/js/multiplexer/shared/ownLookup";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const MUX  = resolve( HERE, "../../../lupin_app/static/js/multiplexer" );

/**
 * `IDENT[ … ] ?? …` — an index read coalesced against a fallback.
 *
 * ⚠️ Anchored on an IDENTIFIER before the bracket so `arr[ i ] ?? x` over a
 * local array is caught too; a table and an array are indistinguishable in
 * source text, which is one of the reasons this sweep needs an allow-list.
 */
const INDEX_COALESCE = /\b([A-Za-z_$][\w$]*)\s*(?:as\s+[^)]*\)?\s*)?\[\s*(?!["'`])[^\]\n]+\]\s*\?\?/;

// 🔴 A QUOTED KEY IS EXCLUDED, AND THAT IS A JUDGEMENT WORTH STATING RATHER THAN
// BURYING IN A REGEX. `raw[ "id_hash" ] ?? raw[ "job_id" ]` cannot walk the
// prototype chain in the way this guard is about: the key is a literal the
// AUTHOR chose, not a string arriving from a server, a peer's message body or a
// URL. The hazard is a DATA-DERIVED key reaching an inherited member; an author
// who types `raw[ "toString" ]` has written a different bug, and a guard that
// cannot tell the two apart flags six harmless lines for every real one and
// then gets switched off.
//
// ⚠️ THE COST OF THIS EXCLUSION, said plainly: a data-derived key that happens to
// be spelled as a literal somewhere is invisible to the sweep. That is the
// trade — see the caveat block at the top of this file.

/** Every `.ts` under the multiplexer client, excluding tests. */
function clientFiles( dir: string = MUX ): string[] {
  const out: string[] = [];
  for ( const entry of readdirSync( dir ) ) {
    const full = join( dir, entry );
    if ( statSync( full ).isDirectory() ) { out.push( ...clientFiles( full ) ); continue; }
    if ( entry.endsWith( ".ts" ) && !entry.endsWith( ".test.ts" ) ) out.push( full );
  }
  return out;
}

// Hand-maintained, and every entry carries WHY. An allow-list with unexplained
// members is how a guard is quietly widened until it matches nothing.
const ALLOWED: ReadonlyArray<{ file: string; why: string }> = [
  { file : "shared/ownLookup.ts",
    why  : "the shared refusal itself — it IS the guarded index read" },
  { file : "render/html.ts",
    why  : "`strings[ i ]` walks a TemplateStringsArray by a NUMERIC loop index, " +
           "not a table by a data-derived string key. An array index cannot reach " +
           "`Object.prototype.toString`, and the line already carries its own " +
           "c8 pragma explaining the `?? \"\"` is defensive. Read before allowing: " +
           "html.ts:148-150." },
];

function findings(): Array<{ file: string; line: number; text: string }> {
  const hits: Array<{ file: string; line: number; text: string }> = [];
  for ( const full of clientFiles() ) {
    const rel = relative( MUX, full ).split( "\\" ).join( "/" );
    if ( ALLOWED.some( ( a ) => a.file === rel ) ) continue;
    readFileSync( full, "utf8" ).split( "\n" ).forEach( ( line, i ) => {
      const code = line.trimStart();
      if ( code.startsWith( "//" ) || code.startsWith( "*" ) ) return;   // prose, not code
      if ( INDEX_COALESCE.test( line ) ) hits.push( { file: rel, line: i + 1, text: line.trim() } );
    } );
  }
  return hits;
}

test( "the sweep reaches a real population AND can actually find the shape", () => {
  // 🔴 TWO CONTROLS, because either alone is satisfiable by a broken sweep.
  const files = clientFiles();
  assert.ok( files.length >= 40,
    `the file walk found only ${ files.length } client sources — it is not reaching the tree` );

  // A PLANTED positive control. Without it, "no findings" is indistinguishable
  // from "the regex matches nothing ever", which is this repo's § AN EMPTY
  // RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE.
  assert.ok( INDEX_COALESCE.test( 'return ( LABELS as Record<string, string> )[ field ] ?? field;' ),
    "the regex no longer matches the exact line this guard was written for — " +
    "rowSchema.ts:81 as it stood before the fix. It is now blind to its own subject" );
  assert.ok( INDEX_COALESCE.test( 'const n = NEEDS[ verb ] ?? null;' ),
    "the regex no longer matches a bare index-and-coalesce" );
  assert.ok( !INDEX_COALESCE.test( 'const x = ownLookup( NEEDS, verb, null );' ),
    "the regex matches the SHARED REFUSAL — it would flag the fix as the defect" );
} );

test( "🔴 NO LOOKUP IN THE MULTIPLEXER CLIENT WALKS THE PROTOTYPE CHAIN", () => {
  const hits = findings();
  assert.deepEqual( hits.map( ( h ) => `${ h.file }:${ h.line }` ), [],
    `these read a table by index and coalesce, which answers for INHERITED keys:\n` +
    hits.map( ( h ) => `  ${ h.file }:${ h.line }  ${ h.text }` ).join( "\n" ) +
    `\n\nUse ownLookup( table, key, fallback ) from shared/ownLookup.ts. If this is a ` +
    `FALSE POSITIVE — an index over an array or a non-table — add the file to ALLOWED ` +
    `above WITH ITS REASON. Do not delete this test, and do not patch the site in ` +
    `place: three in-place repairs is what produced the shared helper.` );
} );

test( "the shared refusal actually refuses — every inherited member, not just toString", () => {
  // ⚠️ THE GUARD ABOVE IS ABOUT SHAPE AND PROVES NOTHING ABOUT BEHAVIOUR. This
  // is the behavioural half, and it drives the real exported function.
  const table = { park: "PARKED" } as Record<string, string>;

  assert.equal( ownLookup( table, "park", "FALLBACK" ), "PARKED", "an own key must still resolve" );

  // Every one of these returns a TRUTHY value under `table[ k ] ?? fallback`,
  // which is why a falsy-guard downstream never caught the defect.
  for ( const inherited of [ "toString", "constructor", "valueOf", "hasOwnProperty",
                             "isPrototypeOf", "propertyIsEnumerable", "toLocaleString" ] ) {
    assert.equal( ownLookup( table, inherited, "FALLBACK" ), "FALLBACK",
      `ownLookup answered for the inherited member ${ inherited } — the prototype chain is ` +
      `still reachable, and a caller's null-check cannot see a function arriving where a ` +
      `spec belongs` );
    // And the control that makes the assertion above mean something: the naked
    // form really does leak, so this is a difference the fix creates.
    assert.notEqual( ( table[ inherited ] ?? "FALLBACK" ), "FALLBACK",
      `the naked index-and-coalesce no longer leaks ${ inherited } — if the runtime changed, ` +
      `this whole guard is describing a hazard that no longer exists and should be re-derived` );
  }

  assert.equal( ownLookup( table, "no-such-verb", "FALLBACK" ), "FALLBACK" );
} );
