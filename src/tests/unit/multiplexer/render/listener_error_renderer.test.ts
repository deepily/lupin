// Row 8033756c — the default `listener_error` subscriber.
//
// THE BAR THESE CASES HAVE TO CLEAR, and why the obvious ones do not.
// Before this change, "the bus survived a throwing listener" and "the sibling
// listeners still ran" were BOTH already true, and both already tested. They
// stayed green through the entire life of the defect, while a total render
// failure produced zero output anywhere. So neither is evidence of anything
// here. What has to be asserted is the OBSERVATION: that a diagnostic reached a
// sink, and that something appeared on the page.
//
// THE TWO OBSERVABLES ARE IN SEPARATE TESTS, DELIBERATELY (Rachel 🕊️'s gate).
// One test covering both cannot tell you which half died — and the mutation arm
// for this row deletes the subscriber, which kills both at once. Split, the arm
// names two casualties and each is individually re-checkable.
//
// Run via:
//   npx tsx --test src/tests/unit/multiplexer/render/listener_error_renderer.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createListenerErrorRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ListenerErrorRenderer";
import type { ListenerErrorRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ListenerErrorRenderer";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { LupinEvent } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
} );

beforeEach( () => {
  document.body.replaceChildren();
} );

interface SinkLine { message: string; args: unknown[] }

interface Harness {
  bus      : ReturnType<typeof createEventBusForTesting>;
  renderer : ListenerErrorRenderer;
  root     : HTMLElement;
  sink     : SinkLine[];
}

function setup( opts: { root?: HTMLElement } = {} ): Harness {
  const bus  = createEventBusForTesting();
  const sink : SinkLine[] = [];
  const root = opts.root ?? document.createElement( "div" );
  if ( opts.root === undefined ) document.body.appendChild( root );
  const renderer = createListenerErrorRenderer( {
    eventBus : bus as unknown as EventBus,
    sink     : ( message: string, ...args: unknown[] ) => { sink.push( { message, args } ); },
  } );
  renderer.mount( root );
  return { bus, renderer, root, sink };
}

/**
 * Register a listener that throws, then emit the event that reaches it.
 *
 * This is the REAL path, not a hand-built `listener_error`: the bus's own
 * wrapper catches the throw and re-emits. A test that emitted `listener_error`
 * directly would pass even if the bus stopped producing it.
 */
function makeAListenerThrow( bus: Harness[ "bus" ], eventType = "store_senders_changed", message = "boom" ): void {
  // ⚠️ UNSUBSCRIBE AFTERWARDS, and this is not tidiness. An early cut of this
  // helper left each throwing listener registered, so the Nth call fired N
  // throws and a five-error case counted 15 — the helper, not the renderer.
  // The count assertions are exact for exactly this reason: a >= would have
  // passed and left the helper's leak in place for every later reader.
  const off = bus.on( eventType as never, () => { throw new Error( message ); } );
  bus.emit( { type: eventType as never, payload: { changeKind: "updated" }, source: "test", ts: 0 } );
  off();
}

function badge(): HTMLElement | null {
  return document.querySelector<HTMLElement>( '[data-testid="multiplexer-listener-error-badge"]' );
}

// ===========================================================================
// Observable 1 — the diagnostic
// ===========================================================================

test( "a throwing listener writes a diagnostic naming the ORIGINATING EVENT TYPE", () => {
  const h = setup();
  makeAListenerThrow( h.bus, "store_senders_changed", "Cannot read properties of null" );

  assert.equal( h.sink.length, 1, "exactly one diagnostic per throw" );
  // The event type is the assertion that matters. "Cannot read properties of
  // null" on its own is unactionable; WHICH event carried it is the first thing
  // a reader needs, and it is what was missing on row 275e5c57.
  assert.match( h.sink[ 0 ].message, /store_senders_changed/ );
  assert.match( h.sink[ 0 ].message, /Cannot read properties of null/ );
} );

test( "the diagnostic carries the original event object for the console, not just a string", () => {
  const h = setup();
  makeAListenerThrow( h.bus, "store_senders_changed" );
  const original = h.sink[ 0 ].args[ 0 ] as LupinEvent<unknown> | undefined;
  assert.notEqual( original, undefined, "the original event is passed through as an arg" );
  assert.equal( original!.type, "store_senders_changed" );
} );

test( "a second throw on a DIFFERENT event names that second type, not the first", () => {
  // A cached-first-value bug would pass the single-throw case above forever.
  const h = setup();
  makeAListenerThrow( h.bus, "store_senders_changed" );
  makeAListenerThrow( h.bus, "store_notifications_changed" );
  assert.equal( h.sink.length, 2 );
  assert.match( h.sink[ 1 ].message, /store_notifications_changed/ );
} );

// ===========================================================================
// Observable 2 — the on-page indicator (Rick's addition to the ruling)
// ===========================================================================

