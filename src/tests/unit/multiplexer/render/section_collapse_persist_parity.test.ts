// Parity A-2 #6 — opt-in persisted accordion collapse, and Finished Tasks as
// the one section that opts in.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1):
//   - `LUPIN_ACCORDION_PERSIST_KEYS`  src/lupin_app/static/html/notifications.html:1527
//     A map of exactly three section ids → localStorage keys. Its existence IS
//     the rule: persistence is for the NAMED few, not for every accordion.
//   - `'finished-tasks-section'`      src/lupin_app/static/html/notifications.html:1541
//     The one entry the multiplexer has a counterpart for.
//   - `toggleSection`                 src/lupin_app/static/html/notifications.html:1544
//     Writes on toggle, and ONLY for a section in the map ("no-op for others").
//   - `applyPersistedAccordions`      src/lupin_app/static/html/notifications.html:1581
//     Restores BEFORE first paint; a missing key falls through to the section's
//     HTML default rather than forcing a state.
//
// 🔴 WHAT IS MIRRORED IS THE BEHAVIOUR, NOT THE BYTE. Legacy stores isOPEN;
// `ViewStateStore` stores isCOLLAPSED. Both clients keep their own settled
// polarity — the legacy file carries a warning at its point of definition
// saying exactly that, about exactly this hazard — so these tests assert what a
// user observes (the state survives, a missing flag means expanded), never that
// the two clients hold the same value.
//
// ⚠️ THE OPT-OUT IS TESTED AS HARD AS THE OPT-IN. A `persist` argument that was
// quietly ignored, and one that was quietly applied to all eight consumers,
// both leave the opt-in tests green. The `no store is touched` and `seven other
// panes` cases below are the ones that can tell those states apart.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/section_collapse_persist_parity.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderSectionHeader,
  wireSectionCollapse,
  type AccordionCollapseStore,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionHeader";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFinishedTasksRenderer,
  FINISHED_TASKS_ACCORDION_ID,
  type FinishedTasksStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/FinishedTasksRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function clickBubbling( el: Element ): void {
  el.dispatchEvent( new Event( "click", { bubbles: true } ) );
}

/**
 * An accordion store that HOLDS state and RECORDS every call.
 *
 * 🔴 IT HOLDS, IT DOES NOT ANSWER A CONSTANT. A fake returning a fixed `false`
 * would satisfy the restore assertions whether or not the code ever read it —
 * the restore test seeds `true` and the default test seeds nothing, and those
 * two produce different observations only because this thing remembers.
 */
function fakeAccordionStore( seed: Record<string, boolean> = {} ) {
  const flags  = new Map( Object.entries( seed ) );
  const reads  : string[] = [];
  const writes : Array<{ key: string; collapsed: boolean }> = [];
  const store: AccordionCollapseStore = {
    isAccordionCollapsed( id ) { reads.push( id ); return flags.get( id ) === true; },
    setAccordionCollapsed( id, collapsed ) { flags.set( id, collapsed ); writes.push( { key: id, collapsed } ); },
  };
  return { store, flags, reads, writes };
}

/** A bare section + header, wired with or without persistence. */
function wire( persist?: { key: string; store: AccordionCollapseStore } ) {
  const section = document.createElement( "section" );
  const handle  = renderSectionHeader( { icon: "✅", title: "Finished Tasks" } );
  section.appendChild( handle.header );
  const off = wireSectionCollapse( section, handle, persist );
  const bar = handle.header.querySelector( "h3" ) as HTMLElement;
  return { section, handle, off, bar };
}

const collapsed = ( section: HTMLElement ): string | null => section.getAttribute( "data-collapsed" );

// ---------------------------------------------------------------------------
// wireSectionCollapse — the opt-OUT half (every consumer but one)
// ---------------------------------------------------------------------------

