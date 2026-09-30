// THE MULTIPLEXER OFFERS EVERY VERB THE SHARED MODULE SHIPS — the guard that was missing.
//
// 🔴 THE ORACLE IS THE SHARED MODULE; THE MULTIPLEXER IS ONLY EVER THE OBSERVATION.
// This is the same design as the notifications client's
// `every_pane_offers_and_routes_every_verb.test.ts`, deliberately, because that
// guard is the reason the un-park gap surfaced within a day:
//
//     ORACLE   (expected)  shared/task-verbs.js — TASK_VERB_SPECS
//     OBSERVED             what taskVerbs.ts declares and what verbLegality offers
//     assert               observed ⊇ oracle
//
// ⚠️ NOTHING HERE RE-TYPES THE VERB LIST. Reading the expected set off the
// multiplexer's own list is the failure mode this file exists to close: a list that
// drops a verb would stop being expected to have it, and the guard would go green on
// exactly the defect it was written for. The oracle must come from the other side.
//
// 🔴 WHY THIS FILE EXISTS AT ALL — the same defect fired TWICE in one week, in
// opposite directions, between the same two clients:
//   · row 75044ab5 — `unpark` shipped in the shared module and in notifications.js,
//     and the multiplexer's built bundle never had it.
//   · row 507183ff — `fixed` shipped in the shared module and in notifications.js,
//     and the multiplexer's hand-written list never had it. Live LONGER than the
//     first one, and asserted in place: `task_verbs.test.ts` pinned the six-verb list
//     against ITSELF, so a test was holding the defect still.
//
// ⇒ The lesson is not "add the verb". It is that **the shared module was not
// actually shared** — two clients each kept a hand-written copy of one vocabulary
// and nothing compared either copy to the module. One side had a guard; this side
// did not. Now both do.
//
// ⚠️ WHAT THIS FILE DOES NOT DO. It does not assert the two clients RENDER the verb
// identically, and it does not open a browser. It asserts the multiplexer's
// declared vocabulary and its legality table account for every verb the module
// ships. Whether the built bundle carries them is a different question, answered by
// `the_shipped_bundle_carries_the_source.test.ts` — source parity and delivery are
// separate failures and deserve separate guards.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/the_multiplexer_offers_every_shared_verb.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

// THE ORACLE.
import { TASK_VERB_SPECS, TASK_VERBS as SHARED_VERBS } from "../../../../lupin_app/static/js/shared/task-verbs.js";

// THE OBSERVATION.
import {
  TASK_VERBS as MUX_VERBS,
  verbNeeds,
  verbLabel,
  verbLegality,
} from "../../../../lupin_app/static/js/multiplexer/render/taskVerbs.js";

/** Statuses a row can hold. Terminal ones offer nothing, by design. */
const OPEN_STATUSES     = [ "queued", "in_progress", "blocked", "claimed", "review", "parked", "not_approved" ];
const TERMINAL_STATUSES = [ "done", "dropped", "wont_fix" ];

test( "positive control: the oracle is non-empty and really was read", () => {
  // Without this, every assertion below could be looping over an empty set and
  // reporting agreement. A guard that cannot fail is not a guard.
  assert.ok( SHARED_VERBS.length >= 6, `the shared module must ship a real verb list; got ${ SHARED_VERBS.length }` );
  assert.ok( Object.keys( TASK_VERB_SPECS ).length === SHARED_VERBS.length,
    "the shared list and its spec table must describe the same verbs" );
  assert.ok( SHARED_VERBS.includes( "fixed" ), "the oracle must carry `fixed`, or this file is testing nothing" );
} );

test( "🔴 EVERY VERB THE SHARED MODULE SHIPS IS DECLARED BY THE MULTIPLEXER", () => {
  // The assertion row 507183ff was filed for. Before this guard, `fixed` was absent
  // here and NOTHING said so.
  const missing = SHARED_VERBS.filter( ( v ) => !MUX_VERBS.includes( v ) );
  assert.deepEqual( missing, [],
    `the multiplexer cannot offer ${ missing.join( ", " ) } — the shared module ships it and this list does not` );
} );

test( "the multiplexer invents no verb the shared module does not ship", () => {
  // The other direction. A verb only the multiplexer knows is the same drift wearing
  // the opposite costume, and it would reach the store as a status nothing else maps.
  const extra = MUX_VERBS.filter( ( v ) => !SHARED_VERBS.includes( v ) );
  assert.deepEqual( extra, [], `the multiplexer offers ${ extra.join( ", " ) }, which the shared module does not ship` );
} );

test( "the two lists agree on ORDER, not merely on membership", () => {
  // Order is what the operator sees. Two lists with the same members in different
  // orders put a terminal verb somewhere different on each client, which is exactly
  // the kind of "both clients have it" that still gets someone the wrong click.
  assert.deepEqual( [ ...MUX_VERBS ], [ ...SHARED_VERBS ] );
} );

