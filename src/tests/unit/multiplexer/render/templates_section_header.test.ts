// Multiplexer Lane 0a (2026-07-02, Rachel 🕊️) — sectionHeader template unit
// tests. 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderSectionHeader,
  setSectionCollapsed,
  wireSectionCollapse,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sectionHeader";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function clickBubbling( el: Element ): void {
  el.dispatchEvent( new Event( "click", { bubbles: true } ) );
}

// ---------------------------------------------------------------------------
// renderSectionHeader — structure
// ---------------------------------------------------------------------------

test( "renderSectionHeader: builds the .section-header contract (icon+title+count+chevron) with testid + actions", () => {
  const refresh = document.createElement( "button" );
  refresh.className = "my-refresh";
  const handle = renderSectionHeader( {
    icon: "🛰️",
    title: "Fleet Status",
    testid: "multiplexer-fleet-header",
    actions: [ refresh ],
  } );

  assert.equal( handle.header.className, "section-header" );
  assert.equal( handle.header.getAttribute( "data-testid" ), "multiplexer-fleet-header" );

  const h3 = handle.header.querySelector( "h3" ) as HTMLElement;
  assert.notEqual( h3, null );
  assert.ok( h3.textContent!.includes( "🛰️ Fleet Status" ) );

  // count chip is inside the h3, empty until setCount.
  assert.equal( handle.countEl.className, "section-header-count" );
  assert.equal( handle.countEl.textContent, "" );
  assert.equal( h3.querySelector( ".section-header-count" ), handle.countEl );

  // actions slot holds the given control THEN the chevron (rightmost).
  assert.equal( handle.actionsEl.className, "section-header-actions" );
  assert.equal( handle.actionsEl.querySelector( ".my-refresh" ), refresh );
  assert.equal( handle.toggleEl.className, "toggle-button" );
  assert.equal( handle.toggleEl.textContent, "▼" );          // expanded glyph
  assert.equal( handle.actionsEl.lastElementChild, handle.toggleEl );
  assert.equal( handle.toggleEl.getAttribute( "role" ), "button" );
} );

test( "renderSectionHeader: no testid + no actions → header carries no data-testid; actions slot holds only the chevron", () => {
  const handle = renderSectionHeader( { icon: "🔔", title: "Notifications" } );
  assert.equal( handle.header.hasAttribute( "data-testid" ), false );
  // Only the chevron in the actions slot.
  assert.equal( handle.actionsEl.children.length, 1 );
  assert.equal( handle.actionsEl.firstElementChild, handle.toggleEl );
} );

test( "setCount: accepts a number and a preformatted string", () => {
  const handle = renderSectionHeader( { icon: "📝", title: "Jobs" } );
  handle.setCount( 7 );
  assert.equal( handle.countEl.textContent, "7" );
  handle.setCount( "12 / 4 buckets" );
  assert.equal( handle.countEl.textContent, "12 / 4 buckets" );
} );

// ---------------------------------------------------------------------------
// setSectionCollapsed — attribute + glyph
// ---------------------------------------------------------------------------

test( "setSectionCollapsed: flips data-collapsed + chevron glyph both directions", () => {
  const section = document.createElement( "section" );
  const handle  = renderSectionHeader( { icon: "🗒️", title: "Task List" } );

  setSectionCollapsed( section, handle, true );
  assert.equal( section.getAttribute( "data-collapsed" ), "true" );
  assert.equal( handle.toggleEl.textContent, "▶" );

  setSectionCollapsed( section, handle, false );
  assert.equal( section.getAttribute( "data-collapsed" ), "false" );
  assert.equal( handle.toggleEl.textContent, "▼" );
} );

// ---------------------------------------------------------------------------
// wireSectionCollapse — click behavior + guard + unsubscribe
// ---------------------------------------------------------------------------

test( "wireSectionCollapse: clicking the header (or chevron) toggles collapse; clicking a control does NOT; unsubscribe detaches", () => {
  const section = document.createElement( "section" );
  const control = document.createElement( "button" );
  control.className = "ctl";
  const handle  = renderSectionHeader( { icon: "🔊", title: "Playing", actions: [ control ] } );
  section.appendChild( handle.header );

  const off = wireSectionCollapse( section, handle );

  // (1) click on the header background (the h3) → collapse.
  clickBubbling( handle.header.querySelector( "h3" ) as HTMLElement );
  assert.equal( section.getAttribute( "data-collapsed" ), "true" );
  assert.equal( handle.toggleEl.textContent, "▶" );

  // (2) click on the chevron span → expand (chevron is not a <button>).
  clickBubbling( handle.toggleEl );
  assert.equal( section.getAttribute( "data-collapsed" ), "false" );
  assert.equal( handle.toggleEl.textContent, "▼" );

  // (3) click on a real control button → NO collapse (its own handler owns it).
  clickBubbling( control );
  assert.equal( section.getAttribute( "data-collapsed" ), "false" );

  // (4) unsubscribe → subsequent header clicks are inert.
  off();
  clickBubbling( handle.header.querySelector( "h3" ) as HTMLElement );
  assert.equal( section.getAttribute( "data-collapsed" ), "false" );
} );