test( "no persist argument: collapse still works, and NO store is touched — session-only, as seven of eight consumers stay", () => {
  const { store, reads, writes } = fakeAccordionStore( { "finished-tasks-section": true } );
  const { section, bar, off } = wire();   // deliberately no persist

  // The seeded `true` would collapse this section if the wiring read the store.
  assert.equal( collapsed( section ), null, "an unpersisted section must not be restored from anywhere" );

  clickBubbling( bar );
  assert.equal( collapsed( section ), "true", "session-only collapse must still toggle" );
  clickBubbling( bar );
  assert.equal( collapsed( section ), "false" );

  assert.deepEqual( reads,  [], "an unpersisted section must not READ the store" );
  assert.deepEqual( writes, [], "an unpersisted section must not WRITE the store" );
  // The store is referenced so this fake cannot be optimised into a no-op fixture.
  assert.equal( store.isAccordionCollapsed( "finished-tasks-section" ), true );
  off();
} );

// ---------------------------------------------------------------------------
// wireSectionCollapse — the opt-IN half
// ---------------------------------------------------------------------------

test( "persist + a stored collapsed flag: the section is restored BEFORE the caller paints (legacy applyPersistedAccordions)", () => {
  const { store, reads } = fakeAccordionStore( { "my-section": true } );
  const { section, handle } = wire( { key: "my-section", store } );

  assert.equal( collapsed( section ), "true", "a stored collapse must be applied at wire time, not on first click" );
  assert.equal( handle.toggleEl.textContent, "▶", "the chevron must agree with the restored state" );
  assert.deepEqual( reads, [ "my-section" ], "exactly one read, under the caller's key" );
} );

test( "persist + a stored EXPANDED flag: the section is restored expanded, not left unset", () => {
  const { store } = fakeAccordionStore( { "my-section": false } );
  const { section, handle } = wire( { key: "my-section", store } );

  assert.equal( collapsed( section ), "false" );
  assert.equal( handle.toggleEl.textContent, "▼" );
} );

test( "persist + NO stored flag: the section stays expanded — legacy's 'missing key = the HTML default'", () => {
  const { store, reads } = fakeAccordionStore();
  const { section, handle } = wire( { key: "never-stored", store } );

  assert.equal( collapsed( section ), "false", "a missing flag means expanded, the store's documented default" );
  assert.equal( handle.toggleEl.textContent, "▼" );
  assert.deepEqual( reads, [ "never-stored" ] );
} );

test( "persist: each toggle writes the NEW state under the caller's key (legacy toggleSection)", () => {
  const { store, writes, flags } = fakeAccordionStore();
  const { section, bar, off } = wire( { key: "my-section", store } );

  clickBubbling( bar );
  assert.equal( collapsed( section ), "true" );
  assert.deepEqual( writes.at( -1 ), { key: "my-section", collapsed: true }, "collapsing must persist TRUE" );

  clickBubbling( bar );
  assert.equal( collapsed( section ), "false" );
  assert.deepEqual( writes.at( -1 ), { key: "my-section", collapsed: false }, "expanding must persist FALSE" );

  assert.equal( writes.length, 2, "one write per toggle — no write on the guard-rejected clicks below" );
  assert.equal( flags.get( "my-section" ), false, "the store holds the last state, so a re-wire would restore it" );

  off();
  clickBubbling( bar );
  assert.equal( writes.length, 2, "after unsubscribe no further writes" );
} );

test( "persist: a click on a real control writes nothing — the collapse guard runs BEFORE the store write", () => {
  const { store, writes } = fakeAccordionStore();
  const control = document.createElement( "button" );
  const section = document.createElement( "section" );
  const handle  = renderSectionHeader( { icon: "✅", title: "Finished Tasks", actions: [ control ] } );
  section.appendChild( handle.header );
  wireSectionCollapse( section, handle, { key: "my-section", store } );

  clickBubbling( control );
  assert.equal( collapsed( section ), "false", "a control click must not collapse" );
  assert.deepEqual( writes, [], "and must not persist a state that did not change" );
} );

test( "persist: the chevron persists too — it is the one control that DOES collapse", () => {
  const { store, writes } = fakeAccordionStore();
  const { section, handle } = wire( { key: "my-section", store } );

  clickBubbling( handle.toggleEl );
  assert.equal( collapsed( section ), "true" );
  assert.deepEqual( writes, [ { key: "my-section", collapsed: true } ] );
} );

// ---------------------------------------------------------------------------
// FinishedTasksRenderer — the ONE call site that opts in
// ---------------------------------------------------------------------------

