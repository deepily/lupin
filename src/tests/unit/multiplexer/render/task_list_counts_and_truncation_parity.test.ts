// Parity A-2 #7 — the Task List's live/parked/total count split, and its
// truncation banner in a mount the container's re-render cannot wipe.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1). All in src/lupin_app/static/js/notifications.js:
//   - `_formatTaskListCount`      :11176  "Live: L" · "Live: L · Parked: P · Total: L+P"
//   - `_taskListCountText`        :11894  park-ACTIVE only, via `_taskIsParked`
//   - `_paintTaskListNotices`     :12296  the persistent mount, and WHY it exists
//   - `_holdingAreaHeaderCount`   :12463  the header the held note is compared against
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
import { holdingAreaHeaderCount } from "../../../../lupin_app/static/js/multiplexer/render/templates/truncationBanner";
import {
  createTaskListRenderer,
  type TaskListStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => {
  localStorage.clear();
  // `holdingAreaHeaderCount` reads the DOCUMENT, not the pane's root, so a
  // header left behind by an earlier test would leak into the next one's answer.
  document.body.replaceChildren();
} );

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

function setup() {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const root  = document.createElement( "div" );
  const r = createTaskListRenderer( { eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE } );
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
// holdingAreaHeaderCount
// ---------------------------------------------------------------------------

test( "holdingAreaHeaderCount: reads a whole number off the Holding Area's count chip", () => {
  const el = document.createElement( "span" );
  el.setAttribute( "data-testid", "multiplexer-holding-area-count" );
  el.textContent = " 7 ";
  document.body.appendChild( el );
  assert.equal( holdingAreaHeaderCount(), 7 );
} );

test( "holdingAreaHeaderCount: an absent element, or a non-numeric sentinel, reads null", () => {
  assert.equal( holdingAreaHeaderCount(), null, "absent → null" );
  const el = document.createElement( "span" );
  el.setAttribute( "data-testid", "multiplexer-holding-area-count" );
  el.textContent = "—";
  document.body.appendChild( el );
  assert.equal( holdingAreaHeaderCount(), null, "the unknown sentinel is not a count" );
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

test( "the held note is DROPPED when it merely repeats the Holding Area's own header", () => {
  const held = "⚠️ 4 row(s) matching your filters are in the HOLDING AREA awaiting approval";

  // Header agrees with the note → the note says nothing new.
  const agreeing = document.createElement( "span" );
  agreeing.setAttribute( "data-testid", "multiplexer-holding-area-count" );
  agreeing.textContent = "4";
  document.body.appendChild( agreeing );

  const a = setup();
  a.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ held ] } );
  a.emit();
  assert.deepEqual( a.noticeTexts(), [], "a note the header already makes is noise" );

  // Header disagrees → the note is the only place that number appears.
  agreeing.textContent = "1";
  const b = setup();
  b.store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ held ] } );
  b.emit();
  assert.deepEqual( b.noticeTexts(), [ "4 waiting for your approval" ] );
} );

test( "a server warning that is not the held note is carried verbatim", () => {
  const { store, emit, noticeTexts } = setup();
  store.setComposite( { tasks: [], count: 0, total: 0, warnings: [ "row-cap truncation applied" ] } );
  emit();
  assert.deepEqual( noticeTexts(), [ "⚠️ Server: row-cap truncation applied" ] );
} );
