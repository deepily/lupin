// Parity A-2 #7 — the Task List's live/parked/total count split, and its
// truncation banner in a mount the container's re-render cannot wipe.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1). All in src/lupin_app/static/js/notifications.js:
//   - `_formatTaskListCount`      :11176  "Live: L" · "Live: L · Parked: P · Total: L+P"
//   - `_taskListCountText`        :11894  park-ACTIVE only, via `_taskIsParked`
//   - `_paintTaskListNotices`     :12296  the persistent mount, and WHY it exists
//   - `_holdingAreaHeaderCount`   :12463  the header the held note is compared against.
//     🔴 DELIBERATELY NOT MIRRORED: legacy READS THE DOM there because the legacy
//     page has no store to ask. This client has one, so `heldHeaderCount()` asks
//     `HoldingAreaStore` instead — María 🌸's ruling, 2026-09-23. It also escapes a
//     hazard legacy's own docstring records: the task list paints first, so the DOM
//     read can catch that header still holding its placeholder.
//   - the four full-panel states  :12057, :12067, :12077 — each clears the mount
//   - `_renderPinnedTaskRow`      :12118  writes "Live: 1" flat, and does NOT clear
//   - `_renderTaskListUnreachable`:12511  last-known → count text; none → "Live: 0"
// The banner element itself is `#task-list-notices`, notifications.html:931.
//
// 🔴 THE PARKED SPLIT IS CONDITIONAL AND THAT IS THE POINT. A clean board reads
// "Live: 3" — not "3", and not "Live: 3 · Parked: 0 · Total: 3". Asserting only
// the split form would let a build that always prints the long form pass, and
// asserting only the short form would let one that never splits pass. Both
// shapes are pinned below, off the same formatter.
//
// ⚠️ PARKED IS A STATUS PLUS A LIVE CLOCK. An EXPIRED park counts as LIVE, which
// is the leg most likely to be got wrong — the store calls it
// "fail-loud-toward-owed" — so it has its own case with a fixed `now`, not a
// clock read at call time.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/task_list_counts_and_truncation_parity.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  formatTaskListCount,
  taskListCountText,
  type TaskListComposite,
} from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import { heldHeaderCount } from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import {
  createTaskListRenderer,
  type TaskListStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => { localStorage.clear(); } );

const FIXED_DATE = (): Date => new Date( "2026-09-23T18:30:07Z" );
const NOW        = Date.parse( "2026-09-23T18:30:07Z" );

/** Far enough ahead that no clock skew in the runner can expire it. */
const FUTURE = "2026-12-01T00:00:00Z";
const PAST   = "2026-01-01T00:00:00Z";

function makeStore(): TaskListStoreLike & { setComposite( c: TaskListComposite | null ): void } {
  let composite: TaskListComposite | null = null;
  return {
    composite         : () => composite,
    refresh           : async () => {},
    refreshAfterWrite : async () => {},
    patchTask         : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    transitionTask    : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    setComposite      : ( c ) => { composite = c; },
  } as TaskListStoreLike & { setComposite( c: TaskListComposite | null ): void };
}

/** N held rows, the shape the Holding Area's store hands back. */
function heldComposite( n: number ): TaskListComposite {
  return {
    tasks: Array.from( { length: n }, ( _, i ) => (
      { id: `h${ i }`, title: `h${ i }`, status: "not_approved", owner_persona: "amy" }
    ) ),
    count: n,
  };
}

function setup( holdingArea?: TaskListComposite | null ) {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const root  = document.createElement( "div" );
  const r = createTaskListRenderer( {
    eventBus : bus,
    stores   : holdingArea === undefined
      ? { taskList: store }
      : { taskList: store, holdingArea: { composite: () => holdingArea } },
    nowDateFn : FIXED_DATE,
  } );
  r.mount( root );
  const emit = (): void => {
    bus.emit<StoreTaskListChangedPayload>( {
      type: "store_task_list_changed", payload: { stampUpdated: true }, source: "test", ts: 0,
    } );
  };
  const countText = (): string => root.querySelector( ".section-header-count" )?.textContent ?? "";
  const notices   = (): HTMLElement => root.querySelector( ".task-list-notices" ) as HTMLElement;
  const noticeTexts = (): string[] =>
    Array.from( notices().children ).map( ( el ) => el.textContent ?? "" );
  return { root, store, emit, countText, notices, noticeTexts };
}

