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
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";
import { SCROLL_REVEAL_SETTLE_MS } from "../../../../lupin_app/static/js/multiplexer/render/scrollReveal";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

// --- Fake ViewStateStore ----------------------------------------------------
// `prefs` seeds persisted choices. Only an explicit `false` hides a section —
// an absent key and an explicit `true` both mean visible, which is the real
// store's rule (ViewStateStore.isSectionVisible) and, since 2026-09-23, the
// renderer's whole visibility model.
interface FakeViewState extends ViewStateStoreLike {
  visible : Map<string, boolean>;
}
function makeFakeViewState( prefs: Record<string, boolean> = {} ): FakeViewState {
  const visible = new Map<string, boolean>( Object.entries( prefs ) );
  // `bulkCalls` and the requestBulkAccordionCollapse stub were dropped on
  // 2026-09-15 with the collapse-all / expand-all buttons; `hasSectionPreference`
  // on 2026-09-23 with the cold-hidden default. The renderer no longer takes
  // either, so a fake still offering one would fail the excess-property check
  // and, worse, assert against a surface the renderer does not have.
  const fake: FakeViewState = {
    visible,
    isSectionVisible: ( id ) => visible.get( id ) !== false,
    setSectionVisible: ( id, v ) => { visible.set( id, v ); },
    getHiddenSectionIds: () => [ ...visible.entries() ].filter( ( [ , v ] ) => v === false ).map( ( [ k ] ) => k ),
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

// ⚠️ THE VISIBILITY PATHS RUN AGAINST THE PRODUCTION TOGGLE LIST, NOT AN INJECTED SPEC.
// They once appended a fake toggle to stand in for the cold-hidden one, and every case
// passed against that stand-in while the real toolbar entry went unexercised. Passing
// SECTION_TOGGLES explicitly still drives the `toggles` option.

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
  for ( const spec of SECTION_TOGGLES ) {
    const btn = el.querySelector( `.toolbar-btn[data-section="${spec.sectionId}"]` ) as HTMLElement;
    assert.notEqual( btn, null );
    assert.equal( btn.getAttribute( "title" ), spec.title );
  }
} );

test( "🔴 EVERY button ships `.active` — all 15 of legacy's do, and none of this page's may differ", () => {
  // The count is asserted against SECTION_TOGGLES rather than a literal so this
  // cannot pass over an empty toolbar, and the failure message names the offenders
  // rather than a bare false.
  const el   = renderSectionToolbar();
  const btns = [ ...el.querySelectorAll( ".toolbar-btn" ) ];
  assert.equal( btns.length, SECTION_TOGGLES.length );
  assert.ok( btns.length > 0, "the toolbar rendered nothing — the loop below would pass over it" );
  const dimmed = btns
    .filter( ( b ) => !b.classList.contains( "active" ) )
    .map( ( b ) => b.getAttribute( "data-section" ) );
  assert.deepEqual( dimmed, [],
    `these buttons ship dimmed: ${ dimmed.join( ", " ) }. Legacy has no cold-hidden section — `
    + `all 15 of its .toolbar-btn carry "active" (notifications.html:43-74) and its markup holds `
    + `zero .section-hidden. A dimmed button here is a cold default legacy does not have.` );
} );

test( "🔴 Filter Settings ships LIT, like legacy's ⚙️ — a dimmed one hides the admin's own pane (row cec9dd43)", () => {
  // The regression this replaces: DEFAULT_HIDDEN_SECTION_IDS held `filter-settings-pane`,
  // read off the `style="display: none;"` at notifications.html:1123. That inline style is
  // the ADMIN GATE (axis 1, rewritten by initializeFilterUI from isAdmin), not a cold-start
  // default. Two lines up, at :69, legacy's own ⚙️ button ships `active` — which is where
  // axis 2 actually states its cold default, and it says VISIBLE.
  const el         = renderSectionToolbar();
  const filtersBtn = el.querySelector( `.toolbar-btn[data-section="filter-settings-pane"]` ) as HTMLElement;
  assert.notEqual( filtersBtn, null, "the production toolbar has no Filter Settings button" );
  assert.ok( filtersBtn.classList.contains( "active" ),
    "Filter Settings ships dimmed, so an admin's cold start hides the pane on axis 2 no matter what isAdmin says" );
} );

test( "parity A-2 #1: Jobs starts visible and its glyph is 📋 (plan §3 R1, R6)", () => {
  const el      = renderSectionToolbar();
  const jobsBtn = el.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  assert.ok( jobsBtn.classList.contains( "active" ), "Jobs must render lit: legacy's Job Queues button ships active" );
  assert.equal( jobsBtn.textContent, "📋" );
} );

