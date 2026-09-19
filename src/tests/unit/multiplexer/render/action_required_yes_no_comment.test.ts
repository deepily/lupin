// Parity A-2 #2j (row 2ebf322f) — the yes_no comment row, and the card 🎤 it introduces.
//
// Legacy:
//   - renderActionRequiredNotification, the yes_no block (notifications.js:23254-23265): a hint,
//     "Press C to add comment" — or "You may comment on your answer here if you wish" when the
//     asker sets display_qualifier_widget, which also opens the row — over an expandable row with
//     a 🎤 and a 300-character input, placeholder "Qualify your answer..."
//   - its wiring (:23375-23396): the hint toggles the row (toggleYesNoComment :25978-25991, which
//     focuses the input on opening); the mic records into the input (context `yn-comment-<id>`,
//     startYesNoCommentVoiceInput); Enter in the input blurs it instead of submitting
//   - submitYesNoWithComment (:26000-26009): a non-blank comment rides as
//     "<answer> [comment: <trimmed>]"
//   - recordingManager (:3752+): click to record, click again to stop, text inserted at the caret
//     (_insertTranscriptionText :3653) and an `input` event fired; error or cancel resets the mic
// Guard: every test reads a behaviour the multiplexer lacked at aac96acd.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_yes_no_comment.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderActionRequiredInteractive,
  withComment,
  YES_NO_COMMENT_HINT,
  YES_NO_COMMENT_HINT_QUALIFIER,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import { createActionRequiredMic, type ActionRequiredRecorderLike } from "../../../../lupin_app/static/js/multiplexer/render/actionRequiredMic";
import { createActionRequiredRenderer, type ActionRequiredStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { createActionRequiredStore } from "../../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { recordingManager, type RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";
import type { ActionRequiredItem, ActionRequiredResponse } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function yesNo( over: Partial<ActionRequiredItem> = {} ): ActionRequiredItem {
  return {
    id_hash : "yn1", prompt: "Deploy now?", response_type: "yes_no", questions: [],
    expires_at: 1, timeout_seconds: 30, state: "pending", ...over,
  };
}

function render( item: ActionRequiredItem, onMic?: ( c: string, b: HTMLButtonElement, i: HTMLInputElement ) => void ) {
  const sent: ActionRequiredResponse[] = [];
  const el = renderActionRequiredInteractive( item, { onSubmit: ( r ) => sent.push( r ), ...( onMic ? { onMic } : {} ) } );
  document.body.replaceChildren( el );
  return {
    el, sent,
    hint      : el.querySelector<HTMLElement>( ".yes-no-comment-hint" )!,
    container : el.querySelector<HTMLElement>( ".yes-no-comment-container" )!,
    input     : el.querySelector<HTMLInputElement>( ".yes-no-comment-input" )!,
    mic       : el.querySelector<HTMLButtonElement>( ".yes-no-comment-mic" )!,
    btn       : ( a: string ) => el.querySelector<HTMLButtonElement>( `button[data-value="${ a }"]` )!,
  };
}

// ---------------------------------------------------------------------------
// The row
// ---------------------------------------------------------------------------

test( "the hint reads \"Press C to add comment\" and the row starts closed", () => {
  const c = render( yesNo() );
  assert.equal( c.hint.textContent, YES_NO_COMMENT_HINT );
  assert.equal( YES_NO_COMMENT_HINT, "Press C to add comment" );
  assert.equal( c.container.classList.contains( "expanded" ), false );
} );

test( "clicking the hint opens the row and focuses the input; clicking again closes it", () => {
  const c = render( yesNo() );
  c.hint.click();
  assert.equal( c.container.classList.contains( "expanded" ), true );
  assert.equal( document.activeElement, c.input );
  c.input.blur();
  c.hint.click();
  assert.equal( c.container.classList.contains( "expanded" ), false );
  assert.notEqual( document.activeElement, c.input, "closing does not focus" );
} );

test( "display_qualifier_widget swaps the hint's wording and opens the row", () => {
  const c = render( yesNo( { display_qualifier_widget: true } ) );
  assert.equal( c.hint.textContent, YES_NO_COMMENT_HINT_QUALIFIER );
  assert.equal( YES_NO_COMMENT_HINT_QUALIFIER, "You may comment on your answer here if you wish" );
  assert.equal( c.container.classList.contains( "expanded" ), true );
} );

test( "the input takes 300 characters with legacy's placeholder", () => {
  const c = render( yesNo() );
  assert.equal( c.input.maxLength, 300 );
  assert.equal( c.input.placeholder, "Qualify your answer..." );
} );

test( "a comment rides with the answer as \"<answer> [comment: <trimmed>]\", for Neither too", () => {
  for ( const answer of [ "yes", "no", "neither" ] ) {
    const c = render( yesNo() );
    c.input.value = "  only after the backup  ";
    c.btn( answer ).click();
    assert.deepEqual( c.sent, [ `${ answer } [comment: only after the backup]` ] );
  }
} );

test( "a blank comment sends the bare answer", () => {
  const c = render( yesNo() );
  c.input.value = "   ";
  c.btn( "yes" ).click();
  assert.deepEqual( c.sent, [ "yes" ] );
  assert.equal( withComment( "no", "" ), "no" );
} );

test( "Enter in the comment leaves the field instead of submitting", () => {
  const c = render( yesNo( { display_qualifier_widget: true } ) );
  c.input.focus();
  const enter = new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } );
  c.input.dispatchEvent( enter );
  assert.equal( enter.defaultPrevented, true );
  assert.notEqual( document.activeElement, c.input );
  const other = new KeyboardEvent( "keydown", { key: "a", cancelable: true } );
  c.input.dispatchEvent( other );
  assert.equal( other.defaultPrevented, false );
  assert.deepEqual( c.sent, [] );
} );

