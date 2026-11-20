// The late-forecast fetch: a fold opened mid-forecast reads the stored result.
//
// The fetcher is real; the API client is a recorder and the target a small store double that keeps one card.
//
// Run: npx tsx --test src/tests/unit/multiplexer/context_forecast_fetch.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createContextForecastFetcher,
  PREDICTION_HINT_ENDPOINT_PREFIX,
  type ContextForecastTarget,
} from "../../../lupin_app/static/js/multiplexer/stores/contextForecastFetch";
import type { ContextForecastPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

function setup( state: ContextForecastPayload["state"] | "none" | undefined, reply: () => Promise<unknown> ) {
  const gets    : string[] = [];
  const applied : Array<[ string, ContextForecastPayload ]> = [];
  const card    = state === undefined ? {} : state === "none" ? { prediction_hint: {} } : { prediction_hint: { context_forecast: { state } } };
  const target: ContextForecastTarget = {
    getById              : ( id ) => ( id === "c1" ? card : undefined ),
    applyContextForecast : ( id, forecast ) => { applied.push( [ id, forecast ] ); },
  };
  const api = { get: async <T>( path: string ): Promise<T> => { gets.push( path ); return ( await reply() ) as T; } };
  return { fetch: createContextForecastFetcher( api, target ), gets, applied };
}

test( "a card still forecasting asks the server and takes the forecast it gets", async () => {
  const ready = { state: "ready" as const, predicted_value: "yes", confidence: 0.8 };
  const h     = setup( "forecasting", async () => ( { context_forecast: ready } ) );
  await h.fetch( "c1" );
  assert.deepEqual( h.gets, [ PREDICTION_HINT_ENDPOINT_PREFIX + "c1" ] );
  assert.deepEqual( h.applied, [ [ "c1", ready ] ] );
} );

test( "a card that is not forecasting, has no forecast or is unknown makes no request", async () => {
  for ( const [ state, id ] of [ [ "ready", "c1" ], [ "forecast_timed_out", "c1" ], [ undefined, "c1" ], [ "none", "c1" ], [ "forecasting", "missing" ] ] as const ) {
    const h = setup( state, async () => ( { context_forecast: { state: "ready" } } ) );
    await h.fetch( id );
    assert.deepEqual( h.gets, [], `asked for ${ String( state ) } / ${ id }` );
  }
} );

test( "a null forecast, which is what the server sends with display off, changes nothing", async () => {
  const h = setup( "forecasting", async () => ( { context_forecast: null } ) );
  await h.fetch( "c1" );
  assert.equal( h.gets.length, 1 );
  assert.deepEqual( h.applied, [] );
} );

test( "a failed request changes nothing and does not throw", async () => {
  const h = setup( "forecasting", async () => { throw new Error( "network down" ); } );
  await h.fetch( "c1" );
  assert.deepEqual( h.applied, [] );
} );

test( "the id is encoded into the path", async () => {
  const h = setup( "forecasting", async () => ( { context_forecast: null } ) );
  const odd: ContextForecastTarget = { getById: () => ( { prediction_hint: { context_forecast: { state: "forecasting" } } } ), applyContextForecast: () => {} };
  const gets: string[] = [];
  await createContextForecastFetcher( { get: async <T>( path: string ): Promise<T> => { gets.push( path ); return { context_forecast: null } as T; } }, odd )( "a/b c" );
  assert.deepEqual( gets, [ PREDICTION_HINT_ENDPOINT_PREFIX + "a%2Fb%20c" ] );
  void h;
} );
