// Parity A-2 #2l (row 2ebf322f) — the multiple_choice "Other" option, and its 🎤.
//
// Legacy:
//   - renderMultipleChoiceUI (notifications.js:23905-24025): every question ends with an "Other"
//     option, the same input type and name as the listed ones, value `__other__`, class
//     `mc-other-radio`; beside it a 🎤 titled "Press Enter or Space to record (30s max, ESC to
//     cancel)" and a text box, placeholder "Type or speak custom answer...". A saved answer that
//     is none of the labels comes back as Other plus its text (multi_select: joined with ", ")
//   - getCurrentQuestionAnswer (:24034-24075): a ticked Other answers with its trimmed text; only
//     Other ticked with no text is invalid
//   - attachMultipleChoiceEventHandlers (:24174-24242): focusing the text ticks Other; Enter in it
//     goes to the next question or submits; the 🎤 records on click, Enter or Space
//   - startMultipleChoiceVoiceInput (:26039-26064): context `mc-<id>`; recordingManager ticks
//     Other as the recording starts (autoSelectElement, :3791-3793); the transcription clears the
//     invalid mark
// Guard: every test reads a behaviour the multiplexer lacked at e06ebfc7.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_multiple_choice_other.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderActionRequiredInteractive,
  MC_OTHER_VALUE,
  MC_OTHER_PLACEHOLDER,
  OPEN_ENDED_MIC_TITLE,
  type ActionRequiredInteractiveHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import { createActionRequiredRenderer, type ActionRequiredStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";
import type { ActionRequiredChangeKind, ActionRequiredItem, ActionRequiredResponse, ActionRequiredStep } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const SINGLE = { header: "DB", question: "Which database?", multiSelect: false, options: [ { label: "PostgreSQL" }, { label: "MySQL" } ] };
const MULTI  = { header: "Features", question: "Which features?", multiSelect: true, options: [ { label: "Search" }, { label: "Export" } ] };

function mc( questions: Array<typeof SINGLE>, over: Partial<ActionRequiredItem> = {} ): ActionRequiredItem {
  return {
    id_hash: "mc1", prompt: "Pick", response_type: "multiple_choice", questions: questions as ActionRequiredItem["questions"],
    expires_at: 1, timeout_seconds: 30, state: "pending", ...over,
  };
}

function render( item: ActionRequiredItem, step?: ActionRequiredStep, withMic = true ) {
  const sent : ActionRequiredResponse[] = [];
  const mics : Array<[ string, HTMLButtonElement, HTMLInputElement ]> = [];
  const handlers: ActionRequiredInteractiveHandlers = {
    onSubmit : ( r ) => sent.push( r ),
    ...( withMic ? { onMic: ( c: string, b: HTMLButtonElement, i: HTMLInputElement ) => { mics.push( [ c, b, i ] ); } } : {} ),
  };
  const el = renderActionRequiredInteractive( item, handlers, step );
  document.body.replaceChildren( el );
  return {
    el, sent, mics,
    radio  : () => el.querySelector<HTMLInputElement>( ".mc-other-radio" )!,
    text   : () => el.querySelector<HTMLInputElement>( ".mc-other-input" )!,
    mic    : () => el.querySelector<HTMLButtonElement>( ".mc-other-mic" )!,
    block  : () => el.querySelector<HTMLElement>( ".action-required-question" )!,
    tick   : ( label: string ) => { el.querySelector<HTMLInputElement>( `input[value="${ label }"]` )!.checked = true; },
    click  : ( cls: string ) => el.querySelector<HTMLButtonElement>( `.${ cls }` )!.click(),
    indicator : () => el.querySelector( ".action-required-question-indicator" )!.textContent,
  };
}

const key = ( target: HTMLElement, k: string ) => {
  const e = new KeyboardEvent( "keydown", { key: k, cancelable: true, bubbles: true } );
  target.dispatchEvent( e );
  return e;
};

// ---------------------------------------------------------------------------
// The option
// ---------------------------------------------------------------------------

test( "every question ends with Other: same type and name as the listed options, 🎤 and text box beside it", () => {
  for ( const [ q, type ] of [ [ SINGLE, "radio" ], [ MULTI, "checkbox" ] ] as const ) {
    const c = render( mc( [ q ] ) );
    const inputs = Array.from( c.el.querySelectorAll<HTMLInputElement>( ".action-required-option-input" ) );
    assert.equal( inputs.length, 3, type );
    assert.ok( inputs[ 2 ] === c.radio(), "Other is last" );
    assert.equal( c.radio().type, type );
    assert.equal( c.radio().value, "__other__" );
    assert.equal( MC_OTHER_VALUE, "__other__" );
    assert.equal( c.radio().name, inputs[ 0 ]!.name );
    assert.equal( c.radio().closest( "label" )!.querySelector( ".action-required-option-text" )!.textContent, "Other" );
    assert.equal( c.mic().textContent, "🎤" );
    assert.equal( c.mic().title, OPEN_ENDED_MIC_TITLE );
    assert.equal( c.text().placeholder, "Type or speak custom answer..." );
    assert.equal( MC_OTHER_PLACEHOLDER, "Type or speak custom answer..." );
    assert.equal( c.text().dataset.draft, "other", "the renderer carries it across a failed submit" );
    assert.equal( c.radio().checked, false );
    assert.equal( c.text().value, "" );
  }
} );

// ---------------------------------------------------------------------------
// The answer
// ---------------------------------------------------------------------------

test( "single: Other ticked answers with its trimmed text", () => {
  const c = render( mc( [ SINGLE ] ) );
  c.radio().checked = true;
  c.text().value = "  Redis  ";
  c.click( "action-required-btn-submit" );
  assert.deepEqual( c.sent, [ { answers: { DB: "Redis" } } ] );
} );

test( "Other ticked with a blank text is invalid: nothing sent, Next does not move", () => {
  const one = render( mc( [ SINGLE ] ) );
  one.radio().checked = true;
  one.text().value = "   ";
  one.click( "action-required-btn-submit" );
  assert.deepEqual( one.sent, [] );
  assert.equal( one.block().classList.contains( "invalid" ), true );

  const two = render( mc( [ SINGLE, MULTI ] ) );
  two.radio().checked = true;
  two.click( "action-required-btn-next" );
  assert.equal( two.indicator(), "Question 1 of 2" );
  assert.equal( two.block().classList.contains( "invalid" ), true );
} );

test( "multi: listed ticks and Other's text answer together, in order", () => {
  const c = render( mc( [ MULTI ] ) );
  c.tick( "Export" );
  c.radio().checked = true;
  c.text().value = "Audit log";
  c.click( "action-required-btn-submit" );
  assert.deepEqual( c.sent, [ { answers: { Features: [ "Export", "Audit log" ] } } ] );
} );

test( "multi: a blank Other beside a listed tick is dropped, not sent as an empty answer", () => {
  const c = render( mc( [ MULTI ] ) );
  c.tick( "Search" );
  c.radio().checked = true;
  c.click( "action-required-btn-submit" );
  assert.deepEqual( c.sent, [ { answers: { Features: [ "Search" ] } } ] );
} );

test( "Other's text is not read unless Other is ticked", () => {
  const c = render( mc( [ SINGLE ] ) );
  c.tick( "MySQL" );
  c.text().value = "Redis";
  c.click( "action-required-btn-submit" );
  assert.deepEqual( c.sent, [ { answers: { DB: "MySQL" } } ] );
} );

test( "a saved answer that is none of the labels comes back as Other with its text", () => {
  const single = render( mc( [ SINGLE ] ), { index: 0, answers: { DB: "Redis" } } );
  assert.equal( single.radio().checked, true );
  assert.equal( single.text().value, "Redis" );

  const multi = render( mc( [ MULTI ] ), { index: 0, answers: { Features: [ "Search", "Audit log", "SSO" ] } } );
  assert.equal( multi.radio().checked, true );
  assert.equal( multi.text().value, "Audit log, SSO" );
  assert.equal( multi.el.querySelector<HTMLInputElement>( 'input[value="Search"]' )!.checked, true );

  const listed = render( mc( [ SINGLE ] ), { index: 0, answers: { DB: "MySQL" } } );
  assert.equal( listed.radio().checked, false, "a listed answer does not tick Other" );
  assert.equal( listed.text().value, "" );
} );

test( "Back and Next keep a custom answer: question 1 comes back as Other with its text", () => {
  const c = render( mc( [ SINGLE, MULTI ] ) );
  c.radio().checked = true;
  c.text().value = "Redis";
  c.click( "action-required-btn-next" );
  assert.equal( c.indicator(), "Question 2 of 2" );
  assert.equal( c.text().value, "", "question 2 has its own, empty Other" );
  c.click( "action-required-btn-back" );
  assert.equal( c.radio().checked, true );
  assert.equal( c.text().value, "Redis" );
} );

// ---------------------------------------------------------------------------
// The wiring
// ---------------------------------------------------------------------------

test( "focusing Other's text ticks Other", () => {
  const c = render( mc( [ SINGLE ] ) );
  c.tick( "MySQL" );
  c.text().focus();
  assert.equal( c.radio().checked, true );
  assert.equal( c.el.querySelector<HTMLInputElement>( 'input[value="MySQL"]' )!.checked, false, "a radio: MySQL is released" );
} );

test( "Enter in Other's text goes to the next question, or submits on the last; other keys do nothing", () => {
  const c = render( mc( [ SINGLE, MULTI ] ) );
  c.text().focus();
  c.text().value = "Redis";
  assert.equal( key( c.text(), "a" ).defaultPrevented, false );
  assert.equal( c.indicator(), "Question 1 of 2" );
  assert.equal( key( c.text(), "Enter" ).defaultPrevented, true );
  assert.equal( c.indicator(), "Question 2 of 2" );
  c.text().focus();
  c.text().value = "SSO";
  key( c.text(), "Enter" );
  assert.deepEqual( c.sent, [ { answers: { DB: "Redis", Features: [ "SSO" ] } } ] );
} );

test( "typing into Other's text clears the invalid mark (the mic's transcription arrives as input)", () => {
  const c = render( mc( [ SINGLE ] ) );
  c.click( "action-required-btn-submit" );
  assert.equal( c.block().classList.contains( "invalid" ), true );
  c.text().dispatchEvent( new Event( "input", { bubbles: true } ) );
  assert.equal( c.block().classList.contains( "invalid" ), false );
} );

test( "the 🎤 records into Other's text under legacy's context `mc-<id>`, and ticks Other", () => {
  const c = render( mc( [ SINGLE ] ) );
  c.tick( "MySQL" );
  const click = new MouseEvent( "click", { cancelable: true, bubbles: true } );
  let bubbled = false;
  c.el.addEventListener( "click", () => { bubbled = true; } );
  c.mic().dispatchEvent( click );
  assert.equal( c.mics.length, 1 );
  assert.equal( c.mics[ 0 ]![ 0 ], "mc-mc1" );
  assert.ok( c.mics[ 0 ]![ 1 ] === c.mic() );
  assert.ok( c.mics[ 0 ]![ 2 ] === c.text() );
  assert.equal( c.radio().checked, true );
  assert.equal( click.defaultPrevented, true );
  assert.equal( bubbled, false, "the click stays on the mic" );
} );

test( "Enter or Space on the 🎤 records; any other key does not", () => {
  const c = render( mc( [ SINGLE ] ) );
  assert.equal( key( c.mic(), "Enter" ).defaultPrevented, true );
  assert.equal( key( c.mic(), " " ).defaultPrevented, true );
  assert.equal( key( c.mic(), "a" ).defaultPrevented, false );
  assert.equal( c.mics.length, 2 );
} );

test( "with no onMic the 🎤 is inert", () => {
  const c = render( mc( [ SINGLE ] ), undefined, false );
  c.mic().click();
  assert.equal( c.mics.length, 0 );
} );

// ---------------------------------------------------------------------------
// The mounted card
// ---------------------------------------------------------------------------

function mount( item: ActionRequiredItem ) {
  let items = [ item ];
  const answers: ActionRequiredResponse[] = [];
  const starts : RecordingManagerStartOptions[] = [];
  const bus = createEventBusForTesting();
  const store: ActionRequiredStoreLike = {
    list: () => items, getById: ( id ) => items.find( ( i ) => i.id_hash === id ),
    respondAndAwait: async ( _id, r ) => { answers.push( r ); },
    togglePause: () => false,
    recordStep: ( _id, step ) => { items = [ { ...items[ 0 ]!, step } ]; },   // the store keeps it on the item (A-1c2)
  };
  const root = document.createElement( "div" );
  document.body.replaceChildren( root );
  const r = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store }, recorder: {
    startRecording: async ( o ) => { starts.push( o ); }, stopRecording: async () => {}, getActiveContextId: () => null } } );
  r.mount( root );
  const set = ( state: ActionRequiredItem["state"], changeKind: ActionRequiredChangeKind ) => {
    items = [ { ...items[ 0 ]!, state } ];
    bus.emit( { type: "store_action_required_changed", payload: { changeKind, id_hash: item.id_hash }, source: "t", ts: 0 } );
  };
  return { root, r, answers, starts, set };
}