test( "the 🎤 hands its context, itself and the comment input to onMic; with no onMic it is inert", () => {
  const calls: Array<[ string, HTMLButtonElement, HTMLInputElement ]> = [];
  const c = render( yesNo(), ( ctx, b, i ) => calls.push( [ ctx, b, i ] ) );
  assert.equal( c.mic.textContent, "🎤" );
  assert.equal( c.mic.title, "Record voice comment" );
  c.mic.click();
  assert.equal( calls.length, 1 );
  assert.equal( calls[ 0 ]![ 0 ], "yn-comment-yn1" );
  assert.equal( calls[ 0 ]![ 1 ], c.mic );
  assert.equal( calls[ 0 ]![ 2 ], c.input );
  render( yesNo() ).mic.click();   // no throw
} );

// ---------------------------------------------------------------------------
// The store keeps the asker's flag
// ---------------------------------------------------------------------------

test( "the store carries display_qualifier_widget from the frame only when it is true", () => {
  const bus = createEventBusForTesting();
  const ar  = createActionRequiredStore( { bus, api: { post: async <T>() => ( {} ) as T }, nowFn: () => 1,
    setIntervalFn: () => 1, clearIntervalFn: () => {}, setTimeoutFn: () => 1, clearTimeoutFn: () => {} } );
  const arrive = ( id: string, flag?: boolean ) => bus.emit( { type: "notification_queue_update", source: "t", ts: 0, payload: { notification: {
    id_hash: id, message: "?", response_requested: true, response_type: "yes_no", ...( flag === undefined ? {} : { display_qualifier_widget: flag } ) } } } );
  arrive( "q1", true );
  arrive( "q2", false );
  arrive( "q3" );
  assert.equal( ar.getById( "q1" )!.display_qualifier_widget, true );
  assert.equal( "display_qualifier_widget" in ar.getById( "q2" )!, false );
  assert.equal( "display_qualifier_widget" in ar.getById( "q3" )!, false );
} );

// ---------------------------------------------------------------------------
// The mic handler (legacy recordingManager)
// ---------------------------------------------------------------------------

function fakeRecorder() {
  const starts: RecordingManagerStartOptions[] = [];
  const stops : string[] = [];
  let active: string | null = null;
  const recorder: ActionRequiredRecorderLike = {
    startRecording : async ( o ) => { starts.push( o ); active = o.contextId; },
    stopRecording  : async ( id ) => { stops.push( id ); active = null; },
    getActiveContextId : () => active,
  };
  return { recorder, starts, stops };
}

function micParts() {
  const button = document.createElement( "button" );
  const input  = document.createElement( "input" );
  document.body.replaceChildren( button, input );
  return { button, input };
}

test( "mic: a click records with the token; the words go in at the caret and fire input", () => {
  const { recorder, starts } = fakeRecorder();
  const { button, input } = micParts();
  const mic = createActionRequiredMic( recorder, () => "tok-1" );
  input.value = "ship it";
  input.focus();
  input.setSelectionRange( 5, 5 );
  let inputs = 0;
  input.addEventListener( "input", () => { inputs += 1; } );
  mic( "yn-comment-a", button, input );
  assert.equal( starts[ 0 ]!.contextId, "yn-comment-a" );
  assert.equal( starts[ 0 ]!.authToken, "tok-1" );
  assert.equal( button.classList.contains( "recording" ), true );
  starts[ 0 ]!.onComplete!( "now ", new Blob() );
  assert.equal( input.value, "ship now it" );
  assert.equal( input.selectionStart, 9 );
  assert.equal( inputs, 1 );
  assert.equal( button.classList.contains( "recording" ), false );
} );

test( "mic: with no caret the words are appended", () => {
  const { recorder, starts } = fakeRecorder();
  const { button, input } = micParts();
  input.value = "ship";
  Object.defineProperty( input, "selectionStart", { value: null } );
  createActionRequiredMic( recorder, () => null )( "c", button, input );
  starts[ 0 ]!.onComplete!( " now", new Blob() );
  assert.equal( input.value, "ship now" );
} );

