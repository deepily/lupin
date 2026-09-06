// Holding-area card — HoldingAreaRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE SENTINEL AND EMPTY STRINGS ARE COMPARED AGAINST notifications.js, NOT
// AGAINST LITERALS TYPED HERE — the same rule the group template's tests carry,
// for the same reason: a literal retyped in this file shares its provenance with
// the one in the renderer, so the two move together on any copy-paste error and
// the comparison can never fail.
//
// ⚠️ THE PANE'S HARDEST STATE IS THE ONE THAT LOOKS LIKE THE EASIEST. An empty
// holding area and a holding area that has not answered yet are DIFFERENT, and
// both would render as a blank container if nobody decided otherwise. The
// pre-first-poll state takes the unreachable sentinel rather than "Nothing
// waiting on triage." because the empty message is the REASSURING reading, and
// a reassurance is what stops the next person looking.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  HOLDING_AREA_SENTINELS,
  HOLDING_AREA_EMPTY_MESSAGE,
  HOLDING_AREA_COUNT_UNKNOWN,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreHoldingAreaChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const HERE = dirname( fileURLToPath( import.meta.url ) );
const LEGACY_PATH = resolve( HERE, "../../../../lupin_app/static/js/notifications.js" );

/** The body of `renderHoldingArea`, sliced out of the legacy client. */
function legacyPaneSource(): string {
  const src   = readFileSync( LEGACY_PATH, "utf8" );
  const start = src.indexOf( "renderHoldingArea( composite ) {" );
  assert.ok( start !== -1, "legacy renderHoldingArea not found — the extraction is pointing at nothing" );
  const end   = src.indexOf( "_renderHoldingAreaGroup( filer, tasks ) {", start );
  assert.ok( end > start, "legacy _renderHoldingAreaGroup not found after the pane renderer" );
  return src.slice( start, end );
}

/** The `key : "message"` sentinel map the legacy pane declares. */
function legacySentinels(): Record<string, string> {
  const body  = legacyPaneSource();
  const found: Record<string, string> = {};
  const re = /(auth_required|query_unavailable|unreachable)\s*:\s*"([^"]*)"/g;
  let m: RegExpExecArray | null;
  while ( ( m = re.exec( body ) ) !== null ) found[ m[ 1 ] ] = m[ 2 ];
  return found;
}

function heldTask( id: string, filer: string ): TaskItem {
  return { id, title: `row ${ id }`, status: "todo", priority: "P2", created_by: filer } as unknown as TaskItem;
}

interface FakeStore extends HoldingAreaStoreLike {
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

function mountPane( composite: TaskListComposite | null ) {
  const bus   = createEventBusForTesting();
  const store = fakeStore( composite );
  const root  = document.createElement( "div" );
  const renderer = createHoldingAreaRenderer( {
    eventBus  : bus,
    store,
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } );
  renderer.mount( root );
  return {
    bus, store, root, renderer,
    container : root.querySelector( ".holding-area-container" ) as HTMLElement,
    countEl   : root.querySelector( '[data-testid="multiplexer-holding-area-count"]' ) as HTMLElement,
  };
}

// ---------------------------------------------------------------------------
// The extraction's positive control — first, because every string comparison
// below is worthless without it.
// ---------------------------------------------------------------------------

test( "the legacy extraction reaches all three sentinel messages and the empty message", () => {
  const legacy = legacySentinels();
  assert.equal( Object.keys( legacy ).length, 3,
    `expected exactly three sentinels in the legacy pane renderer, found ${ Object.keys( legacy ).length } — the slice boundaries have moved` );
  for ( const [ key, message ] of Object.entries( legacy ) ) {
    assert.ok( message.length > 20, `sentinel ${ key } came back too short to be the real one: ${ JSON.stringify( message ) }` );
  }
  assert.equal( new Set( Object.values( legacy ) ).size, 3,
    "two sentinels extracted identical — the regex is matching one entry more than once" );

  assert.ok( legacyPaneSource().includes( HOLDING_AREA_EMPTY_MESSAGE ),
    "the legacy empty message is not in the pane renderer — the extraction or the copy has drifted" );
} );

test( "all three sentinel messages are byte-identical to the legacy client's", () => {
  assert.deepEqual( { ...HOLDING_AREA_SENTINELS }, legacySentinels() );
} );

// ---------------------------------------------------------------------------
// The states
// ---------------------------------------------------------------------------

test( "a signed-out composite paints the auth sentinel and an unknown count", () => {
  const { container, countEl } = mountPane( { status: "auth_required" } );
  assert.equal( container.textContent, HOLDING_AREA_SENTINELS.auth_required );
  assert.equal( countEl.textContent, HOLDING_AREA_COUNT_UNKNOWN );
  assert.ok( container.querySelector( ".holding-area-sentinel" ) );
} );

test( "an unreachable composite paints the unreachable sentinel and NO stale rows", () => {
  const { store, renderer, container, countEl } = mountPane(
    { tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] } );

  // A good poll first, so there IS a last-known state available to leak.
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 1 );

