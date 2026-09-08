// FinishedTasksRenderer — the pane's six states, its controls, and its polarity
// (row 470b7509, the multiplexer port of ba4bb92c).
//
// 🔴 THE FAKE STORE IS A REAL STATE HOLDER, NOT A CONSTANT. A store fake that
// answered the same thing whatever it was asked would make every assertion
// below satisfiable by a renderer that ignores the store entirely — the pill
// counts, the six-state dispatch and the em-dash rule would all be
// unfalsifiable. This one is set per test and read live, so a renderer reading
// the wrong field produces a different observation.
//
// ⚠️ AND THE SIX STATES ARE ASSERTED ON THEIR OWN TESTIDS, never on "the
// container is empty". Six states all wearing one testid would be six states a
// test cannot tell apart — the collapsing this pane exists to prevent, one
// level down in the test surface.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/finished_tasks_renderer.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFinishedTasksRenderer,
  FINISHED_SENTINELS,
  type FinishedTasksStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/FinishedTasksRenderer";
import {
  FINISHED_SHOWN_KEY,
  FINISHED_STATUSES,
  type FinishedEventsByStatus,
  type FinishedTaskEvent,
} from "../../../../lupin_app/static/js/multiplexer/render/finishedTasksModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const FIXED_DATE = (): Date => new Date( "2026-09-07T20:00:00Z" );

function ev( over: Partial<FinishedTaskEvent> = {} ): FinishedTaskEvent {
  return {
    id: 1, item_id: "i1", ts: "2026-09-07T19:00:00.000Z",
    actor: "rio c079db30", transition: "in_progress->done",
    reason: "shipped", title: "a finished row", ...over,
  };
}

/** A store fake that HOLDS state and records the calls the renderer makes. */
function fakeStore( init: {
  events?  : FinishedEventsByStatus;
  measured?: ReadonlyArray<string>;
  error?   : string | null;
  days?    : number;
} = {} ) {
  const state = {
    events    : init.events ?? {},
    measured  : init.measured ?? [],
    error     : init.error ?? null,
    days      : init.days ?? 1,
    refreshes : 0,
    setDays   : [] as number[],
  };
  const store: FinishedTasksStoreLike = {
    eventsByStatus   : () => state.events,
    measuredStatuses : () => state.measured,
    error            : () => state.error,
    windowDays       : () => state.days,
    setWindowDays    : ( d ) => { state.days = d; state.setDays.push( d ); },
    refresh          : async () => { state.refreshes += 1; },
  };
  return { store, state };
}

/** A localStorage fake. `throwOn` makes the named op throw, for the private-mode leg. */
function fakeStorage( seed: Record<string, string> = {}, throwOn?: "getItem" | "setItem" ) {
  const map = new Map( Object.entries( seed ) );
  return {
    map,
    storage: {
      getItem( k: string ): string | null {
        if ( throwOn === "getItem" ) throw new Error( "private mode" );
        return map.get( k ) ?? null;
      },
      setItem( k: string, v: string ): void {
        if ( throwOn === "setItem" ) throw new Error( "quota exceeded" );
        map.set( k, v );
      },
    },
  };
}

function mountPane( opts: {
  store?   : FinishedTasksStoreLike;
  storage? : Pick<Storage, "getItem" | "setItem"> | null;
} = {} ) {
  const root  = document.createElement( "div" );
  const bus   = createEventBusForTesting();
  const store = opts.store ?? fakeStore().store;
  const r = createFinishedTasksRenderer( {
    eventBus  : bus,
    store,
    nowDateFn : FIXED_DATE,
    storage   : opts.storage === undefined ? fakeStorage().storage : opts.storage,
  } );
  r.mount( root );
  return { root, bus, renderer: r, unmount: () => r.unmount() };
}

const q  = ( root: HTMLElement, sel: string ): HTMLElement | null => root.querySelector( sel );
const qa = ( root: HTMLElement, sel: string ): HTMLElement[] => Array.from( root.querySelectorAll( sel ) );
const sentinel = ( root: HTMLElement, variant: string ): HTMLElement | null =>
  root.querySelector( `[data-testid="multiplexer-finished-tasks-${ variant }"]` );

/** Push a resolved poll through the bus, exactly as the store does. */
function poll( bus: ReturnType<typeof createEventBusForTesting> ): void {
  bus.emit( { type: "store_finished_tasks_changed", payload: { stampUpdated: true }, source: "test", ts: 0 } as never );
}