// ---------------------------------------------------------------------------
// formatTaskListCount — the two shapes
// ---------------------------------------------------------------------------

test( "formatTaskListCount: no parked rows prints the SHORT form, with the label still carried", () => {
  assert.equal( formatTaskListCount( 3, 0 ), "Live: 3" );
  assert.equal( formatTaskListCount( 0, 0 ), "Live: 0" );
} );

test( "formatTaskListCount: parked rows print the split, and Total is the SUM (not a third input)", () => {
  assert.equal( formatTaskListCount( 3, 5 ), "Live: 3 · Parked: 5 · Total: 8" );
  // 🔴 Live and Parked are NOT interchangeable here. A build that swapped them
  // would still produce "Total: 8", so the two operands are given different
  // values and both labels are read.
  assert.equal( formatTaskListCount( 5, 3 ), "Live: 5 · Parked: 3 · Total: 8" );
} );

test( "formatTaskListCount: a negative or non-numeric parked count falls back to the SHORT form", () => {
  assert.equal( formatTaskListCount( 2, -1 ), "Live: 2" );
  assert.equal( formatTaskListCount( 2, Number.NaN ), "Live: 2" );
  assert.equal( formatTaskListCount( Number.NaN, 1 ), "Live: 0 · Parked: 1 · Total: 1" );
} );

// ---------------------------------------------------------------------------
// taskListCountText — park-ACTIVE, not the status word
// ---------------------------------------------------------------------------

test( "taskListCountText: a parked row with a FUTURE chase counts as parked", () => {
  const rows = [
    { id: "1", status: "in_progress" },
    { id: "2", status: "parked", next_chase_ts: FUTURE },
  ];
  assert.equal( taskListCountText( rows, NOW ), "Live: 1 · Parked: 1 · Total: 2" );
} );

test( "🔴 taskListCountText: a parked row whose chase has PASSED counts as LIVE — fail-loud-toward-owed", () => {
  const rows = [
    { id: "1", status: "in_progress" },
    { id: "2", status: "parked", next_chase_ts: PAST },
  ];
  assert.equal(
    taskListCountText( rows, NOW ), "Live: 2",
    "an expired park has rejoined the owed work; counting it as parked hides it",
  );
} );

test( "taskListCountText: a parked row with NO chase time counts as LIVE, not parked", () => {
  assert.equal( taskListCountText( [ { id: "1", status: "parked" } ], NOW ), "Live: 1" );
} );

test( "taskListCountText: a non-array argument counts as zero rather than throwing", () => {
  assert.equal( taskListCountText( null, NOW ), "Live: 0" );
  assert.equal( taskListCountText( undefined, NOW ), "Live: 0" );
  assert.equal( taskListCountText( "not rows" as unknown, NOW ), "Live: 0" );
} );

// ---------------------------------------------------------------------------
// heldHeaderCount — the STORE read that replaces legacy's DOM read
// ---------------------------------------------------------------------------

test( "heldHeaderCount: a usable composite gives the same total the Holding Area's own header computes", () => {
  const held = ( n: number ): TaskListComposite => ( {
    tasks: Array.from( { length: n }, ( _, i ) => (
      { id: String( i ), title: `h${ i }`, status: "not_approved", owner_persona: "amy" }
    ) ),
    count: n,
  } );
  assert.equal( heldHeaderCount( held( 4 ) ), 4 );
  assert.equal( heldHeaderCount( held( 0 ) ), 0, "a measured zero IS a number, not an unknown" );
} );

test( "🔴 heldHeaderCount: every state in which that pane shows '—' reads null, not a number", () => {
  // Deriving a count from any composite would hand the caller a figure for a
  // pane that is deliberately displaying no figure — and the caller SUPPRESSES
  // a note on the strength of it.
  assert.equal( heldHeaderCount( null ), null, "pre-first-poll is not 'zero held rows'" );
  for ( const status of [ "auth_required", "query_unavailable", "unreachable" ] ) {
    assert.equal( heldHeaderCount( { status, tasks: [] } as TaskListComposite ), null, status );
  }
  assert.equal(
    heldHeaderCount( { count: 0 } as TaskListComposite ), null,
    "a malformed answer is not an empty queue",
  );
} );

// ---------------------------------------------------------------------------
// The renderer: count text at every exit
// ---------------------------------------------------------------------------