test( "a throwing listener puts an indicator ON THE PAGE", () => {
  const h = setup();
  assert.equal( badge(), null, "precondition: nothing on the page before the throw" );

  makeAListenerThrow( h.bus );

  const el = badge();
  assert.notEqual( el, null, "the user must be able to SEE that something broke" );
  assert.match( el!.textContent ?? "", /1 display error/ );
} );

test( "the indicator names the originating event type too — the page, not only the console", () => {
  const h = setup();
  makeAListenerThrow( h.bus, "store_senders_changed" );
  assert.match( badge()!.textContent ?? "", /store_senders_changed/ );
} );

test( "the indicator is announced politely, never as an interrupt", () => {
  const h = setup();
  makeAListenerThrow( h.bus );
  assert.equal( badge()!.getAttribute( "role" ), "status" );
  assert.equal( badge()!.getAttribute( "aria-live" ), "polite" );
} );

// ===========================================================================
// It must not stack or flap — the ruling's words
// ===========================================================================

test( "repeated errors UPDATE one indicator and count, they do not pile up", () => {
  const h = setup();
  for ( let i = 0; i < 5; i++ ) makeAListenerThrow( h.bus );

  const all = document.querySelectorAll( '[data-testid="multiplexer-listener-error-badge"]' );
  assert.equal( all.length, 1, "one element, however many errors" );
  assert.match( badge()!.textContent ?? "", /5 display errors/ );
  assert.equal( badge()!.getAttribute( "data-error-count" ), "5" );
} );

test( "the count reads singular at one and plural above it", () => {
  const h = setup();
  makeAListenerThrow( h.bus );
  assert.match( badge()!.textContent ?? "", /1 display error\b/ );
  makeAListenerThrow( h.bus );
  assert.match( badge()!.textContent ?? "", /2 display errors/ );
} );

test( "dismiss clears the indicator AND resets the count, so the next error reads 1", () => {
  const h = setup();
  makeAListenerThrow( h.bus );
  makeAListenerThrow( h.bus );
  assert.equal( h.renderer.countForTesting(), 2 );

  badge()!.querySelector<HTMLButtonElement>( ".listener-error-dismiss" )!.click();
  assert.equal( badge(), null, "dismissed" );
  assert.equal( h.renderer.countForTesting(), 0 );

  // A count that kept climbing after a dismiss would make the badge read "3"
  // for what the user experiences as the first error since they cleared it.
  makeAListenerThrow( h.bus );
  assert.match( badge()!.textContent ?? "", /1 display error\b/ );
} );

// ===========================================================================
// 🔴 THE SUBSCRIBER MUST NOT BE ABLE TO DIE SILENTLY
//
// EventBus's recursion guard returns early when the original event is itself a
// `listener_error`, with no trace. This subscriber IS such a listener and it
// touches the DOM, so a throw here would erase the whole control and leave the
// suite green. Asserted, not reasoned about (Rachel's gate item 3).
// ===========================================================================

test( "a DOM that throws does not take the subscriber down, and the console still gets the line", () => {
  const hostileRoot = document.createElement( "div" );
  document.body.appendChild( hostileRoot );
  ( hostileRoot as unknown as { replaceChildren: () => void } ).replaceChildren = (): void => {
    throw new Error( "DOM is on fire" );
  };

  const h = setup( { root: hostileRoot } );

  const consoleErrors: string[] = [];
  const realConsoleError = console.error;
  console.error = ( ...a: unknown[] ): void => { consoleErrors.push( String( a[ 0 ] ) ); };
  try {
    // Must not propagate. If it did, the bus's recursion guard would eat it and
    // nothing anywhere would record that the reporter itself had failed.
    assert.doesNotThrow( () => makeAListenerThrow( h.bus ) );
  } finally {
    console.error = realConsoleError;
  }

  assert.equal( h.sink.length, 1, "the diagnostic went out BEFORE the DOM write was attempted" );
  assert.ok(
    consoleErrors.some( ( line ) => line.includes( "the listener-error reporter itself failed" ) ),
    `the last-resort write must fire when the DOM throws. Saw: ${ JSON.stringify( consoleErrors ) }`,
  );
} );

test( "a sink that throws is survived too — the reporter has no un-guarded path", () => {
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createListenerErrorRenderer( {
    eventBus : bus as unknown as EventBus,
    sink     : (): void => { throw new Error( "sink is down" ); },
  } );
  renderer.mount( root );

  const consoleErrors: string[] = [];
  const realConsoleError = console.error;
  console.error = ( ...a: unknown[] ): void => { consoleErrors.push( String( a[ 0 ] ) ); };
  try {
    assert.doesNotThrow( () => makeAListenerThrow( bus as unknown as Harness[ "bus" ] ) );
  } finally {
    console.error = realConsoleError;
  }
  assert.ok( consoleErrors.some( ( l ) => l.includes( "the listener-error reporter itself failed" ) ) );
} );

// ===========================================================================
// The DEFAULT sink — the one production actually uses
// ===========================================================================

