// Multiplexer section-toolbar parity (2026-06-23, Rachel 🕊️) — section-toolbar
// template (sectionToolbar.ts) + SectionToolbarRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before, mock } from "node:test";
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
  type SectionToggleSpec,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";
import { SCROLL_REVEAL_SETTLE_MS } from "../../../../lupin_app/static/js/multiplexer/render/scrollReveal";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

// --- Fake ViewStateStore ----------------------------------------------------
// Lane 0c: the store now models EXPLICIT preferences. `prefs` seeds persisted
// choices (a present key = an explicit visible/hidden preference); an absent key
// = no preference (the section falls back to its cold-start default).
interface FakeViewState extends ViewStateStoreLike {
  visible : Map<string, boolean>;
}
function makeFakeViewState( prefs: Record<string, boolean> = {} ): FakeViewState {
  const visible = new Map<string, boolean>( Object.entries( prefs ) );
  // `bulkCalls` and the requestBulkAccordionCollapse stub were dropped on
  // 2026-09-15 with the collapse-all / expand-all buttons: the renderer no longer
  // takes that method, so a fake still offering it would fail the excess-property
  // check and, worse, assert against a surface the renderer does not have.
  const fake: FakeViewState = {
    visible,
    isSectionVisible: ( id ) => visible.get( id ) !== false,
    setSectionVisible: ( id, v ) => { visible.set( id, v ); },
    getHiddenSectionIds: () => [ ...visible.entries() ].filter( ( [ , v ] ) => v === false ).map( ( [ k ] ) => k ),
    hasSectionPreference: ( id ) => visible.has( id ),
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

// No production toggle is cold-hidden until B-3 adds Filter Settings, so the
// cold-hidden paths are driven through an injected list holding that spec.
const FILTER_SETTINGS_SPEC: SectionToggleSpec = { sectionId: "filter-settings-section", icon: "⚙️", title: "Filter Settings (Admin)", testid: "x-filter" };
const TOGGLES_WITH_COLD_HIDDEN: ReadonlyArray<SectionToggleSpec> = [ ...SECTION_TOGGLES, FILTER_SETTINGS_SPEC ];

// happy-dom does no layout, so every rect is zeros — which reads as "in view".
// Pin the section below the fold and record the scrolls the helper makes.
function placeOffscreen( el: HTMLElement ): Array<ScrollIntoViewOptions | boolean | undefined> {
  const calls: Array<ScrollIntoViewOptions | boolean | undefined> = [];
  el.getBoundingClientRect = () => ( { top: window.innerHeight + 100, bottom: window.innerHeight + 400, left: 0, right: 0, width: 0, height: 300, x: 0, y: 0, toJSON: () => ( {} ) } ) as DOMRect;
  el.scrollIntoView        = ( arg?: ScrollIntoViewOptions | boolean ) => { calls.push( arg ); };
  return calls;
}
function clickBubbling( el: Element ): void { el.dispatchEvent( new Event( "click", { bubbles: true } ) ); }

// ===========================================================================
// Template — renderSectionToolbar
// ===========================================================================

test( "template: builds #section-toolbar with one toolbar-btn per section and no accordion pair", () => {
  const el = renderSectionToolbar();
  assert.equal( el.id, "section-toolbar" );
  assert.equal( el.className, "section-toolbar" );
  assert.equal( el.getAttribute( "role" ), "toolbar" );
  // The collapse-all / expand-all pair came off this toolbar on 2026-09-15.
  assert.equal( el.querySelectorAll( ".task-accordion-btn" ).length, 0 );
  const btns = el.querySelectorAll( ".toolbar-btn" );
  assert.equal( btns.length, SECTION_TOGGLES.length );
  // A cold-default-VISIBLE section renders `.active`; a cold-default-HIDDEN one
  // (DEFAULT_HIDDEN_SECTION_IDS) renders dimmed. Since A-2 #1 no production toggle
  // is cold-hidden, so the dimmed arm is driven by the custom-list test below.
  for ( const spec of SECTION_TOGGLES ) {
    const btn = el.querySelector( `.toolbar-btn[data-section="${spec.sectionId}"]` ) as HTMLElement;
    assert.notEqual( btn, null );
    assert.equal( btn.classList.contains( "active" ), !DEFAULT_HIDDEN_SECTION_IDS.has( spec.sectionId ) );
    assert.equal( btn.getAttribute( "title" ), spec.title );
  }
  assert.ok( SECTION_TOGGLES.some( s => !DEFAULT_HIDDEN_SECTION_IDS.has( s.sectionId ) ) );
} );

test( "parity A-2 #1: Jobs starts visible, Filter Settings starts hidden, Jobs' glyph is 📋 (plan §3 R1, R3, R6)", () => {
  assert.deepEqual( [ ...DEFAULT_HIDDEN_SECTION_IDS ], [ "filter-settings-section" ] );
  const el      = renderSectionToolbar();
  const jobsBtn = el.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  assert.ok( jobsBtn.classList.contains( "active" ), "Jobs must render lit: legacy's Job Queues button ships active" );
  assert.equal( jobsBtn.textContent, "📋" );
  const dimmed = renderSectionToolbar( [ FILTER_SETTINGS_SPEC ] ).querySelector( ".toolbar-btn" ) as HTMLElement;
  assert.ok( !dimmed.classList.contains( "active" ), "Filter Settings must render dimmed: legacy's section starts display:none" );
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

test( "click a cold-HIDDEN section button (filter-settings-section): FIRST click REVEALS it (persisted choice overrides cold hidden)", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "filter-settings-section" );
  section.hidden = true;                                  // cold-start HTML `hidden` default
  const vs      = makeFakeViewState();                    // no preference yet
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: TOGGLES_WITH_COLD_HIDDEN } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="filter-settings-section"]` ) as HTMLElement;
  // Reconcile: cold-hidden → dimmed + hidden retained.
  assert.ok( !btn.classList.contains( "active" ) );
  assert.ok( section.hidden );
  assert.ok( section.classList.contains( "section-hidden" ) );

  clickBubbling( btn );   // FIRST click: no-preference → cold hidden → flip to VISIBLE
  assert.ok( btn.classList.contains( "active" ) );
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.ok( !section.hidden );                          // HTML `hidden` cold default CLEARED (F-Clay-A3)
  assert.equal( vs.visible.get( "filter-settings-section" ), true );
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
// Renderer — the accordion pair is OFF this toolbar
// ===========================================================================

test( "the toolbar renders NO accordion-action buttons (Rick's 2026-09-15 ruling)", () => {
  // Replaces "click collapse-all → requestBulkAccordionCollapse(true); expand-all
  // → (false)". The pair came off both toolbars, so what can regress now is
  // somebody putting it back.
  clearBody();
  const mount = makeMount();
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  assert.ok( mount.querySelectorAll( ".toolbar-btn" ).length > 0, "the toolbar did not render — this guard proves nothing" );
  assert.equal( mount.querySelectorAll( ".task-accordion-btn" ).length, 0 );
  assert.ok( mount.querySelector( "#section-toolbar-collapse-all" ) === null, "the collapse-all button is back on the toolbar, against Rick's ruling" );
  assert.ok( mount.querySelector( "#section-toolbar-expand-all" ) === null, "the expand-all button is back on the toolbar, against Rick's ruling" );
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
  assert.equal( vs.visible.size, 0 );
  r.unmount();
} );

// ===========================================================================
// Renderer — reconcile on mount (cold defaults + persisted overrides)
// ===========================================================================

test( "mount reconcile (NO preferences): cold defaults — filter settings hidden+dimmed, jobs and notifications visible+active", () => {
  clearBody();
  const mount    = makeMount();
  const filters  = makeSection( "filter-settings-section" );   // cold-default hidden
  filters.hidden = true;
  const jobs     = makeSection( "jobs-pane" );          // cold-default VISIBLE since A-2 #1
  const notifs   = makeSection( "notifications-pane" ); // cold-default visible
  // tts-pane / fleet-status-pane / task-list-pane / commons-activity-pane are
  // toggle specs WITHOUT a DOM element here → exercises the section-null skip
  // inside applyVisibilityToDom during reconcile.
  const vs = makeFakeViewState();                        // no persisted prefs
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: TOGGLES_WITH_COLD_HIDDEN } );
  r.mount( mount );

  const filtersBtn = mount.querySelector( `.toolbar-btn[data-section="filter-settings-section"]` ) as HTMLElement;
  assert.ok( !filtersBtn.classList.contains( "active" ) );       // dimmed
  assert.ok( filters.hidden );                                    // stays hidden
  assert.ok( filters.classList.contains( "section-hidden" ) );

  const jobsBtn = mount.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  assert.ok( jobsBtn.classList.contains( "active" ) );           // lit
  assert.ok( !jobs.hidden );
  assert.ok( !jobs.classList.contains( "section-hidden" ) );

  const notifsBtn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( notifsBtn.classList.contains( "active" ) );         // visible
  assert.ok( !notifs.hidden );
  assert.ok( !notifs.classList.contains( "section-hidden" ) );
  r.unmount();
} );

test( "mount reconcile (WITH preferences): persisted choice OVERRIDES cold default (F-Clay-A3)", () => {
  clearBody();
  const mount  = makeMount();
  const jobs   = makeSection( "filter-settings-section" );   // cold hidden…
  jobs.hidden  = true;
  const notifs = makeSection( "notifications-pane" );    // cold visible…
  // …but the user persisted the OPPOSITE for each.
  const vs = makeFakeViewState( { "filter-settings-section": true, "notifications-pane": false } );
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: TOGGLES_WITH_COLD_HIDDEN } );
  r.mount( mount );

  const jobsBtn = mount.querySelector( `.toolbar-btn[data-section="filter-settings-section"]` ) as HTMLElement;
  assert.ok( jobsBtn.classList.contains( "active" ) );           // persisted-visible wins
  assert.ok( !jobs.hidden );                                      // cold `hidden` CLEARED
  assert.ok( !jobs.classList.contains( "section-hidden" ) );

  const notifsBtn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( !notifsBtn.classList.contains( "active" ) );        // persisted-hidden wins
  assert.ok( notifs.hidden );
  assert.ok( notifs.classList.contains( "section-hidden" ) );
  r.unmount();
} );

// ===========================================================================
// Renderer — showing a section scrolls it into view (parity A-2 #1, via A-0)
// ===========================================================================

test( "showing an off-screen section scrolls it smooth/start through the shared helper; hiding it does not", () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    clearBody();
    const mount   = makeMount();
    const section = makeSection( "tts-pane" );
    const calls   = placeOffscreen( section );
    const vs      = makeFakeViewState( { "tts-pane": false } );   // persisted hidden
    const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
    r.mount( mount );
    assert.equal( calls.length, 0, "the mount reconcile must not scroll" );

    const btn = mount.querySelector( `.toolbar-btn[data-section="tts-pane"]` ) as HTMLElement;
    clickBubbling( btn );   // show
    assert.deepEqual( calls, [ { behavior: "smooth", block: "start" } ] );

    clickBubbling( btn );   // hide
    assert.equal( calls.length, 1, "hiding a section must not scroll" );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    r.unmount();
  } finally {
    mock.timers.reset();
  }
} );

test( "showing a section whose element is absent scrolls nothing and does not throw", () => {
  clearBody();
  const mount = makeMount();           // no #fleet-status-pane element
  const vs    = makeFakeViewState( { "fleet-status-pane": false } );
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  clickBubbling( mount.querySelector( `.toolbar-btn[data-section="fleet-status-pane"]` ) as HTMLElement );
  assert.equal( vs.visible.get( "fleet-status-pane" ), true );
  r.unmount();
} );
