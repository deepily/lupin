// The multiplexer's ticket-lookup box — every branch, plus the two properties
// that are the whole point of the control.
//
// THE TWO THAT MATTER MORE THAN THE REST:
//   1. it requests the VISIBILITY-FREE endpoint, so a held row is findable;
//   2. not-found, ambiguous and failed stay THREE distinct sentences, because
//      they call for three different next moves.
//
// Run: npx tsx --test src/tests/unit/multiplexer/task_lookup_box.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTaskLookupBox,
  describeLookupFailure,
  lookupKindFor,
  lookupFailureState,
} from "../../../lupin_app/static/js/multiplexer/render/taskLookupBox";
import type { TaskItem } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( !( globalThis as { document?: unknown } ).document ) {
    GlobalRegistrator.register();
  }
} );

/** Records every path requested, so "did it call the right door" is assertable. */
function recordingFetcher( outcome: { resolve?: TaskItem; reject?: unknown } ) {
  const calls: string[] = [];
  const fetchTask = ( path: string ): Promise<TaskItem> => {
    calls.push( path );
    if ( outcome.reject !== undefined ) return Promise.reject( outcome.reject );
    return Promise.resolve( outcome.resolve as TaskItem );
  };
  return { calls, fetchTask };
}

const HELD_ROW: TaskItem = {
  id            : "3fdf4fb4-2370-4117-9a02-c271fcecc331",
  title         : "Main is RED: the prototype-chain sweep fails",
  status        : "not_approved",
  owner_persona : "maria",
  priority      : "P2",
};

// ---------------------------------------------------------------------------
// 🔴 THE ENDPOINT — the assertion that stops this being rebuilt on the board query
// ---------------------------------------------------------------------------

test( "it asks the single-row endpoint, which is the one that can see held rows", async () => {
  const { calls, fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );

  box.input.value = "3fdf4fb4";
  await box.submit();

  assert.deepEqual( calls, [ "/api/tasks/3fdf4fb4" ] );
  // The negative half. `/api/tasks?id_prefix=` hides holding-area rows — 1 of 23
  // findable, measured 2026-09-09 — so a future "simplification" onto the board
  // query must redden here rather than quietly halve the feature.
  assert.ok( !calls[ 0 ].includes( "id_prefix" ),
    "the board query cannot see held rows; the lookup must not be moved onto it" );
} );

test( "a held row travels WITH its status, not as an ordinary ticket", async () => {
  // 🔨 THE ASSERTION MOVED, THE GUARANTEE DID NOT. This used to check the box's
  // own sentence for "not_approved"; the box no longer writes a sentence about
  // the row. What matters is unchanged and is checked one step earlier: the row
  // that reaches the list carries its status, so the rendered row shows which
  // pile it is in — usually the actual question. The rendering half is asserted
  // in task_list_renderer_lookup_filter.test.ts against the real table.
  const seen: TaskItem[] = [];
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask, onFound: ( t ) => seen.push( t ) } );

  box.input.value = "3fdf4fb4";
  await box.submit();

  assert.equal( seen.length, 1 );
  assert.equal( seen[ 0 ]!.status, "not_approved",
    "a held row that reaches the list without its status renders as an ordinary live ticket" );
  assert.equal( box.result.getAttribute( "data-state" ), "filtered" );
} );

// ---------------------------------------------------------------------------
// REFUSAL — no round trip for something we can already judge
// ---------------------------------------------------------------------------

test( "junk is refused WITHOUT a request", async () => {
  const { calls, fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );

  box.input.value = "hello";
  await box.submit();

  assert.deepEqual( calls, [], "no request may be spent on a ref we can refuse locally" );
  assert.equal( box.result.getAttribute( "data-state" ), "refused" );
  assert.match( box.result.textContent ?? "", /hyphen/i );
} );

