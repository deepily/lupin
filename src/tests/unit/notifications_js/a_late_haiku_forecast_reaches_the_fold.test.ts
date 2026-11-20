// A late Haiku forecast reaches the fold on the legacy page.
//
// Legacy notifications.js, phase 6 (row 3e63f445): the prediction_hint_updated frame fills the
// forecast line of every fold of that card, a fold opened mid-forecast asks the server, and the
// name is subscribed on the queue socket only.
//
// Like its siblings, notifications.js is loaded by slicing the source through vm.runInThisContext,
// so c8 cannot see it; this behavioural test is its gate.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/a_late_haiku_forecast_reaches_the_fold.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const EVENT            = "prediction_hint_updated";
const CONTEXT_SELECTOR = '[data-testid="prediction-hint-context"]';

type Forecast = { state: string; predicted_value?: unknown; confidence?: number };
type UI = Record<string, unknown> & {
  handleQueueMessage: ( event: { data: string } ) => void;
  handlePredictionHintUpdated: ( envelope: { notification_id?: string; context_forecast?: Forecast | null } ) => void;
  _refreshContextForecast: ( fold: Element ) => Promise<void>;
  _contextForecastText: ( responseType: string, forecast: Forecast ) => string;
  _buildContextForecastLine: ( notification: Record<string, unknown> ) => string;
  _buildQueueAuthMessage: () => { subscribed_events: string[] };
  _buildAudioAuthMessage: () => { subscribed_events: string[] };
  _setupPredictionVoteDelegation: () => void;
};

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
} );

beforeEach( () => { document.body.innerHTML = ""; } );

function makeUI(): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.authToken      = "<test-double-token-placeholder>";
  ui.queueSessionId = "calm dolphin";
  ui.audioSessionId = "wise owl";
  return ui;
}

function addFold( id: string, responseType: string, withLine?: string ): HTMLElement {
  const fold = document.createElement( "details" );
  fold.className = "prediction-hint-fold";
  fold.dataset.notificationId = id;
  fold.dataset.responseType   = responseType;
  if ( withLine !== undefined ) {
    const line = document.createElement( "div" );
    line.className = "prediction-hint-context";
    line.setAttribute( "data-testid", "prediction-hint-context" );
    line.setAttribute( "data-context-state", withLine );
    fold.appendChild( line );
  }
  document.body.appendChild( fold );
  return fold;
}

const READY = { state: "ready", predicted_value: "yes", confidence: 0.904 };

test( "the queue socket subscribes to the name and the audio socket does not", () => {
  const ui = makeUI();
  assert.ok( ui._buildQueueAuthMessage().subscribed_events.includes( EVENT ), "queue socket carries it" );
  assert.ok( !ui._buildAudioAuthMessage().subscribed_events.includes( EVENT ), "audio socket does not" );
} );

test( "the frame reaches the handler whole, and the card's folds change", () => {
  const fold = addFold( "n1", "yes_no", "forecasting" );
  makeUI().handleQueueMessage( { data: JSON.stringify( { type: EVENT, notification_id: "n1", context_forecast: READY } ) } );
  const line = fold.querySelector( CONTEXT_SELECTOR )!;
  assert.equal( line.textContent, "Haiku forecast: Yes (90%)" );
  assert.equal( line.getAttribute( "data-context-state" ), "ready" );
} );

test( "a fold with no line gets one, and a fold of another card is left alone", () => {
  const mine  = addFold( "n1", "yes_no" );
  const other = addFold( "n2", "yes_no", "forecasting" );
  makeUI().handlePredictionHintUpdated( { notification_id: "n1", context_forecast: READY } );
  assert.equal( mine.querySelectorAll( CONTEXT_SELECTOR ).length, 1 );
  assert.equal( mine.querySelector( CONTEXT_SELECTOR )!.textContent, "Haiku forecast: Yes (90%)" );
  assert.equal( other.querySelector( CONTEXT_SELECTOR )!.getAttribute( "data-context-state" ), "forecasting" );
} );