  store.setComposite( { status: "unreachable", tasks: null } );
  renderer.forceRenderForTesting();

  // 🔴 THE POINT OF THIS TEST. The task list replays last-known rows here; this
  // pane must not — a held row awaits a DECISION, so a stale one invites
  // approving something that has already moved.
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 0 );
  assert.equal( container.textContent, HOLDING_AREA_SENTINELS.unreachable );
  assert.equal( countEl.textContent, HOLDING_AREA_COUNT_UNKNOWN );
} );

test( "the pre-first-poll state is the unreachable sentinel, NOT 'nothing waiting'", () => {
  const { container, countEl } = mountPane( null );
  assert.equal( container.textContent, HOLDING_AREA_SENTINELS.unreachable );
  assert.notEqual( container.textContent, HOLDING_AREA_EMPTY_MESSAGE );
  assert.equal( countEl.textContent, HOLDING_AREA_COUNT_UNKNOWN );
} );

test( "query_unavailable renders its OWN message, not the generic unreachable one", () => {
  // ⚠️ Today's store cannot emit this status — it maps 401 to auth_required and
  // everything else to unreachable. The branch is kept because a future third
  // status falling through to the unreachable message would be a WRONG
  // explanation rather than a missing one: a deploy defect and an outage want
  // different responses. The notEqual is the whole guard — a fall-through would
  // still paint A message, and "some sentinel appeared" passes on exactly the
  // wrong one.
  const { container } = mountPane( { status: "query_unavailable" } );
  assert.equal( container.textContent, HOLDING_AREA_SENTINELS.query_unavailable );
  assert.notEqual( container.textContent, HOLDING_AREA_SENTINELS.unreachable );
} );

test( "a genuinely empty queue says so rather than painting blank", () => {
  const { container, countEl } = mountPane( { tasks: [] } );
  assert.equal( container.textContent, HOLDING_AREA_EMPTY_MESSAGE );
  assert.equal( countEl.textContent, "0" );
  assert.ok( container.childNodes.length > 0,
    "the pane painted nothing — an empty holding area must SAY it is empty, or it reads as broken" );
} );

test( "a malformed payload takes the unreachable sentinel, not the empty message", () => {
  // groupHeldRowsByFiler is degrade-safe and returns no groups here, which would
  // paint "Nothing waiting on triage." over an answer nobody understood — an
  // empty result and a broken one wearing one face.
  const { container, countEl } = mountPane( { tasks: "not an array" as unknown as TaskItem[] } );
  assert.equal( container.textContent, HOLDING_AREA_SENTINELS.unreachable );
  assert.equal( countEl.textContent, HOLDING_AREA_COUNT_UNKNOWN );
} );