function fakeFinishedStore(): FinishedTasksStoreLike {
  return {
    eventsByStatus   : () => ( {} ),
    measuredStatuses : () => [],
    error            : () => null,
    windowDays       : () => 1,
    setWindowDays    : () => {},
    refresh          : async () => {},
  };
}

function mountFinished( viewState?: AccordionCollapseStore ) {
  const root = document.createElement( "div" );
  const r = createFinishedTasksRenderer( {
    eventBus  : createEventBusForTesting(),
    store     : fakeFinishedStore(),
    nowDateFn : () => new Date( "2026-09-23T20:00:00Z" ),
    storage   : null,
    viewState,
  } );
  r.mount( root );
  return { root, renderer: r };
}

test( "Finished Tasks keys on the SAME section id legacy's map keys on", () => {
  // Not a restatement of the constant: this is the string that appears in
  // `LUPIN_ACCORDION_PERSIST_KEYS`, pinned to a literal so renaming the export
  // cannot silently move the multiplexer off legacy's id.
  assert.equal( FINISHED_TASKS_ACCORDION_ID, "finished-tasks-section" );
} );

test( "Finished Tasks with a viewState: a stored collapse is restored on mount, and a header click persists", () => {
  const { store, reads, writes } = fakeAccordionStore( { "finished-tasks-section": true } );
  const { root } = mountFinished( store );

  assert.equal( root.getAttribute( "data-collapsed" ), "true", "the pane must mount collapsed when that is the stored state" );
  assert.deepEqual( reads, [ "finished-tasks-section" ] );

  clickBubbling( root.querySelector( ".section-header h3" ) as HTMLElement );
  assert.equal( root.getAttribute( "data-collapsed" ), "false" );
  assert.deepEqual( writes, [ { key: "finished-tasks-section", collapsed: false } ] );
} );

test( "Finished Tasks with NO viewState: collapse still works and nothing is persisted (the default construction)", () => {
  const { root } = mountFinished();   // the option omitted entirely

  assert.equal( root.getAttribute( "data-collapsed" ), null, "no viewState → no restore, so the attribute is unset until a click" );
  clickBubbling( root.querySelector( ".section-header h3" ) as HTMLElement );
  assert.equal( root.getAttribute( "data-collapsed" ), "true", "session-only collapse must survive the option being absent" );
} );

// ---------------------------------------------------------------------------
// The scope guard — persistence did NOT leak to the other seven consumers
// ---------------------------------------------------------------------------

test( "the seven other accordion panes still call wireSectionCollapse with TWO arguments", async () => {
  // A3 #6 says "Do not extend persistence to the other seven consumers." That is
  // a claim about eight call sites, and no behavioural test of one pane can see
  // it — so this reads the call sites and states its own denominator. A pane
  // added later with a third argument reddens this and has to be ruled on.
  const { readFileSync } = await import( "node:fs" );
  const { fileURLToPath } = await import( "node:url" );
  const { dirname, join } = await import( "node:path" );
  const here    = dirname( fileURLToPath( import.meta.url ) );
  const renderDir = join( here, "../../../../lupin_app/static/js/multiplexer/render" );

  const PANES = [
    "FinishedTasksRenderer.ts",
    "TtsChromeRenderer.ts",
    "ActionRequiredRenderer.ts",
    "TaskListRenderer.ts",
    "FleetStatusRenderer.ts",
    "EpicBoardRenderer.ts",
    "HoldingAreaRenderer.ts",
    "JobsPaneRenderer.ts",
  ];
  assert.equal( PANES.length, 8, "the denominator: eight consumers, one of which opts in" );

  const persisting: string[] = [];
  for ( const file of PANES ) {
    const src = readFileSync( join( renderDir, file ), "utf8" );
    const idx = src.indexOf( "wireSectionCollapse(" );
    assert.notEqual( idx, -1, `${ file }: no wireSectionCollapse call — this list is stale` );
    // The call's own text, up to the statement's terminating `);`.
    const call = src.slice( idx, src.indexOf( ");", idx ) + 2 );
    if ( call.includes( "key" ) || call.includes( "store" ) ) persisting.push( file );
  }
  assert.deepEqual(
    persisting,
    [ "FinishedTasksRenderer.ts" ],
    "exactly ONE pane may pass a persist argument; widening it is a ruling, not a refactor",
  );
} );
