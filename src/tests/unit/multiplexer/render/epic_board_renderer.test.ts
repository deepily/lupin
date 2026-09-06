// Epic-board card — EpicBoardRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE FOUR STATE MESSAGES ARE COMPARED AGAINST notifications.js, NOT AGAINST
// LITERALS TYPED HERE — the rule this branch applies to every carbon copy. The
// extraction carries an EQUALITY count derived with a DIFFERENT INSTRUMENT plus
// a SHAPE control, because count and distinctness are both cardinality checks
// and neither looks at shape. That was measured the hard way on the epic board
// template: an unanchored regex returned ten slabs of source and BOTH of those
// controls passed on it.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createEpicBoardRenderer,
  EPIC_BOARD_SIGNIN_MESSAGE,
  EPIC_BOARD_QUERY_UNAVAILABLE_MESSAGE,
  EPIC_BOARD_UNREACHABLE_MESSAGE,
  type EpicBoardTaskStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import { EPIC_BOARD_STATE_KEY, EPIC_ON_RICK_KEY, EPIC_DRIFT_KEY, epicGroupIsExpanded, loadEpicGroupState } from "../../../../lupin_app/static/js/multiplexer/render/epicBoardCollapse";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => { localStorage.clear(); });

// ---------------------------------------------------------------------------
// The legacy side
// ---------------------------------------------------------------------------

const HERE = dirname( fileURLToPath( import.meta.url ) );
const LEGACY_PATH = resolve( HERE, "../../../../lupin_app/static/js/notifications.js" );

function legacyPaneSource(): string {
  const src   = readFileSync( LEGACY_PATH, "utf8" );
  const start = src.indexOf( "renderEpicBoard( composite, stampUpdated = true ) {" );
  assert.ok( start !== -1, "legacy renderEpicBoard not found — the extraction is pointing at nothing" );
  const end   = src.indexOf( "_stampEpicBoardUpdated()", start );
  assert.ok( end > start, "legacy _stampEpicBoardUpdated not found after the pane renderer" );
  return src.slice( start, end );
}

/** The message classes the legacy pane paints, in the order it dispatches them. */
const LEGACY_MESSAGE_CLASSES = [
  "task-list-signin",
  "task-list-query-unavailable",
  "task-list-unreachable",
] as const;

/**
 * The message text the legacy pane paints for one of its state classes.
 *
 * 🔴 ANCHORED ON THE CLASS, NOT ON A BARE QUOTE PAIR. An unanchored
 * `"[^"]{10,}"` regex is what returned ten slabs of source on the epic board's
 * template — the closing quote of one literal pairing with the opening quote of
 * the next.
 *
 * ⚠️ AND THE QUERY-UNAVAILABLE MESSAGE IS CONCATENATED ACROSS THREE SOURCE
 * LINES with `+`, so any extractor that stops at the first backtick returns a
 * TRUNCATED string that still looks like a plausible message. The join is
 * undone explicitly, and a test below proves the join actually fired rather
 * than trusting it.
 */
