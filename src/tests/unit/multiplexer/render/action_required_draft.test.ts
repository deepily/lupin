// Row af818120: the forecast fold reports the controls' state when it opens (multiplexer).
//
// Two layers, both with the real code. The first runs draftAtReveal over widgets that
// renderActionRequiredInteractive built, so the reader is checked against the controls it reads.
// The second mounts the real renderer and the real PredictionVoteStore, opens the fold, and reads what
// the store POSTs; only the API client is a recorder.
//
// The shape is { value: <the string the submit button would send now> } (exposure.py, agreed with the
// server reader). Yes/no cards send no draft, and an empty answer sends none either, never an empty value.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_draft.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { draftAtReveal, DRAFT_MAX_CHARS } from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredDraft";
import { renderActionRequiredInteractive, MC_OTHER_VALUE } from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import { createActionRequiredRenderer, type ActionRequiredStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { createPredictionVoteStore } from "../../../../lupin_app/static/js/multiplexer/stores/PredictionVoteStore";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { ActionRequiredItem, ActionRequiredQuestion } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const ENV : ActionRequiredQuestion = { header: "Env", question: "Which environment?", multiSelect: false, options: [ { label: "staging" }, { label: "prod" } ] };
const TAGS: ActionRequiredQuestion = { header: "Tags", question: "Which tags?", multiSelect: true, options: [ { label: "a" }, { label: "b" }, { label: "c" } ] };

function item( response_type: ActionRequiredItem[ "response_type" ], extra: Partial<ActionRequiredItem> = {} ): ActionRequiredItem {
  return { id_hash: "ar-1", prompt: "Pick", response_type, questions: [], expires_at: Date.now() + 30_000, timeout_seconds: 30, state: "pending", ...extra };
}

function widgetOf( it: ActionRequiredItem ): HTMLElement {
  document.body.replaceChildren();
  const widget = renderActionRequiredInteractive( it, { onSubmit: () => {} }, it.step );
  document.body.appendChild( widget );
  return widget;
}

function tick( widget: HTMLElement, value: string ): void {
  ( widget.querySelector( `.action-required-option-input[value="${value}"]` ) as HTMLInputElement ).checked = true;
}

// ---- the reader, over real widgets ----

test( "a yes/no card has no draft, because clicking is submitting", () => {
  const it = item( "yes_no" );
  assert.equal( draftAtReveal( it, widgetOf( it ) ), null );
} );

test( "a multiple-choice card sends the option ticked, as the answers JSON the submit sends", () => {
  const it = item( "multiple_choice", { questions: [ ENV ] } );
  const w  = widgetOf( it );
  tick( w, "staging" );
  assert.deepEqual( draftAtReveal( it, w ), { value: "{\"answers\":{\"Env\":\"staging\"}}" } );
} );

test( "a multiple-choice card with nothing ticked and nothing saved sends no draft", () => {
  const it = item( "multiple_choice", { questions: [ ENV ] } );
  assert.equal( draftAtReveal( it, widgetOf( it ) ), null );
} );

test( "a ticked Other counts through its trimmed text, and an Other with no text counts for nothing", () => {
  const it = item( "multiple_choice", { questions: [ ENV ] } );
  const w  = widgetOf( it );
  tick( w, MC_OTHER_VALUE );
  assert.equal( draftAtReveal( it, w ), null, "Other ticked with an empty box is no answer" );
  ( w.querySelector( ".mc-other-input" ) as HTMLInputElement ).value = "  qa  ";
  assert.deepEqual( draftAtReveal( it, w ), { value: "{\"answers\":{\"Env\":\"qa\"}}" } );
} );

test( "the answers saved on earlier questions ride with the picks on the question on screen", () => {
  const it = item( "multiple_choice", { questions: [ ENV, TAGS ], step: { index: 1, answers: { Env: "prod" } } } );
  const w  = widgetOf( it );
  tick( w, "a" );
  tick( w, "c" );
  assert.deepEqual( draftAtReveal( it, w ), { value: "{\"answers\":{\"Env\":\"prod\",\"Tags\":[\"a\",\"c\"]}}" } );
} );

test( "saved answers alone are a draft when the question on screen has nothing ticked", () => {
  const it = item( "multiple_choice", { questions: [ ENV, TAGS ], step: { index: 1, answers: { Env: "prod" } } } );
  assert.deepEqual( draftAtReveal( it, widgetOf( it ) ), { value: "{\"answers\":{\"Env\":\"prod\"}}" } );
} );

test( "a multiple-choice card with no question on screen reads only what was saved", () => {
  const it = item( "multiple_choice", { questions: [ ENV ], step: { index: 0, answers: { Env: "prod" } } } );
  assert.deepEqual( draftAtReveal( it, document.createElement( "div" ) ), { value: "{\"answers\":{\"Env\":\"prod\"}}" } );
} );

test( "a batch card sends the fields that hold text and leaves out the empty ones", () => {
  const it = item( "open_ended_batch", { questions: [
    { header: "Topic", question: "Topic?", multiSelect: false, options: [] },
    { header: "Budget", question: "Budget?", multiSelect: false, options: [] },
  ] } );
  const w = widgetOf( it );
  assert.equal( draftAtReveal( it, w ), null, "two empty fields are no draft" );
  ( w.querySelectorAll( ".action-required-batch-input" )[ 1 ] as HTMLInputElement ).value = " 50 ";
  assert.deepEqual( draftAtReveal( it, w ), { value: "{\"answers\":{\"Budget\":\"50\"}}" } );
} );

test( "an open-ended card sends its stripped text, and an empty box sends none", () => {
  const it = item( "open_ended" );
  const w  = widgetOf( it );
  assert.equal( draftAtReveal( it, w ), null );
  ( w.querySelector( "[data-draft='response']" ) as HTMLInputElement ).value = "  hello  ";
  assert.deepEqual( draftAtReveal( it, w ), { value: "hello" } );
} );

test( "a draft is kept at exactly the server's limit and dropped one character over it", () => {
  const it = item( "open_ended" );
  const w  = widgetOf( it );
  const box = w.querySelector( "[data-draft='response']" ) as HTMLInputElement;
  assert.equal( DRAFT_MAX_CHARS, 4096 );
  box.value = "x".repeat( 4084 );   // {"value":"…"} is 12 characters of frame, so 4084 makes 4096
  assert.deepEqual( draftAtReveal( it, w ), { value: "x".repeat( 4084 ) } );
  box.value = "x".repeat( 4085 );
  assert.equal( draftAtReveal( it, w ), null );
} );

// ---- the renderer, the store and the fold ----

interface Post { path: string; body: Record<string, unknown> }

function mount( items: ActionRequiredItem[], getById?: ( id: string ) => ActionRequiredItem | undefined ) {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const posts : Post[] = [];
  const api   = { post: async <T>( path: string, body: unknown ): Promise<T> => { posts.push( { path, body: body as Record<string, unknown> } ); return {} as T; } };
  const store: ActionRequiredStoreLike = {
    list            : () => items,
    getById         : getById ?? ( ( id ) => items.find( ( it ) => it.id_hash === id ) ),
    respondAndAwait : async () => {},
    togglePause     : () => false,
    recordStep      : () => {},
  };
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store }, predictionVoteStore: createPredictionVoteStore( { bus, api } ) } );
  renderer.mount( root );
  const fold = root.querySelector( "details[data-testid='prediction-hint-fold']" ) as HTMLDetailsElement;
  const open = async (): Promise<Record<string, unknown>[]> => {
    fold.open = true;   // the DOM fires `toggle` itself
    await new Promise( ( r ) => setTimeout( r, 0 ) );
    return posts.filter( ( p ) => p.body.fold_opened === true ).map( ( p ) => p.body );
  };
  return { root, renderer, open };
}