const flush = () => new Promise( ( res ) => setTimeout( res, 0 ) );

test( "mounted: dictating into Other and pressing Submit answers with the words", async () => {
  const m = mount( mc( [ SINGLE ] ) );
  m.root.querySelector<HTMLButtonElement>( ".mc-other-mic" )!.click();
  assert.equal( m.starts[ 0 ]!.contextId, "mc-mc1" );
  m.starts[ 0 ]!.onComplete!( "Redis", new Blob() );
  m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!.click();
  await flush();
  assert.deepEqual( m.answers, [ { answers: { DB: "Redis" } } ] );
  m.r.unmount();
} );

test( "mounted: Other's typed text survives a failed submit, still ticked, and the retry sends it", async () => {
  const m = mount( mc( [ SINGLE ] ) );
  const text = () => m.root.querySelector<HTMLInputElement>( ".mc-other-input" )!;
  text().focus();
  text().value = "Redis";
  text().dispatchEvent( new Event( "input", { bubbles: true } ) );
  m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!.click();   // the POST that fails
  await flush();
  m.set( "submitting", "responded-pending" );
  m.set( "failed", "failed" );
  assert.equal( text().value, "Redis" );
  assert.equal( m.root.querySelector<HTMLInputElement>( ".mc-other-radio" )!.checked, true );
  m.root.querySelector<HTMLButtonElement>( ".action-required-btn-submit" )!.click();   // the retry
  await flush();
  assert.deepEqual( m.answers, [ { answers: { DB: "Redis" } }, { answers: { DB: "Redis" } } ] );
  m.r.unmount();
} );
