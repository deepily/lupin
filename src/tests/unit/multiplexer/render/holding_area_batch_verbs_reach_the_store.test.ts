// Holding-area card — THE BATCH VERBS, driven at the layer the operator's click
// enters at (row 87812328).
//
// 🔴 WHY THIS FILE EXISTS AND WHY IT IS NOT THE PURE TESTS' SIBLING. The pure
// module's tests prove the batch's DECISIONS are right; the store's tests prove
// the POST is right. Neither can tell you a button is connected to either one.
// Both panes on this branch reached 100% coverage with 49 passing tests while no
// page carried a mount id and boot.ts wired nothing — a component can be
// complete, correct, fully covered and entirely absent from the running product,
// and every test that BUILDS the component stays green.
//
// So everything below drives the REAL renderer, mounting into a REAL element,
// painting through the REAL group template and the REAL shared row, and clicking
// the REAL buttons. The store is the only fake, because it is the only thing
// that would otherwise reach the network.
//
// ⚠️ THE ID LOOKUP IS THE SUBTLEST PART AND IT IS TESTED AS SUCH. It keys on
// `.task-verb-select[data-task-id]`, filtered to rows where the `approve` option
// is ENABLED. Keying on a per-verb button is what broke the legacy card: when
// five buttons merged into one Submit, the selector matched NOTHING and the
// batch reported success over zero rows — a green-looking total over an empty
// set, which is this repo's oldest failure shape.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import {
  HOLDING_BATCH_BLANK_REASON,
  HOLDING_BATCH_NO_ROWS,
} from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

/** A row in the holding area: `not_approved` is what makes `approve` legal on it. */
function heldRow( id: string, filer: string, status = "not_approved" ): TaskItem {
  return {
    id, title: `row ${ id }`, status, priority: "P2", created_by: `${ filer } 0e61abe3`,
  } as unknown as TaskItem;
}

interface Call { id: string; toStatus: string; extras: Record<string, string> }

interface Harness {
  root      : HTMLElement;
  container : HTMLElement;
  calls     : Call[];
  refreshes : number;
  /** Arm the collision case: a poll whose fetch began BEFORE the batch's writes. */
  setPollInFlight( v: boolean ): void;
  /** An ordinary poll tick — a repaint with no batch involved. */
  forceRefresh(): Promise<void>;
  statusOf  ( filer: string ): string;
  groupOf   ( filer: string ): HTMLElement;
  buttonOf  ( filer: string, cls: string ): HTMLButtonElement;
  reasonBox ( filer: string ): HTMLInputElement;
  unmount   (): void;
}

/**
 * Mount the real pane over a set of rows.
 *
 * `verdict` decides each row's outcome so a partial failure can be built; `null`
 * from it means the transition throws, which is the one thing the renderer must
 * never see (the store swallows it) and is therefore NOT offered here.
 */
