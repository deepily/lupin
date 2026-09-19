// Parity A-2 #2b (row 43338b1b, 2026-09-16, John 🏄🏽) — Action Required reveals itself
// when a prompt arrives: un-hide through the toolbar (which saves the visibility and
// re-lights the ⚠️ button), un-collapse, and scroll through the shared helper.
// Legacy: ensureActionRequiredExpanded (notifications.js:21693-21717) on arrival, and the
// active card's scroll (:23204-23210). Phase 2 A3 B6.

import { test, before, mock } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredRenderer,
  type ActionRequiredStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { SCROLL_REVEAL_SETTLE_MS } from "../../../../lupin_app/static/js/multiplexer/render/scrollReveal";
import type {
  ActionRequiredItem,
  StoreActionRequiredChangedPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function makeItem( id: string ): ActionRequiredItem {
  return {
    id_hash         : id,
    prompt          : "Proceed?",
    response_type   : "yes_no",
    questions       : [],
    expires_at      : Date.now() + 30_000,
    timeout_seconds : 30,
    state           : "pending",
  };
}

interface Harness {
  bus      : ReturnType<typeof createEventBusForTesting>;
  items    : Map<string, ActionRequiredItem>;
  root     : HTMLElement;
  reveals  : number;
  scrolls  : Array<ScrollIntoViewOptions | boolean | undefined>;
  emit     : ( payload: StoreActionRequiredChangedPayload ) => void;
  unmount  : () => void;
}

function setup( withReveal = true ): Harness {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const items = new Map<string, ActionRequiredItem>();
  const store: ActionRequiredStoreLike = {
    list            : () => Array.from( items.values() ),
    getById         : ( id ) => items.get( id ),
    respondAndAwait : async () => {},
  };
  const root = document.createElement( "div" );
  root.id    = "action-required-section";
  document.body.appendChild( root );
  // happy-dom does no layout; pin the section below the fold so the helper scrolls.
  const scrolls: Harness["scrolls"] = [];
  root.getBoundingClientRect = () => ( { top: window.innerHeight + 50, bottom: window.innerHeight + 300, left: 0, right: 0, width: 0, height: 250, x: 0, y: 0, toJSON: () => ( {} ) } ) as DOMRect;
  root.scrollIntoView        = ( arg?: ScrollIntoViewOptions | boolean ) => { scrolls.push( arg ); };

  const h = { bus, items, root, reveals: 0, scrolls } as Harness;
  const renderer = createActionRequiredRenderer( {
    eventBus : bus,
    stores   : { actionRequired: store },
    ...( withReveal ? { revealSection: () => { h.reveals += 1; } } : {} ),
  } );
  renderer.mount( root );
  h.emit    = ( payload ) => bus.emit( { type: "store_action_required_changed", payload, source: "test", ts: 0 } );
  h.unmount = () => renderer.unmount();
  return h;
}

function collapse( root: HTMLElement ): void {
  ( root.querySelector( ".section-header" ) as HTMLElement ).click();
  assert.equal( root.getAttribute( "data-collapsed" ), "true", "precondition: the header click collapsed the section" );
}

test( "an arriving prompt reveals the section, un-collapses it and scrolls it into view smooth/start", () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const h = setup();
    collapse( h.root );
    h.items.set( "a1", makeItem( "a1" ) );
    h.emit( { changeKind: "added", id_hash: "a1" } );

    assert.equal( h.reveals, 1, "the toolbar reveal (un-hide, save, re-light) was not asked for" );
    assert.equal( h.root.getAttribute( "data-collapsed" ), "false", "a collapsed section stayed collapsed with a prompt waiting in it" );
    assert.equal( h.root.querySelector( ".section-header .toggle-button" )!.textContent, "▼" );
    assert.deepEqual( h.scrolls, [ { behavior: "smooth", block: "start" } ] );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    h.unmount();
  } finally {
    mock.timers.reset();
  }
} );

test( "a prompt arriving behind an active card reveals the section but does not scroll again", () => {
  const h = setup();
  h.items.set( "a1", makeItem( "a1" ) );
  h.items.set( "a2", makeItem( "a2" ) );
  h.emit( { changeKind: "added", id_hash: "a2" } );
  assert.equal( h.reveals, 1 );
  assert.equal( h.scrolls.length, 0, "a queued arrival must not yank the page; legacy scrolls when a card takes the slot" );
  h.unmount();
} );

test( "a queued card promoted to the active slot scrolls, without re-revealing", () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const h = setup();
    h.items.set( "a2", makeItem( "a2" ) );
    h.emit( { changeKind: "activated", id_hash: "a2" } );
    assert.equal( h.reveals, 0 );
    assert.equal( h.scrolls.length, 1 );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    h.unmount();
  } finally {
    mock.timers.reset();
  }
} );

test( "an arrival on an expanded section leaves it expanded", () => {
  const h = setup();
  h.items.set( "a1", makeItem( "a1" ) );
  h.emit( { changeKind: "added", id_hash: "a1" } );
  assert.notEqual( h.root.getAttribute( "data-collapsed" ), "true" );
  h.unmount();
} );

test( "other change kinds neither reveal nor scroll", () => {
  const h = setup();
  h.items.set( "a1", makeItem( "a1" ) );
  for ( const changeKind of [ "responded", "expired", "cancelled", "failed" ] as const ) {
    h.emit( { changeKind, id_hash: "a1" } );
  }
  h.emit( { changeKind: "tick", id_hash: "a1", countdownMs: 1000 } );
  assert.equal( h.reveals, 0 );
  assert.equal( h.scrolls.length, 0 );
  h.unmount();
} );

test( "without a revealSection option an arrival still un-collapses and scrolls", () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const h = setup( false );
    collapse( h.root );
    h.items.set( "a1", makeItem( "a1" ) );
    h.emit( { changeKind: "added", id_hash: "a1" } );
    assert.equal( h.root.getAttribute( "data-collapsed" ), "false" );
    assert.equal( h.scrolls.length, 1 );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    h.unmount();
  } finally {
    mock.timers.reset();
  }
} );
