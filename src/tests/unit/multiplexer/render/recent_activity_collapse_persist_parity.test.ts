// Parity — Recent Activity remembers whether it was left open.
//
// María 🌸 found it (2026-09-23): legacy persists this panel's open/closed state
// and the multiplexer's `onHeaderToggle` only flipped a class, so a pane the
// operator closed came back open on every reload.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it. All in src/lupin_app/static/html/notifications.html:
//   - `LUPIN_ACCORDION_PERSIST_KEYS`  :1527  the map — persistence is for the named few
//   - `'commons-recent-activity-body'`:1529  this pane's entry
//   - `toggleSection`                 :1544  writes on toggle, no-op for untracked ids
//   - `applyPersistedAccordions`      :1581  restores BEFORE first paint; missing key
//                                            falls through to the markup's own default
//
// 🔴 THE SECTION ID IS WHAT TRAVELS, NOT THE STORAGE KEY. Legacy writes its own
// localStorage key `notifications_recent_activity_open`; this client keeps every
// accordion flag in ONE `ViewStateStore` envelope, so there is nowhere for a
// second bespoke key to live. The id is the part both clients can share, and
// these tests pin it to a literal so a rename cannot quietly break the pairing.
//
// ⚠️ AND THE POLARITY IS INVERTED ON PURPOSE — legacy stores isOPEN, this stores
// isCOLLAPSED. Nothing below asserts the two clients hold the same value; they
// assert what a user observes.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/recent_activity_collapse_persist_parity.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createCommonsStore } from "../../../../lupin_app/static/js/multiplexer/stores/CommonsStore";
import {
  createCommonsActivityRenderer,
  RECENT_ACTIVITY_ACCORDION_ID,
  type CommonsActivityApiClient,
} from "../../../../lupin_app/static/js/multiplexer/render/CommonsActivityRenderer";
import type { AccordionCollapseStore } from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionHeader";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => {
  const w = globalThis as unknown as { marked?: unknown; DOMPurify?: unknown };
  w.marked    = { parse: ( s: string ): string => `<p>${ s }</p>` };
  w.DOMPurify = { sanitize: ( s: string ): string => s };
  document.body.replaceChildren();
} );

/**
 * An accordion store that HOLDS state and RECORDS every call.
 *
 * 🔴 A CONSTANT WOULD MAKE EVERY RESTORE ASSERTION UNFALSIFIABLE. The
 * seeded-collapsed and seeded-expanded cases differ only in what this thing
 * remembers, so a fake answering a fixed value would pass one of them for the
 * wrong reason.
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

function stubApi(): CommonsActivityApiClient {
  return { get: async <T>(): Promise<T> => ( { entries: [], pool: [], active_sessions: [] } as unknown as T ) };
}

/** The pane's scaffold, with the body OPEN in the markup — the HTML default. */
function buildScaffold(): HTMLElement {
  const root = document.createElement( "div" );
  root.innerHTML = `
    <div id="commons-activity-header">
      <div class="commons-activity-controls">
        <select id="commons-activity-window"><option value="today">Today</option></select>
        <select id="commons-activity-filter-direction"><option value="">Any</option></select>
        <select id="commons-activity-filter-kind"><option value="all">All</option></select>
        <select id="commons-activity-filter-persona"></select>
        <button id="commons-activity-refresh" type="button">⟳</button>
      </div>
    </div>
    <div id="commons-activity-body">
      <div id="commons-activity-entries"></div>
      <div id="commons-activity-empty" hidden></div>
    </div>
  `;
  document.body.appendChild( root );
  return root;
}

function mountPane( viewState?: AccordionCollapseStore ) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  const store   = createCommonsStore( { bus, storage, nowFn: () => Date.parse( "2026-09-23T18:00:00Z" ) } );
  const root    = buildScaffold();
  const r = createCommonsActivityRenderer( {
    eventBus : bus,
    stores   : { commons: store },
    api      : stubApi(),
    rafFn    : ( cb ) => cb(),
    viewState,
  } );
  r.mount( root );
  const body   = root.querySelector( "#commons-activity-body" ) as HTMLElement;
  const header = root.querySelector( "#commons-activity-header" ) as HTMLElement;
  const isCollapsed = (): boolean => body.classList.contains( "collapsed" );
  const clickHeader = (): void => {
    header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  };
  return { root, body, header, isCollapsed, clickHeader, renderer: r };
}