function legacyMessage( cls: string ): string {
  const body = legacyPaneSource();
  const at   = body.indexOf( `${ cls }">` );
  assert.ok( at !== -1, `legacy class ${ cls } not found in the pane renderer` );
  const from = at + cls.length + 2;
  const end  = body.indexOf( "</p>", from );
  assert.ok( end > from, `legacy class ${ cls } has no closing </p>` );
  return body.slice( from, end ).replace( /`\s*\+\s*\n?\s*`/g, "" );
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function task( id: string, epic: string | null, status = "todo" ): TaskItem {
  return {
    id, title: `row ${ id }`, status, priority: "P2",
    correlation_key: epic ?? undefined, blocked_by: [],
  } as unknown as TaskItem;
}

interface FakeStore extends EpicBoardTaskStoreLike {
  setComposite( c: TaskListComposite | null ): void;
  refreshCalls: number;
}

function fakeStore( initial: TaskListComposite | null = null ): FakeStore {
  let composite = initial;
  return {
    refreshCalls: 0,
    composite: () => composite,
    setComposite( c ) { composite = c; },
    async refresh() { this.refreshCalls += 1; },
  };
}

function mountPane( composite: TaskListComposite | null, stories = {} ) {
  const bus   = createEventBusForTesting();
  const store = fakeStore( composite );
  const root  = document.createElement( "div" );
  const renderer = createEpicBoardRenderer( {
    eventBus  : bus,
    store,
    storiesFn : () => stories,
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } );
  renderer.mount( root );
  return {
    bus, store, root, renderer,
    container : root.querySelector( ".epic-board-container" ) as HTMLElement,
    countEl   : root.querySelector( '[data-testid="multiplexer-epic-board-count"]' ) as HTMLElement,
  };
}

function emit( bus: ReturnType<typeof createEventBusForTesting>, stampUpdated: boolean ): void {
  bus.emit<StoreTaskListChangedPayload>( {
    type: "store_task_list_changed", payload: { stampUpdated }, source: "test", ts: 0 } );
}

// ---------------------------------------------------------------------------
// The extraction's controls — first, because every comparison below rests on it
// ---------------------------------------------------------------------------

test( "the legacy extraction reaches exactly three state messages, and they are messages not source", () => {
  const found = LEGACY_MESSAGE_CLASSES.map( legacyMessage );

  // COUNT, as an equality against a figure derived with a DIFFERENT INSTRUMENT
  // (awk over the function's line range piped to grep for the class marker),
  // never a floor. A floor is satisfied by a wrong population that happens to be
  // large — which is exactly what the epic board template's first extractor did.
  assert.equal( found.length, 3 );

  // SHAPE — the control neither count nor distinctness can supply. Both of those
  // are cardinality checks; a population of the right size made of the wrong
  // things passes both.
  for ( const [ i, message ] of found.entries() ) {
    const cls = LEGACY_MESSAGE_CLASSES[ i ];
    assert.ok( message.length > 15, `${ cls } came back too short to be the real message: ${ JSON.stringify( message ) }` );
    assert.ok( !message.includes( "`" ), `${ cls } carries a backtick — the extraction swallowed source: ${ JSON.stringify( message.slice( 0, 60 ) ) }` );
    assert.ok( !/[<>{}]/.test( message ), `${ cls } carries markup or braces — it is source, not a message` );
  }

  assert.equal( new Set( found ).size, 3, "two state messages extracted identical — the slice is picking one up twice" );
} );

test( "the concatenated query-unavailable message is JOINED, not truncated at the first fragment", () => {
  // 🔴 THE ONE THAT WOULD FAIL SILENTLY. That message is built from three
  // source lines with `+`. An extractor stopping at the first backtick returns
  // "🧩 Task-list query did not load" — a plausible, complete-looking sentence
  // that is missing the half telling the operator it is a DEPLOY problem and
  // not an outage. Nothing about the truncated form looks wrong.
  const joined = legacyMessage( "task-list-query-unavailable" );
  assert.ok( joined.includes( "deploy problem" ),
    `the join did not fire — the extraction stopped early: ${ JSON.stringify( joined ) }` );
  assert.ok( joined.length > 100, `joined message is only ${ joined.length } chars — the tail is missing` );
} );

test( "all three state messages are byte-identical to the legacy client's", () => {
  assert.equal( EPIC_BOARD_SIGNIN_MESSAGE,             legacyMessage( "task-list-signin" ) );
  assert.equal( EPIC_BOARD_QUERY_UNAVAILABLE_MESSAGE,  legacyMessage( "task-list-query-unavailable" ) );
  assert.equal( EPIC_BOARD_UNREACHABLE_MESSAGE,        legacyMessage( "task-list-unreachable" ) );
} );

// ---------------------------------------------------------------------------
// The four states
// ---------------------------------------------------------------------------

test( "a signed-out composite paints the sign-in message and zeroes the count", () => {
  const { container, countEl } = mountPane( { status: "auth_required" } );
  assert.equal( container.textContent, EPIC_BOARD_SIGNIN_MESSAGE );
  assert.equal( countEl.textContent, "0" );
} );

test( "query_unavailable gets its OWN message, not the generic unreachable one", () => {
  const { container, countEl } = mountPane( { status: "query_unavailable" } );
  assert.equal( container.textContent, EPIC_BOARD_QUERY_UNAVAILABLE_MESSAGE );
  assert.notEqual( container.textContent, EPIC_BOARD_UNREACHABLE_MESSAGE );
  assert.equal( countEl.textContent, "0" );
} );

test( "an unreachable store shows NOTHING rather than something stale", () => {
  const { store, renderer, container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 1 );

  store.setComposite( { status: "unreachable", tasks: null } );
  renderer.forceRenderForTesting();

  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 0 );
  assert.equal( container.textContent, EPIC_BOARD_UNREACHABLE_MESSAGE );
} );