test( "with no sink injected it writes through the house writer, which tees to the debug panel", () => {
  // Every other case in this file injects a spy, so none of them exercises the
  // arm that ships. The default is debugSink.error deliberately and not a bare
  // console.error: it writes to the console AND to the in-page debug panel, so
  // an operator without devtools open still has somewhere to read the line.
  // Pinned by the `[Notifications ERROR]` prefix, which is debugSink's and
  // nothing else's.
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createListenerErrorRenderer( { eventBus: bus as unknown as EventBus } );
  renderer.mount( root );

  const lines: string[] = [];
  const realConsoleError = console.error;
  console.error = ( ...a: unknown[] ): void => { lines.push( String( a[ 0 ] ) ); };
  try {
    makeAListenerThrow( bus as unknown as Harness[ "bus" ], "store_senders_changed", "default-sink probe" );
  } finally {
    console.error = realConsoleError;
  }

  assert.ok(
    lines.some( ( l ) => l.startsWith( "[Notifications ERROR]" ) && l.includes( "store_senders_changed" ) ),
    `expected a debugSink-prefixed line naming the event type. Saw: ${ JSON.stringify( lines ) }`,
  );
  assert.notEqual( badge(), null, "the indicator still paints on the default path" );
  renderer.unmount();
} );

// ===========================================================================
// Lifecycle — the house contract every other renderer holds
// ===========================================================================

test( "a second mount throws", () => {
  const h = setup();
  assert.throws( () => h.renderer.mount( h.root ), /already mounted/ );
} );

test( "unmount unsubscribes, clears the root, resets the count, and is idempotent", () => {
  const h = setup();
  makeAListenerThrow( h.bus );
  assert.notEqual( badge(), null );

  h.renderer.unmount();
  assert.equal( badge(), null );
  assert.equal( h.renderer.countForTesting(), 0 );

  // The subscription is really gone: a further throw reaches neither observable.
  const before = h.sink.length;
  makeAListenerThrow( h.bus );
  assert.equal( h.sink.length, before, "no diagnostic after unmount" );
  assert.equal( badge(), null, "no indicator after unmount" );

  h.renderer.unmount();   // idempotent
} );

// ===========================================================================
// 🔴 BOOT ACTUALLY MOUNTS IT — a component can be complete, correct, fully
// covered and never mounted, and every test above stays green.
//
// THIS EXISTS BECAUSE A MUTATION ARM SURVIVED. Deleting boot's
// `listenerErrorRenderer.mount(...)` call reddened NOTHING: 33/33 green. The
// existing boot guards sweep `getElementById("…")` ids and the handshake lists,
// so they see the id resolved and the name declared, and never ask whether
// mount() was called. That gap is general — it covers all 28 renderers, not
// just this one — and is reported separately; this case closes it for the one
// renderer whose whole job is to be watching when something else breaks.
// ===========================================================================

test( "boot resolves the mount point AND calls mount() on the renderer", () => {
  const boot = readFileSync(
    resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../../lupin_app/static/js/multiplexer/boot.ts" ),
    "utf8",
  );
  // Comment lines dropped: boot.ts carries a copy-verbatim handshake block in
  // comments, and a hit there is a NAME, not a USE.
  const live = boot.split( "\n" ).filter( ( l ) => !l.trimStart().startsWith( "//" ) ).join( "\n" );

  // Positive control: the sweep can see a mount call that is definitely there.
  assert.match( live, /missedBadgeRenderer\.mount\(/, "the sweep is not reaching boot's mount calls" );

  assert.match( live, /getElementById\(\s*"listener-error-mount"\s*\)/ );
  assert.match(
    live, /listenerErrorRenderer\.mount\(/,
    "boot constructs the renderer but never mounts it — it would subscribe to nothing and the page would be silent again",
  );
} );

// ===========================================================================
// The producer the in-bus shape would have missed
// ===========================================================================

test( "a `listener_error` emitted from OUTSIDE the bus wrapper is caught all the same", () => {
  // NotificationsListRenderer emits this itself from a microtask catch, because
  // a microtask has no bus wrapper. A console.error added inside the bus's
  // handleListenerError would not see this at all — which is the entire reason
  // the subscriber is at boot. Emitted here exactly as that producer emits it.
  const h = setup();
  h.bus.emit( {
    type    : "listener_error" as never,
    payload : {
      originalEvent : { type: "store_notifications_changed", payload: {}, source: "test", ts: 0 },
      error         : "render blew up in a microtask",
    },
    source  : "NotificationsListRenderer",
    ts      : 0,
  } );

  assert.equal( h.sink.length, 1 );
  assert.match( h.sink[ 0 ].message, /store_notifications_changed/ );
  assert.notEqual( badge(), null, "the out-of-band producer reaches the page too" );
} );

test( "a payload with no originalEvent degrades to 'unknown' rather than throwing", () => {
  const h = setup();
  h.bus.emit( {
    type    : "listener_error" as never,
    payload : { originalEvent: null, error: "no context" },
    source  : "test",
    ts      : 0,
  } );
  assert.match( h.sink[ 0 ].message, /unknown/ );
  assert.match( badge()!.textContent ?? "", /unknown/ );
} );
