// 🔴 THE STALE-BUNDLE GATE — a merged file is not a built one.
//
// THE DEFECT THIS EXISTS FOR (row 75044ab5). The un-park verb was written,
// reviewed, merged, and passed 3363 tests. It was absent from
// `dist/multiplexer/boot.js`, whose mtime predated the work by FIFTEEN HOURS, so
// on the multiplexer the verb did not exist. Rick asked why it was missing and
// was told it was done.
//
// ⇒ RICK'S RULING, which is what this file enforces: *"it's fixed should mean
// that it's available to me to see and use."* Merged is not fixed. Green is not
// fixed. **Present in the artifact his browser loads** is fixed.
//
// WHY NOTHING CAUGHT IT. Every test in the TypeScript tier reads the SOURCE.
// Every user reads the BUNDLE. The TS path is compiled by esbuild into `dist/`,
// and a merge does not run that build — so the two can diverge indefinitely with
// the whole suite green. There was no instrument on that gap at all.
//
// ⚠️ WHY THIS COMPARES CONTENT AND NOT mtimes. The obvious gate is "fail if
// dist/ is older than its sources", and it is the wrong instrument: a fresh
// clone, a `git checkout`, or a rebase rewrites source mtimes wholesale, so that
// check goes red for everyone who did nothing wrong and gets disabled within a
// week. Content parity asks the question that actually matters — is the thing I
// wrote IN the thing you load — and it cannot be fooled by a timestamp.
//
// ⚠️ AND IT DELIBERATELY DOES NOT COMPARE AGAINST THE SHARED MODULE. The
// multiplexer's verb list is missing `fixed` while `shared/task-verbs.js` ships
// it (row 507183ff, still open). That is a REAL and separately-tracked defect,
// and folding it in here would make this gate red for a reason that has nothing
// to do with staleness — which is how a gate stops being read. This asks only:
// does the multiplexer's OWN source reach the multiplexer's OWN bundle.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_shipped_bundle_carries_the_source.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { TASK_VERBS } from "../../../lupin_app/static/js/multiplexer/render/taskVerbs";

const HERE      = path.dirname( fileURLToPath( import.meta.url ) );
// multiplexer → unit → tests → src → repo root. FOUR levels; three lands in
// `src/` and every path below silently points at nothing, which failed all five
// assertions at once rather than one — the tell that it was the reader, not the
// bundle.
const REPO_ROOT = path.resolve( HERE, "../../../.." );
const DIST_DIR  = path.join( REPO_ROOT, "src/lupin_app/static/dist/multiplexer" );
const BUNDLE    = path.join( DIST_DIR, "boot.js" );
const MANIFEST  = path.join( DIST_DIR, "manifest.json" );

function bundleSource(): string {
  assert.ok( existsSync( BUNDLE ),
    `no built bundle at ${ BUNDLE } — run \`npm run build\`. Until it exists the `
    + `multiplexer serves nothing, and every source-level test in this tier is `
    + `green about code no browser can load.` );
  return readFileSync( BUNDLE, "utf8" );
}

test( "🔴 EVERY VERB IN THE MULTIPLEXER'S SOURCE REACHES ITS BUILT BUNDLE", () => {
  const bundle = bundleSource();

  // The exact miss: `unpark` was in TASK_VERBS and absent from the bundle.
  const missing = TASK_VERBS.filter( ( verb ) => !bundle.includes( `"${ verb }"` ) );

  assert.deepEqual(
    missing, [],
    `these verbs are in the multiplexer source and NOT in the shipped bundle: `
    + `${ missing.join( ", " ) }. The source is merged and the artifact is stale — `
    + `run \`npm run build\`. A verb the browser cannot load is not shipped, `
    + `however green the suite is.`,
  );
} );

test( "the gate can actually fail — the verb list is non-empty and really is read", () => {
  // POSITIVE CONTROL. If `TASK_VERBS` were ever empty, or the import silently
  // resolved to nothing, the assertion above would pass over an empty array and
  // this whole file would be a green that measures nothing — which is the exact
  // failure mode it was written to prevent, one level up.
  assert.ok( TASK_VERBS.length >= 5,
    "the verb list must be non-trivial, or the parity check above is vacuous" );

  // And prove the haystack is the real artifact rather than an empty string.
  assert.ok( bundleSource().length > 10_000,
    "a bundle this small is not a real build; the check would pass on anything" );
} );

test( "🔴 THE TICKET LOOKUP REACHES THE BUNDLE TOO", () => {
  // Rick's findability P0 (row 732151f2) rides the SAME hazard the un-park verb
  // hit — it is a new control in the TS client, so it exists for him only once
  // the bundle is rebuilt. Named explicitly rather than trusting the verb sweep,
  // because the lookup is not a verb and no other assertion here would see it.
  assert.match( bundleSource(), /multiplexer-task-lookup/,
    "the ticket-lookup box is in source but not in the shipped bundle — run `npm run build`" );
} );