test( "a second frame rewrites the same line and does not add another", () => {
  const fold = addFold( "n1", "yes_no", "forecasting" );
  const ui   = makeUI();
  ui.handlePredictionHintUpdated( { notification_id: "n1", context_forecast: { state: "forecast_timed_out" } } );
  ui.handlePredictionHintUpdated( { notification_id: "n1", context_forecast: READY } );
  assert.equal( fold.querySelectorAll( CONTEXT_SELECTOR ).length, 1 );
  assert.equal( fold.querySelector( CONTEXT_SELECTOR )!.getAttribute( "data-context-state" ), "ready" );
} );

test( "a frame without an id or a forecast changes nothing", () => {
  const fold = addFold( "n1", "yes_no", "forecasting" );
  const ui   = makeUI();
  ui.handlePredictionHintUpdated( { context_forecast: READY } );
  ui.handlePredictionHintUpdated( { notification_id: "n1", context_forecast: null } );
  assert.equal( fold.querySelector( CONTEXT_SELECTOR )!.getAttribute( "data-context-state" ), "forecasting" );
  assert.ok( ui._contextForecasts === undefined, "nothing was remembered" );
} );

test( "each state reads its own words", () => {
  const ui = makeUI();
  assert.equal( ui._contextForecastText( "yes_no", { state: "forecasting" } ), "Haiku forecast: still forecasting" );
  assert.equal( ui._contextForecastText( "yes_no", { state: "unavailable" } ), "Haiku forecast unavailable" );
  assert.equal( ui._contextForecastText( "yes_no", { state: "forecast_timed_out" } ), "Haiku forecast timed out" );
  assert.equal( ui._contextForecastText( "yes_no", { state: "mystery" } ), "Haiku forecast unavailable", "an unknown state reads as unavailable" );
} );

test( "a ready forecast shows its value by card type", () => {
  const ui = makeUI();
  assert.equal( ui._contextForecastText( "yes_no", READY ), "Haiku forecast: Yes (90%)" );
  assert.equal( ui._contextForecastText( "multiple_choice", { state: "ready", predicted_value: { answers: { Plan: "A", Tags: [ "x", "y" ] } }, confidence: 0.5 } ),
    "Haiku forecast: Plan: A; Tags: [x, y] (50%)" );
  assert.equal( ui._contextForecastText( "open_ended", { state: "ready", predicted_value: "free text", confidence: 0.2 } ), "Haiku forecast: free text (20%)" );
  assert.equal( ui._contextForecastText( "open_ended", { state: "ready", predicted_value: 7, confidence: 0.2 } ), "Haiku forecast: 7 (20%)", "a non-string value is written as JSON" );
} );

test( "the line builder uses the last frame over the hint the card arrived with, and is empty with neither", () => {
  const ui = makeUI();
  assert.equal( ui._buildContextForecastLine( { id: "n1", response_type: "yes_no" } ), "" );
  const arrived = { id: "n1", response_type: "yes_no", prediction_hint: { context_forecast: { state: "forecasting" } } };
  assert.ok( ui._buildContextForecastLine( arrived ).includes( 'data-context-state="forecasting"' ) );
  ui.handlePredictionHintUpdated( { notification_id: "n1", context_forecast: READY } );
  const html = ui._buildContextForecastLine( arrived );
  assert.ok( html.includes( 'data-context-state="ready"' ) && html.includes( "Haiku forecast: Yes (90%)" ), "the frame wins" );
  assert.ok( html.includes( 'data-testid="prediction-hint-context"' ) );
} );

test( "the line builder escapes the state", () => {
  const html = makeUI()._buildContextForecastLine( { id: "n1", response_type: "yes_no", prediction_hint: { context_forecast: { state: '"><b>' } } } );
  assert.ok( !html.includes( "<b>" ), "no raw markup from a state value" );
} );

function withFetch( ui: UI, answer: () => Promise<unknown> ): string[] {
  const asked: string[] = [];
  ui.authedFetch = ( path: string ) => { asked.push( path ); return answer(); };
  return asked;
}

