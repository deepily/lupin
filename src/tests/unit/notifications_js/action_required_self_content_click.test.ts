// Bug 11c01fbc — inside an ask_* (action-required) panel, the 📋 abstract
// indicator AND embedded doc-links were dead in HORIZONTAL layout. Root cause:
// the panel is LIFTED into the Reading Pane (_enterActionRequiredPaneMode), so a
// click on ITS OWN 📋 / doc-link reached _openContentPane and hit the guard
// `if ( this._actionRequiredInPane ) return;` — the same guard that (correctly)
// stops a FOREIGN card from replacing the blocking response buttons.
//
// Fix (two call sites, guard untouched): route the card's OWN content to a
// non-pane surface — 📋 → the in-tab tooltip, doc-link → native target=_blank —
// because the pane is SHARED with the live response buttons and would be wiped by
// _renderContentPaneEntry's innerHTML="". The self-test keys on the LIVE lifted
// element (#action-required-content descendant), NOT a class a foreign card could
// carry. These tests assert BOTH directions: self→through, foreign→still blocked.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/action_required_self_content_click.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

// A single shared UI instance owns the two document-level click listeners. The
// listeners are arrow functions that capture THIS instance, so registering them
// once (in before) and mutating the instance's fields per test avoids piling up
// duplicate document listeners across tests.
let ui: Record<string, unknown>;

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );

  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug             = false;
  ui.log               = (): void => {};
  ui._layoutMode       = "horizontal";
  ui._contentPaneHistory = [];
  ui._paneSplitRatio   = 0.667;
  // Recorder replaces _openContentPane so a "routed to the pane" call is observable.
  ui._openContentPaneCalls = [];
  ui._openContentPane = function ( type: string, payload: string, title: string ): void {
    ( this as Record<string, unknown[]> )._openContentPaneCalls.push( [ type, payload, title ] );
  };
  ui.renderMarkdown = ( s: string ): string => s;   // identity — enough for the tooltip innerHTML
  // Plumbing stubs so _initMasterDetailLayout wires listeners without side effects.
  ui._initPaneSplitter          = (): void => {};
  ui._applyPaneSplitRatio       = (): void => {};
  ui._updateToolbarPosition     = (): void => {};
  ui._updateLayoutModeButtonTooltip = (): void => {};

  // Wire the two real document-level listeners ONCE.
  ( ui.initAbstractTooltip as () => void ).call( ui );
  ( ui._initMasterDetailLayout as () => void ).call( ui );
} );

// Build the DOM fresh per test: an action-required card (with its OWN 📋 + doc
// link) plus a FOREIGN center-column card (with its own 📋 + doc link), and the
// #abstract-tooltip surface the self 📋 falls through to.
function buildDOM(): {
  selfIndicator: HTMLElement; selfAnchor: HTMLElement;
  foreignIndicator: HTMLElement; foreignAnchor: HTMLElement;
} {
  document.body.replaceChildren();

  // Tooltip surface (in-tab) that the self 📋 must reach.
  const tooltip = document.createElement( "div" );
  tooltip.id = "abstract-tooltip";
  const tipContent = document.createElement( "div" );
  tipContent.className = "abstract-tooltip-content";
  tooltip.appendChild( tipContent );
  document.body.appendChild( tooltip );

  // The lifted action-required card (self).
  const arContent = document.createElement( "div" );
  arContent.id = "action-required-content";
  const selfIndicator = document.createElement( "span" );
  selfIndicator.className = "abstract-indicator";
  selfIndicator.setAttribute( "data-abstract", encodeURIComponent( "**self abstract**" ) );
  const selfAnchor = document.createElement( "a" );
  selfAnchor.setAttribute( "href", "/app/docs?path=lupin/self.md" );
  selfAnchor.textContent = "self doc";
  arContent.appendChild( selfIndicator );
  arContent.appendChild( selfAnchor );
  document.body.appendChild( arContent );

  // A foreign center-column card.
  const foreignCard = document.createElement( "div" );
  foreignCard.className = "notification-message";
  const foreignIndicator = document.createElement( "span" );
  foreignIndicator.className = "abstract-indicator";
  foreignIndicator.setAttribute( "data-abstract", encodeURIComponent( "**foreign abstract**" ) );
  const foreignAnchor = document.createElement( "a" );
  foreignAnchor.setAttribute( "href", "/app/docs?path=lupin/foreign.md" );
  foreignAnchor.textContent = "foreign doc";
  foreignCard.appendChild( foreignIndicator );
  foreignCard.appendChild( foreignAnchor );
  document.body.appendChild( foreignCard );

  return { selfIndicator, selfAnchor, foreignIndicator, foreignAnchor };
}