function mountWithRows(
  rows    : TaskItem[],
  verdict : ( id: string ) => { ok: boolean; message?: string } = () => ( { ok: true } ),
  onRefresh?: ( h: { setRows( r: TaskItem[] ): void } ) => void,
): Harness {
  let composite: TaskListComposite = { status: "", tasks: rows } as TaskListComposite;
  const calls: Call[] = [];
  let refreshes = 0;

  const bus = createEventBusForTesting();

  // 🔴 THIS FAKE MODELS THE IN-FLIGHT GUARD, AND THE OLD ONE DID NOT.
  // The previous version always refreshed, whatever the real store would have
  // done — so `refresh()` and a `refresh()` that collides with a live poll were
  // INDISTINGUISHABLE here, and every assertion written over it inherited that.
  // The defect it could not see: the real store returned early on a collision,
  // so the batch's `await refresh()` fetched nothing and emitted nothing, and
  // the poll's own repaint then wiped the report (Clayton 😎, F1).
  //
  // ⚠️ `pollInFlight` is the whole discriminator. With it false the fake behaves
  // as it always did, so every pre-existing assertion still means what it meant.
  const doRefresh = (): void => {
    refreshes += 1;
    onRefresh?.( { setRows( r ) { composite = { status: "", tasks: r } as TaskListComposite; } } );
    // The real store emits on every refresh; the renderer repaints from it.
    bus.emit( { type: "store_holding_area_changed", payload: { stampUpdated: true },
                source: "test", ts: 0 } as never );
  };
  const store: HoldingAreaStoreLike & { pollInFlight: boolean } = {
    pollInFlight: false,
    composite: () => composite,
    async refresh() {
      // A collision JOINS the poll: the caller waits, but no NEW read happens,
      // so a write that landed after the poll's fetch began is not visible.
      if ( this.pollInFlight ) { doRefresh(); return; }
      doRefresh();
    },
    async refreshAfterWrite() {
      // Guaranteed post-write read: join first, then fetch again. Against this
      // fake that is one more repaint than `refresh()` — which is exactly the
      // repaint the report has to survive.
      if ( this.pollInFlight ) doRefresh();
      doRefresh();
    },
    async transitionTask( id, toStatus, extras ) {
      calls.push( { id, toStatus, extras } );
      return verdict( id );
    },
  };

  const root = document.createElement( "div" );
  const renderer = createHoldingAreaRenderer( {
    eventBus: bus, store, nowDateFn: () => new Date( "2026-09-05T21:00:00Z" ),
  } );
  renderer.mount( root );
  const container = root.querySelector( ".holding-area-container" ) as HTMLElement;

  const groupOf = ( filer: string ): HTMLElement => {
    const g = Array.from( container.querySelectorAll<HTMLElement>( ".holding-area-group" ) )
      .find( ( el ) => el.dataset.filer === filer );
    assert.ok( g, `no rendered group for filer ${ JSON.stringify( filer ) }` );
    return g;
  };

  return {
    root, container, calls,
    get refreshes() { return refreshes; },
    groupOf,
    setPollInFlight: ( v: boolean ) => { store.pollInFlight = v; },
    forceRefresh: () => store.refresh(),
    statusOf : ( filer ) =>
      ( groupOf( filer ).querySelector( ".holding-area-group-status" ) as HTMLElement ).textContent ?? "",
    buttonOf : ( filer, cls ) => groupOf( filer ).querySelector( `.${ cls }` ) as HTMLButtonElement,
    reasonBox: ( filer ) => groupOf( filer ).querySelector( ".holding-wont-fix-all-reason" ) as HTMLInputElement,
    unmount  : () => renderer.unmount(),
  } as Harness;
}

/** A real bubbling click, so the container's delegation is what routes it. */
function click( el: HTMLElement ): void {
  el.dispatchEvent( new globalThis.MouseEvent( "click", { bubbles: true } ) );
}

// ---------------------------------------------------------------------------
// THE INSTALL QUESTION: is the button connected to anything at all?
// ---------------------------------------------------------------------------

test( "the pane renders both batch buttons and the reason box for each filer", () => {
  // The positive control for every test below. Without it, a harness that
  // rendered nothing would satisfy each "no request was made" assertion.
  const h = mountWithRows( [ heldRow( "a", "krishna" ), heldRow( "b", "mr radio" ) ] );
  for ( const filer of [ "Krishna", "Mr Radio" ] ) {
    assert.ok( h.buttonOf( filer, "holding-approve-all" ),  `${ filer } has no approve-all button` );
    assert.ok( h.buttonOf( filer, "holding-wont-fix-all" ), `${ filer } has no won't-fix-all button` );
    assert.ok( h.reasonBox( filer ), `${ filer } has no batch reason box` );
  }
  h.unmount();
} );

test( "clicking Approve all REACHES THE STORE — one transition per held row, to queued", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ] );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.deepEqual( h.calls.map( ( c ) => c.id ).sort(), [ "a", "b" ] );
  assert.deepEqual( [ ...new Set( h.calls.map( ( c ) => c.toStatus ) ) ], [ "queued" ] );
  assert.deepEqual( h.calls[ 0 ]?.extras, {}, "approve posted a reason key it was never asked for" );
  h.unmount();
} );

test( "clicking Won't fix all with a reason REACHES THE STORE — wont_fix, ONE reason on every row", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ] );
  h.reasonBox( "Krishna" ).value = "  superseded by the v2 door  ";
  click( h.buttonOf( "Krishna", "holding-wont-fix-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.equal( h.calls.length, 2 );
  for ( const c of h.calls ) {
    assert.equal( c.toStatus, "wont_fix" );
    assert.deepEqual( c.extras, { reason: "superseded by the v2 door" }, "the reason was not trimmed, or not shared" );
  }
  h.unmount();
} );

test( "the batch acts ONLY on its own filer's rows", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ), heldRow( "b", "mr radio" ) ] );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a" ] );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// The refusals that happen BEFORE anything leaves the browser
// ---------------------------------------------------------------------------

