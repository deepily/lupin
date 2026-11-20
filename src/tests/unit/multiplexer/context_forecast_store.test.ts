// The action-required store takes a card's late Haiku forecast from a frame.
//
// The store and the bus are real. The frame is what the server sends: { notification_id, context_forecast }.
//
// Run: npx tsx --test src/tests/unit/multiplexer/context_forecast_store.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createActionRequiredStore } from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import type { ContextForecastPayload, StoreActionRequiredChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

function setup() {
  const bus     = createEventBusForTesting();
  const changes : string[] = [];
  bus.on<StoreActionRequiredChangedPayload>( "store_action_required_changed", ( e ) => changes.push( `${ e.payload.changeKind }:${ e.payload.id_hash }` ) );
  const store = createActionRequiredStore( {
    bus,
    api             : { post: async () => ( {} ) },
    setIntervalFn   : () => 0,
    clearIntervalFn : () => {},
    setTimeoutFn    : () => 0,
    clearTimeoutFn  : () => {},
    nowFn           : () => 1_700_000_000_000,
  } );
  const ask = ( id: string, hint: unknown ): void => bus.emit( {
    type    : "notification_queue_update",
    payload : { notification: { id_hash: id, message: "Proceed?", response_requested: true, response_type: "yes_no", response_options: [ "yes", "no" ], timeout_seconds: 60,
                                ...( hint === undefined ? {} : { prediction_hint: hint } ) } },
    source  : "test",
    ts      : 0,
  } );
  const frame = ( payload: unknown ): void => bus.emit( { type: "prediction_hint_updated", payload, source: "test", ts: 0 } );
  return { bus, store, changes, ask, frame };
}

const HINT  = { state: "insufficient_evidence", retrieval_metric: "cosine", category: "c", context_forecast: { state: "forecasting" } };
const READY: ContextForecastPayload = { state: "ready", predicted_value: "yes", confidence: 0.9 };

test( "a card arrives with the forecasting state its hint carried", () => {
  const h = setup();
  h.ask( "c1", HINT );
  assert.equal( h.store.getById( "c1" )!.prediction_hint!.context_forecast!.state, "forecasting" );
} );

test( "a frame replaces the card's forecast, keeps the rest of its hint and emits context-forecast", () => {
  const h = setup();
  h.ask( "c1", HINT );
  h.changes.length = 0;
  h.frame( { notification_id: "c1", context_forecast: READY } );
  const hint = h.store.getById( "c1" )!.prediction_hint!;
  assert.deepEqual( hint.context_forecast, READY );
  assert.equal( hint.state, "insufficient_evidence" );
  assert.equal( hint.category, "c" );
  assert.deepEqual( h.changes, [ "context-forecast:c1" ] );
} );

test( "applyContextForecast, the fetch route's way in, does the same", () => {
  const h = setup();
  h.ask( "c1", HINT );
  h.changes.length = 0;
  h.store.applyContextForecast( "c1", { state: "forecast_timed_out" } );
  assert.equal( h.store.getById( "c1" )!.prediction_hint!.context_forecast!.state, "forecast_timed_out" );
  assert.deepEqual( h.changes, [ "context-forecast:c1" ] );
} );

test( "a frame for an unknown card, for a card with no hint, or with no id or forecast changes and emits nothing", () => {
  const h = setup();
  h.ask( "bare", undefined );
  h.changes.length = 0;
  h.frame( { notification_id: "nobody", context_forecast: READY } );
  h.frame( { notification_id: "bare", context_forecast: READY } );
  h.frame( { context_forecast: READY } );
  h.frame( { notification_id: "bare" } );
  assert.deepEqual( h.changes, [] );
  assert.equal( h.store.getById( "bare" )!.prediction_hint, undefined );
} );
