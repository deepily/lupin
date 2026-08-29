// Multiplexer section-toolbar parity (2026-06-23, Rachel 🕊️) — section-toolbar
// template (sectionToolbar.ts) + SectionToolbarRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  createSectionToolbarRenderer,
  type ViewStateStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render";
import {
  renderSectionToolbar,
  SECTION_TOGGLES,
  DEFAULT_HIDDEN_SECTION_IDS,
  COLLAPSE_ALL_ID,
  EXPAND_ALL_ID,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

// --- Fake ViewStateStore ----------------------------------------------------
// Lane 0c: the store now models EXPLICIT preferences. `prefs` seeds persisted
// choices (a present key = an explicit visible/hidden preference); an absent key
// = no preference (the section falls back to its cold-start default).
interface FakeViewState extends ViewStateStoreLike {
  visible : Map<string, boolean>;
  bulkCalls : boolean[];
}
function makeFakeViewState( prefs: Record<string, boolean> = {} ): FakeViewState {
  const visible = new Map<string, boolean>( Object.entries( prefs ) );
  const fake: FakeViewState = {
    visible,
    bulkCalls: [],
    isSectionVisible: ( id ) => visible.get( id ) !== false,
    setSectionVisible: ( id, v ) => { visible.set( id, v ); },
    getHiddenSectionIds: () => [ ...visible.entries() ].filter( ( [ , v ] ) => v === false ).map( ( [ k ] ) => k ),
    hasSectionPreference: ( id ) => visible.has( id ),
    requestBulkAccordionCollapse: ( collapsed ) => { fake.bulkCalls.push( collapsed ); },
  };
  return fake;
}

function makeMount(): HTMLElement {
  const div = document.createElement( "div" );
  div.id = "section-toolbar-mount";
  document.body.appendChild( div );
  return div;
}
function makeSection( id: string ): HTMLElement {
  const sec = document.createElement( "section" );
  sec.id = id;
  document.body.appendChild( sec );
  return sec;
}
function clearBody(): void { document.body.replaceChildren(); }
function clickBubbling( el: Element ): void { el.dispatchEvent( new Event( "click", { bubbles: true } ) ); }

// ===========================================================================
// Template — renderSectionToolbar
// ===========================================================================

test( "template: builds #section-toolbar with collapse/expand + one toolbar-btn per section", () => {
  const el = renderSectionToolbar();
  assert.equal( el.id, "section-toolbar" );
  assert.equal( el.className, "section-toolbar" );
  assert.equal( el.getAttribute( "role" ), "toolbar" );
  assert.ok( el.querySelector( `#${COLLAPSE_ALL_ID}` ) !== null );
  assert.ok( el.querySelector( `#${EXPAND_ALL_ID}` ) !== null );
  const btns = el.querySelectorAll( ".toolbar-btn" );
  assert.equal( btns.length, SECTION_TOGGLES.length );
  // Lane 0c: a cold-default-VISIBLE section renders `.active`; a
  // cold-default-HIDDEN section (DEFAULT_HIDDEN_SECTION_IDS, e.g. jobs-pane)
  // renders dimmed. SECTION_TOGGLES spans both, so both ternary arms render.
  for ( const spec of SECTION_TOGGLES ) {
    const btn = el.querySelector( `.toolbar-btn[data-section="${spec.sectionId}"]` ) as HTMLElement;
    assert.notEqual( btn, null );
    assert.equal( btn.classList.contains( "active" ), !DEFAULT_HIDDEN_SECTION_IDS.has( spec.sectionId ) );
    assert.equal( btn.getAttribute( "title" ), spec.title );
  }
  // At least one of each kind exists (guards the assertion above from vacuity).
  assert.ok( SECTION_TOGGLES.some( s => DEFAULT_HIDDEN_SECTION_IDS.has( s.sectionId ) ) );
  assert.ok( SECTION_TOGGLES.some( s => !DEFAULT_HIDDEN_SECTION_IDS.has( s.sectionId ) ) );
} );

test( "template: a custom toggles list renders exactly those buttons", () => {
  const el = renderSectionToolbar( [ { sectionId: "x-pane", icon: "🧪", title: "X", testid: "x" } ] );
  assert.equal( el.querySelectorAll( ".toolbar-btn" ).length, 1 );
  assert.ok( el.querySelector( `.toolbar-btn[data-section="x-pane"]` ) !== null );
} );

// ===========================================================================
// Renderer — mount / unmount lifecycle
// ===========================================================================

test( "mount: builds toolbar into root; double mount throws; unmount idempotent", () => {
  clearBody();
  const mount = makeMount();
  const r = createSectionToolbarRenderer( { stores: { viewState: makeFakeViewState() }, doc: document } );
  r.mount( mount );
  assert.ok( mount.querySelector( "#section-toolbar" ) !== null );
  assert.throws( () => r.mount( mount ), /already mounted/ );
  r.unmount();
  assert.ok( mount.querySelector( "#section-toolbar" ) === null );
  r.unmount();   // idempotent — no throw, toolbar already null
} );

// ===========================================================================
// Renderer — per-section visibility toggle
// ===========================================================================

test( "click a cold-VISIBLE section button: hide → show toggles .section-hidden + hidden attr + .active + persists", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "notifications-pane" );   // cold-default visible
  const vs      = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( btn.classList.contains( "active" ) );       // reconcile left it visible
  assert.ok( !section.hidden );

  clickBubbling( btn );   // hide (no-preference → cold visible → flip to hidden)
  assert.ok( section.classList.contains( "section-hidden" ) );
  assert.ok( section.hidden );
  assert.ok( !btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "notifications-pane" ), false );

  clickBubbling( btn );   // show (now has a preference=false → flip to visible)
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.ok( !section.hidden );
  assert.ok( btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "notifications-pane" ), true );
  r.unmount();
} );