test( "an empty box is refused the same way, not treated as a search for everything", async () => {
  const { calls, fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );

  box.input.value = "   ";
  await box.submit();

  assert.deepEqual( calls, [] );
  assert.equal( box.result.getAttribute( "data-state" ), "refused" );
} );

// ---------------------------------------------------------------------------
// THE THREE FAILURES — they must not collapse into one
// ---------------------------------------------------------------------------

test( "404, 422, 401 and 500 produce four DIFFERENT sentences", async () => {
  // 🔴 WAS THREE. The 401 arm was missing here and present on the notifications
  // client, so a signed-out user got "Lookup failed" on this pane and "sign back
  // in" on the other — found in review 2026-09-09, and the reason the parity
  // guard now RUNS both clients instead of grepping them.
  const notFound  = describeLookupFailure( "49e52a90", { status: 404 } );
  const ambiguous = describeLookupFailure( "49e5", {
    status : 422,
    detail : "task id prefix '49e5' is ambiguous — it matches 2 items: a, b. Supply more characters or the full UUID.",
  } );
  const signedOut = describeLookupFailure( "49e52a90", { status: 401 } );
  const broken    = describeLookupFailure( "49e52a90", { status: 500, detail: "boom" } );

  const distinct = new Set( [ notFound, ambiguous, signedOut, broken ] );
  assert.equal( distinct.size, 4,
    "four outcomes calling for four different next moves must read differently" );

  assert.match( notFound,  /No ticket matches/ );
  // The server's own 422 NAMES the candidates — more useful than anything we
  // could compose, so it is passed through rather than replaced.
  assert.match( ambiguous, /matches 2 items/ );
  assert.match( signedOut, /sign back in/ );
  assert.match( broken,    /store did not answer/ );
} );

test( "the four failure states are as distinct as the four sentences", () => {
  // The sentence was never the whole divergence: every failure used to stamp
  // data-state="missing", so CSS, tests and anything else reading the DOM could
  // not tell a signed-out session from a dead store. The STATE is the part other
  // code branches on.
  const states = [ 404, 422, 401, 500 ].map( ( status ) => lookupFailureState( { status } ) );
  assert.deepEqual( states, [ "missing", "ambiguous", "auth_required", "unreachable" ] );
  assert.equal( new Set( states ).size, 4 );
  // A rejection with no status at all is an outage, not a missing ticket.
  assert.equal( lookupFailureState( {} ), "unreachable" );
} );

test( "an ambiguous prefix with no detail still says something usable", () => {
  assert.match( describeLookupFailure( "49e5", { status: 422 } ), /not a usable ticket reference/ );
} );

test( "a failure with neither detail nor message does not render undefined", () => {
  const text = describeLookupFailure( "49e52a90", {} );
  assert.match( text, /store did not answer/ );
  assert.ok( !text.includes( "undefined" ) );
} );

test( "a failure's own `message` is NOT surfaced to the user", () => {
  // 🔴 THIS TEST IS THE INVERSE OF WHAT IT ONCE ASSERTED, and deliberately so.
  // Passing the transport's message through produced "Lookup failed: HTTP 500"
  // on this pane while the notifications client said "The store did not answer.
  // Try again in a moment." — a divergence the parity guard caught on its first
  // run, after two humans had read both files and missed it.
  //
  // A 5xx's message is "HTTP 500" or a stack fragment: nothing the reader can
  // act on, and a way for internals to reach a page. The 422 arm still passes
  // `detail` through, because there it NAMES the candidate ids.
  const text = describeLookupFailure( "49e52a90", { message: "network down" } );
  assert.ok( !text.includes( "network down" ), `transport text leaked to the user: "${ text }"` );
  assert.match( text, /store did not answer/ );
} );

test( "a rejected lookup lands in the result region rather than throwing out of submit", async () => {
  const { fetchTask } = recordingFetcher( { reject: { status: 404 } } );
  const box = renderTaskLookupBox( { fetchTask } );

  box.input.value = "deadbeef";
  await box.submit();   // must not reject

  assert.equal( box.result.getAttribute( "data-state" ), "missing" );
  assert.match( box.result.textContent ?? "", /No ticket matches "deadbeef"/ );
} );

