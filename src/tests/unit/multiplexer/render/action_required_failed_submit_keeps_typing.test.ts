// Row 2ebf322f, review finding on #2j/#2k (Mr. Radio, 2026-09-18) — a failed submit keeps
// what the operator typed.
//
// Legacy submitResponse (notifications.js:24369+): the card is never rebuilt on a failure; its
// catch re-enables the controls in place (:24481-24488), so the typed text is still there to
// retry. The multiplexer rebuilds the card for "submitting" and again for "failed". Without a
// carry-over, the comment was lost and an open_ended retry sent the DEFAULT (which #2k puts in
// the box) instead of the typed answer.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_failed_submit_keeps_typing.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createActionRequiredRenderer, type ActionRequiredStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { ActionRequiredChangeKind, ActionRequiredItem, ActionRequiredResponse } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function card( over: Partial<ActionRequiredItem> ): ActionRequiredItem {
  return { id_hash: "c1", prompt: "?", response_type: "yes_no", questions: [], expires_at: 1, timeout_seconds: 30, state: "pending", ...over };
}

// Drive the real submitting → failed sequence the store emits around a rejected POST.
function mount( first: ActionRequiredItem ) {
  let items = [ first ];
  const answers: ActionRequiredResponse[] = [];
  const bus = createEventBusForTesting();
  const store: ActionRequiredStoreLike = {
    list: () => items, getById: ( id ) => items.find( ( i ) => i.id_hash === id ),
    respondAndAwait: async ( _id, r ) => { answers.push( r ); },
    togglePause: () => false, recordStep: () => {},
  };
  const root = document.createElement( "div" );
  document.body.replaceChildren( root );
  const r = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store }, recorder: {
    startRecording: async () => {}, stopRecording: async () => {}, getActiveContextId: () => null } } );
  r.mount( root );
  const set = ( next: ActionRequiredItem[], changeKind: ActionRequiredChangeKind, id: string ) => {
    items = next;
    bus.emit( { type: "store_action_required_changed", payload: { changeKind, id_hash: id }, source: "t", ts: 0 } );
  };
  const failRoundTrip = () => {
    set( [ { ...items[ 0 ]!, state: "submitting" } ], "responded-pending", items[ 0 ]!.id_hash );
    set( [ { ...items[ 0 ]!, state: "failed" } ], "failed", items[ 0 ]!.id_hash );
  };
  return { root, r, answers, set, failRoundTrip };
}

const type = ( input: HTMLInputElement, v: string ) => { input.value = v; input.dispatchEvent( new Event( "input" ) ); };
const flush = () => new Promise( ( res ) => setTimeout( res, 0 ) );

test( "yes_no: the comment survives a failed submit, its row still open, and the retry carries it", async () => {
  const m = mount( card( {} ) );
  m.root.querySelector<HTMLElement>( ".yes-no-comment-hint" )!.click();
  type( m.root.querySelector<HTMLInputElement>( ".yes-no-comment-input" )!, "after the backup" );
  m.failRoundTrip();
  const input = m.root.querySelector<HTMLInputElement>( ".yes-no-comment-input" )!;
  assert.equal( input.value, "after the backup" );
  assert.equal( m.root.querySelector( ".yes-no-comment-container" )!.classList.contains( "expanded" ), true );
  m.root.querySelector<HTMLButtonElement>( 'button[data-value="yes"]' )!.click();
  await flush();
  assert.deepEqual( m.answers, [ "yes [comment: after the backup]" ] );
  m.r.unmount();
} );

test( "open_ended: a retry after a failed submit sends the typed answer, not the default", async () => {
  const m = mount( card( { response_type: "open_ended", default: "the-default" } ) );
  type( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!, "billing-api" );
  m.failRoundTrip();
  assert.equal( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!.value, "billing-api" );
  m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!.click();
  await flush();
  assert.deepEqual( m.answers, [ "billing-api" ] );
  m.r.unmount();
} );

test( "a blank field restores blank: a cleared default stays cleared and keeps Submit disabled", () => {
  const m = mount( card( { response_type: "open_ended", default: "the-default" } ) );
  type( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!, "" );
  m.failRoundTrip();
  assert.equal( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!.value, "" );
  assert.equal( m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!.disabled, true );
  m.r.unmount();
} );

test( "a blank comment does not open the row", () => {
  const m = mount( card( {} ) );
  m.failRoundTrip();
  assert.equal( m.root.querySelector( ".yes-no-comment-container" )!.classList.contains( "expanded" ), false );
  m.r.unmount();
} );

test( "typed text belongs to its card: once the card leaves, the same id arriving again starts empty", () => {
  const m = mount( card( { response_type: "open_ended" } ) );
  type( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!, "draft" );
  m.failRoundTrip();   // the draft is now saved
  m.set( [ card( { id_hash: "other", response_type: "open_ended" } ) ], "removed", "c1" );
  m.set( [ card( { response_type: "open_ended" } ) ], "added", "c1" );
  assert.equal( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!.value, "" );
  m.set( [], "removed", "c1" );
  m.r.unmount();
} );

test( "a field with nothing saved under its key keeps its own value (never the text \"undefined\")", () => {
  const m = mount( card( {} ) );
  type( m.root.querySelector<HTMLInputElement>( ".yes-no-comment-input" )!, "saved as comment" );
  m.set( [ card( { state: "submitting" } ) ], "responded-pending", "c1" );
  m.set( [ card( { response_type: "open_ended", default: "own-default", state: "failed" } ) ], "failed", "c1" );
  assert.equal( m.root.querySelector<HTMLInputElement>( ".action-required-input" )!.value, "own-default" );
  m.r.unmount();
} );

// Krishna's review of b51dc7ea: open_ended_batch had no draft keys, so its boxes reverted to their
// defaults on the failed rebuild and a retry sent those. Legacy keeps the same card (the batch render
// is at notifications.js:23288, the catch at :24471), so every typed box survives.
test( "open_ended_batch: a retry after a failed submit sends every typed answer, not the defaults", async () => {
  const m = mount( card( { response_type: "open_ended_batch", questions: [
    { header: "Env", question: "Which env?", defaultValue: "staging" },
    { header: "When", question: "When?", defaultValue: "now" },
  ] as ActionRequiredItem["questions"] } ) );
  const boxes = () => Array.from( m.root.querySelectorAll<HTMLInputElement>( ".action-required-batch-input" ) );
  type( boxes()[ 0 ]!, "prod" );
  type( boxes()[ 1 ]!, "after lunch" );
  m.failRoundTrip();
  assert.deepEqual( boxes().map( ( b ) => b.value ), [ "prod", "after lunch" ] );
  m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit-all" )!.click();
  await flush();
  assert.deepEqual( m.answers, [ { answers: { Env: "prod", When: "after lunch" } } ] );
  m.r.unmount();
} );