// ---------------------------------------------------------------------------
// Chrome
// ---------------------------------------------------------------------------

test( "the pane builds its own chrome: header, count chip, refresh, updated stamp, controls, container", () => {
  const { root, unmount } = mountPane();
  assert.notEqual( q( root, ".section-header" ), null );
  assert.notEqual( q( root, '[data-testid="multiplexer-finished-tasks-count"]' ), null );
  assert.notEqual( q( root, ".finished-tasks-refresh" ), null );
  assert.notEqual( q( root, '[data-testid="multiplexer-finished-tasks-updated"]' ), null );
  assert.notEqual( q( root, ".finished-tasks-controls" ), null );
  assert.notEqual( q( root, '[data-testid="multiplexer-finished-tasks-container"]' ), null );
  unmount();
} );

test( "🔴 EVERY CONTROL IS IN .section-content AND NOT IN .section-header", () => {
  // The header carries the collapse handler, so a slider there would collapse
  // the panel on every drag. SLICED rather than asserted globally: "the slider
  // exists somewhere in the pane" is true in the right AND the wrong
  // arrangement, so it would measure nothing.
  const { root, unmount } = mountPane();
  const header = q( root, ".section-header" )!;
  const body   = q( root, ".section-content" )!;

  assert.equal( header.querySelector( "#finished-tasks-window" ), null,
    "the slider is in the header — it will collapse the panel on every drag" );
  assert.equal( header.querySelector( ".finished-pill" ), null, "the pills are in the header" );
  assert.notEqual( body.querySelector( "#finished-tasks-window" ), null, "the slider is not in the body" );
  assert.equal( body.querySelectorAll( ".finished-pill" ).length, 3, "the pills are not in the body" );
  unmount();
} );

test( "mounting twice throws rather than building a second set of controls", () => {
  const { renderer, unmount } = mountPane();
  assert.throws( () => renderer.mount( document.createElement( "div" ) ), /already mounted/ );
  unmount();
} );

test( "unmount empties the root and detaches the subscription", () => {
  const { root, bus, unmount } = mountPane();
  unmount();
  assert.equal( root.childNodes.length, 0 );
  poll( bus );   // must not throw against a torn-down renderer
} );

test( "forceRenderForTesting repaints while mounted and is inert after unmount", () => {
  const { renderer, root, unmount } = mountPane( {
    store: fakeStore( { events: { done: [ ev() ] }, measured: [ ...FINISHED_STATUSES ] } ).store,
  } );
  renderer.forceRenderForTesting();
  assert.notEqual( q( root, '[data-testid="multiplexer-finished-tasks-table"]' ), null );
  unmount();
  renderer.forceRenderForTesting();
} );

// ---------------------------------------------------------------------------
// The pills
// ---------------------------------------------------------------------------

test( "three pills, in FINISHED_STATUSES order, each carrying data-status and the legacy id", () => {
  const { root, unmount } = mountPane();
  const pills = qa( root, ".finished-pill" );
  assert.deepEqual( pills.map( ( p ) => p.getAttribute( "data-status" ) ), [ ...FINISHED_STATUSES ] );
  assert.deepEqual( pills.map( ( p ) => p.id ),
    [ "finished-pill-done", "finished-pill-dropped", "finished-pill-wont-fix" ],
    "the ids must match the legacy pane's — wont_fix renders as wont-fix" );
  unmount();
} );

test( "🔴 DONE IS PRE-LIT ALONE — aria-pressed true on done, false on the other two", () => {
  const { root, unmount } = mountPane();
  assert.deepEqual( qa( root, ".finished-pill" ).map( ( p ) => p.getAttribute( "aria-pressed" ) ),
    [ "true", "false", "false" ] );
  unmount();
} );

