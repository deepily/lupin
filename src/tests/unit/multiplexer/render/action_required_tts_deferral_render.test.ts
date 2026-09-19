// Parity A-2 #2d (row dcaeb0fc) — how the section draws a card that arrived while TTS played.
// Legacy renders it minimized at position 1 with nothing in the active slot
// (addActionRequiredNotification, notifications.js:21782-21784), and the page does not
// move until it takes the slot.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_tts_deferral_render.test.ts

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

function card( id: string, waiting: boolean ): ActionRequiredItem {
  return {
    id_hash         : id,
    prompt          : `Proceed ${ id }?`,
    response_type   : "yes_no",
    questions       : [],
    expires_at      : waiting ? null : Date.now() + 30_000,
    timeout_seconds : 30,
    state           : "pending",
  };
}

function setup() {
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
  const scrolls: unknown[] = [];
  root.getBoundingClientRect = () => ( { top: window.innerHeight + 50, bottom: window.innerHeight + 300, left: 0, right: 0, width: 0, height: 250, x: 0, y: 0, toJSON: () => ( {} ) } ) as DOMRect;
  root.scrollIntoView        = ( arg?: ScrollIntoViewOptions | boolean ) => { scrolls.push( arg ); };
  const renderer = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store } } );
  renderer.mount( root );
  const emit = ( payload: StoreActionRequiredChangedPayload ) =>
    bus.emit( { type: "store_action_required_changed", payload, source: "test", ts: 0 } );
  const slotIds  = () => Array.from( root.querySelectorAll<HTMLElement>( ".action-required-active-slot > [data-id-hash]" ) ).map( ( e ) => e.dataset.idHash );
  const queueIds = () => Array.from( root.querySelectorAll<HTMLElement>( ".action-required-pending-queue [data-testid='multiplexer-action-required-queued']" ) )
    .map( ( e ) => `${ e.querySelector( ".action-required-minimized-position" )!.textContent }:${ e.dataset.idHash }` );
  return { items, root, scrolls, emit, slotIds, queueIds, unmount: () => renderer.unmount() };
}

test( "a card waiting for TTS draws as queued row #1 with the active slot empty", () => {
  const h = setup();
  h.items.set( "a1", card( "a1", true ) );
  h.items.set( "a2", card( "a2", true ) );
  h.emit( { changeKind: "added", id_hash: "a2" } );
  assert.deepEqual( h.slotIds(), [] );
  assert.deepEqual( h.queueIds(), [ "#1:a1", "#2:a2" ] );
  const controls = h.root.querySelectorAll( ".action-required-active-slot :is(button, input), .action-required-pending-queue :is(button, input)" ).length;
  assert.equal( controls, 0, "a waiting card cannot be answered" );
  h.unmount();
} );

test( "when it activates it moves into the slot and leaves the queue", () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const h = setup();
    h.items.set( "a1", card( "a1", true ) );
    h.items.set( "a2", card( "a2", true ) );
    h.emit( { changeKind: "added", id_hash: "a1" } );
    h.items.set( "a1", card( "a1", false ) );
    h.emit( { changeKind: "activated", id_hash: "a1" } );
    assert.deepEqual( h.slotIds(), [ "a1" ] );
    assert.deepEqual( h.queueIds(), [ "#1:a2" ] );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    h.unmount();
  } finally {
    mock.timers.reset();
  }
} );

test( "a waiting arrival does not scroll the page; its activation does", () => {
  mock.timers.enable( { apis: [ "setTimeout" ] } );
  try {
    const h = setup();
    h.items.set( "a1", card( "a1", true ) );
    h.emit( { changeKind: "added", id_hash: "a1" } );
    assert.equal( h.scrolls.length, 0, "legacy scrolls when the card takes the slot, not before" );
    h.items.set( "a1", card( "a1", false ) );
    h.emit( { changeKind: "activated", id_hash: "a1" } );
    assert.equal( h.scrolls.length, 1 );
    mock.timers.tick( SCROLL_REVEAL_SETTLE_MS );
    h.unmount();
  } finally {
    mock.timers.reset();
  }
} );