test( "the unreachable branch LEAVES THE COUNT ALONE rather than zeroing it", () => {
  // ⚠️ CARBON COPY, AND IT IS THE ONE STATE THAT DOES NOT TOUCH THE COUNT.
  // Zeroing would ASSERT there are no epics; leaving it says the last known
  // figure is the last thing anyone measured, and the message beside it already
  // says the rows are not being shown.
  const { store, renderer, countEl } = mountPane( {
    tasks: [ task( "t1", "epic:alpha" ), task( "t2", "epic:beta" ) ] } );
  assert.equal( countEl.textContent, "2" );

  store.setComposite( { status: "unreachable", tasks: null } );
  renderer.forceRenderForTesting();
  assert.equal( countEl.textContent, "2", "the unreachable branch zeroed the count — it now asserts there are no epics" );
} );

test( "the pre-first-poll state takes the unreachable branch", () => {
  const { container } = mountPane( null );
  assert.equal( container.textContent, EPIC_BOARD_UNREACHABLE_MESSAGE );
} );

test( "a malformed payload takes the unreachable branch too", () => {
  const { container } = mountPane( { tasks: "not an array" as unknown as TaskItem[] } );
  assert.equal( container.textContent, EPIC_BOARD_UNREACHABLE_MESSAGE );
} );

// ---------------------------------------------------------------------------
// The count, and the filter
// ---------------------------------------------------------------------------

test( "the count is EPICS, not rows — the one place this pane disagrees with its siblings", () => {
  // 🔴 FIVE ROWS ACROSS TWO EPICS, chosen so the two numbers cannot agree. A
  // count taken off the rows would read 5 and look perfectly plausible.
  const { countEl, container } = mountPane( { tasks: [
    task( "t1", "epic:alpha" ), task( "t2", "epic:alpha" ), task( "t3", "epic:alpha" ),
    task( "t4", "epic:beta" ),  task( "t5", "epic:beta" ),
  ] } );

  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 5 );
  assert.equal( countEl.textContent, "2" );
} );

test( "drift rows do NOT inflate the epic count", () => {
  // Drift always renders as a section but is not an epic, so a count taken off
  // the rendered sections would read one higher than the epics there are.
  const { countEl, container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ), task( "t2", null ) ] } );
  assert.equal( container.querySelectorAll( "tbody.epic-group" ).length, 2, "expected the alpha epic and the drift section" );
  assert.equal( countEl.textContent, "1" );
} );

test( "closed rows are filtered out with the task list's OWN open-row filter", () => {
  const { countEl, container } = mountPane( { tasks: [
    task( "t1", "epic:alpha" ),
    task( "t2", "epic:beta", "done" ),
  ] } );

  // ⚠️ THE TWO PANES MUST NEVER DISAGREE ABOUT WHICH ROWS EXIST. A closed row
  // dropping the whole beta epic is the point — the board shows open work.
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 1 );
  assert.equal( countEl.textContent, "1" );
} );