test( "mic: a second click on the same context stops it; a click while transcribing does nothing", () => {
  const { recorder, starts, stops } = fakeRecorder();
  const { button, input } = micParts();
  const mic = createActionRequiredMic( recorder, () => null );
  mic( "c", button, input );
  mic( "c", button, input );
  assert.deepEqual( stops, [ "c" ] );
  assert.equal( button.classList.contains( "processing" ), true );
  mic( "c", button, input );
  assert.equal( starts.length, 1 );
  assert.equal( stops.length, 1 );
} );

// Legacy, every card mic (startYesNoCommentVoiceInput :26028-26032, startMultipleChoiceVoiceInput
// :26052-26056, the task-reason mic :13354-13357): `if ( isRecording() ) stopRecording(); else if
// ( !isProcessing() ) startRecording(...)`. A click while ANY context records stops that one — it
// uploads, so its own field gets the words — and starts nothing. Review finding 2 on row 2ebf322f.
test( "mic: a click while another context records stops that one and starts nothing", () => {
  const { recorder, starts, stops } = fakeRecorder();
  const { button, input } = micParts();
  void recorder.startRecording( { contextId: "task-reason-t1" } );
  createActionRequiredMic( recorder, () => null )( "yn-comment-a", button, input );
  assert.deepEqual( stops, [ "task-reason-t1" ] );
  assert.equal( starts.length, 1, "no recording started for the card" );
  assert.equal( button.className, "", "the card mic stays idle" );
} );

test( "mic, real recordingManager: the other pane's recording is stopped, never cancelled", async () => {
  ( globalThis.navigator as unknown as { mediaDevices: unknown } ).mediaDevices = {
    getUserMedia: () => new Promise( () => {} ),
  };
  let cancelled = 0;
  void recordingManager.startRecording( { contextId: "task-reason-t1", onCancel: () => { cancelled += 1; } } );
  const { button, input } = micParts();
  createActionRequiredMic( recordingManager, () => null )( "yn-comment-a", button, input );
  await new Promise( ( res ) => setTimeout( res, 0 ) );
  assert.equal( cancelled, 0, "the dictation in the other pane is not thrown away" );
  assert.equal( recordingManager.getActiveContextId(), null, "it was stopped, and nothing new started" );
} );

test( "mic: an error or a cancel returns the button to idle", () => {
  for ( const end of [ "onError", "onCancel" ] as const ) {
    const { recorder, starts } = fakeRecorder();
    const { button, input } = micParts();
    createActionRequiredMic( recorder, () => null )( "c", button, input );
    const cb = starts[ 0 ]![ end ] as ( e?: unknown ) => void;
    cb( { type: "x", message: "y", originalError: null } );
    assert.equal( button.className, "", end );
  }
} );

// ---------------------------------------------------------------------------
// The mounted card
// ---------------------------------------------------------------------------

test( "mounted: dictating into the comment and pressing Yes answers with the comment", async () => {
  const { recorder, starts } = fakeRecorder();
  const item = yesNo();
  const answers: ActionRequiredResponse[] = [];
  const store: ActionRequiredStoreLike = {
    list: () => [ item ], getById: () => item,
    respondAndAwait: async ( _id, r ) => { answers.push( r ); },
    togglePause: () => false, recordStep: () => {},
  };
  const root = document.createElement( "div" );
  document.body.replaceChildren( root );
  const r = createActionRequiredRenderer( { eventBus: createEventBusForTesting(), stores: { actionRequired: store }, recorder, getAuthToken: () => "tok-9" } );
  r.mount( root );
  root.querySelector<HTMLElement>( ".yes-no-comment-hint" )!.click();
  root.querySelector<HTMLButtonElement>( ".yes-no-comment-mic" )!.click();
  assert.equal( starts[ 0 ]!.authToken, "tok-9" );
  starts[ 0 ]!.onComplete!( "after lunch", new Blob() );
  root.querySelector<HTMLButtonElement>( 'button[data-value="yes"]' )!.click();
  await new Promise( ( res ) => setTimeout( res, 0 ) );
  assert.deepEqual( answers, [ "yes [comment: after lunch]" ] );
  r.unmount();
} );

test( "mounted with no token source: the recording goes up with a null token", () => {
  const { recorder, starts } = fakeRecorder();
  const item = yesNo();
  const store: ActionRequiredStoreLike = {
    list: () => [ item ], getById: () => item, respondAndAwait: async () => {}, togglePause: () => false, recordStep: () => {},
  };
  const root = document.createElement( "div" );
  document.body.replaceChildren( root );
  const r = createActionRequiredRenderer( { eventBus: createEventBusForTesting(), stores: { actionRequired: store }, recorder } );
  r.mount( root );
  root.querySelector<HTMLButtonElement>( ".yes-no-comment-mic" )!.click();
  assert.equal( starts[ 0 ]!.authToken, null );
  r.unmount();
} );