test( "click a cold-HIDDEN section button (jobs-pane): FIRST click REVEALS it (persisted choice overrides cold hidden)", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "jobs-pane" );
  section.hidden = true;                                  // cold-start HTML `hidden` default
  const vs      = makeFakeViewState();                    // no preference yet
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  // Reconcile: cold-hidden → dimmed + hidden retained.
  assert.ok( !btn.classList.contains( "active" ) );
  assert.ok( section.hidden );
  assert.ok( section.classList.contains( "section-hidden" ) );

  clickBubbling( btn );   // FIRST click: no-preference → cold hidden → flip to VISIBLE
  assert.ok( btn.classList.contains( "active" ) );
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.ok( !section.hidden );                          // HTML `hidden` cold default CLEARED (F-Clay-A3)
  assert.equal( vs.visible.get( "jobs-pane" ), true );
  r.unmount();
} );

test( "click a section button whose section element is ABSENT: still persists + flips button", () => {
  clearBody();
  const mount = makeMount();           // NOTE: no #tts-pane section created
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  const btn = mount.querySelector( `.toolbar-btn[data-section="tts-pane"]` ) as HTMLElement;
  clickBubbling( btn );
  assert.ok( !btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "tts-pane" ), false );   // persisted despite missing section
  r.unmount();
} );

// ===========================================================================
// Renderer — collapse-all / expand-all
// ===========================================================================

test( "click collapse-all → requestBulkAccordionCollapse(true); expand-all → (false)", () => {
  clearBody();
  const mount = makeMount();
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  clickBubbling( mount.querySelector( `#${COLLAPSE_ALL_ID}` ) as HTMLElement );
  clickBubbling( mount.querySelector( `#${EXPAND_ALL_ID}` ) as HTMLElement );
  assert.deepEqual( vs.bulkCalls, [ true, false ] );
  r.unmount();
} );

// ===========================================================================
// Renderer — click dispatch guards
// ===========================================================================

test( "click on the toolbar background (not a button) is a no-op", () => {
  clearBody();
  const mount = makeMount();
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  clickBubbling( mount.querySelector( "#section-toolbar" ) as HTMLElement );
  assert.deepEqual( vs.bulkCalls, [] );
  assert.equal( vs.visible.size, 0 );
  r.unmount();
} );

test( "click with null target is a no-op (defensive)", () => {
  clearBody();
  const mount = makeMount();
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  const evt = new Event( "click", { bubbles: true } );
  Object.defineProperty( evt, "target", { value: null } );
  ( mount.querySelector( "#section-toolbar" ) as HTMLElement ).dispatchEvent( evt );
  assert.deepEqual( vs.bulkCalls, [] );
  r.unmount();
} );

// ===========================================================================
// Renderer — reconcile on mount (cold defaults + persisted overrides)
// ===========================================================================

test( "mount reconcile (NO preferences): cold defaults — jobs-pane hidden+dimmed, notifications visible+active", () => {
  clearBody();
  const mount    = makeMount();
  const jobs     = makeSection( "jobs-pane" );          // cold-default hidden
  jobs.hidden    = true;
  const notifs   = makeSection( "notifications-pane" ); // cold-default visible
  // tts-pane / fleet-status-pane / task-list-pane / commons-activity-pane are
  // toggle specs WITHOUT a DOM element here → exercises the section-null skip
  // inside applyVisibilityToDom during reconcile.
  const vs = makeFakeViewState();                        // no persisted prefs
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const jobsBtn = mount.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  assert.ok( !jobsBtn.classList.contains( "active" ) );          // dimmed
  assert.ok( jobs.hidden );                                       // stays hidden
  assert.ok( jobs.classList.contains( "section-hidden" ) );

  const notifsBtn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( notifsBtn.classList.contains( "active" ) );         // visible
  assert.ok( !notifs.hidden );
  assert.ok( !notifs.classList.contains( "section-hidden" ) );
  r.unmount();
} );

test( "mount reconcile (WITH preferences): persisted choice OVERRIDES cold default (F-Clay-A3)", () => {
  clearBody();
  const mount  = makeMount();
  const jobs   = makeSection( "jobs-pane" );             // cold hidden…
  jobs.hidden  = true;
  const notifs = makeSection( "notifications-pane" );    // cold visible…
  // …but the user persisted the OPPOSITE for each.
  const vs = makeFakeViewState( { "jobs-pane": true, "notifications-pane": false } );
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const jobsBtn = mount.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  assert.ok( jobsBtn.classList.contains( "active" ) );           // persisted-visible wins
  assert.ok( !jobs.hidden );                                      // cold `hidden` CLEARED
  assert.ok( !jobs.classList.contains( "section-hidden" ) );

  const notifsBtn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( !notifsBtn.classList.contains( "active" ) );        // persisted-hidden wins
  assert.ok( notifs.hidden );
  assert.ok( notifs.classList.contains( "section-hidden" ) );
  r.unmount();
} );