test( "the pane mounts a notices element that is a SIBLING of the container, not inside it", () => {
  const { root, notices } = setup();
  const container = root.querySelector( ".task-list-container" ) as HTMLElement;
  assert.notEqual( notices(), null );
  assert.equal( notices().parentElement, root, "the mount hangs off the section root" );
  assert.equal(
    container.contains( notices() ), false,
    "inside the container is exactly where legacy's banner used to be wiped by the next 60s poll",
  );
  assert.ok(
    notices().classList.contains( "section-content" ),
    "it must collapse with the pane, or a collapsed section shows a banner about rows nobody can see",
  );
  assert.equal( notices().getAttribute( "role" ), "status", "as legacy, for a screen reader" );
} );

test( "ok path: the header prints the SPLIT when the board carries a park-active row", () => {
  const { store, emit, countText } = setup();
  store.setComposite( {
    tasks: [
      { id: "1", title: "live",   status: "in_progress", owner_persona: "amy" },
      { id: "2", title: "parked", status: "parked", owner_persona: "amy", next_chase_ts: FUTURE },
      { id: "3", title: "done",   status: "done", owner_persona: "amy" },
    ],
    count: 3,
  } );
  emit();
  assert.equal( countText(), "Live: 1 · Parked: 1 · Total: 2", "the terminal row is excluded before the split" );
} );

test( "ok path: a clean board prints the SHORT form", () => {
  const { store, emit, countText } = setup();
  store.setComposite( { tasks: [ { id: "1", title: "a", status: "queued", owner_persona: "amy" } ], count: 1 } );
  emit();
  assert.equal( countText(), "Live: 1" );
} );

test( "auth_required, unreachable-with-nothing, and empty all print 'Live: 0'", () => {
  const a = setup();
  a.store.setComposite( { status: "auth_required" } );
  a.emit();
  assert.equal( a.countText(), "Live: 0", "sign-in" );

  const b = setup();
  b.store.setComposite( { status: "unreachable", tasks: null } );
  b.emit();
  assert.equal( b.countText(), "Live: 0", "unreachable with no prior fetch" );

  const c = setup();
  c.store.setComposite( { tasks: [ { id: "1", title: "d", status: "done", owner_persona: "amy" } ], count: 1 } );
  c.emit();
  assert.equal( c.countText(), "Live: 0", "all rows terminal" );
} );

test( "unreachable AFTER a good fetch: the count is the last-known rows' own split, not a frozen integer", () => {
  const { store, emit, countText } = setup();
  store.setComposite( {
    tasks: [
      { id: "1", title: "live",   status: "in_progress", owner_persona: "amy" },
      { id: "2", title: "parked", status: "parked", owner_persona: "amy", next_chase_ts: FUTURE },
    ],
    count: 2,
  } );
  emit();
  assert.equal( countText(), "Live: 1 · Parked: 1 · Total: 2" );

  store.setComposite( { status: "unreachable", tasks: null } );
  emit();
  assert.equal(
    countText(), "Live: 1 · Parked: 1 · Total: 2",
    "the replayed rows keep their split — a bare '2' here would disagree with what is on screen",
  );
} );

// ---------------------------------------------------------------------------
// The renderer: the banner
// ---------------------------------------------------------------------------

test( "has_more: the banner paints into the notices mount, above the rows", () => {
  const { store, emit, noticeTexts } = setup();
  store.setComposite( {
    tasks: [ { id: "1", title: "a", status: "queued", owner_persona: "amy" } ],
    count: 1, total: 9, has_more: true,
  } );
  emit();
  const texts = noticeTexts();
  assert.equal( texts.length, 1 );
  assert.match( texts[ 0 ]!, /^✂️ Board truncated: showing 1 of 9 — 8 not displayed\.$/ );
} );

test( "a complete page paints NO banner", () => {
  const { store, emit, noticeTexts } = setup();
  store.setComposite( { tasks: [ { id: "1", title: "a", status: "queued", owner_persona: "amy" } ], count: 1, total: 1 } );
  emit();
  assert.deepEqual( noticeTexts(), [] );
} );