test( "parity A-2 #2a: Action Required has a ⚠️ toggle, first in the list as it is first on the page (Phase 2 A3 B4)", () => {
  assert.deepEqual( SECTION_TOGGLES[ 0 ], {
    sectionId : "action-required-section",
    icon      : "⚠️",
    title     : "Action Required",
    testid    : "multiplexer-section-toolbar-action-required",
  } );
} );

test( "clicking the ⚠️ toggle hides and re-shows #action-required-section and persists each choice", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "action-required-section" );
  const vs      = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  const btn = mount.querySelector( `.toolbar-btn[data-section="action-required-section"]` ) as HTMLElement;
  assert.ok( btn.classList.contains( "active" ) );
  clickBubbling( btn );
  assert.ok( section.hidden );
  assert.equal( vs.visible.get( "action-required-section" ), false );
  clickBubbling( btn );
  assert.ok( !section.hidden );
  assert.equal( vs.visible.get( "action-required-section" ), true );
  r.unmount();
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

test( "click a section button: hide → show toggles .section-hidden + hidden attr + .active + persists", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "notifications-pane" );
  const vs      = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( btn.classList.contains( "active" ) );       // reconcile left it visible
  assert.ok( !section.hidden );

  clickBubbling( btn );   // hide (no preference → visible → flip to hidden)
  assert.ok( section.classList.contains( "section-hidden" ) );
  assert.ok( section.hidden );
  assert.ok( !btn.classList.contains( "active" ) );
  // A-2 #4 — the preference is stored under the FRESH key, on Rick's ruling (2026-09-19,
  // plan §6a item 9, which REVERSED "keep the first id so saved preferences survive").
  // The old key must stay UNWRITTEN: the ruling says the one-time reset is the accepted
  // price and must not be "fixed" by falling back, and a dual write would be that fallback
  // arriving quietly. Asserting only the new key would let one be added back unnoticed.
  assert.equal( vs.visible.get( "notifications-header-and-pane" ), false );
  assert.equal( vs.visible.has( "notifications-pane" ), false, "the superseded key was written too" );

  clickBubbling( btn );   // show (now has a preference=false → flip to visible)
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.ok( !section.hidden );
  assert.ok( btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "notifications-header-and-pane" ), true );
  assert.equal( vs.visible.has( "notifications-pane" ), false, "the superseded key was written too" );
  r.unmount();
} );

test( "🔴 filter-settings-pane arrives UNHIDDEN and the first click HIDES it — the admin's pane is not gated twice", () => {
  // The inverse of the case this replaces, which asserted the first click REVEALED the
  // pane. That was only true because axis 2 started it hidden for everyone, admins
  // included. A pane an admin must click to see is the defect, not the behaviour.
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "filter-settings-pane" );
  section.hidden = true;                                  // arrives hidden — the reconcile must CLEAR this
  const vs      = makeFakeViewState();                    // no preference
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="filter-settings-pane"]` ) as HTMLElement;
  assert.ok( btn.classList.contains( "active" ), "the ⚙️ button must reconcile LIT" );
  assert.ok( !section.hidden, "the reconcile left `hidden` standing, so an admin's pane stays invisible" );
  assert.ok( !section.classList.contains( "section-hidden" ) );

  clickBubbling( btn );   // first click on a visible section HIDES it
  assert.ok( !btn.classList.contains( "active" ) );
  assert.ok( section.classList.contains( "section-hidden" ) );
  assert.ok( section.hidden );
  assert.equal( vs.visible.get( "filter-settings-pane" ), false );
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
// Renderer — reconcile on mount
// ===========================================================================

test( "mount reconcile (NO preferences): every section comes up visible + lit, `hidden` cleared", () => {
  clearBody();
  const mount    = makeMount();
  const filters  = makeSection( "filter-settings-pane" );
  filters.hidden = true;                                 // arrives hidden; the reconcile clears it
  const jobs     = makeSection( "jobs-pane" );
  const notifs   = makeSection( "notifications-pane" );
  // tts-pane / fleet-status-pane / task-list-pane / commons-activity-pane are
  // toggle specs WITHOUT a DOM element here → exercises the section-null skip
  // inside applyVisibilityToDom during reconcile.
  const vs = makeFakeViewState();                        // no persisted prefs
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  for ( const [ section, id ] of [ [ filters, "filter-settings-pane" ], [ jobs, "jobs-pane" ], [ notifs, "notifications-pane" ] ] as const ) {
    const btn = mount.querySelector( `.toolbar-btn[data-section="${ id }"]` ) as HTMLElement;
    assert.ok( btn.classList.contains( "active" ), `${ id } reconciled dimmed` );
    assert.ok( !section.hidden, `${ id } kept its \`hidden\` attribute` );
    assert.ok( !section.classList.contains( "section-hidden" ), `${ id } kept .section-hidden` );
  }
  r.unmount();
} );