test( "held rows render grouped by filer, and the count is the ROW total not the group count", () => {
  const { container, countEl } = mountPane( { tasks: [
    heldTask( "t1", "Krishna 420f5ec9" ),
    heldTask( "t2", "mr radio 0e61abe3" ),
    heldTask( "t3", "Krishna 420f5ec9" ),
  ] } );

  assert.equal( container.querySelectorAll( ".holding-area-group" ).length, 2 );
  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 3 );

  // 🔴 THREE ROWS IN TWO GROUPS, chosen so the two numbers differ. A count taken
  // off the groups would read 2 and look perfectly plausible.
  assert.equal( countEl.textContent, "3" );
} );

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test( "the store event repaints the pane", () => {
  const { bus, store, container } = mountPane( { tasks: [] } );
  assert.equal( container.textContent, HOLDING_AREA_EMPTY_MESSAGE );

  store.setComposite( { tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] } );
  bus.emit<StoreHoldingAreaChangedPayload>( { type: "store_holding_area_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } );

  assert.equal( container.querySelectorAll( "tr.task-row" ).length, 1 );
} );

test( "a stamping render writes the updated stamp; a non-stamping one leaves it alone", () => {
  const { bus, store, root } = mountPane( { tasks: [] } );
  const updated = root.querySelector( '[data-testid="multiplexer-holding-area-updated"]' ) as HTMLElement;

  // The initial mount paint does NOT stamp — nothing has been fetched for it.
  assert.equal( updated.textContent, "" );

  store.setComposite( { tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] } );
  bus.emit<StoreHoldingAreaChangedPayload>( { type: "store_holding_area_changed", payload: { stampUpdated: false }, source: "test", ts: 0 } );
  assert.equal( updated.textContent, "", "a non-stamping render wrote a stamp" );

  bus.emit<StoreHoldingAreaChangedPayload>( { type: "store_holding_area_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } );
  assert.ok( updated.textContent!.startsWith( "updated " ),
    `stamp not written: ${ JSON.stringify( updated.textContent ) }` );
} );

test( "a sentinel render never stamps — a sentinel is not fresh data", () => {
  const { bus, store, root } = mountPane( { tasks: [] } );
  const updated = root.querySelector( '[data-testid="multiplexer-holding-area-updated"]' ) as HTMLElement;

  store.setComposite( { status: "unreachable", tasks: null } );
  bus.emit<StoreHoldingAreaChangedPayload>( { type: "store_holding_area_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } );
  assert.equal( updated.textContent, "",
    "an unreachable poll stamped 'updated' — the pane would claim a freshness it does not have" );
} );

test( "the refresh button asks the store to refresh", async () => {
  const { store, root } = mountPane( { tasks: [] } );
  const btn = root.querySelector( '[data-testid="multiplexer-holding-area-refresh"]' ) as HTMLButtonElement;
  btn.click();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( store.refreshCalls, 1 );
} );

test( "mounting twice throws rather than painting two panes", () => {
  const { renderer, root } = mountPane( { tasks: [] } );
  assert.throws( () => renderer.mount( root ), /already mounted/ );
} );

test( "unmount empties the root and detaches the subscription", () => {
  const { bus, store, renderer, root } = mountPane( { tasks: [] } );
  renderer.unmount();
  assert.equal( root.childNodes.length, 0 );

  // A repaint after unmount must not resurrect anything.
  store.setComposite( { tasks: [ heldTask( "t1", "Krishna 420f5ec9" ) ] } );
  bus.emit<StoreHoldingAreaChangedPayload>( { type: "store_holding_area_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } );
  assert.equal( root.childNodes.length, 0 );
} );

test( "forceRenderForTesting is inert once unmounted", () => {
  const { renderer, root } = mountPane( { tasks: [] } );
  renderer.unmount();
  renderer.forceRenderForTesting();
  assert.equal( root.childNodes.length, 0 );
} );

// ---------------------------------------------------------------------------
// 🔴 THE LEAK IS INVISIBLE FROM THE DOM, SO THIS TEST WATCHES THE BUS INSTEAD.
//
// M44 — deleting the `for ( const off of this.unsubscribers ) off();` line in
// unmount — SURVIVED the whole suite above. It is not an equivalent mutant: the
// bus keeps a reference to the dead renderer forever, which is a real leak. It
// is simply undetectable through the container, because unmount nulls
// `this.container` and every repaint returns at that guard. So the pane looks
// perfectly correct while the listener accumulates on every mount/unmount cycle.
//
// ⇒ A test that enters below the layer the defect enters at cannot speak to it.
// The defect lives on the SUBSCRIPTION, so the assertion has to be about the
// subscription — count the unsubscribes the renderer actually calls.
// ---------------------------------------------------------------------------

test( "unmount calls every unsubscribe it took out — the leak the DOM cannot show", () => {
  const inner = createEventBusForTesting();
  let taken = 0;
  let released = 0;

  const countingBus = {
    on<T>( type: Parameters<typeof inner.on>[ 0 ], listener: ( e: never ) => void ): () => void {
      taken += 1;
      const off = inner.on<T>( type, listener as never );
      return () => { released += 1; off(); };
    },
    off : inner.off.bind( inner ),
    emit: inner.emit.bind( inner ),
  } as unknown as typeof inner;

  const renderer = createHoldingAreaRenderer( {
    eventBus  : countingBus,
    store     : fakeStore( { tasks: [] } ),
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } );
  renderer.mount( document.createElement( "div" ) );

  // Positive control: without this, a renderer that subscribed to NOTHING would
  // satisfy `released === taken` at 0 === 0 and pass vacuously.
  assert.ok( taken >= 1, `the renderer took out no subscriptions — this test would pass vacuously (taken=${ taken })` );
  assert.equal( released, 0, "a subscription was released before unmount" );

  renderer.unmount();
  assert.equal( released, taken, `unmount released ${ released } of ${ taken } subscriptions — the rest leak onto the bus` );
} );
