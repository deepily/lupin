// Multiplexer parity row B-3 — FilterSettingsRenderer tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/filter_settings_renderer.test.ts`.
//
// Coverage target: 100% lines/branches/functions on FilterSettingsRenderer.ts.
// Uses the REAL NotificationStore, the REAL ViewStateStore and the REAL EventBus with an
// in-memory StorageService. The admin gate is the subject, and it lives in the store — a
// stubbed store would let this file agree with itself about a rule it does not implement.
//
// 🔴 F1 IS ASSERTED AS STRINGS, NOT BEHAVIOUR. Legacy's labels are "👤 My Jobs Only",
// "🚫 Not My Jobs", "👥 All Users' Jobs"; the mux's Mine switch elsewhere says
// "Mine / Not Mine / All Users". Same behaviour, different words — a port ships that
// silently unless something reads the copy.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { createViewStateStore } from "../../../../lupin_app/static/js/multiplexer/stores/ViewStateStore";
import { createFilterSettingsRenderer } from "../../../../lupin_app/static/js/multiplexer/render/FilterSettingsRenderer";
import type { FilterSettingsRenderer } from "../../../../lupin_app/static/js/multiplexer/render/FilterSettingsRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

let mounted: FilterSettingsRenderer | null = null;

function setup( opts: { isAdmin?: boolean } = {} ) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus, new InMemoryStorage() );
  let admin     = opts.isAdmin ?? true;
  const store   = createNotificationStore( {
    bus, storage, sharedStorage: null,
    setTimeoutFn: ( cb ) => { cb(); return 0; }, clearTimeoutFn: () => {},
    nowFn: () => 1_700_000_000_000, isAdmin: () => admin,
  } );
  const viewState = createViewStateStore( { bus, storage } );
  const renderer  = createFilterSettingsRenderer( {
    eventBus: bus, store, viewState, isAdmin: () => admin,
  } );
  mounted = renderer;
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  return { bus, store, viewState, renderer, root, setAdmin( v: boolean ) { admin = v; } };
}

function btn( root: HTMLElement, mode: string ): HTMLButtonElement {
  return root.querySelector( `button[data-mode="${mode}"]` ) as HTMLButtonElement;
}
function displayText( root: HTMLElement ): string {
  return root.querySelector( '[data-testid="multiplexer-filter-mode-display"]' )?.textContent ?? "";
}

afterEach( () => {
  if ( mounted ) { mounted.unmount(); mounted = null; }
  document.body.replaceChildren();
} );

// ===========================================================================
// B7 — the static header and the live line
// ===========================================================================

test( "B7: the header is static and reads ⚙️ Queue Filter Settings", () => {
  const { renderer, root } = setup();
  renderer.mount( root );
  const h = root.querySelector( '[data-testid="multiplexer-filter-settings-header"] h3' );
  assert.match( h?.textContent ?? "", /⚙️\s*Queue Filter Settings/ );
} );

test( "B7: the Currently-viewing line reflects the store's mode", () => {
  const { renderer, root } = setup();
  renderer.mount( root );
  assert.equal( displayText( root ), "Your jobs only" );
  assert.match( root.querySelector( "#filter-status" )?.textContent ?? "", /^Currently viewing: / );
} );

test( "B7: the line follows a mode change made ELSEWHERE", () => {
  // The mode is shared with the jobs pane, so this renderer cannot be the only writer.
  const { store, renderer, root } = setup();
  renderer.mount( root );
  store.setFilterMode( "all" );
  assert.equal( displayText( root ), "All users' jobs" );
} );

// ===========================================================================
// F1 — legacy's LONG labels
// ===========================================================================

test( "🔴 F1: the three buttons carry legacy's long labels, verbatim", () => {
  const { renderer, root } = setup();
  renderer.mount( root );
  assert.equal( btn( root, "own" ).textContent,    "👤 My Jobs Only" );
  assert.equal( btn( root, "others" ).textContent, "🚫 Not My Jobs" );
  assert.equal( btn( root, "all" ).textContent,    "👥 All Users' Jobs" );
} );

