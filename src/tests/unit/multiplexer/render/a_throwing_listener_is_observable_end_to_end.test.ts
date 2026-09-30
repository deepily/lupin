// Row 8033756c, TESTER leg — a throwing listener must be OBSERVABLE, in BOTH
// channels, through the REAL wiring. Written by Sam 🎙️ 2026-09-26.
//
// WHAT THIS ADDS OVER listener_error_renderer.test.ts. That file is the unit
// gate and it injects a `sink` spy, which is the right call for asserting the
// renderer's own logic. But injecting the sink means the DEFAULT sink is never
// exercised, and the default sink is the entire console half of the row's
// requirement §3 ("a test that proves a throwing listener is now observable").
// So here the renderer is built with NO sink — the production default — and the
// assertion is made against the real `console.error`, patched at the global.
//
// 🔴 THE POINT OF ENTRY IS THE THROW, NOT THE EVENT. Nothing below emits
// `listener_error` by hand. A listener is registered that throws, an ORDINARY
// event is emitted, and the assertions read what an operator would see. Emitting
// `listener_error` directly would assert the subscriber works while leaving the
// producer side — EventBus's catch — completely unmeasured, and the producer is
// half of what row 8033756c is about.
//
// 🔴 AND THE SECOND PRODUCER IS COVERED TOO. The surface is 2 emitters, not 1:
// EventBus.handleListenerError, and NotificationsListRenderer's microtask catch,
// which re-emits `listener_error` from OUTSIDE any bus wrapper. A fix that only
// reached the in-bus path would leave the microtask path silent and the row half
// done. The last test reproduces that emitter's exact shape.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createListenerErrorRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ListenerErrorRenderer";
import type { ListenerErrorRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ListenerErrorRenderer";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { ListenerErrorPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

const BADGE = '[data-testid="multiplexer-listener-error-badge"]';

let bus       : EventBus;
let renderer  : ListenerErrorRenderer;
let mount     : HTMLElement;
let consoleErrorCalls: string[];
let realConsoleError: typeof console.error;

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
} );

beforeEach( () => {
  document.body.replaceChildren();
  mount    = document.createElement( "div" );
  mount.id = "listener-error-mount";
  document.body.appendChild( mount );

  bus = createEventBusForTesting();
  // No `sink` — the production default (debugSink.error → console.error).
  renderer = createListenerErrorRenderer( { eventBus: bus } );
  renderer.mount( mount );

  consoleErrorCalls = [];
  realConsoleError  = console.error;
  console.error     = ( ...args: unknown[] ): void => {
    consoleErrorCalls.push( args.map( ( a ) => String( a ) ).join( " " ) );
  };
} );

afterEach( () => {
  console.error = realConsoleError;
  renderer.unmount();
} );

function badge(): HTMLElement | null {
  return document.querySelector( BADGE );
}

// ---------------------------------------------------------------------------
// The control. Without it, every assertion below is satisfiable by a renderer
// that paints a badge unconditionally on mount.
// ---------------------------------------------------------------------------

test( "control: a listener that does NOT throw leaves both channels silent", () => {
  bus.on( "notification_arrived", () => { /* well-behaved */ } );
  bus.emit( { type: "notification_arrived", payload: {}, source: "test", ts: Date.now() } );

  assert.equal( badge(), null, "no badge should exist when nothing threw" );
  assert.deepEqual( consoleErrorCalls, [], "console.error must not be called when nothing threw" );
} );

// ---------------------------------------------------------------------------
// The row's requirement, both channels, from a real throw.
// ---------------------------------------------------------------------------

test( "a throwing listener produces a console.error line naming the failure", () => {
  bus.on( "notification_arrived", () => {
    throw new TypeError( "Cannot read properties of null (reading 'borrowed')" );
  } );
  bus.emit( { type: "notification_arrived", payload: {}, source: "test", ts: Date.now() } );

  assert.equal( consoleErrorCalls.length, 1, "exactly one console.error line" );
  const line = consoleErrorCalls[ 0 ];
  assert.match( line, /Cannot read properties of null \(reading 'borrowed'\)/,
    "the console line must carry the original error text — the 2026-09-22 incident's exact message" );
  assert.match( line, /notification_arrived/,
    "and must name the event whose listener threw, or the reader cannot locate it" );
} );

test( "the same throw also paints a badge the operator can see", () => {
  bus.on( "notification_arrived", () => { throw new Error( "render exploded" ); } );
  bus.emit( { type: "notification_arrived", payload: {}, source: "test", ts: Date.now() } );

  const el = badge();
  assert.notEqual( el, null, "a badge must be in the DOM after a listener throws" );
  assert.match( el!.textContent ?? "", /notification_arrived/,
    "the badge must name the event, not just say 'an error occurred'" );
} );

test( "two throws are counted, not collapsed into one badge that says 1", () => {
  bus.on( "notification_arrived", () => { throw new Error( "first" ); } );
  bus.emit( { type: "notification_arrived", payload: {}, source: "test", ts: Date.now() } );
  bus.emit( { type: "notification_arrived", payload: {}, source: "test", ts: Date.now() } );

  assert.equal( renderer.countForTesting(), 2, "both throws counted" );
  assert.equal( consoleErrorCalls.length, 2, "both throws reached the console" );
} );

// ---------------------------------------------------------------------------
// The second producer. Sam's finding, 2026-09-26: the surface is 2 emitters.
// ---------------------------------------------------------------------------

test( "the microtask producer reaches the same subscriber — NotificationsListRenderer's shape", () => {
  // NotificationsListRenderer.ts catches its own microtask throw and re-emits
  // `listener_error` directly, outside any bus wrapper. Reproduced verbatim in
  // shape so a fix that only touched EventBus would fail here.
  const trigger = { type: "notification_arrived" as const, payload: {}, source: "test", ts: Date.now() };
  try {
    throw new Error( "microtask render exploded" );
  } catch ( err ) {
    bus.emit<ListenerErrorPayload>( {
      type    : "listener_error",
      payload : { originalEvent: trigger, error: err instanceof Error ? err.message : String( err ) },
      source  : "NotificationsListRenderer",
      ts      : Date.now(),
    } );
  }

  assert.equal( consoleErrorCalls.length, 1, "the out-of-bus emitter must reach the console too" );
  assert.match( consoleErrorCalls[ 0 ], /microtask render exploded/ );
  assert.notEqual( badge(), null, "and must paint the badge — otherwise this path stays silent" );
} );