test( "a rejection that is not an object at all is still handled", async () => {
  // `throw null` / a rejected primitive is exactly the case a `?? {}` guard
  // exists for, and the one nobody writes a test for.
  const { fetchTask } = recordingFetcher( { reject: null } );
  const box = renderTaskLookupBox( { fetchTask } );

  box.input.value = "deadbeef";
  await box.submit();

  // A rejected primitive carries no status, so it is an outage — not a missing
  // ticket, which is what this used to claim.
  assert.equal( box.result.getAttribute( "data-state" ), "unreachable" );
  assert.match( box.result.textContent ?? "", /store did not answer/ );
} );

// ---------------------------------------------------------------------------
// THE FOUND ROW GOES TO THE LIST — the behaviour Rick asked for
//
// 🔨 THIS SECTION REPLACES "THE FOUND SUMMARY", which tested `describeFoundTask`
// — a function that composed a sentence naming the row under the box. Rick
// rejected that build in as many words: "it doesn't display it it only puts the
// title up in green text… what do you think search does? Not confirm that it can
// find it but find it and then display it. It's like a filter."
//
// So the assertions moved rather than vanished. The box's job is now to hand the
// ROW up; the list renders it. What used to be asserted about a sentence is now
// asserted about the row that reaches the caller.
// ---------------------------------------------------------------------------

test( "a found row is handed UP to the caller, not described in the box", async () => {
  const seen: TaskItem[] = [];
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask, onFound: ( t ) => seen.push( t ) } );

  box.input.value = "3fdf4fb4";
  await box.submit();

  assert.equal( seen.length, 1, "the list never received the row it is supposed to show" );
  assert.equal( seen[ 0 ], HELD_ROW, "the WHOLE row must travel — the list needs its fields, not a summary" );
  // The box's own text is now an affordance, not an answer.
  assert.equal( box.result.getAttribute( "data-state" ), "filtered" );
  assert.ok( !( box.result.textContent ?? "" ).includes( HELD_ROW.title as string ),
    "the box must not ALSO narrate the row — that is the build that was rejected" );
} );

test( "the filtered state is legible — a one-row list without it reads as an empty board", async () => {
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );

  box.input.value = "3fdf4fb4";
  await box.submit();

  assert.match( box.result.textContent ?? "", /Showing the one matching ticket/ );
  assert.match( box.result.textContent ?? "", /whole list/, "the way back must be named, not just available" );
} );

test( "the clear control appears ONLY once a filter is live, and puts the list back", async () => {
  const cleared: number[] = [];
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask, onCleared: () => cleared.push( 1 ) } );
  const clearBtn = box.root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-lookup-clear']" )!;

  // A permanent "clear" on an unfiltered list is a control that does nothing,
  // which teaches the operator to ignore it for the one moment it matters.
  assert.equal( clearBtn.hidden, true, "nothing is filtered yet — the escape hatch must not be offered" );

  box.input.value = "3fdf4fb4";
  await box.submit();
  assert.equal( clearBtn.hidden, false );

  clearBtn.click();
  assert.deepEqual( cleared, [ 1 ], "the list was never told to come back" );
  assert.equal( box.input.value, "", "a stale ref left in the box invites a second Enter on old input" );
  assert.equal( clearBtn.hidden, true );
} );

test( "a FAILED lookup leaves the board alone", async () => {
  // The list the operator was reading is not the thing that went wrong. Wiping it
  // on a typo would make the search actively destructive.
  const seen: TaskItem[] = [];
  const { fetchTask } = recordingFetcher( { reject: { status: 404 } } );
  const box = renderTaskLookupBox( { fetchTask, onFound: ( t ) => seen.push( t ) } );

  box.input.value = "deadbeef";
  await box.submit();

  assert.deepEqual( seen, [], "a miss must not pin anything" );
  assert.equal( box.result.getAttribute( "data-state" ), "missing" );
} );

