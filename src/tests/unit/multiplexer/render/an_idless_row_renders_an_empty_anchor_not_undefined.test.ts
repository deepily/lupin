// Row 87812328 — the three `?? ""` / unassigned-key branches the coverage gate
// named at 99.74%, and why each gets a TEST rather than a `c8 ignore`.
//
// THE GATE'S RECEIPT, taken BEFORE this file existed, from lcov BRDA records on
// the whole-tier run at de5166b7 (3184 pass / 0 fail, branches 5857/5872):
//     rowDisclosure.ts   BRDA line=129 block=24 branch=0 taken=0
//     rowDisclosure.ts   BRDA line=168 block=29 branch=0 taken=0
//     epicBoardModel.ts  BRDA line=134 block=51 branch=0 taken=0
// `taken=0` is the claim this file answers. c8's text column was NOT used to
// find these — that column is not a stable inventory, per a9c5c258 on this
// branch, which measured a gap surfacing only once its neighbours closed.
//
// 🔴 WHY NOT A PRAGMA. All three are REACHABLE, and two of them say so in their
// own signatures: `renderControlsRow( taskId: string | null | undefined, ... )`
// and `renderErrorStripe( taskId: string | null | undefined )` both DECLARE the
// nullish case. A branch whose own type says the input is optional is not a
// defensive branch — it is a documented input nobody had exercised. The third is
// a sort comparator that must place the unassigned bucket last, which is a
// stated parity requirement, not a guard.
//
// WHAT GOES WRONG WITHOUT THEM. `taskId ?? ""` is what stops the attribute
// reading the literal string "undefined". That is not cosmetic: TaskListRenderer
// resolves a control's owner with
// `controlsRow.getAttribute( "data-controls-for" )` and then compares the result
// against real task ids. An attribute reading "undefined" is a NON-EMPTY string,
// so it passes the `id === ""` guard the renderer uses to refuse an idless row,
// and the row is then treated as a task named "undefined" — a silent mutation
// aimed at nothing, which is the exact shape of defect D-A recorded in
// `taskIdOf`'s header.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const RD = () => import( "../../../../lupin_app/static/js/multiplexer/render/templates/rowDisclosure" );
const EM = () => import( "../../../../lupin_app/static/js/multiplexer/render/epicBoardModel" );

// ------------------------------------------------- rowDisclosure.ts:129

test( "POSITIVE CONTROL: a real id reaches data-controls-for unchanged", async () => {
  // Without this, every assertion below is satisfied by a function that writes
  // "" no matter what it is handed — a coalesce that always fires looks exactly
  // like a coalesce that fires correctly.
  const { renderControlsRow } = await RD();
  const tr = renderControlsRow( "aaaa1111-2222-3333-4444-555566667777", "task-status-queued", {} );
  assert.equal( tr.getAttribute( "data-controls-for" ), "aaaa1111-2222-3333-4444-555566667777" );
} );

test( "🔴 renderControlsRow( null ) writes an EMPTY anchor, never the string \"undefined\"", async () => {
  const { renderControlsRow } = await RD();
  const tr = renderControlsRow( null, "task-status-queued", {} );

  assert.equal( tr.getAttribute( "data-controls-for" ), "",
    "an idless controls row did not anchor on the empty string — if this reads \"undefined\" or " +
    "\"null\" it is a NON-EMPTY id that passes TaskListRenderer's `id === \"\"` refusal, and the " +
    "row is mutated as a task by that name" );
  assert.notEqual( tr.getAttribute( "data-controls-for" ), "undefined" );
  assert.notEqual( tr.getAttribute( "data-controls-for" ), "null" );
} );

test( "🔴 renderControlsRow( undefined ) does the same — both nullish spellings", async () => {
  // `?? ""` catches null AND undefined; a `|| ""` written in its place would also
  // swallow a legitimately falsy id, so the two spellings are asserted apart.
  const { renderControlsRow } = await RD();
  const tr = renderControlsRow( undefined, "task-status-queued", {} );
  assert.equal( tr.getAttribute( "data-controls-for" ), "" );
} );

// ------------------------------------------------- rowDisclosure.ts:168

test( "POSITIVE CONTROL: a real id reaches data-error-for unchanged", async () => {
  const { renderErrorStripe } = await RD();
  const tr = renderErrorStripe( "bbbb2222-3333-4444-5555-666677778888" );
  assert.equal( tr.getAttribute( "data-error-for" ), "bbbb2222-3333-4444-5555-666677778888" );
} );

test( "🔴 renderErrorStripe( null ) writes an EMPTY anchor, never the string \"undefined\"", async () => {
  const { renderErrorStripe } = await RD();
  const tr = renderErrorStripe( null );

  assert.equal( tr.getAttribute( "data-error-for" ), "",
    "an idless error stripe did not anchor on the empty string — a stripe anchored to " +
    "\"undefined\" is claimed by any OTHER idless row, so one row's failure paints on another" );
  assert.notEqual( tr.getAttribute( "data-error-for" ), "undefined" );
} );

test( "🔴 renderErrorStripe( undefined ) does the same", async () => {
  const { renderErrorStripe } = await RD();
  assert.equal( renderErrorStripe( undefined ).getAttribute( "data-error-for" ), "" );
} );

// ------------------------------------------------- epicBoardModel.ts:134

test( "🔴 the UNASSIGNED bucket sorts LAST even when it is the biggest", async () => {
  // The comparator's `a === EPIC_UNASSIGNED_KEY ? 1 : 0` leg. Size is the SECOND
  // key, so the discriminating fixture must make the unassigned bucket the
  // LARGEST: a comparator that dropped the unassigned test entirely would sort
  // biggest-first and put it at the FRONT. A fixture where unassigned is small
  // is satisfied by BOTH the correct and the broken comparator and measures
  // nothing — the same defect as a fake that ignores its input.
  const { groupTasksByEpic, EPIC_UNASSIGNED_KEY } = await EM();

  const tasks = [
    { id: "1", title: "a", correlation_key: "epic:zeta"  },
    { id: "2", title: "b", correlation_key: "epic:alpha" },
    { id: "3", title: "c", correlation_key: EPIC_UNASSIGNED_KEY },
    { id: "4", title: "d", correlation_key: EPIC_UNASSIGNED_KEY },
    { id: "5", title: "e", correlation_key: EPIC_UNASSIGNED_KEY },
  ];
  const keys = groupTasksByEpic( tasks as never ).groups.map( ( g ) => g.epicKey );

  assert.equal( keys.length, 3, "fixture did not produce the three buckets it needs" );
  assert.equal( keys[ keys.length - 1 ], EPIC_UNASSIGNED_KEY,
    "the unassigned bucket did not sort last — with 3 members against 1 each it is the " +
    "biggest, so a comparator that ignores the unassigned key sorts it to the FRONT" );
} );

test( "POSITIVE CONTROL: with no unassigned bucket, size still orders the rest", async () => {
  // Proves the assertion above is about the unassigned leg specifically, and not
  // about the comparator being broken in some way that happens to end correctly.
  const { groupTasksByEpic } = await EM();
  const tasks = [
    { id: "1", title: "a", correlation_key: "epic:small" },
    { id: "2", title: "b", correlation_key: "epic:big"   },
    { id: "3", title: "c", correlation_key: "epic:big"   },
  ];
  const keys = groupTasksByEpic( tasks as never ).groups.map( ( g ) => g.epicKey );
  assert.deepEqual( keys, [ "epic:big", "epic:small" ], "size is no longer the second sort key" );
} );
