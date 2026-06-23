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
  COLLAPSE_ALL_ID,
  EXPAND_ALL_ID,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

// --- Fake ViewStateStore ----------------------------------------------------
interface FakeViewState extends ViewStateStoreLike {
  visible : Map<string, boolean>;
  hidden  : string[];
  bulkCalls : boolean[];
}
function makeFakeViewState( hidden: string[] = [] ): FakeViewState {
  const visible = new Map<string, boolean>();
  const fake: FakeViewState = {
    visible,
    hidden,
    bulkCalls: [],
    isSectionVisible: ( id ) => visible.get( id ) !== false,
    setSectionVisible: ( id, v ) => { visible.set( id, v ); },
    getHiddenSectionIds: () => hidden,
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
  assert.notEqual( el.querySelector( `#${COLLAPSE_ALL_ID}` ), null );
  assert.notEqual( el.querySelector( `#${EXPAND_ALL_ID}` ), null );
  const btns = el.querySelectorAll( ".toolbar-btn" );
  assert.equal( btns.length, SECTION_TOGGLES.length );
  // Every section button is rendered `.active` with its data-section + title.
  for ( const spec of SECTION_TOGGLES ) {
    const btn = el.querySelector( `.toolbar-btn[data-section="${spec.sectionId}"]` ) as HTMLElement;
    assert.notEqual( btn, null );
    assert.ok( btn.classList.contains( "active" ) );
    assert.equal( btn.getAttribute( "title" ), spec.title );
  }
} );

test( "template: a custom toggles list renders exactly those buttons", () => {
  const el = renderSectionToolbar( [ { sectionId: "x-pane", icon: "🧪", title: "X", testid: "x" } ] );
  assert.equal( el.querySelectorAll( ".toolbar-btn" ).length, 1 );
  assert.notEqual( el.querySelector( `.toolbar-btn[data-section="x-pane"]` ), null );
} );

// ===========================================================================
// Renderer — mount / unmount lifecycle
// ===========================================================================

test( "mount: builds toolbar into root; double mount throws; unmount idempotent", () => {
  clearBody();
  const mount = makeMount();
  const r = createSectionToolbarRenderer( { stores: { viewState: makeFakeViewState() }, doc: document } );
  r.mount( mount );
  assert.notEqual( mount.querySelector( "#section-toolbar" ), null );
  assert.throws( () => r.mount( mount ), /already mounted/ );
  r.unmount();
  assert.equal( mount.querySelector( "#section-toolbar" ), null );
  r.unmount();   // idempotent — no throw, toolbar already null
} );

// ===========================================================================
// Renderer — per-section visibility toggle
// ===========================================================================

test( "click a section button: toggles section .section-hidden + button .active + persists", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "notifications-pane" );
  const vs      = makeFakeViewState();
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const btn = mount.querySelector( `.toolbar-btn[data-section="notifications-pane"]` ) as HTMLElement;
  assert.ok( btn.classList.contains( "active" ) );

  clickBubbling( btn );   // hide
  assert.ok( section.classList.contains( "section-hidden" ) );
  assert.ok( !btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "notifications-pane" ), false );

  clickBubbling( btn );   // show
  assert.ok( !section.classList.contains( "section-hidden" ) );
  assert.ok( btn.classList.contains( "active" ) );
  assert.equal( vs.visible.get( "notifications-pane" ), true );
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
// Renderer — persisted section visibility re-applied on mount
// ===========================================================================

test( "mount re-applies persisted hidden sections (button dimmed + section hidden); unknown ids skipped", () => {
  clearBody();
  const mount   = makeMount();
  const section = makeSection( "jobs-pane" );
  // "jobs-pane" is a real toggle + real section; "ghost-pane" is neither →
  // exercises the btn-null + section-null skip branches in applyPersisted.
  const vs = makeFakeViewState( [ "jobs-pane", "ghost-pane" ] );
  const r = createSectionToolbarRenderer( { stores: { viewState: vs }, doc: document } );
  r.mount( mount );

  const jobsBtn = mount.querySelector( `.toolbar-btn[data-section="jobs-pane"]` ) as HTMLElement;
  assert.ok( !jobsBtn.classList.contains( "active" ) );           // dimmed
  assert.ok( section.classList.contains( "section-hidden" ) );    // hidden
  // ghost-pane: no button, no section → silently skipped (no throw).
  assert.equal( mount.querySelector( `.toolbar-btn[data-section="ghost-pane"]` ), null );
  r.unmount();
} );