test( "F1: and the legacy ids the CSS keys on", () => {
  const { renderer, root } = setup();
  renderer.mount( root );
  assert.notEqual( root.querySelector( "#filter-own-jobs" ), null );
  assert.notEqual( root.querySelector( "#filter-others-jobs" ), null );
  assert.notEqual( root.querySelector( "#filter-all-jobs" ), null );
} );

// ===========================================================================
// The switch itself
// ===========================================================================

test( "clicking a mode button sets the mode and re-lights the buttons", () => {
  const { store, renderer, root } = setup();
  renderer.mount( root );
  assert.equal( btn( root, "own" ).classList.contains( "active" ), true, "own is the default" );

  btn( root, "others" ).click();
  assert.equal( store.filterMode(), "others" );
  assert.equal( btn( root, "others" ).classList.contains( "active" ), true );
  assert.equal( btn( root, "own" ).classList.contains( "active" ), false, "exactly one is lit" );
  assert.equal( displayText( root ), "Other users' jobs" );
} );

test( "the active button is announced, not just coloured", () => {
  const { renderer, root } = setup();
  renderer.mount( root );
  assert.equal( btn( root, "own" ).getAttribute( "aria-pressed" ), "true" );
  assert.equal( btn( root, "all" ).getAttribute( "aria-pressed" ), "false" );
} );

test( "a click on the pane that is not a mode button does nothing", () => {
  const { store, renderer, root } = setup();
  renderer.mount( root );
  ( root.querySelector( "#filter-status" ) as HTMLElement ).click();
  assert.equal( store.filterMode(), "own" );
} );

test( "🔴 F3: a NON-ADMIN click leaves the buttons showing what is REALLY in force", () => {
  // The store refuses (part 1 of this row). The pane repaints from the store's ACTUAL
  // mode rather than the clicked one, so a refused click does not leave a lit button
  // claiming a mode that was never applied — which would be the UI lying on the store's
  // behalf.
  const { store, renderer, root } = setup( { isAdmin: false } );
  renderer.mount( root );
  btn( root, "all" ).click();
  assert.equal( store.filterMode(), "own", "the store refused" );
  assert.equal( btn( root, "all" ).classList.contains( "active" ), false, "and the button did not light" );
  assert.equal( btn( root, "own" ).classList.contains( "active" ), true );
  assert.equal( displayText( root ), "Your jobs only" );
} );

// ===========================================================================
// B1 — the ADMIN GATE: inline `display`, from isAdmin alone, exactly as legacy
//
// 🔴 THESE ASSERT ON `style.display`, NOT ON `hidden`, AND THAT IS THE POINT.
// The element has two independent hide axes and this renderer writes only one:
//   axis 1  inline `style.display`      — THIS renderer, from isAdmin alone
//   axis 2  `.section-hidden` + `hidden` — SectionToolbarRenderer's user toggle
// `.section-hidden` is `display:none !important`, so the pane is visible only when
// BOTH say visible. An earlier cut of these tests read `root.hidden` and so was green
// against a version with NO admin gate at all: the toolbar cleared `hidden`, the
// assertions saw what they asked for, and a non-admin could open the pane.
// ===========================================================================

function gateSaysVisible( root: HTMLElement ): boolean {
  return root.style.display !== "none";
}

test( "B1: the gate is SHUT for a non-admin", () => {
  const { renderer, root } = setup( { isAdmin: false } );
  renderer.mount( root );
  assert.equal( root.style.display, "none" );
} );

test( "B1: the gate is OPEN for an admin", () => {
  const { renderer, root } = setup( { isAdmin: true } );
  renderer.mount( root );
  assert.equal( gateSaysVisible( root ), true );
} );

test( "B1: reveal() leaves the gate open for an ADMIN", () => {
  const { renderer, root } = setup( { isAdmin: true } );
  renderer.mount( root );
  renderer.reveal();
  assert.equal( gateSaysVisible( root ), true );
} );

test( "🔴 B1: reveal() is a NO-OP for a non-admin", () => {
  const { renderer, root } = setup( { isAdmin: false } );
  renderer.mount( root );
  renderer.reveal();
  assert.equal( root.style.display, "none" );
} );

