// The card's background Haiku forecast, drawn inside the forecast fold.
//
// The fold keeps its own state text; the Haiku forecast is a separate child with its own test id and state attribute.
// A card that carries no `context_forecast` (display switch off) draws no such child.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_context_forecast.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  contextForecastLine,
  predictionHintBox,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredChrome";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createActionRequiredRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { createPredictionVoteStore } from "../../../../lupin_app/static/js/multiplexer/stores/PredictionVoteStore";
import type { ActionRequiredItem, ContextForecastPayload, PredictionHint } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const line = ( type: string, forecast: ContextForecastPayload | undefined ): HTMLElement | null => contextForecastLine( type, forecast );

test( "no forecast on the card draws no line", () => {
  assert.equal( line( "yes_no", undefined ), null );
} );

test( "each state that has no value reads its own text and carries its state", () => {
  const cases: Array<[ ContextForecastPayload["state"], string ]> = [
    [ "forecasting", "Haiku forecast: still forecasting" ],
    [ "unavailable", "Haiku forecast unavailable" ],
    [ "forecast_timed_out", "Haiku forecast timed out" ],
  ];
  for ( const [ state, text ] of cases ) {
    const el = line( "yes_no", { state } )!;
    assert.equal( el.textContent, text );
    assert.equal( el.getAttribute( "data-context-state" ), state );
    assert.equal( el.getAttribute( "data-testid" ), "prediction-hint-context" );
  }
} );

test( "a state the client does not know reads as unavailable but keeps the state it was sent", () => {
  const el = line( "yes_no", { state: "mystery" as ContextForecastPayload["state"] } )!;
  assert.equal( el.textContent, "Haiku forecast unavailable" );
  assert.equal( el.getAttribute( "data-context-state" ), "mystery" );
} );

test( "a ready yes/no forecast shows the capitalised value and the rounded confidence", () => {
  assert.equal( line( "yes_no", { state: "ready", predicted_value: "yes", confidence: 0.904 } )!.textContent, "Haiku forecast: Yes (90%)" );
} );

test( "a ready multiple-choice forecast shows the value as JSON, as the hint does for other types", () => {
  assert.equal( line( "multiple_choice", { state: "ready", predicted_value: { answers: { Plan: "A" } }, confidence: 0.5 } )!.textContent,
    'Haiku forecast: {"answers":{"Plan":"A"}} (50%)' );
  assert.equal( line( "multiple_choice", { state: "ready", predicted_value: "A" } )!.textContent, "Haiku forecast: A (0%)", "a missing confidence reads as zero" );
} );

function box( hint: PredictionHint | undefined ): HTMLElement {
  return predictionHintBox( { id_hash: "a1", response_type: "yes_no", ...( hint === undefined ? {} : { prediction_hint: hint } ) }, undefined );
}

test( "the line sits inside the fold of a card whose own hint is not ready, and the fold keeps its state", () => {
  const el = box( { state: "below_threshold", retrieval_metric: "cosine", category: "c", context_forecast: { state: "forecasting" } } );
  assert.equal( el.getAttribute( "data-hint-state" ), "below_threshold" );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "Forecast too uncertain to show" );
  assert.equal( el.querySelector( '[data-testid="prediction-hint-context"]' )!.getAttribute( "data-context-state" ), "forecasting" );
} );

test( "the line sits inside the fold of a ready card too, and a card with no forecast has none", () => {
  const ready = { state: "ready" as const, retrieval_metric: "cosine", category: "c", predicted_value: "no", confidence: 0.7 };
  assert.equal( box( { ...ready, context_forecast: { state: "forecast_timed_out" } } ).querySelector( '[data-testid="prediction-hint-context"]' )!.textContent, "Haiku forecast timed out" );
  assert.ok( box( ready ).querySelector( '[data-testid="prediction-hint-context"]' ) === null, "a card with no forecast has no context line" );
  assert.ok( box( undefined ).querySelector( '[data-testid="prediction-hint-context"]' ) === null, "a card with no hint has no context line" );
} );

function mountCard( fetchForecast: ( ( id: string ) => Promise<void> ) | undefined ) {
  document.body.replaceChildren();
  const item: ActionRequiredItem = {
    id_hash : "ar-1", prompt : "Ship it?", response_type : "yes_no", questions : [], expires_at : Date.now() + 30_000, timeout_seconds : 30, state : "pending",
    prediction_hint : { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c", context_forecast: { state: "forecasting" } },
  };
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createActionRequiredRenderer( {
    eventBus : bus,
    stores   : { actionRequired: { list: () => [ item ], getById: () => item, respondAndAwait: async () => {} } },
    predictionVoteStore  : createPredictionVoteStore( { bus, api: { post: async <T,>(): Promise<T> => ( {} as T ) } } ),
    ...( fetchForecast === undefined ? {} : { contextForecastFetch: fetchForecast } ),
  } );
  renderer.mount( root );
  return { root, renderer };
}

test( "opening the fold asks for the card's current Haiku forecast", () => {
  const asked: string[] = [];
  const h = mountCard( async ( id ) => { asked.push( id ); } );
  ( h.root.querySelector( '[data-testid="prediction-hint-fold"]' ) as HTMLDetailsElement ).open = true;
  assert.deepEqual( asked, [ "ar-1" ] );
  h.renderer.unmount();
} );

test( "a renderer given no fetch opens the fold without asking", () => {
  const h = mountCard( undefined );
  ( h.root.querySelector( '[data-testid="prediction-hint-fold"]' ) as HTMLDetailsElement ).open = true;
  assert.equal( h.root.querySelector( '[data-testid="prediction-hint-context"]' )!.getAttribute( "data-context-state" ), "forecasting" );
  h.renderer.unmount();
} );

// A source pin: boot.ts runs at import, so its wiring cannot be driven from node. Resolved from this file.
const BOOT_CODE = readFileSync(
  resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../../lupin_app/static/js/multiplexer/boot.ts" ),
  "utf8",
).split( "\n" ).filter( ( line ) => !line.trimStart().startsWith( "//" ) ).join( "\n" );

test( "boot gives the renderer the fetcher, built over the api client and the action-required store", () => {
  const calls = [ ...BOOT_CODE.matchAll( /createActionRequiredRenderer\(\{([\s\S]*?)\n\s*\}\);/g ) ];
  assert.equal( calls.length, 1 );
  assert.match( ( calls[ 0 ] as RegExpMatchArray )[ 1 ] as string, /\bcontextForecastFetch\s*:\s*createContextForecastFetcher\(apiClient,\s*stores\.actionRequired\)\s*,/ );
} );