test( "the manifest names a hashed bundle that actually exists on disk", () => {
  // The page boots manifest-first (multiplexer.html) and falls back to the
  // stable boot.js. A manifest naming an absent file means every load takes the
  // fallback silently — so the hashed-asset scheme would be doing nothing while
  // looking installed, and a stale fallback is exactly what row 75044ab5 is about.
  assert.ok( existsSync( MANIFEST ), `no build manifest at ${ MANIFEST }` );

  const manifest = JSON.parse( readFileSync( MANIFEST, "utf8" ) ) as Record<string, string>;
  const hashed   = manifest[ "boot.js" ];

  assert.ok( hashed, "manifest is missing its 'boot.js' key — the page cannot resolve a bundle" );
  assert.ok( existsSync( path.join( DIST_DIR, hashed ) ),
    `manifest names ${ hashed }, which is not on disk — every page load would fall `
    + `back to the stable bundle without saying so` );
} );

test( "the stable bundle and the hashed one the manifest names are the same build", () => {
  // They are written by one build step, so a divergence means a partial or
  // interrupted build left two different answers to "what is the current
  // multiplexer" — and which one a viewer gets depends on whether the manifest
  // fetch succeeded.
  const manifest = JSON.parse( readFileSync( MANIFEST, "utf8" ) ) as Record<string, string>;
  const hashed   = readFileSync( path.join( DIST_DIR, manifest[ "boot.js" ] ), "utf8" );

  assert.equal( hashed.length, bundleSource().length,
    "the hashed bundle and the stable bundle differ — the build did not finish cleanly" );
} );

// ---------------------------------------------------------------------------
// 🔴 BEHAVIOUR PARITY, NOT ONLY PRESENCE — added by Mr. Radio 🦉 2026-09-09 with
// María's clearance, because THIS GATE DID NOT CATCH THE DEFECT IT SHOULD HAVE.
//
// THE MISS, MEASURED. Rick ruled the task list must sort priority-first and I
// changed all four comparators. Source correct, 3,288 unit tests green, and the
// SHIPPED bundle still carried the old status-first comparator. I found it by
// grepping the minified `boot.js` by hand. This file was green throughout.
//
// ⇒ WHY IT WAS BLIND. Every check above asks whether a NAME reaches the bundle —
// a verb string, the lookup box. My change altered no name: same functions, same
// identifiers, two lines swapped INSIDE one of them. A presence check cannot see
// a reordering, so the gate was answering a question I had not asked it.
//
// ⚠️ THE HONEST LIMIT OF THE FIX BELOW, stated rather than left to be discovered.
// This does NOT generalise. It pins ONE comparator's key order because that is
// the one that shipped stale today; the next stale bundle will be some other
// behaviour this file also cannot see. The general instrument is a source-hash
// stamped into the build and compared here — that is a bigger row, and naming it
// is not the same as having built it. Until then this file's denominator is
// "verbs + the lookup box + this one comparator", and a reader should not take
// its green as "the bundle is current".
// ---------------------------------------------------------------------------

test( "🔴 THE SHIPPED COMPARATOR SORTS PRIORITY BEFORE STATUS — Rick's 2026-09-09 ruling", () => {
  // Matched against the MINIFIED bundle, so it must not depend on identifier
  // names — esbuild renames everything. The invariant that survives minification
  // is the ORDER of the two subtractions inside byUrgency: the priority pair is
  // read first, the status pair second. esbuild's keepNames wrapper leaves the
  // literal "byUrgency" adjacent, which is what anchors the search.
  const src = bundleSource();

  const comparators = src.match( /\.priority\)[\s\S]{0,80}?\.status\)[\s\S]{0,60}?"byUrgency"/g ) ?? [];
  const reversed    = src.match( /\.status\)[\s\S]{0,80}?\.priority\)[\s\S]{0,60}?"byUrgency"/g ) ?? [];

  // POSITIVE CONTROL FIRST: a zero here means the regex found nothing at all —
  // a renamed wrapper or a changed minifier — and a "no reversed copies" pass
  // would then be vacuous rather than reassuring. Assert we can SEE the thing
  // before asserting anything about it.
  assert.ok( comparators.length > 0,
    "found no byUrgency comparator in the bundle at all — this check has gone blind "
    + "(minifier or wrapper changed); fix the matcher before trusting a green here" );

  // Both copies — taskListModel and epicBoardModel each declare their own.
  assert.equal( comparators.length, 2,
    `expected 2 priority-first comparators in the bundle, found ${ comparators.length } — `
    + `the multiplexer declares byUrgency twice (taskListModel, epicBoardModel)` );

  assert.equal( reversed.length, 0,
    "the shipped bundle contains a STATUS-FIRST byUrgency — the source was changed to "
    + "priority-first but this build predates it, or one of the two copies was missed. "
    + "Run `npm run build`." );
} );