test( "the stories map reaches the section labels", () => {
  const { container } = mountPane(
    { tasks: [ task( "t1", "epic:board-visibility" ) ] },
    { "epic:board-visibility": { title: "Board Visibility", story: "Make it legible." } } );

  const tbody = container.querySelector( 'tbody[data-epic="epic:board-visibility"]' ) as HTMLElement;
  assert.equal( tbody.querySelector( ".epic-group-label" )!.textContent, "Board Visibility" );
  assert.equal( tbody.querySelector( "tr.epic-story-row" )!.textContent, "Make it legible." );
} );

test( "with NO stories map the board still renders, de-slugged and story-less", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:board-visibility" ) ] } );
  const tbody = container.querySelector( 'tbody[data-epic="epic:board-visibility"]' ) as HTMLElement;
  assert.equal( tbody.querySelector( ".epic-group-label" )!.textContent, "board visibility" );
  assert.equal( tbody.querySelectorAll( "tr.epic-story-row" ).length, 0 );
} );

// ---------------------------------------------------------------------------
// The accordion
//
// 🔴 AN EPIC DEFAULTS TO COLLAPSED AND THE HIGHLIGHT DEFAULTS TO OPEN. That is
// epicDefaultExpanded's rule — "a collapsed highlight highlights nothing" — and
// it is a TRI-STATE, not a boolean: expanded, collapsed, or ABSENT falling
// through to a per-key default. These tests were written first assuming a
// default-open epic and went red; the code was right and the tests were wrong.
// ---------------------------------------------------------------------------

test( "an epic starts COLLAPSED and the on-Rick highlight starts OPEN, with no stored choice", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  assert.equal( localStorage.getItem( EPIC_BOARD_STATE_KEY ), null, "the fixture is not on the ABSENT branch" );

  const alpha = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.ok( alpha.classList.contains( "collapsed" ), "an epic defaulted to open" );

  const rickPane = mountPane( { tasks: [ {
    ...task( "t2", "epic:beta" ), blocked_by: [ { kind: "user", id: "rick" } ] } as unknown as TaskItem ] } );
  const onRick = rickPane.container.querySelector( `tbody[data-epic="${ EPIC_ON_RICK_KEY }"]` ) as HTMLElement;
  assert.ok( !onRick.classList.contains( "collapsed" ), "the highlight defaulted to collapsed — it highlights nothing" );
} );

test( "clicking a section header toggles it, in the DOM and in the persisted choice", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const tbody  = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  const header = tbody.querySelector( "tr.epic-group-header" ) as HTMLElement;

  assert.ok( tbody.classList.contains( "collapsed" ) );
  header.click();

  assert.ok( !tbody.classList.contains( "collapsed" ) );
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );
  assert.equal( tbody.querySelector( ".epic-group-chevron" )!.textContent, "▾" );

  // 🔴 THE PERSISTED CHOICE IS THE SOURCE OF TRUTH — the DOM followed it, not
  // the other way round. Without this the collapse survives no repaint.
  //
  // ⚠️ `loadEpicGroupState()` IS NOT OPTIONAL HERE. epicGroupIsExpanded is PURE:
  // called with no state it does not read localStorage, it takes the ABSENT
  // branch and returns epicDefaultExpanded — so the no-arg form ALWAYS answers
  // the default, whatever is stored. The first cut of this test used it and read
  // `false` off a section that was open on screen and `true` in the store.
  assert.equal( epicGroupIsExpanded( "epic:alpha", loadEpicGroupState() ), true );
  assert.ok( localStorage.getItem( EPIC_BOARD_STATE_KEY ), "nothing was persisted — the choice dies on the next paint" );
} );

test( "a second click closes it again, and the choice follows both ways", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const tbody  = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  const header = tbody.querySelector( "tr.epic-group-header" ) as HTMLElement;

  header.click();
  header.click();

  assert.ok( tbody.classList.contains( "collapsed" ) );
  assert.equal( header.getAttribute( "aria-expanded" ), "false" );
  assert.equal( tbody.querySelector( ".epic-group-chevron" )!.textContent, "▸" );
  assert.equal( epicGroupIsExpanded( "epic:alpha", loadEpicGroupState() ), false );
} );