test( "🔴 the banner SURVIVES the next poll's re-render of the container — the defect this mount exists for", () => {
  const { store, emit, noticeTexts, root } = setup();
  const truncated = ( n: number ): TaskListComposite => ( {
    tasks: Array.from( { length: n }, ( _, i ) => (
      { id: String( i ), title: `t${ i }`, status: "queued", owner_persona: "amy" }
    ) ),
    count: n, total: 99, has_more: true,
  } );
  store.setComposite( truncated( 1 ) );
  emit();
  assert.equal( noticeTexts().length, 1, "painted once" );

  // A second poll repaints the container wholesale. In legacy, before the mount
  // moved out, this is the render that made the banner disappear.
  store.setComposite( truncated( 2 ) );
  emit();
  assert.equal( root.querySelectorAll( "tr.task-row" ).length > 0, true, "rows really were repainted" );
  assert.equal( noticeTexts().length, 1, "and the banner is still there" );
} );

test( "every full-panel state CLEARS a banner left by the poll before it", () => {
  for ( const state of [
    { status: "auth_required" } as TaskListComposite,
    { status: "unreachable", tasks: null } as TaskListComposite,
  ] ) {
    const { store, emit, noticeTexts } = setup();
    store.setComposite( { tasks: [ { id: "1", title: "a", status: "queued", owner_persona: "amy" } ], count: 1, total: 9, has_more: true } );
    emit();
    assert.equal( noticeTexts().length, 1, "positive control: the banner was there to clear" );

    store.setComposite( state );
    emit();
    assert.deepEqual(
      noticeTexts(), [],
      `${ state.status }: a banner over a panel that shows no board describes a board that is not on screen`,
    );
  }
} );

const HELD_WARNING = "⚠️ 4 row(s) matching your filters are in the HOLDING AREA awaiting approval";

test( "the held note is DROPPED when the Holding Area's store already says the same number", () => {
  const a = setup( heldComposite( 4 ) );
  a.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ HELD_WARNING ] } );
  a.emit();
  assert.deepEqual( a.noticeTexts(), [], "a note the other pane already makes is noise" );
} );

test( "the held note is KEPT when that store says a different number", () => {
  const b = setup( heldComposite( 1 ) );
  b.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ HELD_WARNING ] } );
  b.emit();
  assert.deepEqual( b.noticeTexts(), [ "4 waiting for your approval" ] );
} );

test( "🔴 the held note is KEPT when there is no Holding Area store, and when it can show no number", () => {
  // No store wired at all — a pane that is not on the page has no header to
  // disagree with, and the note is the ONLY place that number appears. Showing
  // it is the safe direction; suppressing it on an absent comparison is not.
  const none = setup();
  none.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ HELD_WARNING ] } );
  none.emit();
  assert.deepEqual( none.noticeTexts(), [ "4 waiting for your approval" ], "no store wired" );

  // Store wired but pre-first-poll — the pane is showing "—", not "4".
  const unpolled = setup( null );
  unpolled.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ HELD_WARNING ] } );
  unpolled.emit();
  assert.deepEqual( unpolled.noticeTexts(), [ "4 waiting for your approval" ], "null composite" );
} );

test( "🔴 a ZERO-row held note is still kept pre-first-poll — null and 0 are different answers", () => {
  // ⚠️ THIS CASE EXISTS BECAUSE THE TWO ABOVE CANNOT SEE THE DIFFERENCE. With a
  // note of 4, an unmeasured header (null) and a measured 0 BOTH fail to match,
  // so both keep the note and a build that confused them would pass. At 0 they
  // diverge: null still keeps it, 0 would suppress it — and suppressing a note
  // on the strength of a poll that has not happened is the actual defect.
  const zeroNote = "⚠️ 0 row(s) matching your filters are in the HOLDING AREA awaiting approval";
  const unpolled = setup( null );
  unpolled.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ zeroNote ] } );
  unpolled.emit();
  assert.deepEqual(
    unpolled.noticeTexts(), [ "0 waiting for your approval" ],
    "pre-first-poll is UNMEASURED, and unmeasured never agrees with a count",
  );

  // Positive control on the other arm: a genuinely-measured 0 DOES agree, and
  // suppresses. Without this the case above would also pass on a build that
  // never suppresses anything.
  const measured = setup( heldComposite( 0 ) );
  measured.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ zeroNote ] } );
  measured.emit();
  assert.deepEqual( measured.noticeTexts(), [], "a measured zero agrees with the note and drops it" );
} );

test( "a server warning that is not the held note is carried verbatim", () => {
  const { store, emit, noticeTexts } = setup();
  store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ "row-cap truncation applied" ] } );
  emit();
  assert.deepEqual( noticeTexts(), [ "⚠️ Server: row-cap truncation applied" ] );
} );
