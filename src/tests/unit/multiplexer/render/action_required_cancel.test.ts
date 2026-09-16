// Guard — parity A-2 #2g (Phase 2 A3 R6): the Action Required card's ✕ cancel.
//
// Legacy (notifications.js `cancelActionRequired`, and the `.action-required-cancel-btn` built
// in `renderActionRequiredNotification`): a ✕ at the head of every card header, titled
// "Cancel and use default (Esc)", which answers the prompt with its `response_default` through
// the ordinary submit path. With no default it falls back by type: yes_no → "no";
// multiple_choice / open_ended_batch → '{"cancelled":true,"answers":{}}'; anything else →
// "[cancelled]". The Escape key is A-2 #2h.
//
// 🔴 AT b00968ee THE CARD HAD NO CANCEL: an operator who wanted the default had to wait out the
// timer, and the expiry is local-only, so no answer was ever sent from this client.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  cancelResponseFor,
  createActionRequiredStore,
} from "../../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import {
  createActionRequiredRenderer,
  AR_CANCEL_TITLE,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type { ActionRequiredItem } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function item( over: Partial<ActionRequiredItem> ): ActionRequiredItem {
  return { id_hash: "a1", prompt: "p", response_type: "open_ended", questions: [], expires_at: 1,
           timeout_seconds: 30, state: "pending", ...over };
}

// ---------------------------------------------------------------------------
// The value a cancel sends
// ---------------------------------------------------------------------------

test( "cancel value: the prompt's own default wins, even an empty one", () => {
  assert.equal( cancelResponseFor( item( { response_type: "yes_no", default: "yes" } ) ), "yes" );
  assert.equal( cancelResponseFor( item( { response_type: "open_ended", default: "" } ) ), "",
    "legacy checks for undefined/null, so an empty default is still THE default" );
} );

test( "cancel value: with no default, each type falls back as legacy does", () => {
  assert.equal( cancelResponseFor( item( { response_type: "yes_no" } ) ), "no" );
  assert.equal( cancelResponseFor( item( { response_type: "multiple_choice" } ) ), '{"cancelled":true,"answers":{}}' );
  assert.equal( cancelResponseFor( item( { response_type: "open_ended_batch" } ) ), '{"cancelled":true,"answers":{}}' );
  assert.equal( cancelResponseFor( item( { response_type: "open_ended" } ) ), "[cancelled]" );
} );

// ---------------------------------------------------------------------------
// The button, over the real store and a recording api
// ---------------------------------------------------------------------------

function mounted( notification: Record<string, unknown>, reject = false ) {
  const bus   = createEventBusForTesting();
  const posts: Array<{ path: string; body: Record<string, unknown> }> = [];
  const store = createActionRequiredStore( {
    bus,
    api: { post: async ( path, body ) => {
      posts.push( { path, body: body as Record<string, unknown> } );
      if ( reject ) throw new Error( "refused" );
      return {} as never;
    } },
    setIntervalFn : () => 0, clearIntervalFn : () => {},
    setTimeoutFn  : () => 0, clearTimeoutFn  : () => {},
    nowFn         : () => 1_700_000_000_000,
  } );
  const renderer = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store } } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  renderer.mount( root );
  bus.emit( { type: "notification_queue_update", source: "test", ts: 0,
              payload: { notification: { id_hash: "a1", message: "Proceed?", response_requested: true,
                                         timeout_seconds: 60, ...notification } } } as never );
  return { root, store, posts, renderer };
}

const flush = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

function cancelButton( root: ParentNode ): HTMLButtonElement {
  const btn = root.querySelector<HTMLButtonElement>( ".action-required-header .action-required-cancel-btn" );
  assert.ok( btn, "the card header carries no ✕" );
  return btn;
}

test( "🔴 the ✕ leads the card header, titled as legacy's", () => {
  const m = mounted( { response_type: "yes_no" } );
  const btn = cancelButton( m.root );
  assert.equal( btn.textContent, "✕" );
  assert.equal( btn.title, AR_CANCEL_TITLE );
  assert.equal( btn.type, "button" );
  assert.equal( btn.parentElement!.firstElementChild === btn, true, "the ✕ must open the header, as legacy's does" );
  m.renderer.unmount();
} );

test( "🔴 clicking ✕ answers with the prompt's default through the ordinary answer path", async () => {
  const m = mounted( { response_type: "yes_no", response_default: "yes" } );
  cancelButton( m.root ).click();
  await flush();
  assert.equal( m.posts.length, 1, "the ✕ sent no answer" );
  assert.equal( m.posts[ 0 ]!.body.response_value, "yes" );
  assert.equal( m.store.getById( "a1" )!.state, "responded" );
  m.renderer.unmount();
} );

test( "clicking ✕ on a batch prompt with no default sends legacy's cancelled structure verbatim", async () => {
  const m = mounted( { response_type: "open_ended_batch" } );
  cancelButton( m.root ).click();
  await flush();
  assert.equal( m.posts[ 0 ]!.body.response_value, '{"cancelled":true,"answers":{}}' );
  m.renderer.unmount();
} );

test( "a refused cancel leaves the card retryable, with its ✕ still there", async () => {
  const m = mounted( { response_type: "open_ended" }, true );
  cancelButton( m.root ).click();
  await flush();
  assert.equal( m.store.getById( "a1" )!.state, "failed" );
  assert.ok( m.root.querySelector( ".action-required-error-stripe" ) );
  cancelButton( m.root );
  m.renderer.unmount();
} );