test( "a blank won't-fix reason refuses, names the blast radius, and posts NOTHING", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  h.reasonBox( "Krishna" ).value = "   ";          // whitespace is blank
  click( h.buttonOf( "Krishna", "holding-wont-fix-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.equal( h.calls.length, 0, "a blank reason still posted — the server would answer N identical 422s" );
  assert.equal( h.statusOf( "Krishna" ), HOLDING_BATCH_BLANK_REASON );
  h.unmount();
} );

test( "approve needs NO reason — a blank box does not refuse it", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.calls.length, 1 );
  h.unmount();
} );

test( "a group whose rows are all terminal says so rather than reporting success over zero rows", async () => {
  // 🔴 THIS IS THE LEGACY CARD'S OWN BUG, PINNED. A "which rows are here" lookup
  // keyed on a control that only renders when a verb is legal matched NOTHING
  // after the button merge — and the batch then reported a clean success over an
  // empty set. `wont_fix` is terminal, so `approve` is disabled on these rows.
  const h = mountWithRows( [ heldRow( "a", "krishna", "wont_fix" ) ] );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.equal( h.calls.length, 0 );
  assert.equal( h.statusOf( "Krishna" ), HOLDING_BATCH_NO_ROWS );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// Partial failure — the case the whole report exists for
// ---------------------------------------------------------------------------

test( "every row is attempted, whatever the ones before it returned", async () => {
  // The loop-body invariant, seen from the outside: a refusal on the FIRST row
  // must not abandon the other two.
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ), heldRow( "c", "krishna" ) ],
    ( id ) => id === "a" ? { ok: false, message: "403 denied" } : { ok: true },
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( h.calls.map( ( c ) => c.id ).sort(), [ "a", "b", "c" ] );
  h.unmount();
} );

test( "🔴 THE PARTIAL-FAILURE REPORT SURVIVES THE REFRESH — the legacy card's is erased by it", async () => {
  // THE DIVERGENCE THIS BRANCH MAKES FROM THE CARBON COPY, AND ITS RECEIPT.
  // notifications.js `_applyHoldingBatch` paints its report and calls
  // refreshHoldingArea() on the very next line — and the refresh rebuilds every
  // group from scratch, status span included. So the sentence its own docstring
  // calls the whole point of the method is destroyed before anyone reads it. It
  // is invisible when the batch fully succeeds (the group is gone anyway); it
  // costs EXACTLY the case the report exists for.
  //
  // This renderer paints AFTER the refresh instead. The assertion below fails on
  // the legacy ordering and passes on this one — measured, not asserted.
  const rows = [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ), heldRow( "c", "krishna" ) ];
  const h = mountWithRows(
    rows,
    ( id ) => id === "a" ? { ok: true } : { ok: false, message: "403: not on the promotion allowlist" },
    // The refresh does what a real poll does: the approved row is gone, the two
    // refused ones remain, and the pane repaints from that.
    ( ctl ) => ctl.setRows( [ rows[ 1 ] as TaskItem, rows[ 2 ] as TaskItem ] ),
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  const line = h.statusOf( "Krishna" );
  assert.notEqual( line, "", "the report was erased by the refresh — this is the legacy defect" );
  assert.match( line, /\b1 of 3 approved\b/ );
  assert.match( line, /\b2 refused\b/ );
  assert.match( line, /403: not on the promotion allowlist/ );
  h.unmount();
} );

test( "a fully successful batch refreshes exactly once and leaves no stale report behind", async () => {
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ],
    () => ( { ok: true } ),
    ( ctl ) => ctl.setRows( [] ),          // everything approved → the group is gone
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.equal( h.refreshes, 1, "the pane refreshed more than once for one batch" );
  assert.equal( h.container.querySelectorAll( ".holding-area-group" ).length, 0 );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// The in-flight guard
// ---------------------------------------------------------------------------

test( "both batch buttons are dead WHILE a batch runs, and live again after", async () => {
  // Both, not just the one pressed: Approve-All and Won't-Fix-All act on the SAME
  // rows, so leaving the other live mid-batch lets a group be closed halfway
  // through being approved — a race between two verbs over one set of ids,
  // decided by whichever transition the server happens to see last.
  let seenDisabled: boolean[] | null = null;
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ],
    ( id ) => {
      if ( id === "a" && seenDisabled === null ) {
        const g = h.groupOf( "Krishna" );
        seenDisabled = Array.from( g.querySelectorAll<HTMLButtonElement>(
          ".holding-approve-all, .holding-wont-fix-all" ) ).map( ( b ) => b.disabled );
      }
      return { ok: true };
    },
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.deepEqual( seenDisabled, [ true, true ], "a batch button stayed live mid-batch" );
  h.unmount();
} );