test( "a fold still forecasting asks the server by id and shows what comes back", async () => {
  const fold  = addFold( "n 1", "yes_no", "forecasting" );
  const ui    = makeUI();
  const asked = withFetch( ui, async () => ( { ok: true, json: async () => ( { context_forecast: READY } ) } ) );
  await ui._refreshContextForecast( fold );
  assert.deepEqual( asked, [ "/api/notify/prediction-hint/n%201" ] );
  assert.equal( fold.querySelector( CONTEXT_SELECTOR )!.textContent, "Haiku forecast: Yes (90%)" );
} );

test( "a fold that is not forecasting does not ask", async () => {
  const ui    = makeUI();
  const asked = withFetch( ui, async () => ( { ok: true, json: async () => ( {} ) } ) );
  await ui._refreshContextForecast( addFold( "n1", "yes_no", "ready" ) );
  await ui._refreshContextForecast( addFold( "n2", "yes_no" ) );
  assert.deepEqual( asked, [] );
} );

test( "a refused call, a null forecast and a thrown call each leave the line as it was", async () => {
  const ui = makeUI();
  for ( const answer of [
    async () => ( { ok: false, json: async () => ( {} ) } ),
    async () => ( { ok: true, json: async () => ( { context_forecast: null } ) } ),
    async () => { throw new Error( "network down" ); },
  ] ) {
    const fold = addFold( "n1", "yes_no", "forecasting" );
    withFetch( ui, answer );
    await ui._refreshContextForecast( fold );
    assert.equal( fold.querySelector( CONTEXT_SELECTOR )!.getAttribute( "data-context-state" ), "forecasting" );
    fold.remove();
  }
} );

test( "opening a fold reports it and asks for the forecast", () => {
  const ui   = makeUI();
  const seen: unknown[][]   = [];
  const asked: Element[]    = [];
  ui._reportPredictionSeen = ( ...args: unknown[] ) => { seen.push( args ); };
  ui._draftAtReveal        = () => null;
  ui._refreshContextForecast = ( fold: Element ) => { asked.push( fold ); return Promise.resolve(); };
  ui._setupPredictionVoteDelegation();
  const fold = document.createElement( "details" );
  fold.className = "prediction-hint-fold";
  fold.dataset.notificationId = "n1";
  document.body.appendChild( fold );
  fold.open = true;
  assert.deepEqual( seen, [ [ "n1", "fold_opened", null ] ] );
  assert.deepEqual( asked, [ fold ] );
} );

test( "a real drawn fold, opened, asks the hint route for its card", async () => {
  const ui   = makeUI();
  const urls: string[] = [];
  ui.actionRequiredNotifications = new Map();
  ui.authedFetch = ( path: string, init?: { method?: string } ) => {
    urls.push( `${ init && init.method ? init.method : "GET" } ${ path }` );
    return Promise.resolve( { ok: true, json: async () => ( { context_forecast: READY } ) } );
  };
  const n = { id: "late-1", response_type: "yes_no", message: "Deploy?",
    prediction_hint: { state: "ready", predicted_value: "yes", confidence: 0.9, retrieval_metric: "dot", strategy: "context_baseline",
      context_forecast: { state: "forecasting" } } };
  document.body.innerHTML = ( ui.buildPredictionHintSection as ( n: unknown ) => string )( n );
  ui._setupPredictionVoteDelegation();
  const fold = document.querySelector( "details.prediction-hint-fold" ) as HTMLDetailsElement;
  assert.ok( fold, "the fold was drawn" );
  assert.equal( fold.querySelector( CONTEXT_SELECTOR )!.getAttribute( "data-context-state" ), "forecasting" );
  fold.open = true;
  await new Promise( ( r ) => setTimeout( r, 20 ) );
  assert.ok( urls.includes( "GET /api/notify/prediction-hint/late-1" ), `asked: ${ JSON.stringify( urls ) }` );
} );
