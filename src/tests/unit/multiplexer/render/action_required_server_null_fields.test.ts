// Multiplexer — an Action Required card fed the server's REAL frame, where an unsupplied field is null, not absent.
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_server_null_fields.test.ts
//
// Row 759250e4. The three e2e asks (ts-2fdb5363) reached the store and no card painted. MEASURED on the wire:
// the :8000 server logged "conf=0.000, hint=no" for the failing ask, and its to_dict() carried `prediction_hint: None`
// (and `response_default: None`, `voice_persona: None`, `abstract: ""` — routers/notifications.py:1025 coerces it).
// The store admitted the null on `!== undefined`; predictionHintBox then read `predicted_value` through it. EventBus wraps
// every listener in a try/catch, so the throw landed as a `listener_error` and nothing reached the console. Same defect
// class as 0420f38f0 (voice_persona), which fixed one field of the five nullable ones.
//
// REAL store, REAL renderer, REAL bus; only the clock and the timers are fakes. Each arm names one null field, so a
// red names the field that broke the card.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createActionRequiredStore } from "../../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import { createActionRequiredRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type { ListenerErrorPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

const FIXTURE = JSON.parse(
  readFileSync( new URL( "../fixtures/notification_queue_update_no_persona.json", import.meta.url ), "utf8" ),
) as { frame: { queue_name: string; value: number; notification: Record<string, unknown> } };

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => {
  ( globalThis as { marked?: unknown } ).marked       = { parse: ( s: string ) => `<p>${ s }</p>` };
  ( globalThis as { DOMPurify?: unknown } ).DOMPurify = { sanitize: ( s: string ) => s };
} );

// The frame the e2e ask produces: the fixture's real to_dict() shape, made response-required the way the test's
// POST /api/notify (response_requested=true, response_type=yes_no, timeout_seconds=120) makes it.
function askFrame( overrides: Record<string, unknown> = {} ) {
  const frame = structuredClone( FIXTURE.frame );
  Object.assign( frame.notification, {
    id                 : "ask-null-fields",
    id_hash            : "ask-null-fields",
    response_requested : true,
    response_type      : "yes_no",
    timeout_seconds    : 120,
    abstract           : "",     // routers/notifications.py:1025 `abstract = abstract or ""` — a real ask never carries null here
  }, overrides );
  return frame;
}

function paint( frame: ReturnType<typeof askFrame> ) {
  const bus    = createEventBusForTesting();
  const errors : ListenerErrorPayload[] = [];
  bus.on<ListenerErrorPayload>( "listener_error", ( e ) => errors.push( e.payload ) );
  const store = createActionRequiredStore( {
    bus,
    api             : { post: async () => ( { ok: true } ) },
    setIntervalFn   : () => 0,
    clearIntervalFn : () => {},
    setTimeoutFn    : () => 0,
    clearTimeoutFn  : () => {},
    nowFn           : () => 1_700_000_000_000,
  } );
  const root     = document.createElement( "div" );
  const renderer = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store } } );
  renderer.mount( root );
  bus.emit( { type: "notification_queue_update", payload: frame, ts: 0 } as never );
  return { root, errors, store };
}

function widgetFor( root: HTMLElement, id: string ): Element | null {
  return root.querySelector( `[data-testid="multiplexer-action-required"][data-id-hash="${ id }"]` );
}

function assertPainted( frame: ReturnType<typeof askFrame>, field: string ): void {
  const { root, errors, store } = paint( frame );
  assert.equal( store.list().length, 1, "the store took the ask (delivery is not what is under test)" );
  assert.deepEqual( errors.map( ( e ) => String( ( e as { error?: unknown } ).error ) ), [],
    `a listener threw while painting an ask whose ${ field } is null` );
  assert.ok( widgetFor( root, "ask-null-fields" ) !== null,
    `no card carries the ask's data-id-hash when ${ field } is null` );
}

test( "the server's own ask frame paints a card (every unsupplied field is null)", () => {
  assertPainted( askFrame(), "unsupplied fields" );
} );

test( "abstract: null (not what /api/notify sends, but a legal frame) still paints the card", () => {
  assertPainted( askFrame( { abstract: null } ), "abstract" );
} );

test( "prediction_hint: null (the ROOT CAUSE: no confident hint) still paints the card", () => {
  assertPainted( askFrame( { prediction_hint: null } ), "prediction_hint" );
} );

test( "a null hint is shown as the cold-start ghost box, not dropped and not thrown", () => {
  const { root } = paint( askFrame( { prediction_hint: null } ) );
  assert.ok( root.querySelector( ".prediction-hint-cold" ) !== null, "the card has no cold-start box" );
} );

test( "response_default: null still paints the card and leaves the item with no default", () => {
  const frame = askFrame( { response_default: null } );
  assertPainted( frame, "response_default" );
  assert.equal( paint( frame ).store.list()[ 0 ]!.default, undefined, "a null default must not enter the store" );
} );

test( "sender_id: null still paints the card", () => {
  assertPainted( askFrame( { sender_id: null } ), "sender_id" );
} );
