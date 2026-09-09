// TaskListStore must not leave an optimistic "approved" row standing on a 202.
//
// 🔴 THE THIRD SITE, AND THE ONLY ONE THAT LEAVES A FALSE FACT ON SCREEN. The other two
// browser call sites return a wrong VALUE to their caller. This one writes the new status
// into the cached row BEFORE the request and restores only if `done` rejects — so when a
// 202 resolves, the pane keeps painting a row as approved for a promotion Rick has not
// been asked about. Tiffany 💍's finding, 2026-09-06; this is its guard.
//
// ⚠️ HELD, NOT SHIPPED. Rick ruled "fix the false success only" and this site is reachable
// ONLY through the asynchronous opt-in, which no production caller sends today — measured
// 2026-09-08: `transitionExtras` (render/taskVerbs.ts:222-234) can construct exactly three
// keys, `reason` / `park_reason` / `next_chase_ts`, and there is no pass-through that could
// carry a fourth. So this guard is written and proven ahead of the ruling rather than
// under it. Mr. Radio's instruction, 2026-09-08 20:00 EDT.
//
// ⚠️ WHY THIS FILE CARRIES ITS OWN HARNESS. `task_list_store.test.ts` settles its post with
// `res( null )` — it can express "the server answered" but not "the server answered THIS
// body", and the whole question here is which body. Rather than widen a peer's fixture and
// change what its existing arms measure, this file builds a settler that resolves with a
// value.
//
// Run via:
//   npx tsx --test src/tests/unit/multiplexer/task_list_store_202_leaves_no_optimistic_approval.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTaskListStore,
  type TaskListApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import type { TaskListComposite } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

const ENDPOINT = "/api/tasks?x=1";
let nowSeq = 9000;
const nowFn = (): number => nowSeq++;

/** The server's 202 body, shape taken from routers/tasks.py:1349-1356. */
const AWAITING_BODY = {
  status      : "awaiting_human_approval",
  ticket_id   : "11111111-2222-3333-4444-555555555555",
  task_id     : "t1",
  to_status   : "queued",
  resolves_by : "2026-09-08T23:59:00+00:00",
  check_with  : "task_promotion_status",
};

const seedComposite = (): TaskListComposite => ( {
  tasks: [
    { id: "t1", title: "one", status: "not_approved", owner_persona: "amy", priority: "P2" },
    { id: "t2", title: "two", status: "queued",       owner_persona: "bob", priority: "P1" },
  ],
  count: 2,
} );

/**
 * A store whose POST resolves with `answer` — the body, not a bare null.
 *
 * The GET is the seed, so the store has a cached composite to mutate optimistically.
 */
async function primedStore( answer: unknown ) {
  const posts: Array<{ path: string; body: unknown }> = [];
  const api: TaskListApiClient = {
    get   : async <T,>(): Promise<T> => seedComposite() as T,
    patch : async <T,>(): Promise<T> => null as T,
    post  : async <T,>( path: string, body: unknown ): Promise<T> => {
      posts.push( { path, body } );
      return answer as T;
    },
  };
  const store = createTaskListStore( {
    bus: createEventBusForTesting(), api, endpoint: ENDPOINT, nowFn,
    actorProvider: () => "rick@x.com",
  } );
  await store.refresh();
  return { store, posts };
}

const statusOf = ( store: { composite: () => TaskListComposite | null }, id: string ) =>
  store.composite()?.tasks?.find( ( t ) => t.id === id )?.status;

// ---------------------------------------------------------------------------
// The guard
// ---------------------------------------------------------------------------

test( "an awaiting-approval answer REJECTS `done`, so the renderer's rollback fires", async () => {
  const { store } = await primedStore( AWAITING_BODY );

  const { done } = store.transitionTask( "t1", "queued", {} );

  // The optimistic write has already happened — that is the store's contract and is not
  // the defect. The defect is what happens next.
  assert.equal( statusOf( store, "t1" ), "queued", "the optimistic edit should still be written up front" );

  // Today `done` RESOLVES here, so the renderer never rolls back and the row stays
  // "queued" — approved-looking — for a promotion nobody has answered.
  await assert.rejects(
    done,
    "`done` resolved on a 202, so the renderer's rollback never fires and the optimistic row stands",
  );
} );

test( "after the rejection, restoreState puts the row back to not_approved", async () => {
  const { store } = await primedStore( AWAITING_BODY );

  // 🔴 THE ROLLBACK IS CONDITIONAL, AND THAT IS THE WHOLE ASSERTION. An earlier draft of
  // this arm called `restoreState()` unconditionally and PASSED against the unfixed store
  // — of course it did: restoring always restores. It was satisfiable by two paths and so
  // could not tell which one ran. The renderer only rolls back when `done` REJECTS, so the
  // test must too.
  const { done, restoreState } = store.transitionTask( "t1", "queued", {} );
  let rejected = false;
  await done.catch( () => { rejected = true; } );
  if ( rejected ) restoreState();

  assert.equal(
    statusOf( store, "t1" ), "not_approved",
    "the row is still painted approved after a 202 — the exact false FACT this guard exists for",
  );
} );

test( "the rejection identifies the pending state and carries the ticket", async () => {
  const { store } = await primedStore( AWAITING_BODY );

  const { done } = store.transitionTask( "t1", "queued", {} );
  const err = await done.then( () => null, ( e: unknown ) => e );

  // A bare rejection would make "Rick has not answered yet" indistinguishable from "the
  // server refused" — a different wrong answer rather than a fix.
  assert.equal( ( err as { pending?: unknown } )?.pending, true, "the rejection must say it is pending, not a refusal" );
  assert.equal( ( err as { ticketId?: unknown } )?.ticketId, AWAITING_BODY.ticket_id, "the ticket id must survive to the caller" );
} );

// ---------------------------------------------------------------------------
// The controls. Without these the guard is satisfied by a store that rejects
// EVERYTHING — strictly worse than the defect, and it would pass arm one.
// ---------------------------------------------------------------------------

test( "CONTROL — an ordinary success still resolves, and the optimistic row stands", async () => {
  const { store } = await primedStore( null );

  const { done } = store.transitionTask( "t1", "queued", {} );
  await done;                                    // must NOT reject

  assert.equal( statusOf( store, "t1" ), "queued", "a real transition must keep its optimistic row" );
} );

test( "CONTROL — a 200 body that merely mentions the marker in another field still resolves", async () => {
  // The discriminator is the `status` FIELD. A payload-wide substring match would call
  // this pending and roll back a transition that actually happened.
  const { store } = await primedStore( { status: "queued", reason: "not awaiting_human_approval at all" } );

  const { done } = store.transitionTask( "t1", "queued", {} );
  await done;

  assert.equal( statusOf( store, "t1" ), "queued" );
} );

test( "CONTROL — the posted body still carries no `asynchronous` key", async () => {
  // The latency claim this whole file is held under: no production caller opts in, so this
  // door cannot return a 202 today. If the store ever starts sending the opt-in, this
  // guard stops being pre-emptive and the hold needs revisiting — loudly, here.
  const { store, posts } = await primedStore( null );

  const { done } = store.transitionTask( "t1", "queued", { reason: "because" } );
  await done;

  assert.equal( posts.length, 1 );
  assert.ok(
    !Object.prototype.hasOwnProperty.call( posts[ 0 ]!.body as object, "asynchronous" ),
    "TaskListStore now sends the asynchronous opt-in — this site is no longer unreachable, and the hold on its fix needs revisiting",
  );
} );
