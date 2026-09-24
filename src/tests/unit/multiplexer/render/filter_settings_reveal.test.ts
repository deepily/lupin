// Parity A-2 #11 — the reveal both filter badges call.
//
// 🔴 WHY THIS FILE EXISTS: María 🌸's surviving mutant, 2026-09-23. The reveal was an
// inline arrow inside `bootMultiplexer()`, and boot runs at import and exports nothing,
// so every boot guard in this tree is a source pin that reads the file as TEXT. A source
// pin cannot see a logic error — only a spelling one. Emptying that arrow's body killed
// NO test. The body was extracted so it could be driven; these drive it.
//
// The last case is the one that answers the mutant in the operator's terms: the REAL
// toolbar renderer and the REAL pane renderer, assembled, and the question is whether the
// pane is on screen afterwards.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/filter_settings_reveal.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createFilterSettingsReveal } from "../../../../lupin_app/static/js/multiplexer/render/filterSettingsReveal";
import { createSectionToolbarRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SectionToolbarRenderer";
import { createFilterSettingsRenderer } from "../../../../lupin_app/static/js/multiplexer/render/FilterSettingsRenderer";
import { SECTION_TOGGLES } from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { createViewStateStore } from "../../../../lupin_app/static/js/multiplexer/stores/ViewStateStore";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function makePane(): HTMLElement {
  const pane = document.createElement( "section" );
  pane.id = "filter-settings-pane";
  document.body.appendChild( pane );
  return pane;
}

// A toolbar double that records what it was asked to show. Deliberately NOT the real
// renderer for the first cases: they are about what the reveal ASKS FOR, and a real
// renderer would let a wrong id still look right if the section happened to be visible.
function fakeToolbar() {
  const shown: string[] = [];
  return { shown, toolbar: { showSection: ( id: string ): void => { shown.push( id ); } } };
}

test( "🔴 the reveal asks the toolbar to show Filter Settings BY NAME", () => {
  document.body.replaceChildren();
  makePane();
  const { shown, toolbar } = fakeToolbar();
  createFilterSettingsReveal( { toolbar: () => toolbar, doc: document } )();
  assert.deepEqual( shown, [ "filter-settings-pane" ],
    "an empty reveal body records nothing here — this is the case the inline arrow never had" );
} );

test( "the toolbar is read at CALL time, not captured at construction", () => {
  // Boot constructs the badges that close over this reveal BEFORE it constructs the
  // toolbar renderer, so a captured reference would read a const in its temporal dead
  // zone. This proves the thunk is invoked per call: the toolbar does not yet exist when
  // the reveal is built, and the call still finds it.
  document.body.replaceChildren();
  makePane();
  let toolbar: { showSection( id: string ): void } | null = null;
  const shown: string[] = [];
  const reveal = createFilterSettingsReveal( {
    /* c8 ignore next */ // the null arm cannot be reached: the toolbar is assigned before the reveal is invoked, which is the property under test.
    toolbar : () => toolbar ?? ( ( () => { throw new Error( "read before the toolbar existed" ); } )() ),
    doc     : document,
  } );
  toolbar = { showSection: ( id: string ): void => { shown.push( id ); } };
  reveal();
  assert.deepEqual( shown, [ "filter-settings-pane" ] );
} );

test( "the reveal scrolls the pane, because showSection deliberately does not", () => {
  document.body.replaceChildren();
  const pane = makePane();
  // happy-dom does no layout, so every rect is zeros and reads as "in view". Pin the
  // pane below the fold, or the shared helper correctly decides not to scroll and this
  // case would pass against a reveal that never asked.
  pane.getBoundingClientRect = () => ( {
    top: window.innerHeight + 100, bottom: window.innerHeight + 400,
    left: 0, right: 0, width: 0, height: 300, x: 0, y: 0, toJSON: () => ( {} ),
  } ) as DOMRect;
  const calls: Array<ScrollIntoViewOptions | boolean | undefined> = [];
  pane.scrollIntoView = ( arg?: ScrollIntoViewOptions | boolean ): void => { calls.push( arg ); };

  const { toolbar } = fakeToolbar();
  createFilterSettingsReveal( { toolbar: () => toolbar, doc: document } )();
  assert.equal( calls.length, 1, "the pane was not scrolled into view" );
  assert.deepEqual( calls[ 0 ], { behavior: "smooth", block: "start" } );
} );

test( "a missing pane is a no-op, not a throw", () => {
  // The `pane !== null` else-arm. Boot throws at startup if the pane is absent, so this
  // cannot happen in production — but the branch exists and the gate counts branches.
  document.body.replaceChildren();
  const { shown, toolbar } = fakeToolbar();
  createFilterSettingsReveal( { toolbar: () => toolbar, doc: document } )();
  assert.deepEqual( shown, [ "filter-settings-pane" ], "the toolbar is still asked, pane or no pane" );
} );

// ---------------------------------------------------------------------------
// 🔴 THE MUTANT, ANSWERED IN THE OPERATOR'S TERMS
//
// Real toolbar renderer, real pane renderer, real stores. The question is not "was
// showSection called" but "is the pane on screen" — which is what an empty reveal body
// would get wrong, and what every single-axis test in this tree cannot see.
// ---------------------------------------------------------------------------

test( "🔴 an admin who HID Filter Settings gets it back when a badge reveal runs", () => {
  document.body.replaceChildren();
  const pane = makePane();
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus, new InMemoryStorage() );
  const store   = createNotificationStore( {
    bus, storage, sharedStorage: null,
    setTimeoutFn: ( cb ) => { cb(); return 0; }, clearTimeoutFn: () => {},
    nowFn: () => 1_700_000_000_000, isAdmin: () => true,
  } );
  const viewState = createViewStateStore( { bus, storage } );

  // The operator hid the pane earlier — the only state in which the reveal has work to
  // do, since cec9dd43 made it visible by default for an admin.
  viewState.setSectionVisible( "filter-settings-pane", false );

  const toolbarMount = document.createElement( "div" );
  document.body.appendChild( toolbarMount );
  const toolbar = createSectionToolbarRenderer( {
    stores: { viewState }, doc: document, toggles: SECTION_TOGGLES,
  } );
  toolbar.mount( toolbarMount );
  const filterSettings = createFilterSettingsRenderer( {
    eventBus: bus, store, viewState, isAdmin: () => true,
  } );
  filterSettings.mount( pane );

  const onScreen = (): boolean =>
    !pane.hidden && !pane.classList.contains( "section-hidden" ) && pane.style.display !== "none";

  assert.equal( onScreen(), false, "precondition: the operator hid it, so it starts off screen" );

  createFilterSettingsReveal( { toolbar: () => toolbar, doc: document } )();

  assert.equal( onScreen(), true,
    "the pane is still off screen after the reveal — an empty reveal body looks exactly like this" );
  const btn = toolbarMount.querySelector( `.toolbar-btn[data-section="filter-settings-pane"]` ) as HTMLElement;
  assert.ok( btn.classList.contains( "active" ), "the ⚙️ button must agree with the pane it toggles" );
  assert.equal( viewState.isSectionVisible( "filter-settings-pane" ), true,
    "the reveal must PERSIST, or the pane re-hides on the next load and the reveal looks like it failed" );

  filterSettings.unmount();
  toolbar.unmount();
} );