const HINT = { state: "ready" as const, retrieval_metric: "dot", confidence: 0.8, predicted_value: "yes", category: "deploy", strategy: "history" };

test( "opening the fold of a multiple-choice card reports the selection in the same call", async () => {
  const it = item( "multiple_choice", { questions: [ ENV ], prediction_hint: HINT } );
  const h  = mount( [ it ] );
  tick( h.root, "prod" );
  assert.deepEqual( await h.open(), [ { fold_opened: true, draft_at_reveal: { value: "{\"answers\":{\"Env\":\"prod\"}}" } } ] );
  h.renderer.unmount();
} );

test( "opening the fold of an open-ended card reports the typed text", async () => {
  const it = item( "open_ended", { prediction_hint: HINT } );
  const h  = mount( [ it ] );
  ( h.root.querySelector( "[data-draft='response']" ) as HTMLInputElement ).value = "typed";
  assert.deepEqual( await h.open(), [ { fold_opened: true, draft_at_reveal: { value: "typed" } } ] );
  h.renderer.unmount();
} );

test( "opening the fold of a yes/no card reports the open and no draft", async () => {
  const it = item( "yes_no", { prediction_hint: HINT } );
  const h  = mount( [ it ] );
  assert.deepEqual( await h.open(), [ { fold_opened: true } ] );
  h.renderer.unmount();
} );

test( "an empty selection reports the open with no draft key at all", async () => {
  const it = item( "multiple_choice", { questions: [ ENV ], prediction_hint: HINT } );
  const h  = mount( [ it ] );
  const sent = await h.open();
  assert.deepEqual( sent, [ { fold_opened: true } ] );
  assert.equal( "draft_at_reveal" in sent[ 0 ]!, false );
  h.renderer.unmount();
} );

test( "a card the store no longer knows, or one whose widget has left the page, reports the open with no draft", async () => {
  const gone = item( "open_ended", { prediction_hint: HINT } );
  const a    = mount( [ gone ], () => undefined );
  ( a.root.querySelector( "[data-draft='response']" ) as HTMLInputElement ).value = "typed";
  assert.deepEqual( await a.open(), [ { fold_opened: true } ] );
  a.renderer.unmount();
  const away = item( "open_ended", { prediction_hint: HINT } );
  const b    = mount( [ away ] );
  ( b.root.querySelector( "[data-draft='response']" ) as HTMLInputElement ).value = "typed";
  b.root.querySelector( ".action-required-widget-interactive" )!.remove();   // the fold is still in the detached widget
  assert.deepEqual( await b.open(), [ { fold_opened: true } ] );
  b.renderer.unmount();
} );
