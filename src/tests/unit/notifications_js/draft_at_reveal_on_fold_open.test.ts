// Row af818120: the forecast fold reports the controls' state when it opens (legacy client).
//
// The multiplexer half is src/tests/unit/multiplexer/render/action_required_draft.test.ts. This half
// loads the real notifications.js the way batch_prediction_prefill.test.ts does: the class source is
// sliced off the bottom-of-file init block and run in a vm context, and an instance is built with
// Object.create() so the heavy constructor never runs.
//
// The multiple-choice and batch cards are drawn by the real renderMultipleChoiceUI and
// renderOpenEndedBatchUI. The open-ended card's markup is built inline in a larger method, so this
// file carries a copy of its input element; the class names it reads are the ones that markup uses.
//
// notifications.js has no c8 number (see run-typescript-tests.sh): these assertions are its gate.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/draft_at_reveal_on_fold_open.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

interface Call { url: string; body: Record<string, unknown> }
type Notification = Record<string, unknown>;
type UI = Record<string, any> & {
  calls: Call[];
  open: ( id: string ) => Promise<Record<string, unknown>[]>;
};

function makeUI(): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  ui.debug   = false;
  ui.log     = (): void => {};
  ui.actionRequiredNotifications = new Map();
  ui.calls   = [];
  ui.authedFetch = async ( url: string, init: { body: string } ): Promise<{ ok: boolean }> => {
    ui.calls.push( { url, body: JSON.parse( init.body ) } );
    return { ok: true };
  };
  return ui;
}

const ENV  = { header: "Env", question: "Which environment?", multi_select: false, options: [ { label: "staging", description: "" }, { label: "prod", description: "" } ] };
const TAGS = { header: "Tags", question: "Which tags?", multi_select: true, options: [ { label: "a", description: "" }, { label: "b", description: "" }, { label: "c", description: "" } ] };

function note( response_type: string, extra: Notification = {} ): Notification {
  return { id: "n1", response_type, sender_id: "claude.code@lupin.deepily.ai#abc", message: "Pick", ...extra };
}

// Put a card for `n` on the page and its state in the map, drawn by the real renderer where there is one.
function place( ui: UI, n: Notification, html: string, state: Record<string, unknown> = {} ): HTMLElement {
  document.body.replaceChildren();
  const card = document.createElement( "div" );
  card.id    = `action-required-${n.id as string}`;
  card.innerHTML = html;
  document.body.appendChild( card );
  ui.actionRequiredNotifications.set( n.id, { notification: n, currentQuestionIndex: 0, collectedAnswers: {}, ...state } );
  return card;
}

function mcCard( ui: UI, questions: unknown[], state: Record<string, unknown> = {}, index = 0 ): HTMLElement {
  const n = note( "multiple_choice", { response_options: { questions } } );
  return place( ui, n, ui.renderMultipleChoiceUI( n, index ), { currentQuestionIndex: index, ...state } );
}

const OPEN_ENDED_HTML = `<div class="response-open-ended"><input type="text" class="response-text-input" id="response-input-n1" value=""></div>`;

beforeEach( () => { document.body.replaceChildren(); } );

test( "a yes/no card has no draft, because clicking is submitting", () => {
  const ui = makeUI();
  place( ui, note( "yes_no" ), `<div class="response-yes-no"></div>` );
  assert.equal( ui._draftAtReveal( "n1" ), null );
} );

test( "an open-ended card sends its stripped text, and an empty box sends none", () => {
  const ui   = makeUI();
  const card = place( ui, note( "open_ended" ), OPEN_ENDED_HTML );
  assert.equal( ui._draftAtReveal( "n1" ), null );
  ( card.querySelector( ".response-text-input" ) as HTMLInputElement ).value = "  hello  ";
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "hello" } );
} );

test( "a multiple-choice card sends the option ticked, as the answers JSON the submit sends", () => {
  const ui   = makeUI();
  const card = mcCard( ui, [ ENV ] );
  assert.equal( ui._draftAtReveal( "n1" ), null, "nothing ticked, nothing saved" );
  ( card.querySelector( ".mc-input[value='staging']" ) as HTMLInputElement ).checked = true;
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "{\"answers\":{\"Env\":\"staging\"}}" } );
} );

test( "a ticked Other counts through its trimmed text, and with no text it counts for nothing", () => {
  const ui   = makeUI();
  const card = mcCard( ui, [ ENV ] );
  ( card.querySelector( ".mc-input[value='__other__']" ) as HTMLInputElement ).checked = true;
  assert.equal( ui._draftAtReveal( "n1" ), null );
  ( card.querySelector( ".mc-other-input" ) as HTMLInputElement ).value = "  qa  ";
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "{\"answers\":{\"Env\":\"qa\"}}" } );
} );