test( "🔴 EVERY SHARED VERB CARRIES ITS OBLIGATIONS HERE, AND THEY MATCH THE MODULE", () => {
  // A verb in the list with no entry in the obligations table is worse than a missing
  // verb: it renders, it is clickable, and it posts nothing coherent.
  for ( const verb of SHARED_VERBS ) {
    const spec  = TASK_VERB_SPECS[ verb as keyof typeof TASK_VERB_SPECS ] as Record<string, unknown>;
    const needs = verbNeeds( verb );

    assert.ok( needs, `${ verb } is declared but has no obligations entry` );
    assert.equal( needs!.status, spec.status,
      `${ verb } posts to_status "${ needs!.status }" here and "${ String( spec.status ) }" in the shared module` );
    assert.equal( needs!.reason, spec.reason,
      `${ verb } disagrees about whether a reason is required` );
    assert.equal( needs!.date, spec.date,
      `${ verb } disagrees about whether a date is required` );
    // The module calls it `armsTwice` — behaviour, not a store fact — and this client
    // calls it `terminal`. Same obligation, two names; assert across the rename rather
    // than letting the rename hide a disagreement.
    assert.equal( needs!.terminal, spec.armsTwice,
      `${ verb } disagrees about whether it arms twice / is terminal` );
  }
} );

test( "every shared verb has a human label on this client, and it is not the raw key", () => {
  // ⚠️ THIS DELIBERATELY DOES NOT ASSERT label EQUALITY WITH THE MODULE, and the
  // reason is a finding rather than a shortcut. The first cut of this test did assert
  // it and reddened immediately on `wont_fix`: the shared module's spec says
  // "Won't-fix" and this client says "Won't fix". Measured before concluding —
  // notifications.js:10519 hardcodes "Won't fix" too, so BOTH clients agree with each
  // other and the module's `label` field agrees with NEITHER. It is not the source of
  // any rendered label; each client carries its own copy.
  //
  // ⇒ So a label-equality assertion here would pin a relationship that has never held
  // and that nothing depends on, and "fixing" it means changing a user-visible string
  // on a verb this row is not about. That is laundering an unrelated omission into
  // this diff — the move Sam correctly refused on THIS VERY FILE, and the refusal is
  // why row 507183ff exists to be worked at all.
  //
  // ⇒ Named, not absorbed. If the label field should be the single source, that is its
  // own row: three copies of every label (module, multiplexer, notifications.js) is
  // the same not-actually-shared shape this file guards one layer up.
  for ( const verb of SHARED_VERBS ) {
    const label = verbLabel( verb );
    assert.notEqual( label, verb, `${ verb } falls through to its raw key — no label is defined` );
    assert.ok( label.trim().length > 0, `${ verb } has a blank label` );
  }
} );

test( "the label drift above is REAL and still there — a canary, not a claim", () => {
  // A test that documents a divergence must FAIL when the divergence is fixed, or the
  // comment above rots into a lie the moment someone aligns the two. This is the
  // canary: when `wont_fix` finally agrees, this reddens and the note gets deleted
  // with it.
  assert.notEqual( verbLabel( "wont_fix" ), TASK_VERB_SPECS.wont_fix.label,
    "wont_fix labels now AGREE — delete this canary and the note above it" );
  // And the verb this row IS about must agree, because it was written today from the
  // module's own spec.
  assert.equal( verbLabel( "fixed" ), TASK_VERB_SPECS.fixed.label );
} );

test( "🔴 EVERY SHARED VERB IS OFFERED BY verbLegality ON EVERY STATUS", () => {
  // Declaring a verb and never OFFERING it is the same defect one layer down — the
  // operator cannot click a row the legality table does not return.
  for ( const status of [ ...OPEN_STATUSES, ...TERMINAL_STATUSES ] ) {
    const offered = verbLegality( status ).map( ( e ) => e.verb );
    assert.deepEqual( offered, [ ...SHARED_VERBS ],
      `on a ${ status } row the multiplexer offers [${ offered.join( ", " ) }]` );
  }
} );

test( "`fixed` is ENABLED on open rows and greyed on terminal ones, with a reason", () => {
  // The specific behaviour row 507183ff asks for, stated as behaviour rather than as
  // presence. The shared spec carries legalFrom: null / illegalFrom: null, so nothing
  // narrows it below "any non-terminal row".
  for ( const status of OPEN_STATUSES ) {
    const entry = verbLegality( status ).find( ( e ) => e.verb === "fixed" )!;
    assert.equal( entry.enabled, true, `a ${ status } row cannot be marked fixed` );
    assert.equal( entry.why, "", "an enabled verb must carry no refusal text" );
  }
  for ( const status of TERMINAL_STATUSES ) {
    const entry = verbLegality( status ).find( ( e ) => e.verb === "fixed" )!;
    assert.equal( entry.enabled, false, `a ${ status } row is terminal and must not offer fixed` );
    assert.ok( entry.why.includes( status ), `the refusal must name the row's own status; got "${ entry.why }"` );
  }
} );

test( "`fixed` closes the row to `done` — the positive terminal verb the board lacked", () => {
  // Rick's complaint, row 1e12cc08: a board whose only human-driven terminal verb is a
  // NEGATIVE one drifts toward an inflated open count, and the create/close ratio gate
  // reads that count. `wont_fix` counts toward the ratio and `dropped` does not, so
  // which terminal verb exists is not bookkeeping.
  const needs = verbNeeds( "fixed" )!;
  assert.equal( needs.status, "done" );
  assert.equal( needs.reason, false, "a fix explains itself; a mandatory note here was rejected as friction" );
  assert.equal( needs.terminal, true, "`done` is append-only, so a misclick is not undoable — it must arm twice" );
} );
