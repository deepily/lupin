// Epic-board card — EpicStoriesStore unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE MEMO COVERS THE FAILURE CASE, AND THAT IS THE WHOLE POINT OF THIS
// STORE. A one-shot that memoizes only its SUCCESSES retries a down endpoint on
// every render — one request per paint, forever, against an endpoint that is
// already failing. So the interesting tests here are not "does it fetch" but
// "does it STOP", and each one counts CALLS rather than reading a result.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createEpicStoriesStore,
  EPIC_STORIES_ENDPOINT,
  type EpicStoriesApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/EpicStoriesStore";

interface FakeApi extends EpicStoriesApiClient {
  calls: string[];
}

function fakeApi( handler: ( path: string ) => Promise<unknown> ): FakeApi {
  const calls: string[] = [];
  return {
    calls,
    async get<T>( path: string ): Promise<T> {
      calls.push( path );
      return ( await handler( path ) ) as T;
    },
  };
}

const okBody = { stories: { "epic:alpha": { title: "Alpha", story: "The alpha story." } } };

// ---------------------------------------------------------------------------
// The happy path
// ---------------------------------------------------------------------------

test( "it asks the endpoint the legacy client asks, and caches what comes back", async () => {
  const api   = fakeApi( async () => okBody );
  const store = createEpicStoriesStore( { api } );

  assert.deepEqual( store.stories(), {}, "the store answered before it fetched" );
  assert.equal( store.hasAttempted(), false );

  const loaded = await store.load();

  assert.deepEqual( api.calls, [ EPIC_STORIES_ENDPOINT ] );
  assert.deepEqual( loaded, okBody.stories );
  assert.deepEqual( store.stories(), okBody.stories );
  assert.equal( store.hasAttempted(), true );
} );

test( "a second load is a NO-OP — the file is hand-edited, not live state", async () => {
  const api   = fakeApi( async () => okBody );
  const store = createEpicStoriesStore( { api } );

  await store.load();
  await store.load();
  await store.load();

  assert.equal( api.calls.length, 1, `the store fetched ${ api.calls.length } times — it is polling a static file` );
} );

test( "two concurrent callers fire ONE request", async () => {
  // ⚠️ THE FLAG IS SET BEFORE THE AWAIT, and this is what that buys. Setting it
  // after the try/catch would let both callers pass the guard before either
  // resolved, and the "one-shot" would be a two-shot under exactly the
  // condition boot creates — a paint and an explicit load in the same tick.
  const api   = fakeApi( async () => okBody );
  const store = createEpicStoriesStore( { api } );

  await Promise.all( [ store.load(), store.load() ] );
  assert.equal( api.calls.length, 1, `${ api.calls.length } concurrent requests — the guard sits after the await` );
} );

// ---------------------------------------------------------------------------
// Every failure resolves to {} — and STAYS resolved
// ---------------------------------------------------------------------------

test( "a throwing endpoint yields {} and is NEVER retried", async () => {
  // 🔴 THE ONE THAT MATTERS. A memo covering only successes turns a failing
  // endpoint into one request per paint, forever.
  const logs: string[] = [];
  const api   = fakeApi( async () => { throw new Error( "boom" ); } );
  const store = createEpicStoriesStore( { api, logFn: ( m ) => logs.push( m ) } );

  assert.deepEqual( await store.load(), {} );
  await store.load();
  await store.load();

  assert.equal( api.calls.length, 1, `a failing endpoint was hit ${ api.calls.length } times` );
  assert.equal( store.hasAttempted(), true, "a failed attempt must still count as attempted" );
  assert.equal( logs.length, 1 );
  assert.ok( logs[ 0 ]!.includes( "de-slugged" ),
    `the diagnostic does not say what the operator will SEE: ${ logs[ 0 ] }` );
} );

test( "a body with no stories map yields {} and says so once", async () => {
  const logs: string[] = [];
  const api   = fakeApi( async () => ( { unexpected: true } ) );
  const store = createEpicStoriesStore( { api, logFn: ( m ) => logs.push( m ) } );

  assert.deepEqual( await store.load(), {} );
  assert.equal( logs.length, 1 );
  assert.ok( logs[ 0 ]!.includes( "de-slugged" ) );
} );

test( "a non-object stories field is refused rather than cached", async () => {
  // ⚠️ THE SHAPE CHECK IS NOT CEREMONY. `stories: "none"` is TRUTHY, so a guard
  // testing only truthiness would cache a STRING as the map — and every lookup
  // against it then returns a character or undefined rather than failing loudly.
  for ( const bad of [ { stories: "none" }, { stories: 7 }, { stories: null } ] ) {
    const store = createEpicStoriesStore( { api: fakeApi( async () => bad ) } );
    assert.deepEqual( await store.load(), {}, `cached a bad stories field: ${ JSON.stringify( bad ) }` );
  }
} );

test( "a null body yields {}", async () => {
  const store = createEpicStoriesStore( { api: fakeApi( async () => null ) } );
  assert.deepEqual( await store.load(), {} );
} );

test( "an injected endpoint is the one asked for", async () => {
  const api   = fakeApi( async () => okBody );
  const store = createEpicStoriesStore( { api, endpoint: "/api/somewhere-else" } );
  await store.load();
  assert.deepEqual( api.calls, [ "/api/somewhere-else" ] );
} );