test( "mount reconcile (WITH preferences): a persisted HIDDEN choice dims a button the template painted lit", () => {
  // The discriminating direction. Persisted-VISIBLE and no-preference now agree, so only
  // a persisted `false` can tell you the reconcile consulted the store at all — pinning
  // the other direction would pass against a renderer that never asked.
  clearBody();
  const mount  = makeMount();
  const filters = makeSection( "filter-settings-pane" );
  const notifs  = makeSection( "notifications-pane" );
  // A-2 #4 — notifications' preference lives under its FRESH key (`notifications-header-and-pane`,
  // Rick's ruling 2026-09-19); every other entry is unchanged and still keyed on its own id.
  // Seeding the OLD key here would let this pass against a renderer that kept the
  // superseded behaviour, which is the one thing this assertion must be able to fail on.
  const vs = makeFakeViewState( { "filter-settings-pane": true, "notifications-header-and-pane": false } );
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  const notifsBtn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( !notifsBtn.classList.contains( "active" ), "the template ships every button lit, so a dim here proves the store was read" );
  assert.ok( notifs.hidden );
  assert.ok( notifs.classList.contains( "section-hidden" ) );

  const filtersBtn = mount.querySelector( `.toolbar-btn[data-section="filter-settings-pane"]` ) as HTMLElement;
  assert.ok( filtersBtn.classList.contains( "active" ) );        // persisted-visible, unchanged
  assert.ok( !filters.hidden );
  assert.ok( !filters.classList.contains( "section-hidden" ) );
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

// ===========================================================================
// Renderer — showSection, the programmatic reveal (parity A-2 #2b)
// ===========================================================================

test( "showSection on a persisted-hidden section un-hides it, saves the choice and re-lights its button, without scrolling", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "action-required-section" );
  const calls   = placeOffscreen( section );
  const vs      = makeFakeViewState( { "action-required-section": false } );
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  const btn = mount.querySelector( `.toolbar-btn[data-section="action-required-section"]` ) as HTMLElement;
  assert.ok( section.hidden && !btn.classList.contains( "active" ), "precondition: reconcile hid it" );

  r.showSection( "action-required-section" );
  assert.ok( !section.hidden );
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.ok( btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "action-required-section" ), true );
  assert.equal( calls.length, 0, "the caller owns the scroll, so it can un-collapse first" );
  r.unmount();
} );

// The "showSection on a cold-hidden section" case that stood here was retired on
// 2026-09-23 with the cold-hidden default. Its reveal path is the case above, which
// reaches it the only way left: a section the USER hid. A-2 #11's badges take it.

test( "showSection on an already-visible section writes nothing (legacy saves only when it un-hid)", () => {
  clearBody();
  const mount = makeMount();
  makeSection( "action-required-section" );
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );
  r.showSection( "action-required-section" );
  assert.equal( vs.visible.has( "action-required-section" ), false );
  r.unmount();
} );

test( "showSection before the toolbar mounts still un-hides the section and saves the choice", () => {
  clearBody();
  const section  = makeSection( "action-required-section" );
  section.hidden = true;
  section.classList.add( "section-hidden" );
  const vs = makeFakeViewState( { "action-required-section": false } );
  const r  = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.showSection( "action-required-section" );
  assert.ok( !section.hidden );
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.equal( vs.visible.get( "action-required-section" ), true );
} );

// ===========================================================================
// A-2 #4 — the one button that owns TWO mounts, and the fresh persist key
//
// Legacy needs neither: `#section-notifications` (notifications.html:478) wraps the
// header and the body in ONE div, so its `💬` hides both by hiding the wrapper. This
// page made them SIBLINGS (multiplexer.html:171 header region, :188 pane), so the
// button must name both or it hides the body and leaves a title bar floating over
// nothing — which reads as a rendering glitch, not as a section that is switched off.
//
// The persist key is FRESH on Rick's direct ruling (2026-09-19 ~19:10 EDT, plan §6a
// item 9), REVERSING the earlier "keep the first id so saved preferences survive".
// One consequence is load-bearing and is asserted below rather than described: the old
// key must never be written, because a dual write is the forbidden fallback arriving
// quietly and nothing else would notice it.
// ===========================================================================

/** The production notifications entry, so these run against the shipped spec. */
const NOTIFS_SPEC = SECTION_TOGGLES.find( ( t ) => t.sectionId === "notifications-pane" )!;