test( "the operator's choice survives a repaint", () => {
  const { bus, container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  ( container.querySelector( "tr.epic-group-header" ) as HTMLElement ).click();   // open it

  emit( bus, true );

  const tbody = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.ok( !tbody.classList.contains( "collapsed" ), "the repaint discarded the operator's choice" );
} );

test( "Enter and Space activate a focused header, and Space does not scroll", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const tbody  = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  const header = tbody.querySelector( "tr.epic-group-header" ) as HTMLElement;

  header.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true, cancelable: true } ) );
  assert.ok( !tbody.classList.contains( "collapsed" ) );

  const space = new KeyboardEvent( "keydown", { key: " ", bubbles: true, cancelable: true } );
  header.dispatchEvent( space );
  assert.ok( tbody.classList.contains( "collapsed" ) );
  assert.ok( space.defaultPrevented, "Space was not prevented — it would scroll the page instead of acting" );
} );

test( "an unrelated key does nothing", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const tbody  = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  const header = tbody.querySelector( "tr.epic-group-header" ) as HTMLElement;

  header.dispatchEvent( new KeyboardEvent( "keydown", { key: "a", bubbles: true, cancelable: true } ) );
  assert.ok( tbody.classList.contains( "collapsed" ), "an unrelated key toggled the section" );
} );

test( "a keypress on a NON-header element does nothing", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const row = container.querySelector( "tr.task-row" ) as HTMLElement;
  row.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true, cancelable: true } ) );

  const tbody = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.ok( tbody.classList.contains( "collapsed" ) );
} );

test( "a click that is not on a header is ignored", () => {
  const { container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  ( container.querySelector( "tr.task-row" ) as HTMLElement ).click();
  const tbody = container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.ok( tbody.classList.contains( "collapsed" ) );
} );

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test( "the pane repaints off the TASK LIST's event — it takes no fetch of its own", () => {
  const { bus, store, container } = mountPane( { tasks: [] } );
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 0 );

  store.setComposite( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  emit( bus, true );

  // 🔴 THE SHARED CLOCK. A pane with its own timer reads as a bug the first time
  // the two disagree, so the subscription is to store_task_list_changed.
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 1 );
} );

test( "a stamping render writes the stamp; a non-stamping one leaves it alone", () => {
  const { bus, root } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const updated = root.querySelector( '[data-testid="multiplexer-epic-board-updated"]' ) as HTMLElement;
  assert.equal( updated.textContent, "" );

  emit( bus, false );
  assert.equal( updated.textContent, "", "a non-stamping render wrote a stamp" );

  emit( bus, true );
  assert.ok( updated.textContent!.startsWith( "updated " ) );
} );

test( "an unreachable render never stamps — a sentinel is not fresh data", () => {
  const { bus, store, root } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const updated = root.querySelector( '[data-testid="multiplexer-epic-board-updated"]' ) as HTMLElement;

  store.setComposite( { status: "unreachable", tasks: null } );
  emit( bus, true );
  assert.equal( updated.textContent, "", "an unreachable poll claimed a freshness it does not have" );
} );

test( "the refresh button asks the SHARED store to refresh", async () => {
  const { store, root } = mountPane( { tasks: [] } );
  ( root.querySelector( '[data-testid="multiplexer-epic-board-refresh"]' ) as HTMLButtonElement ).click();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( store.refreshCalls, 1 );
} );

test( "mounting twice throws rather than painting two boards", () => {
  const { renderer, root } = mountPane( { tasks: [] } );
  assert.throws( () => renderer.mount( root ), /already mounted/ );
} );

