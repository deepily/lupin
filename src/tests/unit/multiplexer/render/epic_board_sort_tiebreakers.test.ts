// Row 87812328 — the two epic-board sort TIE-BREAKERS, which are the last legs of
// two comparators nothing had ever driven.
//
// 🔴 A COMPARATOR'S LATER LEGS ARE INVISIBLE TO A FIXTURE WHOSE ROWS ALL DIFFER.
// `byEpic`'s sort falls through unassigned-last → bigger-bucket-first → key, and
// `onRick`'s falls through priority → id. Every existing fixture separates its
// rows on the FIRST leg, so the fallthroughs ran zero times while both files sat
// at 100% lines and 100% functions. Coverage answers "did this line run", never
// "could the test have noticed it running wrong" — and for a comparator the two
// come apart the moment two rows tie.
//
// ⇒ So each test below builds a deliberate TIE on every earlier leg. That is the
// only shape that reaches the leg under test, and it is why these read as
// fussily-constructed fixtures rather than realistic ones.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/epic_board_sort_tiebreakers.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  groupTasksByEpic,
  EPIC_UNASSIGNED_KEY,
} from "../../../../lupin_app/static/js/multiplexer/render/epicBoardModel";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

/** A row bucketed under `key`, which must carry the epic prefix to bucket at all. */
function inEpic( key: string, over: Partial<TaskItem> = {} ): TaskItem {
  return { title: "t", status: "queued", priority: "P1", correlation_key: key, ...over } as TaskItem;
}

/** A row blocked on Rick — BOTH halves matter: the id AND a user/persona kind. */
function onRick( over: Partial<TaskItem> = {} ): TaskItem {
  return {
    title: "t", status: "queued", priority: "P1",
    blocked_by: [ { id: "rick", kind: "user" } ],
    ...over,
  } as TaskItem;
}

test( "POSITIVE CONTROL: the fixtures actually bucket and actually reach Rick's list", () => {
  // Without this, every ordering assertion below is satisfied by a model that
  // produced no groups and no onRick rows at all — a comparison over two empty
  // arrays is green, and an absence prints exactly like a correct order.
  const m = groupTasksByEpic( [ inEpic( "epic:alpha" ), onRick() ] );
  assert.equal( m.groups.length, 1, "the epic fixture did not bucket — check the key prefix" );
  assert.equal( m.onRick.length, 1, "the blocked-on-Rick fixture did not register" );
  assert.equal( m.totalCount, 2 );
} );

test( "🔴 THE UNASSIGNED EPIC SORTS LAST, whatever its size — the leg no fixture had reached", () => {
  // The unassigned bucket is given the BIGGEST size here on purpose. Under the
  // size leg alone it would come first; only the unassigned-last leg puts it at
  // the end. A fixture where it is also the smallest proves nothing, because
  // both legs would agree.
  const m = groupTasksByEpic( [
    inEpic( EPIC_UNASSIGNED_KEY ),
    inEpic( EPIC_UNASSIGNED_KEY ),
    inEpic( EPIC_UNASSIGNED_KEY ),
    inEpic( "epic:alpha" ),
  ] );

  assert.deepEqual( m.groups.map( ( g ) => g.epicKey ), [ "epic:alpha", EPIC_UNASSIGNED_KEY ],
    "the unassigned bucket did not sort last. It is the biggest here, so a size-only " +
    "comparator puts it FIRST — which is the wrong answer this leg exists to prevent" );
} );

test( "two epics of EQUAL size fall through to the key, so a render never reshuffles them", () => {
  // The size leg ties deliberately; without that, the key leg is unreachable and
  // the order below would be a fact about the input order instead of the sort.
  const m = groupTasksByEpic( [
    inEpic( "epic:zulu" ), inEpic( "epic:zulu" ),
    inEpic( "epic:alpha" ), inEpic( "epic:alpha" ),
  ] );

  assert.deepEqual( m.groups.map( ( g ) => g.epicKey ), [ "epic:alpha", "epic:zulu" ],
    "two equal-sized epics no longer order by key — the generator's sort_key parity is " +
    "gone and two renders of the same data can disagree" );
} );

test( "🔴 AN ID-LESS ROW ON RICK'S LIST STILL ORDERS — the `|| \"\"` leg", () => {
  // Both rows are P1, so the priority leg ties and the id leg is the only thing
  // deciding. One row carries NO id: `String( a.id || "" )` is what stops that
  // becoming `String( undefined )` → the literal "undefined", which sorts
  // between "b" and "z" rather than first and would be invisible in any
  // assertion that only checked the pair was ordered somehow.
  const m = groupTasksByEpic( [
    onRick( { id: "bbb", title: "has an id" } ),
    onRick( { title: "no id at all" } ),
  ] );

  assert.equal( m.onRick.length, 2 );
  assert.deepEqual( m.onRick.map( ( t ) => t.title ), [ "no id at all", "has an id" ],
    'the id-less row did not sort first. If `|| ""` were dropped it would stringify to ' +
    '"undefined" and sort AFTER "bbb", which is an ordering nobody chose' );
} );

test( "and Rick's list still leads with priority when the priorities DIFFER", () => {
  // The control for the test above: it shows the id leg is a FALLTHROUGH and not
  // the primary key. Without it, a comparator that sorted by id alone would pass
  // the previous test and be wrong about every ordinary case.
  const m = groupTasksByEpic( [
    onRick( { id: "aaa", priority: "P3", title: "low but early id" } ),
    onRick( { id: "zzz", priority: "P0", title: "urgent but late id" } ),
  ] );

  assert.deepEqual( m.onRick.map( ( t ) => t.title ), [ "urgent but late id", "low but early id" ],
    "priority is no longer the leading leg on Rick's list — the id tie-breaker has been " +
    "promoted over urgency" );
} );