test( "a SECOND press mid-batch is ignored — the guard is not the disabled attribute", async () => {
  // Measured on the legacy card: a second click mid-batch took the transition
  // count from 1 to 2. `disabled` is a property on an element this pane repaints,
  // so it is the affordance; a filer-keyed in-flight set is the mechanism.
  let pressedAgain = false;
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ],
    ( ) => {
      if ( !pressedAgain ) {
        pressedAgain = true;
        const btn = h.buttonOf( "Krishna", "holding-approve-all" );
        btn.disabled = false;              // defeat the affordance deliberately
        click( btn );                      // and press it again mid-batch
      }
      return { ok: true };
    },
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.equal( h.calls.length, 2, `a re-entrant batch fired ${ h.calls.length } transitions over 2 rows` );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// Clicks that are not batch clicks
// ---------------------------------------------------------------------------

test( "a click on anything else in the pane posts nothing", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  click( h.groupOf( "Krishna" ).querySelector( ".holding-area-filer" ) as HTMLElement );
  click( h.reasonBox( "Krishna" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );

test( "a batch button with no data-filer is a no-op rather than a batch over an empty scope", async () => {
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  const btn = h.buttonOf( "Krishna", "holding-approve-all" );
  delete btn.dataset.filer;
  click( btn );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.calls.length, 0 );
  h.unmount();
} );

test( "a filer whose label contains selector metacharacters still batches correctly", async () => {
  // The group is found by comparing `dataset.filer` in JavaScript, never by
  // building an attribute selector out of a store-sourced string. A persona name
  // carrying a quote or a bracket would either break such a selector outright or
  // make it match something else.
  // ⚠️ THE EXPECTED LABEL IS `We"Ird [X]`, NOT `We"ird [X]`, and that is the model
  // being right rather than the test being clever: `taskFilerLabel` display-cases
  // at every WORD BOUNDARY, and a quote is a non-word character, so the `i` after
  // it begins a word. Written out because the first cut of this test asserted the
  // intuitive spelling and failed — the label is what the pane really renders.
  const h = mountWithRows( [ heldRow( "a", 'we"ird [x]' ), heldRow( "b", "krishna" ) ] );
  click( h.buttonOf( 'We"Ird [X]', "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a" ] );
  h.unmount();
} );

test( "unmount detaches the batch delegation — a click after it posts nothing", async () => {
  // A leak invisible from the DOM is what survived sixteen passing tests on this
  // pane: `unmount` nulls the container, so every repaint returns at that guard
  // and the pane LOOKS perfectly correct while listeners accumulate.
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  const btn = h.buttonOf( "Krishna", "holding-approve-all" );
  h.unmount();
  click( btn );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.calls.length, 0 );
} );

// ---------------------------------------------------------------------------
// Degrade safety — the paths a batch can be walking when the world moves under
// it. Every one of these is REACHABLE, not defensive: a batch approve can sit
// for minutes on the approval gate, and a pane that is repainted, collapsed or
// unmounted in that window is ordinary rather than exotic.
// ---------------------------------------------------------------------------

test( "the pane can be UNMOUNTED mid-batch: the remaining rows still post, and nothing throws", async () => {
  // The window is real. `not_approved → queued` IS the promotion, so with the
  // gate enforcing, each row waits out its own timeout — the operator has ample
  // time to navigate away. The loop keeps its promise to the rows it already
  // committed to; the painting simply lands nowhere.
  let unmounted = false;
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ), heldRow( "c", "krishna" ) ],
    ( id ) => {
      if ( id === "a" && !unmounted ) { unmounted = true; h.unmount(); }
      return { ok: true };
    },
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a", "b", "c" ],
    "unmounting mid-batch abandoned rows the batch had already committed to" );
} );

test( "a batch button naming a filer with no rendered group says so rather than throwing", async () => {
  // The staleness case: a poll repaints between the press and the lookup, and the
  // group the button belonged to is gone. It must read as "no rows", never as a
  // crash and never as a silent success.
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  const btn = h.buttonOf( "Krishna", "holding-approve-all" );
  btn.dataset.filer = "Somebody Who Left";
  click( btn );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.calls.length, 0 );
} );