function click( el: HTMLElement ): MouseEvent {
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  el.dispatchEvent( ev );
  return ev;
}

beforeEach( () => {
  ui._layoutMode             = "horizontal";
  ui._actionRequiredInPane   = true;    // the card owns the pane
  ( ui._openContentPaneCalls as unknown[] ).length = 0;
  ui._contentPaneHistory     = [];
} );

// ── Abstract 📋 indicator ──────────────────────────────────────────────────

test( "self 📋 → in-tab tooltip, NOT the pane (self→through)", () => {
  const { selfIndicator } = buildDOM();
  click( selfIndicator );

  assert.equal( ( ui._openContentPaneCalls as unknown[] ).length, 0,
    "self 📋 must NOT route to _openContentPane (would wipe the response buttons)" );
  const tip = document.querySelector( "#abstract-tooltip .abstract-tooltip-content" ) as HTMLElement;
  assert.equal( tip.innerHTML, "**self abstract**", "self abstract rendered into the in-tab tooltip" );
} );

test( "foreign 📋 → still routed to the pane where the guard holds (foreign→blocked)", () => {
  const { foreignIndicator } = buildDOM();
  click( foreignIndicator );

  const calls = ui._openContentPaneCalls as string[][];
  assert.equal( calls.length, 1, "foreign 📋 still routes to the pane" );
  assert.equal( calls[ 0 ][ 0 ], "abstract" );
  assert.equal( calls[ 0 ][ 1 ], "**foreign abstract**" );
} );

test( "self 📋 in vertical mode also uses the tooltip (vertical unaffected)", () => {
  ui._layoutMode           = "vertical";
  ui._actionRequiredInPane = false;
  const { selfIndicator } = buildDOM();
  click( selfIndicator );

  assert.equal( ( ui._openContentPaneCalls as unknown[] ).length, 0 );
  const tip = document.querySelector( "#abstract-tooltip .abstract-tooltip-content" ) as HTMLElement;
  assert.equal( tip.innerHTML, "**self abstract**" );
} );

// ── Embedded doc-link ──────────────────────────────────────────────────────

test( "self doc-link → native new tab (not prevented), NOT the pane (self→through)", () => {
  const { selfAnchor } = buildDOM();
  const ev = click( selfAnchor );

  assert.equal( ( ui._openContentPaneCalls as unknown[] ).length, 0,
    "self doc-link must NOT route to _openContentPane" );
  assert.equal( ev.defaultPrevented, false,
    "self doc-link keeps default nav so target=_blank opens a new tab (vertical parity)" );
} );

test( "foreign doc-link → routed to the pane and prevented (foreign→blocked)", () => {
  const { foreignAnchor } = buildDOM();
  const ev = click( foreignAnchor );

  const calls = ui._openContentPaneCalls as string[][];
  assert.equal( calls.length, 1, "foreign doc-link still routes to the pane" );
  assert.equal( calls[ 0 ][ 0 ], "doc" );
  assert.equal( calls[ 0 ][ 1 ], "/app/docs?path=lupin/foreign.md" );
  assert.equal( ev.defaultPrevented, true, "foreign doc-link default nav prevented (pane handles it)" );
} );

// ── Guard intact (control) — the real _openContentPane still blocks foreign ──

test( "control: real _openContentPane still returns early while the card owns the pane", () => {
  buildDOM();
  // Give the real method the DOM + stashed history state it inspects.
  const shell = document.createElement( "div" ); shell.className = "content-shell";
  const pane  = document.createElement( "div" ); pane.id = "content-pane"; pane.hidden = true;
  const body  = document.createElement( "div" ); body.id = "content-pane-body";
  shell.appendChild( pane ); shell.appendChild( body );
  document.body.appendChild( shell );

  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: Record<string, unknown> };
  const realOpen = Ctor.prototype._openContentPane as ( ...a: unknown[] ) => void;

  ui._actionRequiredInPane = true;
  ui._contentPaneHistory   = [];
  realOpen.call( ui, "abstract", "**foreign**", "T" );
  assert.equal( pane.hidden, true, "guard held: pane stays hidden" );
  assert.equal( ( ui._contentPaneHistory as unknown[] ).length, 0, "guard held: no history push" );

  // Control's control: with the guard clear, the same call DOES open — proving the
  // guard is the only thing blocking, not a broken precondition.
  ui._actionRequiredInPane = false;
  realOpen.call( ui, "abstract", "**foreign**", "T" );
  assert.equal( pane.hidden, false, "guard clear → pane opens" );
  assert.equal( ( ui._contentPaneHistory as unknown[] ).length, 1, "guard clear → history push" );
} );
