// Row ed6db05a — an Action Required card's prediction hint carries working thumbs votes.
//
// Fix 2650df28 stopped mounting the controls when the renderer has no vote integration, and
// boot.ts built the renderer with none, so production cards showed no thumbs at all. Boot now
// hands the renderer the PredictionVoteStore (`predictionVoteStore: stores.predictionVote`).
//
// The renderer, the store and the controls below are the real ones; only the API client is a
// recorder, and it records what the store POSTs. The boot half is a source pin, as in
// boot_wires_action_required_to_reveal_through_the_toolbar.test.ts: boot.ts runs at import and
// exports nothing, so the pin checks that boot passes the store.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_prediction_vote.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredRenderer,
  type ActionRequiredStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import {
  createPredictionVoteStore,
  PREDICTION_VOTE_MIN_PCT,
} from "../../../../lupin_app/static/js/multiplexer/stores/PredictionVoteStore";
import type { ActionRequiredItem } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const AT_GATE = PREDICTION_VOTE_MIN_PCT / 100;

function makeItem( id: string, confidence: number ): ActionRequiredItem {
  return {
    id_hash         : id,
    prompt          : "Deploy to staging?",
    response_type   : "yes_no",
    questions       : [],
    expires_at      : Date.now() + 30_000,
    timeout_seconds : 30,
    state           : "pending",
    prediction_hint : { confidence, predicted_value: "yes", category: "deploy", strategy: "history" },
  };
}

interface Post { path: string; body: Record<string, unknown> }

// Built the way boot builds it: the real store, handed to the renderer as `predictionVoteStore`.
function setup( confidence: number, post?: ( path: string ) => Promise<unknown> ) {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const posts : Post[] = [];
  const api   = {
    post: async <T>( path: string, body: unknown ): Promise<T> => {
      posts.push( { path, body: body as Record<string, unknown> } );
      return ( post === undefined ? {} : await post( path ) ) as T;
    },
  };
  const voteStore = createPredictionVoteStore( { bus, api } );
  const items     = [ makeItem( "ar-1", confidence ) ];
  const store: ActionRequiredStoreLike = {
    list            : () => items,
    getById         : ( id ) => items.find( ( it ) => it.id_hash === id ),
    respondAndAwait : async () => {},
  };
  const root = document.createElement( "div" );
  root.id    = "action-required-section";
  document.body.appendChild( root );
  const renderer = createActionRequiredRenderer( {
    eventBus            : bus,
    stores              : { actionRequired: store },
    predictionVoteStore : voteStore,
  } );
  renderer.mount( root );
  return { root, posts, voteStore, renderer };
}

const flush = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

test( "a hint at the gate mounts the thumbs on the card", () => {
  const h = setup( AT_GATE );
  assert.equal( h.root.querySelector( '[data-testid="prediction-hint-vote"]' ) !== null, true,
    "no vote controls on a card whose hint is at PREDICTION_VOTE_MIN_PCT" );
  h.renderer.unmount();
} );

test( "a hint below the gate mounts no thumbs", () => {
  const h = setup( AT_GATE - 0.01 );
  assert.equal( h.root.querySelector( '[data-testid="prediction-hint-vote"]' ) === null, true );
  assert.equal( h.root.querySelector( ".prediction-hint" ) !== null, true, "the hint box itself is still drawn" );
  h.renderer.unmount();
} );

test( "a click POSTs the vote to the prediction-vote endpoint with the item id and direction", async () => {
  const h = setup( AT_GATE );
  ( h.root.querySelector( '[data-testid="prediction-vote-down"]' ) as HTMLElement ).click();
  await flush();
  assert.deepEqual( h.posts, [ {
    path : "/api/notify/prediction-vote/ar-1",
    body : {
      vote            : "down",
      question        : "Deploy to staging?",
      predicted_value : "yes",
      category        : "deploy",
      response_type   : "yes_no",
    },
  } ] );
  assert.equal( h.voteStore.getVote( "ar-1" ), "down", "the store did not record the cast" );
  h.renderer.unmount();
} );

test( "a recorded vote keeps its highlight when the card is repainted", async () => {
  const h = setup( AT_GATE );
  ( h.root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement ).click();
  await flush();
  h.renderer.forceRenderForTesting();
  const up = h.root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement;
  assert.equal( up.classList.contains( "selected" ), true );
  h.renderer.unmount();
} );

test( "a refused POST drops the optimistic highlight", async () => {
  const h = setup( AT_GATE, async () => { throw new Error( "HTTP 500" ); } );
  ( h.root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement ).click();
  assert.equal(
    ( h.root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement ).classList.contains( "selected" ),
    true, "precondition: the click painted its highlight before the POST settled",
  );
  await flush();
  const up = h.root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement;
  assert.equal( up.classList.contains( "selected" ), false, "a failed cast kept the highlight" );
  assert.equal( h.voteStore.getVote( "ar-1" ), undefined );
  h.renderer.unmount();
} );

test( "a cast the store declines (resolves false) drops the optimistic highlight too", async () => {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const items = [ makeItem( "ar-1", AT_GATE ) ];
  const root  = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createActionRequiredRenderer( {
    eventBus : bus,
    stores   : { actionRequired: { list: () => items, getById: () => items[ 0 ], respondAndAwait: async () => {} } },
    predictionVoteStore : { getVote: () => undefined, setContext: () => {}, vote: async () => false },
  } );
  renderer.mount( root );
  ( root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement ).click();
  await flush();
  assert.equal( ( root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement ).classList.contains( "selected" ), false );
  renderer.unmount();
} );

test( "an explicit integration wins over the store: the click goes to it and nothing is POSTed", () => {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const calls : Array<[ string, string ]> = [];
  const items = [ makeItem( "ar-1", AT_GATE ) ];
  const root  = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createActionRequiredRenderer( {
    eventBus : bus,
    stores   : { actionRequired: { list: () => items, getById: () => items[ 0 ], respondAndAwait: async () => {} } },
    predictionVote : { getVote: () => undefined, onVote: ( id, dir ) => { calls.push( [ id, dir ] ); } },
    predictionVoteStore : createPredictionVoteStore( { bus, api: { post: async () => { throw new Error( "must not POST" ); } } } ),
  } );
  renderer.mount( root );
  ( root.querySelector( '[data-testid="prediction-vote-up"]' ) as HTMLElement ).click();
  assert.deepEqual( calls, [ [ "ar-1", "up" ] ] );
  renderer.unmount();
} );

// A source pin: boot.ts runs bootMultiplexer() at import, so the wiring cannot be driven from node.
// Resolved from this file, never from LUPIN_ROOT, so a worktree reads its own boot.ts.
const BOOT_CODE = readFileSync(
  resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../../lupin_app/static/js/multiplexer/boot.ts" ),
  "utf8",
).split( "\n" ).filter( ( line ) => !line.trimStart().startsWith( "//" ) ).join( "\n" );

test( "boot hands the action-required renderer the prediction vote store", () => {
  const calls = [ ...BOOT_CODE.matchAll( /createActionRequiredRenderer\(\{([\s\S]*?)\n\s*\}\);/g ) ];
  assert.equal( calls.length, 1, `expected exactly one createActionRequiredRenderer({ … }) call, found ${calls.length}` );
  assert.match( ( calls[ 0 ] as RegExpMatchArray )[ 1 ] as string, /\bpredictionVoteStore\s*:\s*stores\.predictionVote\s*,/ );
} );