test( "positive control: the shipped notifications entry really does name two elements and a fresh key", () => {
  // Without this, every assertion below could be passing against a one-element entry.
  assert.deepEqual( NOTIFS_SPEC.sectionIds, [ "notifications-pane", "notifications-header-region" ] );
  assert.equal( NOTIFS_SPEC.persistKey, "notifications-header-and-pane" );
  assert.equal( NOTIFS_SPEC.sectionIds![ 0 ], NOTIFS_SPEC.sectionId,
    "the handle must stay the FIRST id — two e2e guards resolve data-section as an element id" );
} );

test( "🔴 💬 hides the header region AND the pane, not the pane alone", () => {
  clearBody();
  const mount  = makeMount();
  const pane   = makeSection( "notifications-pane" );
  const header = makeSection( "notifications-header-region" );
  const vs     = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( !pane.hidden && !header.hidden, "precondition: both start visible" );

  clickBubbling( btn );
  assert.ok( pane.hidden,   "the pane did not hide" );
  assert.ok( header.hidden, "the HEADER REGION did not hide — the title bar is left floating" );
  assert.ok( pane.classList.contains( "section-hidden" ) );
  assert.ok( header.classList.contains( "section-hidden" ) );

  clickBubbling( btn );
  assert.ok( !pane.hidden,   "the pane did not come back" );
  assert.ok( !header.hidden, "the header region did not come back" );
  r.unmount();
} );

test( "every OTHER button still owns exactly one element — this did not become a broadcast", () => {
  // The mechanism is opt-in. A change that hid siblings for every toggle would pass the
  // test above and be badly wrong, and no assertion up to here would have said so.
  clearBody();
  const mount = makeMount();
  const jobs  = makeSection( "jobs-pane" );
  const other = makeSection( "notifications-header-region" );   // a bystander
  const vs    = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  clickBubbling( mount.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement );
  assert.ok( jobs.hidden,   "precondition: the jobs button works at all" );
  assert.ok( !other.hidden, "hiding Jobs also hid an element it does not own" );
  r.unmount();
} );

test( "🔴 the preference is stored under the FRESH key, and the superseded key is never written", () => {
  clearBody();
  const mount = makeMount();
  makeSection( "notifications-pane" );
  makeSection( "notifications-header-region" );
  const vs = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  clickBubbling( mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement );
  assert.equal( vs.visible.get( "notifications-header-and-pane" ), false, "nothing was stored under the fresh key" );
  assert.equal( vs.visible.has( "notifications-pane" ), false,
    "the SUPERSEDED key was written — that is the fallback Rick's ruling forbids" );
  r.unmount();
} );

test( "a preference saved under the OLD key is ignored — the one-time reset Rick accepted", () => {
  // This is the ruling's cost, pinned so nobody later reads it as a bug and repairs it
  // by falling back. An operator who had hidden notifications sees it VISIBLE once.
  clearBody();
  const mount  = makeMount();
  const pane   = makeSection( "notifications-pane" );
  const header = makeSection( "notifications-header-region" );
  const vs = makeFakeViewState( { "notifications-pane": false } );   // the stale saved choice
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  assert.ok( !pane.hidden,   "the stale key still drove visibility — the old key is being read" );
  assert.ok( !header.hidden );
  assert.ok( ( mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement )
    .classList.contains( "active" ) );
  r.unmount();
} );

// ⚠️ A TEST WAS DELETED HERE IN THE B-3 REBASE, NOT LOST. It read "the cold default still
// keys on the SECTION id, not the persist key" and pinned the two-key distinction inside
// `currentEffectiveVisible`. B-3 (row cec9dd43) deleted the cold-hidden concept and that
// method with it, so the test asserted a distinction that no longer exists — it would have
// kept passing while meaning nothing, which is worse than absent. The surviving key
// behaviour (reads and writes both go through the persist key, at all five store call
// sites) is pinned by the two tests above.

test( "the RECONCILE reads the persist key too — a preference that saves must also restore", () => {
  // The quiet one. The toggle saves under the fresh key; if the mount-time reconcile looked
  // the section up under its raw id it would find nothing and paint the default — a
  // preference that stores correctly and is silently never restored. Nothing else here
  // exercises the mount path against a pre-seeded fresh key.
  clearBody();
  const mount  = makeMount();
  const pane   = makeSection( "notifications-pane" );
  const header = makeSection( "notifications-header-region" );
  const vs = makeFakeViewState( { "notifications-header-and-pane": false } );   // persisted HIDDEN
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document, toggles: SECTION_TOGGLES } );
  r.mount( mount );

  assert.ok( pane.hidden,   "the reconcile did not restore the persisted choice for the pane" );
  assert.ok( header.hidden, "the reconcile restored the pane but not the header region" );
  r.unmount();
} );