test( "🔴 B1: the gate outranks the TOOLBAR clearing axis 2 — María's finding", () => {
  // The ⚙️ toolbar button carries no admin gate of its own (sectionToolbar.ts renders
  // one button per spec, role-blind), so a non-admin CAN clear axis 2. Legacy survives
  // that because axis 1 is still standing. This drives exactly what the toolbar does:
  // `hidden = false` plus `.section-hidden` off.
  const { renderer, root } = setup( { isAdmin: false } );
  renderer.mount( root );

  root.hidden = false;
  root.classList.remove( "section-hidden" );

  assert.equal( root.style.display, "none",
    "axis 2 is clear, and the pane is STILL shut — the inline display is the gate" );
} );

test( "🔴 B1: a non-admin reveal PERSISTS NOTHING either", () => {
  // A persisted visibility would re-open the pane on the next load, after the refusal
  // that was supposed to stop it — the same evaporating-refusal shape the store's
  // setter avoids.
  const { viewState, renderer, root } = setup( { isAdmin: false } );
  renderer.mount( root );
  renderer.reveal();
  assert.equal( viewState.hasSectionPreference( "filter-settings-pane" ), false );
} );

test( "B1: a persisted visibility still does not open the gate for a non-admin", () => {
  // An admin reveals it, then a non-admin signs in on the same browser. The stored
  // preference is axis 2's and must not outrank axis 1.
  const { viewState, renderer, root, setAdmin } = setup( { isAdmin: true } );
  viewState.setSectionVisible( "filter-settings-pane", true );
  setAdmin( false );
  renderer.mount( root );
  assert.equal( root.style.display, "none" );
} );

// ===========================================================================
// B3 — visibility IS persisted, disclosure is NOT
// ===========================================================================

test( "🔴 B3: reveal() PERSISTS the visibility, explicitly", () => {
  // Without this the pane re-hides on the next load and the reveal looks like it failed.
  const { viewState, renderer, root } = setup( { isAdmin: true } );
  renderer.mount( root );
  renderer.reveal();
  assert.equal( viewState.isSectionVisible( "filter-settings-pane" ), true );
  assert.equal( viewState.hasSectionPreference( "filter-settings-pane" ), true );
} );

test( "🔴 B3: collapsing the body persists NOTHING — disclosure is within-session", () => {
  const { viewState, renderer, root } = setup( { isAdmin: true } );
  renderer.mount( root );
  renderer.reveal();
  const before = viewState.isSectionVisible( "filter-settings-pane" );

  ( root.querySelector( ".section-header" ) as HTMLElement ).click();
  assert.equal( root.getAttribute( "data-collapsed" ), "true", "B2 — the header click collapsed it" );
  assert.equal( viewState.isSectionVisible( "filter-settings-pane" ), before,
    "collapsing the BODY must not touch the pane's VISIBILITY — they are different preferences" );
} );

test( "B2: the collapse chevron is a real <button>, not a span", () => {
  // Rick's 2026-09-06 ruling: a `<span role=button>` with no tabindex cannot be focused,
  // so a keyboard user could reach legacy's collapse and not the mux's.
  const { renderer, root } = setup();
  renderer.mount( root );
  const chevron = root.querySelector( ".toggle-button" );
  assert.equal( chevron?.tagName, "BUTTON" );
} );

// ===========================================================================
// Lifecycle
// ===========================================================================

test( "a second mount throws rather than double-subscribing", () => {
  const { renderer, root } = setup();
  renderer.mount( root );
  assert.throws( () => renderer.mount( root ), /already mounted/ );
} );

test( "unmount empties the root and stops repainting", () => {
  const { store, renderer, root } = setup();
  renderer.mount( root );
  renderer.unmount();
  mounted = null;
  assert.equal( root.childNodes.length, 0 );
  store.setFilterMode( "all" );
  assert.equal( root.childNodes.length, 0, "an unmounted renderer must not repaint" );
} );

test( "unmount is safe when nothing was mounted, and twice", () => {
  const { renderer, root } = setup();
  renderer.unmount();
  renderer.mount( root );
  renderer.unmount();
  renderer.unmount();
  mounted = null;
  assert.equal( root.childNodes.length, 0 );
} );

test( "reveal() before mount does not throw", () => {
  const { renderer } = setup( { isAdmin: true } );
  renderer.reveal();
  mounted = null;
} );