test( "a pill click toggles it, and the change is a CLIENT-SIDE repaint with NO fetch", () => {
  const { store, state } = fakeStore( {
    events   : { done: [ ev() ], dropped: [ ev( { id: 2, transition: "queued->dropped", title: "dropped row" } ) ] },
    measured : [ "done", "dropped" ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );
  state.refreshes = 0;

  assert.equal( qa( root, '[data-testid="multiplexer-finished-task-row"]' ).length, 1 );
  q( root, "#finished-pill-dropped" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );

  assert.equal( q( root, "#finished-pill-dropped" )!.getAttribute( "aria-pressed" ), "true" );
  assert.equal( qa( root, '[data-testid="multiplexer-finished-task-row"]' ).length, 2,
    "lighting a pill must reveal rows already in hand" );
  assert.equal( state.refreshes, 0,
    "a pill click fired a fetch — the pane must repaint from data already fetched" );
  unmount();
} );

test( "🔴 CLICKING THE LAST LIT PILL OFF RE-LIGHTS DONE", () => {
  // There is no useful state in which this pane shows nothing on purpose, and
  // DONE-pre-lit is the ruled default.
  const { root, unmount } = mountPane();
  q( root, "#finished-pill-done" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( q( root, "#finished-pill-done" )!.getAttribute( "aria-pressed" ), "true",
    "turning the last pill off left the pane with nothing selected" );
  unmount();
} );

test( "a pill's count comes from the FULL fetch, not from the visible set", () => {
  // A count that depended on lit-ness would read 0 for every unlit pill — and
  // that number is exactly what an operator uses to decide whether to light it.
  const { store } = fakeStore( {
    events   : { done: [ ev() ], dropped: [ ev( { id: 2 } ), ev( { id: 3 } ) ], wont_fix: [] },
    measured : [ "done", "dropped", "wont_fix" ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );

  const count = ( s: string ): string | null =>
    q( root, `[data-testid="multiplexer-finished-pill-count-${ s }"]` )!.textContent;
  assert.equal( count( "done" ), "1" );
  assert.equal( count( "dropped" ), "2", "an UNLIT pill must still show its own count" );
  assert.equal( count( "wont_fix" ), "0" );
  unmount();
} );

test( "🔴 A ZERO-COUNT PILL IS DIMMED, NOT HIDDEN, AND STAYS CLICKABLE", () => {
  // "Zero is a claim, not a default." A pill that vanishes at zero turns
  // "nothing was refused today" into "this feature does not exist", and makes
  // the control bar change width as the day goes on.
  const { store } = fakeStore( {
    events   : { done: [ ev() ], dropped: [], wont_fix: [] },
    measured : [ "done", "dropped", "wont_fix" ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );

  const zero = q( root, "#finished-pill-dropped" )!;
  assert.ok( zero.classList.contains( "finished-pill-zero" ), "a measured zero must dim its pill" );
  assert.equal( zero.hasAttribute( "hidden" ), false, "a zero-count pill must not be hidden" );
  zero.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( zero.getAttribute( "aria-pressed" ), "true", "a zero-count pill must stay clickable" );
  unmount();
} );

test( "🔴 AN UNMEASURED PILL KEEPS THE EM DASH — it does not read 0", () => {
  // Absent and empty are different facts, and this is where the difference
  // becomes visible to a person: "—" says nobody counted, "0" says somebody did.
  const { store } = fakeStore( { events: { done: [ ev() ] }, measured: [ "done" ], error: "HTTP 500 (dropped)" } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );
  assert.equal( q( root, '[data-testid="multiplexer-finished-pill-count-dropped"]' )!.textContent, "—" );
  assert.equal( q( root, "#finished-pill-dropped" )!.classList.contains( "finished-pill-zero" ), false,
    "an unmeasured pill must not be dimmed as though it were a measured zero" );
  unmount();
} );

// ---------------------------------------------------------------------------
// Persistence — positive polarity
// ---------------------------------------------------------------------------

test( "🔴 THE PERSISTED VALUE IS THE LIT SET, AND IT ROUND-TRIPS", () => {
  const s = fakeStorage();
  const { root, unmount } = mountPane( { storage: s.storage } );
  q( root, "#finished-pill-dropped" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );

  // 🔴 THE DISCRIMINATING ASSERTION. Under NEGATIVE polarity this same click
  // would write ["wont_fix"] — the one that is hidden. The two spellings differ
  // here, which is why the VALUE is asserted rather than its length.
  assert.equal( s.map.get( FINISHED_SHOWN_KEY ), '["done","dropped"]' );
  unmount();
} );

test( "a persisted selection is honoured on mount", () => {
  const s = fakeStorage( { [ FINISHED_SHOWN_KEY ]: '["wont_fix"]' } );
  const { root, unmount } = mountPane( { storage: s.storage } );
  assert.deepEqual(
    qa( root, ".finished-pill" ).map( ( p ) => p.getAttribute( "aria-pressed" ) ),
    [ "false", "false", "true" ],
    "the pane did not read the persisted selection — or read it with the polarity inverted",
  );
  unmount();
} );

test( "a MISSING key mounts the spec default rather than an empty pane", () => {
  const { root, unmount } = mountPane( { storage: fakeStorage().storage } );
  assert.deepEqual( qa( root, ".finished-pill" ).map( ( p ) => p.getAttribute( "aria-pressed" ) ),
    [ "true", "false", "false" ] );
  unmount();
} );

test( "🔴 A HOST WITH NO STORAGE AT ALL STILL RENDERS, AND STILL DEFAULTS TO DONE", () => {
  // `null` means NO PERSISTENCE, not "use the default backend". It is the state
  // the production default resolves to on a host without localStorage, so it is
  // driven here rather than left as a branch only a browser can reach.
  const { root, unmount } = mountPane( { storage: null } );
  assert.deepEqual( qa( root, ".finished-pill" ).map( ( p ) => p.getAttribute( "aria-pressed" ) ),
    [ "true", "false", "false" ] );
  // And a click must still work — it simply persists nowhere.
  q( root, "#finished-pill-dropped" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( q( root, "#finished-pill-dropped" )!.getAttribute( "aria-pressed" ), "true" );
  unmount();
} );

test( "a row with NO timestamp renders the em dash and an empty hover, not NaN", () => {
  // The wire type says `ts: string`, but the projection is a database row and a
  // torn one must render readably rather than as "NaNm".
  const { store } = fakeStore( {
    events   : { done: [ { ...ev(), ts: null as unknown as string } ] },
    measured : [ ...FINISHED_STATUSES ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );
  assert.equal( q( root, ".finished-when" )!.textContent, "—" );
  assert.equal( q( root, ".finished-when" )!.getAttribute( "title" ), "" );
  unmount();
} );

test( "a storage that THROWS never breaks rendering — in either direction", () => {
  // A private-mode or quota failure must not take the pane down. Both legs,
  // because a try/catch on one side only still fails on the other.
  const readFails = mountPane( { storage: fakeStorage( {}, "getItem" ).storage } );
  assert.equal( qa( readFails.root, ".finished-pill" ).length, 3 );
  readFails.unmount();

  const writeFails = mountPane( { storage: fakeStorage( {}, "setItem" ).storage } );
  q( writeFails.root, "#finished-pill-dropped" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( q( writeFails.root, "#finished-pill-dropped" )!.getAttribute( "aria-pressed" ), "true",
    "a failed write must not stop the click from taking effect on screen" );
  writeFails.unmount();
} );

// ---------------------------------------------------------------------------
// The window slider
// ---------------------------------------------------------------------------

test( "the slider is a WIDTH control with the ruled range, and there is NO stepper beside it", () => {
  const { root, unmount } = mountPane();
  const slider = q( root, "#finished-tasks-window" ) as HTMLInputElement;
  assert.equal( slider.type, "range" );
  assert.equal( slider.min, "1" );
  assert.equal( slider.max, "14" );
  assert.equal( slider.step, "1" );
  assert.equal( slider.value, "1" );
  // Rick ruled a WIDTH slider, "not a stepper, not both" — so the ABSENCE of a
  // second control is part of the spec rather than an omission.
  assert.equal( qa( root, ".finished-tasks-controls button" ).length, 3,
    "the controls bar has a button that is not one of the three pills — a stepper was ruled out" );
  unmount();
} );

test( "🔴 `input` IS PREVIEW ONLY — it moves the readout and fires NO fetch", () => {
  const { store, state } = fakeStore();
  const { root, unmount } = mountPane( { store } );
  const slider = q( root, "#finished-tasks-window" ) as HTMLInputElement;

  slider.value = "7";
  slider.dispatchEvent( new Event( "input", { bubbles: true } ) );

  assert.equal( q( root, "#finished-tasks-window-value" )!.textContent, "7d" );
  assert.deepEqual( state.setDays, [ 7 ] );
  assert.equal( state.refreshes, 0, "dragging the slider fired a request — one per pixel" );
  unmount();
} );

test( "`change` COMMITS — it fires exactly one fetch", () => {
  const { store, state } = fakeStore();
  const { root, unmount } = mountPane( { store } );
  const slider = q( root, "#finished-tasks-window" ) as HTMLInputElement;

  slider.value = "14";
  slider.dispatchEvent( new Event( "change", { bubbles: true } ) );

  assert.equal( q( root, "#finished-tasks-window-value" )!.textContent, "14d" );
  assert.equal( state.days, 14 );
  assert.equal( state.refreshes, 1 );
  unmount();
} );

test( "an out-of-range slider value is clamped before it reaches the store", () => {
  const { store, state } = fakeStore();
  const { root, unmount } = mountPane( { store } );
  const slider = q( root, "#finished-tasks-window" ) as HTMLInputElement;
  slider.value = "0";
  slider.dispatchEvent( new Event( "change", { bubbles: true } ) );
  assert.equal( state.days, 1, "a zero-day window can never contain anything and must never reach the wire" );
  unmount();
} );

test( "the ⟳ button refreshes", () => {
  const { store, state } = fakeStore();
  const { root, unmount } = mountPane( { store } );
  q( root, ".finished-tasks-refresh" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( state.refreshes, 1 );
  unmount();
} );

// ---------------------------------------------------------------------------
// The count chip
// ---------------------------------------------------------------------------

test( "🔴 THE COUNT CHIP SHOWS AN EM DASH BEFORE THE FIRST POLL, NEVER 0", () => {
  // "0 finished today" and "not loaded yet" are materially different statements
  // to the person who asked for this pane BECAUSE work was going unfinished.
  const { root, unmount } = mountPane();
  assert.equal( q( root, '[data-testid="multiplexer-finished-tasks-count"]' )!.textContent, "—" );
  unmount();
} );

test( "after a poll the chip counts VISIBLE rows, and a measured zero really does read 0", () => {
  const { store } = fakeStore( {
    events   : { done: [ ev(), ev( { id: 2 } ) ], dropped: [ ev( { id: 3 } ) ] },
    measured : [ "done", "dropped" ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );
  assert.equal( q( root, '[data-testid="multiplexer-finished-tasks-count"]' )!.textContent, "2",
    "the chip counts LIT rows, and dropped is not lit by default" );

  const empty = mountPane( { store: fakeStore( { events: { done: [] }, measured: [ "done" ] } ).store } );
  poll( empty.bus );
  assert.equal( q( empty.root, '[data-testid="multiplexer-finished-tasks-count"]' )!.textContent, "0",
    "once a poll HAS resolved a real zero must read 0 — the em dash is for unmeasured only" );
  empty.unmount();
  unmount();
} );

test( "the updated stamp is written on a poll and is empty before one", () => {
  const { root, bus, unmount } = mountPane();
  assert.equal( q( root, '[data-testid="multiplexer-finished-tasks-updated"]' )!.textContent, "" );
  poll( bus );
  assert.match( q( root, '[data-testid="multiplexer-finished-tasks-updated"]' )!.textContent ?? "", /^updated / );
  unmount();
} );

// ---------------------------------------------------------------------------
// The six states — each on its OWN testid
// ---------------------------------------------------------------------------

test( "🔴 SIX STATES, SIX SEPARATELY-SELECTABLE SENTINELS, AND FIVE ARE REACHED THROUGH THE RENDERER", () => {
  const reached = new Set<string>();

  // 1 — unmeasured: nothing fetched yet, no failure.
  {
    const p = mountPane();
    assert.notEqual( sentinel( p.root, "unmeasured" ), null );
    reached.add( "unmeasured" ); p.unmount();
  }
  // 2 — error: nothing measured AND a failure explains why.
  {
    const p = mountPane( { store: fakeStore( { error: "HTTP 500 (done)" } ).store } );
    poll( p.bus );
    const el = sentinel( p.root, "error" )!;
    assert.notEqual( el, null );
    assert.match( el.textContent ?? "", /HTTP 500/, "the error sentinel must name the failure" );
    assert.match( el.textContent ?? "", /not "no finished work"/,
      "the error sentinel must say nothing was MEASURED — that is the whole distinction" );
    reached.add( "error" ); p.unmount();
  }
  // 3 — empty: measured, and a real zero.
  {
    const p = mountPane( { store: fakeStore( { events: { done: [] }, measured: [ "done" ] } ).store } );
    poll( p.bus );
    const el = sentinel( p.root, "empty" )!;
    assert.notEqual( el, null );
    assert.match( el.textContent ?? "", /measured zero/,
      "an empty result must be described as MEASURED, or it reads like a broken fetch" );
    reached.add( "empty" ); p.unmount();
  }
  // 4 — partial: some statuses answered, some did not. Rows AND the caveat.
  {
    const p = mountPane( { store: fakeStore( { events: { done: [ ev() ] }, measured: [ "done" ], error: "HTTP 500 (dropped)" } ).store } );
    poll( p.bus );
    assert.notEqual( sentinel( p.root, "partial" ), null );
    assert.notEqual( q( p.root, '[data-testid="multiplexer-finished-tasks-table"]' ), null,
      "a partial result must still show the rows it DID get — withholding them helps nobody" );
    reached.add( "partial" ); p.unmount();
  }
  // 5 — rows: measured, complete, non-empty.
  {
    const p = mountPane( { store: fakeStore( { events: { done: [ ev() ] }, measured: [ ...FINISHED_STATUSES ] } ).store } );
    poll( p.bus );
    assert.notEqual( q( p.root, '[data-testid="multiplexer-finished-tasks-table"]' ), null );
    assert.equal( sentinel( p.root, "partial" ), null, "a complete result must NOT wear the partial caveat" );
    reached.add( "rows" ); p.unmount();
  }

  assert.deepEqual( [ ...reached ].sort(), [ "empty", "error", "partial", "rows", "unmeasured" ] );
} );

test( "the SIXTH state (no_filter) is unreachable through the click path BY DESIGN, and its message still exists", () => {
  // ⚠️ SAID PLAINLY RATHER THAN QUIETLY DROPPED. The pill handler can never
  // leave the selection empty — it re-lights DONE — so five of the six states
  // are reachable through the renderer and this one is not. It is carried for
  // the same reason the holding area carries `query_unavailable`: deleting it
  // would make a future empty selection render the WRONG explanation rather
  // than a missing one, and a wrong explanation is worse than a gap.
  const { root, unmount } = mountPane( { storage: fakeStorage( { [ FINISHED_SHOWN_KEY ]: '["dropped"]' } ).storage } );
  q( root, "#finished-pill-dropped" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( q( root, "#finished-pill-done" )!.getAttribute( "aria-pressed" ), "true",
    "emptying the selection must re-light DONE rather than reaching the no_filter state" );
  assert.match( FINISHED_SENTINELS.no_filter, /Pick at least one pill/ );
  unmount();
} );

// ---------------------------------------------------------------------------
// The table
// ---------------------------------------------------------------------------

test( "the table is WHEN / WHAT / WHO / WHY, with the absolute instant on hover", () => {
  const { store } = fakeStore( {
    events   : { done: [ ev( { ts: "2026-09-07T19:46:00.000Z", title: "ported the pane", actor: "rio c079db30", reason: "shipped" } ) ] },
    measured : [ ...FINISHED_STATUSES ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );

  assert.deepEqual( qa( root, ".finished-tasks-table th" ).map( ( th ) => th.textContent ), [ "When", "What", "Who", "Why" ] );
  assert.equal( q( root, ".finished-when" )!.textContent, "14m" );
  assert.equal( q( root, ".finished-when" )!.getAttribute( "title" ), "2026-09-07T19:46:00.000Z" );
  assert.equal( q( root, ".finished-what" )!.textContent, "ported the pane" );
  assert.equal( q( root, ".finished-who" )!.textContent, "rio", "WHO is the persona; the session id is noise" );
  assert.equal( q( root, ".finished-why" )!.textContent, "shipped" );
  unmount();
} );

test( "a row carries its terminal status AND the shared task-status class", () => {
  const { store } = fakeStore( {
    events   : { wont_fix: [ ev( { id: 9, transition: "queued->wont_fix", title: "refused" } ) ] },
    measured : [ ...FINISHED_STATUSES ],
  } );
  const { root, bus, unmount } = mountPane( {
    store, storage: fakeStorage( { [ FINISHED_SHOWN_KEY ]: '["wont_fix"]' } ).storage,
  } );
  poll( bus );

  const row = q( root, '[data-testid="multiplexer-finished-task-row"]' )!;
  assert.equal( row.getAttribute( "data-status" ), "wont_fix" );
  assert.ok( row.classList.contains( "task-status-wont-fix" ),
    "a terminal row must be tinted the way the task list tints it — this is the class the ride-along fix added" );
  unmount();
} );

test( "a title or a reason carrying markup is rendered as TEXT, not as HTML", () => {
  const { store } = fakeStore( {
    events   : { done: [ ev( { title: "<img src=x onerror=alert(1)>", reason: "<b>bold</b>" } ) ] },
    measured : [ ...FINISHED_STATUSES ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );

  assert.equal( q( root, ".finished-what" )!.querySelector( "img" ), null, "a title was interpreted as markup" );
  assert.equal( q( root, ".finished-what" )!.textContent, "<img src=x onerror=alert(1)>" );
  assert.equal( q( root, ".finished-why" )!.querySelector( "b" ), null );
  unmount();
} );

test( "an absent title, actor and reason render readable placeholders rather than blanks", () => {
  const { store } = fakeStore( {
    events   : { done: [ ev( { title: null, reason: null, actor: null } ) ] },
    measured : [ ...FINISHED_STATUSES ],
  } );
  const { root, bus, unmount } = mountPane( { store } );
  poll( bus );
  assert.equal( q( root, ".finished-what" )!.textContent, "(untitled)" );
  assert.equal( q( root, ".finished-who" )!.textContent, "—" );
  assert.equal( q( root, ".finished-why" )!.textContent, "" );
  unmount();
} );

test( "rows from several lit statuses interleave by time rather than clumping per status", () => {
  const { store } = fakeStore( {
    events : {
      done    : [ ev( { id: 1, ts: "2026-09-07T10:00:00Z", title: "old-done" } ) ],
      dropped : [ ev( { id: 2, ts: "2026-09-07T18:00:00Z", title: "new-dropped", transition: "queued->dropped" } ) ],
    },
    measured : [ ...FINISHED_STATUSES ],
  } );
  const { root, bus, unmount } = mountPane( {
    store, storage: fakeStorage( { [ FINISHED_SHOWN_KEY ]: '["done","dropped"]' } ).storage,
  } );
  poll( bus );
  assert.deepEqual( qa( root, ".finished-what" ).map( ( c ) => c.textContent ), [ "new-dropped", "old-done" ] );
  unmount();
} );


// ── the click layer, which is where the incident would ENTER (Mr. Radio, row follow-on) ──

test( "a pill carrying an INHERITED name as its data-status does not take the pane down", () => {
  // 🔴 ENTERS AT THE CLICK, NOT AT mergeShownEvents. The model-level test proves the
  // function refuses; only this one proves the PATH does. Traced:
  //   onPillClick -> pill.getAttribute( "data-status" )   <- UNFILTERED
  //     -> [ ...this.shown, status ] -> this.shown
  //     -> mergeShownEvents( eventsByStatus, this.shown )
  // parseShownStatuses CANNOT deliver this — it filters against FINISHED_STATUSES,
  // so the persisted route is closed (measured: ["toString"] -> ["done"]). The
  // toggle is the one writer that appends a status without filtering it.
  //
  // Pre-fix, the bare index returned Object.prototype.toString, which IS
  // `!== undefined`, so the spread threw:
  //   TypeError: Spread syntax requires ...iterable[Symbol.iterator] to be a function
  const { root, bus, unmount } = mountPane( {
    store: fakeStore( { events: { done: [ ev( { title: "a real row" } ) ] },
                        measured: [ "done" ] } ).store,
  } );
  poll( bus );

  // ⚠️ RE-POINT AN EXISTING PILL, DO NOT APPEND ONE. Listeners are attached
  // PER-PILL at build time (FinishedTasksRenderer:243), so an injected button has
  // no listener and clicking it is a no-op — the first cut of this test did that
  // and passed against the PRE-FIX code, which is a blind fixture, not a guard.
  const hostile = q( root, "#finished-pill-dropped" )!;
  hostile.setAttribute( "data-status", "toString" );

  // ⚠️ `assert.doesNotThrow` CANNOT SEE THIS. A DOM listener's exception is REPORTED,
  // not propagated to dispatchEvent, so the throw never reaches the caller. Count the
  // reported errors instead — that is the only assertion that can observe it.
  const errors: unknown[] = [];
  const onErr = ( e: unknown ): void => { errors.push( e ); };
  window.addEventListener( "error", onErr );
  hostile.dispatchEvent( new Event( "click", { bubbles: true } ) );
  window.removeEventListener( "error", onErr );

  assert.deepEqual( errors, [],
    "an inherited data-status reached the prototype and threw inside the click handler" );

  // POSITIVE CONTROL: the pane is still alive and still showing the real row —
  // "did not throw" is also satisfied by a click handler that silently died.
  poll( bus );
  assert.ok( root.textContent?.includes( "a real row" ),
    "the pane survived the click but stopped rendering its rows" );
  unmount();
} );