test( "unmount empties the root and a later event resurrects nothing", () => {
  const { bus, store, renderer, root } = mountPane( { tasks: [] } );
  renderer.unmount();
  assert.equal( root.childNodes.length, 0 );

  store.setComposite( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  emit( bus, true );
  assert.equal( root.childNodes.length, 0 );
} );

test( "forceRenderForTesting is inert once unmounted", () => {
  const { renderer, root } = mountPane( { tasks: [] } );
  renderer.unmount();
  renderer.forceRenderForTesting();
  assert.equal( root.childNodes.length, 0 );
} );

test( "unmount calls every unsubscribe it took out — the leak the DOM cannot show", () => {
  // 🔴 SAME LAYER LESSON AS THE HOLDING AREA. unmount nulls the container, so a
  // renderer that never released its subscription still LOOKS correct: every
  // repaint returns at that guard. The defect lives on the SUBSCRIPTION, so the
  // assertion has to be about the subscription.
  const inner = createEventBusForTesting();
  let taken = 0, released = 0;
  const countingBus = {
    on<T>( type: Parameters<typeof inner.on>[ 0 ], listener: ( e: never ) => void ): () => void {
      taken += 1;
      const off = inner.on<T>( type, listener as never );
      return () => { released += 1; off(); };
    },
    off : inner.off.bind( inner ),
    emit: inner.emit.bind( inner ),
  } as unknown as typeof inner;

  const renderer = createEpicBoardRenderer( {
    eventBus: countingBus, store: fakeStore( { tasks: [] } ), storiesFn: () => ( {} ),
    nowDateFn: () => new Date( "2026-09-05T21:00:00Z" ),
  } );
  renderer.mount( document.createElement( "div" ) );

  // Positive control — without it a renderer that subscribed to NOTHING would
  // satisfy released === taken at 0 === 0 and pass vacuously.
  assert.ok( taken >= 1, `the renderer took out no subscriptions — this test would pass vacuously (taken=${ taken })` );
  renderer.unmount();
  assert.equal( released, taken, `unmount released ${ released } of ${ taken } subscriptions — the rest leak onto the bus` );
} );

test( "the persisted choice is what a REPAINT reads, not the default", () => {
  // ⚠️ THE TRI-STATE, PINNED END TO END: expanded / collapsed / ABSENT-falls-
  // through-to-a-per-key-default. This walks all three — default collapsed, a
  // recorded open choice, and that choice surviving a repaint — because a
  // renderer that persisted correctly and then re-read the DEFAULT on repaint
  // would pass every single-state test and still throw the choice away.
  const { bus, container } = mountPane( { tasks: [ task( "t1", "epic:alpha" ) ] } );
  const tbodyOf = () => container.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;

  assert.ok( tbodyOf().classList.contains( "collapsed" ), "ABSENT branch: an epic should default collapsed" );

  ( container.querySelector( "tr.epic-group-header" ) as HTMLElement ).click();
  assert.equal( epicGroupIsExpanded( "epic:alpha", loadEpicGroupState() ), true );

  emit( bus, true );
  assert.ok( !tbodyOf().classList.contains( "collapsed" ),
    "the repaint re-read the default instead of the recorded choice" );
} );

test( "a null row does not throw, and surfaces in DRIFT rather than vanishing", () => {
  // ⚠️ I WROTE THIS TEST BACKWARDS FIRST — asserting the null row was dropped —
  // and it went red. The code is right and the assumption was wrong:
  // isOpenStatus treats a MISSING status as OPEN, "degrade-safe", which is this
  // fleet's fail-loud-toward-owed rule. So a malformed row is not silently
  // discarded; it carries no correlation_key, lands in DRIFT, and the drift
  // section's whole job is to show rows whose epic is missing.
  //
  // ⇒ A test asserting the row VANISHED would have pinned the opposite policy,
  // and it would have looked like the tidier behaviour.
  const { container, countEl } = mountPane( {
    tasks: [ task( "t1", "epic:alpha" ), null as unknown as TaskItem ] } );

  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 2 );

  const drift = container.querySelector( `tbody[data-epic="${ EPIC_DRIFT_KEY }"]` ) as HTMLElement;
  assert.equal( drift.querySelectorAll( "tr.task-row" ).length, 1, "the malformed row did not reach drift" );

  // The epic count is unmoved: drift is a section, never an epic.
  assert.equal( countEl.textContent, "1" );
} );