test( "a group missing its reason box refuses the won't-fix batch rather than posting a blank reason", async () => {
  // Degrade-safe in the SAFE direction: no box is read as no reason, which is a
  // refusal. The opposite default would close every row under a filer with an
  // empty justification — the exact thing the box exists to prevent.
  const h = mountWithRows( [ heldRow( "a", "krishna" ) ] );
  h.reasonBox( "Krishna" ).remove();
  click( h.buttonOf( "Krishna", "holding-wont-fix-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.calls.length, 0 );
  assert.equal( h.statusOf( "Krishna" ), HOLDING_BATCH_BLANK_REASON );
} );

test( "a refusal carrying NO message still produces a report, not `undefined` on screen", async () => {
  // The store always sets one, but `transitionTask`'s contract types `message`
  // as optional — so any other implementation of that interface may omit it, and
  // the report must not render the word "undefined" at an operator.
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ],
    ( id ) => id === "a" ? { ok: false } : { ok: true },
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  const line = h.statusOf( "Krishna" );
  assert.match( line, /\b1 of 2 approved\b/ );
  assert.match( line, /\b1 refused\b/ );
  assert.ok( !line.includes( "undefined" ), `the report leaked "undefined" to the operator: ${ line }` );
} );

test( "an ID-LESS row is skipped rather than posted to `/api/tasks//transition`", async () => {
  // A malformed row reaches the pane as a rendered select whose `data-task-id`
  // is the empty string — the attribute is PRESENT, so the selector matches it.
  // Posting it would hit a different route entirely and the failure would be
  // reported against a row nobody can find.
  const rows = [ heldRow( "a", "krishna" ), heldRow( "", "krishna" ) ];
  const h = mountWithRows( rows );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( h.calls.map( ( c ) => c.id ), [ "a" ] );
} );

// ---------------------------------------------------------------------------
// 🔴 THE COLLISION CASE — the one the old fixture could not express
// ---------------------------------------------------------------------------

test( "THE REPORT SURVIVES A POLL THAT WAS ALREADY IN FLIGHT — the case the old fake could not pose", async () => {
  // Clayton 😎's F1. The real store's `refresh()` returned early when a poll was
  // in flight, so the batch's `await refresh()` fetched NOTHING and emitted
  // NOTHING — and the poll's own repaint then landed after the report was
  // painted and rebuilt the group with an empty status line. The batch's
  // docstring said "the pane refreshes exactly once"; it could refresh ZERO
  // times.
  //
  // ⚠️ WHY THE OLD SUITE WAS GREEN THROUGHOUT: its fake had no in-flight guard,
  // so it always refreshed. A collision and a clean call produced byte-identical
  // behaviour, and no assertion written over it — however well named — could
  // separate them. The fix is the FIXTURE, not the assertions.
  //
  // Two things are asserted together on purpose. The report surviving alone
  // would also be satisfied by never repainting at all, so the repaint is
  // asserted to have HAPPENED as well.
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ],
    () => ( { ok: false, message: "403 not on the allowlist" } ),
  );
  h.setPollInFlight( true );

  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );

  assert.ok( h.refreshes >= 2,
    `a batch colliding with a live poll must still take a read that can SEE its own writes; ` +
    `refreshes=${ h.refreshes } means it joined the poll and never fetched again` );

  const line = h.statusOf( "Krishna" );
  assert.match( line, /\b0 of 2 approved\b/ );
  assert.match( line, /\b2 refused\b/ );
  assert.match( line, /403 not on the allowlist/ );
} );

test( "and the report survives a LATER repaint too — a poll landing after the batch is finished", async () => {
  // The narrower fix — reordering the batch's own refresh — would pass the test
  // above and fail this one, because the erasing render does not have to be the
  // batch's. Every render rebuilds the groups and the status line comes back
  // empty, so the report has to be STATE the render re-applies, not a string
  // painted once into the DOM.
  const h = mountWithRows(
    [ heldRow( "a", "krishna" ), heldRow( "b", "krishna" ) ],
    ( id ) => id === "a" ? { ok: false, message: "409 conflict" } : { ok: true },
  );
  click( h.buttonOf( "Krishna", "holding-approve-all" ) );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.match( h.statusOf( "Krishna" ), /409 conflict/ );

  // An ordinary 60s poll tick, entirely unrelated to the batch.
  await h.forceRefresh();
  assert.match( h.statusOf( "Krishna" ), /409 conflict/,
    "an unrelated poll repaint erased the partial-failure report — the one message " +
    "whose entire job is to still be there after the pane refreshes" );
} );