test( "answers saved on earlier questions ride with the picks on the question on screen, and reading marks nothing invalid", () => {
  const ui   = makeUI();
  const card = mcCard( ui, [ ENV, TAGS ], { collectedAnswers: { Env: "prod" } }, 1 );
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "{\"answers\":{\"Env\":\"prod\"}}" }, "saved answers alone" );
  ( card.querySelector( ".mc-input[value='a']" ) as HTMLInputElement ).checked = true;
  ( card.querySelector( ".mc-input[value='c']" ) as HTMLInputElement ).checked = true;
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "{\"answers\":{\"Env\":\"prod\",\"Tags\":[\"a\",\"c\"]}}" } );
  assert.equal( card.querySelector( ".response-multiple-choice" )!.classList.contains( "invalid" ), false );
} );

test( "a batch card sends the fields that hold text and leaves out the empty ones", () => {
  const ui = makeUI();
  const n  = note( "open_ended_batch", { response_options: { questions: [
    { header: "Topic", question: "Topic?", default_value: "" }, { header: "Budget", question: "Budget?", default_value: "" } ] } } );
  const card = place( ui, n, ui.renderOpenEndedBatchUI( n ) );
  assert.equal( ui._draftAtReveal( "n1" ), null );
  ( card.querySelectorAll( ".batch-text-input" )[ 1 ] as HTMLInputElement ).value = " 50 ";
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "{\"answers\":{\"Budget\":\"50\"}}" } );
} );

test( "a card with no state or no controls on the page has no draft", () => {
  const ui = makeUI();
  assert.equal( ui._draftAtReveal( "nope" ), null );
  place( ui, note( "open_ended" ), OPEN_ENDED_HTML );
  document.body.replaceChildren();
  assert.equal( ui._draftAtReveal( "n1" ), null, "the state is there but the card is gone" );
} );

test( "a draft is kept at exactly the server's limit and dropped one character over it", () => {
  const ui   = makeUI();
  const card = place( ui, note( "open_ended" ), OPEN_ENDED_HTML );
  const box  = card.querySelector( ".response-text-input" ) as HTMLInputElement;
  box.value = "x".repeat( 4084 );   // {"value":"…"} is 12 characters of frame, so 4084 makes 4096
  assert.deepEqual( ui._draftAtReveal( "n1" ), { value: "x".repeat( 4084 ) } );
  box.value = "x".repeat( 4085 );
  assert.equal( ui._draftAtReveal( "n1" ), null );
} );

test( "the seen report carries the draft on a fold-open, never on a render, and nothing when it is null", async () => {
  const ui = makeUI();
  await ui._reportPredictionSeen( "n1", "rendered", { value: "ignored" } );
  await ui._reportPredictionSeen( "n1", "fold_opened", { value: "yes" } );
  await ui._reportPredictionSeen( "n2", "fold_opened", null );
  await ui._reportPredictionSeen( "n3", "fold_opened" );
  assert.deepEqual( ui.calls.map( ( c: Call ) => c.body ), [
    { rendered: true },
    { fold_opened: true, draft_at_reveal: { value: "yes" } },
    { fold_opened: true },
    { fold_opened: true },
  ] );
  assert.equal( ui.calls[ 0 ]!.url, "/api/notify/prediction-seen/n1" );
} );

test( "getCurrentQuestionAnswer still marks the card invalid when nothing is chosen, and returns the pick when something is", () => {
  const ui   = makeUI();
  const card = mcCard( ui, [ ENV ] );
  assert.equal( ui.getCurrentQuestionAnswer( "n1" ), null );
  assert.equal( card.querySelector( ".response-multiple-choice" )!.classList.contains( "invalid" ), true );
  ( card.querySelector( ".mc-input[value='prod']" ) as HTMLInputElement ).checked = true;
  assert.deepEqual( ui.getCurrentQuestionAnswer( "n1" ), { header: "Env", value: "prod" } );
  assert.equal( ui.getCurrentQuestionAnswer( "gone" ), null, "no card, no state: null and no throw" );
} );

test( "opening the fold on the page sends the draft in the same call", async () => {
  const ui = makeUI();
  ui._setupPredictionVoteDelegation();
  const card = mcCard( ui, [ ENV ] );
  ( card.querySelector( ".mc-input[value='staging']" ) as HTMLInputElement ).checked = true;
  const fold = document.createElement( "details" );
  fold.className = "prediction-hint-fold";
  fold.dataset.notificationId = "n1";
  card.appendChild( fold );
  fold.open = true;   // the DOM fires `toggle` itself
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( ui.calls.map( ( c: Call ) => c.body ), [ { fold_opened: true, draft_at_reveal: { value: "{\"answers\":{\"Env\":\"staging\"}}" } } ] );
} );
