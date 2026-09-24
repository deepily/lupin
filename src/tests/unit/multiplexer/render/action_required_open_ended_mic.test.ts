// Parity A-2 #2k (row 2ebf322f) — the open_ended card: 🎤 first, and the default as the value.
//
// Legacy: renderActionRequiredNotification, open_ended block (notifications.js:23323-23342),
// and its wiring (:23454-23512):
//   - voice first: the 🎤 ("Press Enter or Space to record (30s max, ESC to cancel)") comes
//     before the input, takes focus when the card renders (:23482), and Enter or Space on
//     it records (startVoiceInput, context `response-input-<id>`)
//   - the input carries response_default as its VALUE, placeholder "Type your response..."
//   - validateInput: Submit is disabled until the input has text; typing clears `.invalid`
//   - Submit, or Enter in the input, sends the trimmed text
// Guard: each test reads a behaviour the multiplexer lacked at cc811ab9.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_open_ended_mic.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderActionRequiredInteractive } from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import { createActionRequiredRenderer, type ActionRequiredStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type { ActionRequiredRecorderLike } from "../../../../lupin_app/static/js/multiplexer/render/actionRequiredMic";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";
import type { ActionRequiredItem, ActionRequiredResponse } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function openEnded( over: Partial<ActionRequiredItem> = {} ): ActionRequiredItem {
  return {
    id_hash : "oe1", prompt: "Name the service?", response_type: "open_ended", questions: [],
    expires_at: 1, timeout_seconds: 30, state: "pending", ...over,
  };
}

function render( item: ActionRequiredItem, onMic?: ( c: string, b: HTMLButtonElement, i: HTMLInputElement ) => void ) {
  const sent: ActionRequiredResponse[] = [];
  const el = renderActionRequiredInteractive( item, { onSubmit: ( r ) => sent.push( r ), ...( onMic ? { onMic } : {} ) } );
  document.body.replaceChildren( el );
  const input  = el.querySelector<HTMLInputElement>( ".action-required-input" )!;
  const type   = ( v: string ) => { input.value = v; input.dispatchEvent( new Event( "input" ) ); };
  return {
    el, sent, input, type,
    mic    : el.querySelector<HTMLButtonElement>( ".response-mic" )!,
    submit : el.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!,
  };
}

test( "voice first: the 🎤 comes before the input, with legacy's title", () => {
  const c = render( openEnded() );
  const order = Array.from( c.el.querySelector( ".action-required-controls" )!.children, ( e ) => e.className.split( " " )[ 0 ] );
  assert.deepEqual( order, [ "action-required-mic", "action-required-input", "action-required-btn" ] );
  assert.equal( c.mic.textContent, "🎤" );
  assert.equal( c.mic.title, "Press Enter or Space to record (30s max, ESC to cancel)" );
} );

test( "the default is the input's value, and the placeholder is legacy's", () => {
  const c = render( openEnded( { default: "billing-api" } ) );
  assert.equal( c.input.value, "billing-api" );
  assert.equal( c.input.placeholder, "Type your response..." );
  assert.equal( render( openEnded() ).input.value, "" );
} );

test( "Submit waits for text: disabled when empty or blank, enabled once typed, enabled at once with a default", () => {
  const c = render( openEnded() );
  assert.equal( c.submit.disabled, true );
  c.type( "   " );
  assert.equal( c.submit.disabled, true );
  c.type( "x" );
  assert.equal( c.submit.disabled, false );
  assert.equal( render( openEnded( { default: "d" } ) ).submit.disabled, false );
} );

test( "Submit and Enter send the trimmed text; Enter on a blank input sends nothing", () => {
  const c = render( openEnded() );
  c.input.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } ) );
  assert.deepEqual( c.sent, [] );
  c.type( "  billing-api  " );
  c.submit.click();
  c.input.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } ) );
  assert.deepEqual( c.sent, [ "billing-api", "billing-api" ] );
} );

test( "typing clears an .invalid mark", () => {
  const c = render( openEnded() );
  c.input.classList.add( "invalid" );
  c.type( "a" );
  assert.equal( c.input.classList.contains( "invalid" ), false );
} );

test( "the 🎤 records into the input on a click, on Enter and on Space — not on other keys", () => {
  const calls: Array<[ string, HTMLButtonElement, HTMLInputElement ]> = [];
  const c = render( openEnded(), ( ctx, b, i ) => calls.push( [ ctx, b, i ] ) );
  c.mic.click();
  for ( const key of [ "Enter", " ", "a" ] ) {
    const ev = new KeyboardEvent( "keydown", { key, cancelable: true } );
    c.mic.dispatchEvent( ev );
    assert.equal( ev.defaultPrevented, key !== "a", `key ${ JSON.stringify( key ) }` );
  }
  assert.equal( calls.length, 3 );
  assert.equal( calls[ 0 ]?.[ 0 ], "response-input-oe1" );
  assert.ok( calls[ 0 ]?.[ 1 ] === c.mic && calls[ 0 ]?.[ 2 ] === c.input, "the mic and the input are handed over" );
  render( openEnded() ).mic.click();   // no onMic — inert
} );

// ---------------------------------------------------------------------------
// The mounted card
// ---------------------------------------------------------------------------

function mounted( item: ActionRequiredItem ) {
  const starts : RecordingManagerStartOptions[] = [];
  const answers: ActionRequiredResponse[] = [];
  let current = item;
  const recorder: ActionRequiredRecorderLike = {
    startRecording : async ( o ) => { starts.push( o ); },
    stopRecording  : async () => {},
    getActiveContextId : () => null,
  };
  const store: ActionRequiredStoreLike = {
    list: () => [ current ], getById: () => current,
    respondAndAwait: async ( _id, r ) => { answers.push( r ); },
    togglePause: () => false, recordStep: () => {},
  };
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.replaceChildren( root );
  const r = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store }, recorder } );
  r.mount( root );
  const change = ( next: ActionRequiredItem, changeKind: "failed" | "activated" ) => {
    current = next;
    bus.emit( { type: "store_action_required_changed", payload: { changeKind, id_hash: next.id_hash }, source: "t", ts: 0 } );
  };
  return { root, r, starts, answers, change };
}

test( "mounted: a card that takes the slot focuses its 🎤; a rebuild of the same card does not", () => {
  const m = mounted( openEnded() );
  const mic = () => m.root.querySelector<HTMLButtonElement>( ".response-mic" )!;
  assert.ok( document.activeElement === mic(), "the 🎤 has focus" );
  mic().blur();
  m.change( openEnded( { state: "failed" } ), "failed" );
  assert.ok( document.activeElement !== mic(), "the 🎤 did not take focus again" );
  m.change( openEnded( { id_hash: "oe2" } ), "activated" );
  assert.ok( document.activeElement === mic(), "the 🎤 has focus" );
  m.r.unmount();
} );

test( "mounted: dictation fills the input, enables Submit, and Submit answers with it", async () => {
  const m = mounted( openEnded() );
  m.root.querySelector<HTMLButtonElement>( ".response-mic" )!.click();
  m.starts[ 0 ]!.onComplete!( "billing-api", new Blob() );
  const submit = m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!;
  assert.equal( submit.disabled, false );
  submit.click();
  await new Promise( ( res ) => setTimeout( res, 0 ) );
  assert.deepEqual( m.answers, [ "billing-api" ] );
  m.r.unmount();
} );