test( "a REFUSED ref spends no request and pins nothing", async () => {
  const seen: TaskItem[] = [];
  const { calls, fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask, onFound: ( t ) => seen.push( t ) } );

  box.input.value = "zz";
  await box.submit();

  assert.deepEqual( calls, [] );
  assert.deepEqual( seen, [] );
  assert.equal( box.result.getAttribute( "data-state" ), "refused" );
} );

// ---------------------------------------------------------------------------
// INTERACTION
// ---------------------------------------------------------------------------

test( "Enter in the input runs the lookup; another key does not", async () => {
  const { calls, fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );
  box.input.value = "3fdf4fb4";

  box.input.dispatchEvent( new KeyboardEvent( "keydown", { key: "a", bubbles: true } ) );
  assert.deepEqual( calls, [], "an ordinary keystroke must not fire a request per character" );

  box.input.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( calls, [ "/api/tasks/3fdf4fb4" ] );
} );

test( "clicking the button runs the lookup", async () => {
  const { calls, fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );
  box.input.value = "3fdf4fb4";

  const go = box.root.querySelector<HTMLButtonElement>( '[data-testid="multiplexer-task-lookup-go"]' );
  assert.ok( go, "the go button must be in the mounted subtree" );
  go!.click();
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.deepEqual( calls, [ "/api/tasks/3fdf4fb4" ] );
} );

test( "the result region announces itself to a screen reader without stealing focus", () => {
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );
  assert.equal( box.result.getAttribute( "role" ), "status" );
} );

// ---------------------------------------------------------------------------
// PARITY — one classifier, both clients
// ---------------------------------------------------------------------------

test( "the box classifies refs through the SHARED module, not a private copy", () => {
  // `taskVerbs.ts` is the standing receipt for what a second hand-written copy
  // costs: the multiplexer cannot offer `fixed` because its list drifted from
  // the shared module's. This asserts the lookup reads the same classifier the
  // notifications client will.
  assert.equal( lookupKindFor( "49e52a90" ), "prefix" );
  assert.equal( lookupKindFor( "49e52a90-d08c-4085-a172-780b19b6451a" ), "full" );
  assert.equal( lookupKindFor( "nope" ), "invalid" );
} );

// ---------------------------------------------------------------------------
// THE INPUT ITSELF — Rick, row 700f0e1d, 2026-09-11
//
// The box used to be `type="search"`, which gets the browser's own ✕. That ✕
// emptied the box and left the filter on — a control that looks like "clear"
// and is not. The holding area's second box, and the found-but-refused outcome it
// needed, were removed the same day: the task list's box already reaches held rows.
// ---------------------------------------------------------------------------

test( "🔴 the Find input is NOT type=search, so the browser adds no ✕ of its own", () => {
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );
  assert.equal( box.input.type, "text", "a search input brings back the ✕ that clears the box but not the filter" );
  assert.equal( box.input.getAttribute( "enterkeyhint" ), "search", "the phone keyboard lost its search key" );
} );

test( "the box's own controls read input → 🔎 → ✕, so the real clear sits with the search", () => {
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask } );
  const order = Array.from( box.root.children ).map( ( el ) => el.className );
  assert.deepEqual( order.slice( 0, 3 ), [ "task-lookup-input", "task-lookup-go", "task-lookup-clear" ] );
} );

test( "a found row is reported as FILTERED", async () => {
  const { fetchTask } = recordingFetcher( { resolve: HELD_ROW } );
  const box = renderTaskLookupBox( { fetchTask, onFound: () => {} } );
  box.input.value = "3fdf4fb4";
  await box.submit();

  assert.equal( box.result.getAttribute( "data-state" ), "filtered" );
} );