// ---------------------------------------------------------------------------
// The id
// ---------------------------------------------------------------------------

test( "the pane keys on the SAME section id legacy's map keys on", () => {
  assert.equal( RECENT_ACTIVITY_ACCORDION_ID, "commons-recent-activity-body" );
} );

// ---------------------------------------------------------------------------
// Restore — legacy applyPersistedAccordions
// ---------------------------------------------------------------------------

test( "a stored COLLAPSED flag closes the panel at mount, before the first render", () => {
  const { store, reads } = fakeAccordionStore( { "commons-recent-activity-body": true } );
  const { isCollapsed } = mountPane( store );

  assert.equal( isCollapsed(), true, "the operator left it closed; it must come back closed" );
  assert.deepEqual( reads, [ "commons-recent-activity-body" ], "exactly one read, under that id" );
} );

test( "a stored EXPANDED flag leaves the panel open", () => {
  const { store } = fakeAccordionStore( { "commons-recent-activity-body": false } );
  const { isCollapsed } = mountPane( store );
  assert.equal( isCollapsed(), false );
} );

test( "NO stored flag leaves the markup's own default alone — legacy's 'missing key = the HTML default'", () => {
  const { store, reads, writes } = fakeAccordionStore();
  const { isCollapsed } = mountPane( store );

  assert.equal( isCollapsed(), false, "the scaffold ships open, and nothing overrides it" );
  assert.deepEqual( reads, [ "commons-recent-activity-body" ] );
  assert.deepEqual( writes, [], "a restore must never write — that would invent a decision" );
} );

// ---------------------------------------------------------------------------
// Persist — legacy toggleSection
// ---------------------------------------------------------------------------

test( "each header click writes the RESULTING state under the pane's id", () => {
  const { store, writes, flags } = fakeAccordionStore();
  const { clickHeader, isCollapsed } = mountPane( store );

  clickHeader();
  assert.equal( isCollapsed(), true );
  assert.deepEqual( writes.at( -1 ), { key: "commons-recent-activity-body", collapsed: true } );

  clickHeader();
  assert.equal( isCollapsed(), false );
  assert.deepEqual( writes.at( -1 ), { key: "commons-recent-activity-body", collapsed: false } );

  assert.equal( writes.length, 2, "one write per toggle" );
  assert.equal( flags.get( "commons-recent-activity-body" ), false, "the store holds the last state" );
} );

test( "🔴 what is WRITTEN is what the DOM now holds — a full round trip, not two readings of one intent", () => {
  // The write takes `classList.toggle`'s return value rather than re-reading the
  // class, so this drives a close through a real click and then restores a
  // SECOND pane from the same store. If the two ever disagreed in sense, this
  // is where it would show: the new pane would come back open.
  const { store } = fakeAccordionStore();
  const first = mountPane( store );
  first.clickHeader();
  assert.equal( first.isCollapsed(), true );

  const second = mountPane( store );
  assert.equal( second.isCollapsed(), true, "a reload must land on the state the operator left" );
} );

test( "a click on a CONTROL inside the header does not toggle, and writes nothing", () => {
  const { store, writes } = fakeAccordionStore();
  const { root, isCollapsed } = mountPane( store );

  ( root.querySelector( "#commons-activity-refresh" ) as HTMLElement )
    .dispatchEvent( new Event( "click", { bubbles: true } ) );

  assert.equal( isCollapsed(), false, "the refresh button owns its own click" );
  assert.deepEqual( writes, [], "and must not persist a state that never changed" );
} );

// ---------------------------------------------------------------------------
// The opt-out
// ---------------------------------------------------------------------------

test( "NO viewState: collapse still works, and nothing is read or written", () => {
  const { store, reads, writes } = fakeAccordionStore( { "commons-recent-activity-body": true } );
  const { clickHeader, isCollapsed } = mountPane();   // deliberately not passed

  // The seeded `true` would close this pane if the renderer reached for a store.
  assert.equal( isCollapsed(), false, "an opted-out pane must not be restored from anywhere" );
  clickHeader();
  assert.equal( isCollapsed(), true, "session-only collapse must still work" );
  clickHeader();
  assert.equal( isCollapsed(), false );

  assert.deepEqual( reads,  [], "no read" );
  assert.deepEqual( writes, [], "no write" );
  // Referenced so this fake cannot collapse into an unused fixture.
  assert.equal( store.isAccordionCollapsed( "commons-recent-activity-body" ), true );
} );
