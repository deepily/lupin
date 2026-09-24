// Multiplexer — BroadcastAckTallyRenderer tests (row 4f320c27 M1).
// Run via `npx tsx --test src/tests/unit/multiplexer/render/broadcast_ack_tally_renderer.test.ts`.
//
// Coverage target: 100% lines/branches/functions on BroadcastAckTallyRenderer.ts.
// Uses the REAL AckStore, the REAL BroadcastStore and the REAL EventBus with an
// in-memory StorageService, plus injected timers. The renderer's whole live path is
// a bus subscription onto a store fold; stubbing either end would leave a fixture
// that answers the same however the renderer behaves.
//
// 🔴 THE LEGACY STRINGS ARE THE CONTRACT. `broadcast-panel.js` is what the user has
// been reading, so the summary wording, the fallbacks (👤 / the session id's first
// eight / "[?]") and the "waiting on:" line are asserted verbatim rather than
// paraphrased. A port that renders the same DATA in different WORDS is a change the
// user sees and no test would catch.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createAckStore } from "../../../../lupin_app/static/js/multiplexer/stores/AckStore";
import { createBroadcastStore } from "../../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import { createBroadcastAckTallyRenderer } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastAckTallyRenderer";
import type { BroadcastAckTallyRenderer } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastAckTallyRenderer";
import type { AckStore } from "../../../../lupin_app/static/js/multiplexer/stores/AckStore";
import type { BroadcastStore, BroadcastRecipient } from "../../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import { COMMONS_BROADCAST_ACK_TYPE } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const BCAST = "22222222-bbbb-4ccc-8ddd-333333333333";
const OTHER = "99999999-cccc-4ddd-8eee-444444444444";

const THREE: BroadcastRecipient[] = [
  { session_id: "s1aaaaaa-1111", persona_name: "Mr. Radio", persona_icon: "🦉", persona_color: "#FFA000" },
  { session_id: "s2bbbbbb-2222", persona_name: "María",     persona_icon: "🌸", persona_color: "#F48FB1" },
  { session_id: "s3cccccc-3333", persona_name: null,        persona_icon: null, persona_color: null },
];

function makeTimers() {
  let nextId = 1;
  const q: { id: number; cb: () => void }[] = [];
  return {
    setTimeoutFn: ( ( cb: () => void ): unknown => { const e = { id: nextId++, cb }; q.push( e ); return e.id; } ) as ( cb: () => void, ms: number ) => unknown,
    clearTimeoutFn: ( ( id: unknown ): void => { const i = q.findIndex( e => e.id === id ); if ( i >= 0 ) q.splice( i, 1 ); } ) as ( id: unknown ) => void,
    fire(): void { const e = q.shift(); if ( e ) e.cb(); },
    pending(): number { return q.length; },
  };
}

let mounted: BroadcastAckTallyRenderer | null = null;

function setup( recipients: BroadcastRecipient[] = THREE ) {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting();
  const ackStore = createAckStore( { bus } );
  const bStore   = createBroadcastStore( { storage } );
  const timers   = makeTimers();
  const root     = document.createElement( "div" );
  document.body.appendChild( root );

  // The REAL BroadcastStore, filled through its real hydrate seam.
  const hydrated = bStore.hydrate( { get<T>( _p: string ): Promise<T> {
    return Promise.resolve( { sessions: recipients } as T );
  } } );

  const renderer = createBroadcastAckTallyRenderer( {
    eventBus: bus, ackStore, broadcastStore: bStore,
    timeoutMs: 5 * 60 * 1000, setTimeoutFn: timers.setTimeoutFn, clearTimeoutFn: timers.clearTimeoutFn,
  } );
  mounted = renderer;
  // 🔴 EVERY TEST BELOW MUST SAY THE ROSTER IS KNOWN, because until the card's first
  // recipient fetch lands it is UNKNOWN, not empty — and a renderer that has not been
  // told cannot print a denominator. Declared through the public seam the card uses, so
  // these tests exercise the same path production does rather than a back door.
  const announceRecipients = () => renderer.recipientsChanged();
  return { bus, ackStore, bStore, renderer, root, timers, hydrated, announceRecipients };
}

function liveAck( bus: ReturnType<typeof createEventBusForTesting>, fields: Record<string, unknown> ): void {
  bus.emit( { type: COMMONS_BROADCAST_ACK_TYPE, payload: { broadcast_id: BCAST, ...fields }, source: "test", ts: 0 } );
}

function txt( root: HTMLElement, testid: string ): string | null {
  const n = root.querySelector( `[data-testid="${testid}"]` );
  return n ? n.textContent : null;
}

afterEach( () => {
  if ( mounted ) { mounted.unmount(); mounted = null; }
  document.body.replaceChildren();
} );

// ===========================================================================
// Mount / track / dismiss
// ===========================================================================

test( "a mounted renderer tracking nothing renders nothing", async () => {
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  assert.equal( renderer.trackedBroadcastId(), null );
  assert.equal( root.querySelector( '[data-testid="broadcast-ack-tally"]' ), null );
} );

test( "a second mount throws rather than silently double-subscribing", async () => {
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  assert.throws( () => renderer.mount( root ), /already mounted/ );
} );

test( "track() renders the tally and reports the tracked id", async () => {
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  assert.equal( renderer.trackedBroadcastId(), BCAST );
  assert.equal( txt( root, "broadcast-ack-summary" ), "0/3 complete" );
} );

test( "🔴 track() BEFORE mount() still paints once mounted", async () => {
  // Order matters in production: the send completes (track) and the panel may mount
  // after. A renderer that only painted from track() would show an empty panel.
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.track( BCAST );
  renderer.mount( root ); renderer.recipientsChanged();
  assert.equal( txt( root, "broadcast-ack-summary" ), "0/3 complete" );
} );

test( "dismiss() empties the panel and forgets the broadcast", async () => {
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  renderer.dismiss();
  assert.equal( renderer.trackedBroadcastId(), null );
  assert.equal( root.querySelector( '[data-testid="broadcast-ack-tally"]' ), null );
} );

test( "dismiss() cancels the pending timeout — a dismissed tally cannot come back", async () => {
  const { renderer, root, timers, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  assert.equal( timers.pending(), 1 );
  renderer.dismiss();
  assert.equal( timers.pending(), 0 );
} );

test( "re-tracking replaces the previous timer rather than leaving two running", async () => {
  const { renderer, root, timers, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  renderer.track( OTHER );
  assert.equal( timers.pending(), 1, "the first broadcast's deadline must not survive" );
  assert.equal( renderer.trackedBroadcastId(), OTHER );
} );

// ===========================================================================
// The live fold drives repaints
// ===========================================================================

test( "a live ack repaints the tally", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111", persona_name: "Mr. Radio", persona_icon: "🦉", status: "completed", body_summary: "on it" } );
  assert.equal( txt( root, "broadcast-ack-summary" ), "1/3 complete" );
  stop();
} );

test( "🔴 ANOTHER BROADCAST'S ACK DOES NOT REPAINT THIS TALLY", async () => {
  // Two cards can be open. A tally that repainted on any ack would flicker, and
  // worse, would read its own counts at a moment it had no reason to.
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  bus.emit( { type: COMMONS_BROADCAST_ACK_TYPE, payload: { broadcast_id: OTHER, session_id: "x" }, source: "test", ts: 0 } );
  assert.equal( txt( root, "broadcast-ack-summary" ), "0/3 complete" );
  stop();
} );

// ===========================================================================
// The legacy summary strings, verbatim
// ===========================================================================

test( "PARTIAL reads `R/E complete`", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  liveAck( bus, { session_id: "s2bbbbbb-2222" } );
  assert.equal( txt( root, "broadcast-ack-summary" ), "2/3 complete" );
  stop();
} );

test( "COMPLETE reads `✅ All N sessions acknowledged`", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  THREE.forEach( r => liveAck( bus, { session_id: r.session_id } ) );
  assert.equal( txt( root, "broadcast-ack-summary" ), "✅ All 3 sessions acknowledged" );
  stop();
} );

test( "COMPLETE with ONE expected session is SINGULAR — `1 session`, not `1 sessions`", async () => {
  const one = [ THREE[ 0 ]! ];
  const { bus, ackStore, renderer, root, hydrated } = setup( one );
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: one[ 0 ]!.session_id } );
  assert.equal( txt( root, "broadcast-ack-summary" ), "✅ All 1 session acknowledged" );
  stop();
} );

// ===========================================================================
// Timeout
// ===========================================================================

test( "🔴 A PARTIAL TALLY AT THE DEADLINE GOES TIMED-OUT AND STAYS ON SCREEN", async () => {
  const { bus, ackStore, renderer, root, timers, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  timers.fire();
  assert.equal( txt( root, "broadcast-ack-summary" ), "1/3 sessions acknowledged — 2 timed out" );
  assert.equal( root.querySelector( '[data-testid="broadcast-ack-tally"]' )!.getAttribute( "data-timed-out" ), "true" );
  assert.equal( root.classList.contains( "timed-out" ), true );
  stop();
} );

test( "a COMPLETE tally at the deadline is dismissed quietly", async () => {
  // Nothing left to report. Legacy dismisses rather than leaving a green panel up.
  const { bus, ackStore, renderer, root, timers, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  THREE.forEach( r => liveAck( bus, { session_id: r.session_id } ) );
  timers.fire();
  assert.equal( renderer.trackedBroadcastId(), null );
  assert.equal( root.querySelector( '[data-testid="broadcast-ack-tally"]' ), null );
  stop();
} );

test( "a deadline that fires after dismiss() is a no-op", async () => {
  const { renderer, root, timers, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  renderer.dismiss();
  timers.fire();  // the queue is empty — nothing to fire
  assert.equal( renderer.trackedBroadcastId(), null );
} );

test( "🔴 THE PENDING LIST DISAPPEARS ONCE TIMED OUT — `waiting on` stops being true", async () => {
  const { bus, ackStore, renderer, root, timers, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  assert.notEqual( txt( root, "broadcast-ack-pending" ), null, "precondition — it is shown while partial" );
  timers.fire();
  assert.equal( txt( root, "broadcast-ack-pending" ), null );
  stop();
} );

// ===========================================================================
// Ack rows + fallbacks (the legacy T10 textContent rule)
// ===========================================================================

test( "an ack row carries icon, persona, [status] and the summary", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111", persona_name: "Mr. Radio", persona_icon: "🦉", persona_color: "#FFA000", status: "completed", body_summary: "on it" } );

  const row = root.querySelector( '[data-testid="broadcast-ack-row"]' )!;
  assert.equal( row.querySelector( ".broadcast-ack-icon" )!.textContent, "🦉" );
  assert.equal( row.querySelector( ".broadcast-ack-persona" )!.textContent, "Mr. Radio" );
  assert.equal( row.querySelector( ".broadcast-ack-status" )!.textContent, "[completed]" );
  // The legacy CLASS for a row's body text (broadcast-panel.css:283). Asserted by the
  // name the stylesheet keys on, not a name of my own — a class nothing styles renders
  // unstyled and every textContent assertion still passes.
  assert.equal( row.querySelector( ".broadcast-ack-summary" )!.textContent, "on it" );
  assert.equal( row.getAttribute( "data-session-id" ), "s1aaaaaa-1111" );
  stop();
} );

test( "the legacy fallbacks: 👤, the session id's first eight, and [?]", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s3cccccc-3333" } );
  const row = root.querySelector( '[data-testid="broadcast-ack-row"]' )!;
  assert.equal( row.querySelector( ".broadcast-ack-icon" )!.textContent, "👤" );
  assert.equal( row.querySelector( ".broadcast-ack-persona" )!.textContent, "s3cccccc" );
  assert.equal( row.querySelector( ".broadcast-ack-status" )!.textContent, "[?]" );
  stop();
} );

test( "an UNATTRIBUTED ack (no session_id) renders without a data-session-id and reads `unknown`", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { persona_name: null } );
  const row = root.querySelector( '[data-testid="broadcast-ack-row"]' )!;
  assert.equal( row.hasAttribute( "data-session-id" ), false );
  assert.equal( row.querySelector( ".broadcast-ack-persona" )!.textContent, "unknown" );
  stop();
} );

test( "a persona colour styles the chip; an unattributed ack is left unstyled", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111", persona_color: "#FFA000" } );
  liveAck( bus, { session_id: "s2bbbbbb-2222" } );
  const icons = root.querySelectorAll( ".broadcast-ack-icon" );
  assert.match( ( icons[ 0 ] as HTMLElement ).style.color, /255,\s*160,\s*0|#FFA000/i );
  assert.equal( ( icons[ 1 ] as HTMLElement ).style.color, "" );
  stop();
} );

test( "🔴 SERVER TEXT IS RENDERED AS TEXT — an ack summary containing markup is not parsed", async () => {
  // body_summary and persona_name originate in another seat's payload. Legacy marked
  // this T10; the hazard is identical here, and an escaped-looking string in a diff is
  // not evidence — the assertion is that NO element was created from it.
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111", persona_name: "<img src=x onerror=alert(1)>", body_summary: "<script>alert(2)</script>" } );

  assert.equal( root.querySelector( "img" ), null, "the persona name must not become an element" );
  assert.equal( root.querySelector( "script" ), null, "the summary must not become an element" );
  assert.equal( root.querySelector( ".broadcast-ack-persona" )!.textContent, "<img src=x onerror=alert(1)>" );
  stop();
} );

// ===========================================================================
// The pending list
// ===========================================================================

test( "`waiting on:` names the un-acked seats, falling back to a short id", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  assert.equal( txt( root, "broadcast-ack-pending" ), "waiting on: María, s3cccccc" );
  stop();
} );

test( "no pending row once every expected seat has acked", async () => {
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  THREE.forEach( r => liveAck( bus, { session_id: r.session_id } ) );
  assert.equal( txt( root, "broadcast-ack-pending" ), null );
  stop();
} );

test( "an UNATTRIBUTED ack counts toward received but clears nobody from `waiting on`", async () => {
  // It genuinely cannot be matched to an expected seat. Naming a seat as answered on
  // the strength of an unattributable ack would be a guess presented as a fact.
  const { bus, ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { persona_name: "somebody" } );
  assert.equal( txt( root, "broadcast-ack-summary" ), "1/3 complete" );
  assert.equal( txt( root, "broadcast-ack-pending" ), "waiting on: Mr. Radio, María, s3cccccc" );
  stop();
} );

test( "MORE acks than expected shows no pending row and does not go negative", async () => {
  // A seat that acked and was then reaped leaves received > expected after a
  // recipient refresh. The panel must stay coherent rather than render "-1".
  const { bus, ackStore, renderer, root, hydrated } = setup( [ THREE[ 0 ]! ] );
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  liveAck( bus, { session_id: "s2bbbbbb-2222" } );
  assert.equal( txt( root, "broadcast-ack-summary" ), "2/1 complete" );
  assert.equal( txt( root, "broadcast-ack-pending" ), null );
  stop();
} );

// ===========================================================================
// 🔴 HYDRATION — the half legacy never had, and the reason the server work exists
// ===========================================================================

test( "🔴 A HYDRATED TALLY RENDERS WITHOUT A SINGLE LIVE ACK — this is what survives a reload", async () => {
  const { ackStore, renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  // No ackStore.start(): nothing live is subscribed, exactly as after a page reload.
  await ackStore.hydrate( { get<T>( _p: string ): Promise<T> {
    return Promise.resolve( { acks: [
      { session_id: "s1aaaaaa-1111", persona_name: "Mr. Radio", persona_icon: "🦉", ack_status: "completed", body_summary: "on it" },
      { session_id: "s2bbbbbb-2222", persona_name: "María", ack_status: "pending" },
    ] } as T );
  } }, BCAST );

  assert.equal( txt( root, "broadcast-ack-summary" ), "2/3 complete" );
  assert.equal( root.querySelectorAll( '[data-testid="broadcast-ack-row"]' ).length, 2 );
  assert.equal( txt( root, "broadcast-ack-pending" ), "waiting on: s3cccccc" );
} );

// ===========================================================================
// unmount
// ===========================================================================

test( "unmount clears the root, cancels the timer and stops repainting", async () => {
  const { bus, ackStore, renderer, root, timers, hydrated } = setup();
  await hydrated;
  const stop = ackStore.start();
  renderer.mount( root ); renderer.recipientsChanged(); renderer.track( BCAST );
  renderer.unmount();
  mounted = null;

  assert.equal( root.childNodes.length, 0 );
  assert.equal( timers.pending(), 0 );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  assert.equal( root.childNodes.length, 0, "an unmounted renderer must not repaint" );
  stop();
} );

test( "unmount is safe when nothing was ever mounted", () => {
  const { renderer } = setup();
  renderer.unmount();
  mounted = null;
  assert.equal( renderer.trackedBroadcastId(), null );
} );

test( "unmount twice is safe", async () => {
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.unmount();
  renderer.unmount();
  mounted = null;
  assert.equal( renderer.trackedBroadcastId(), null );
} );

test( "omitting `timeoutMs` uses the production default rather than no timer at all", async () => {
  // The default arm of `options.timeoutMs ?? DEFAULT_TIMEOUT_MS`, measured rather than
  // assumed: a renderer built without the option must still arm a deadline.
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting();
  const ackStore = createAckStore( { bus } );
  const bStore   = createBroadcastStore( { storage } );
  const timers   = makeTimers();
  const root     = document.createElement( "div" );
  document.body.appendChild( root );
  await bStore.hydrate( { get<T>( _p: string ): Promise<T> { return Promise.resolve( { sessions: THREE } as T ); } } );

  const renderer = createBroadcastAckTallyRenderer( {
    eventBus: bus, ackStore, broadcastStore: bStore,
    setTimeoutFn: timers.setTimeoutFn, clearTimeoutFn: timers.clearTimeoutFn,
  } );
  mounted = renderer;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  assert.equal( timers.pending(), 1, "a deadline must be armed even with no explicit timeoutMs" );
  timers.fire();
  assert.equal( txt( root, "broadcast-ack-summary" ), "0/3 sessions acknowledged — 3 timed out" );
} );

// ===========================================================================
// 🔴 THE RELOAD SEAM — persist the tracked id, restore it, replay the acks.
//
// Without this the server half buys nothing: the acks are persisted and AckStore can
// replay them, but on a fresh page nothing has called track(), so there is no
// broadcast id to replay them FOR. The id is the one piece of state the server cannot
// give back — it lives in the send that already happened.
//
// These tests simulate a reload the only way a unit test honestly can: a SECOND
// renderer over the SAME StorageService backend and a FRESH bus and AckStore, so
// nothing survives except what was written to storage. The Playwright case drives the
// real page.
// ===========================================================================

function storageBacked() {
  const storage = createStorageServiceForTesting();
  let now = 1_700_000_000_000;
  const mk = ( opts: { api?: { acks: unknown[] } | Error; nowOffset?: number } = {} ) => {
    const bus      = createEventBusForTesting();
    const ackStore = createAckStore( { bus } );
    const bStore   = createBroadcastStore( { storage } );
    const timers   = makeTimers();
    const root     = document.createElement( "div" );
    document.body.appendChild( root );
    const api = {
      get<T>( _p: string ): Promise<T> {
        if ( opts.api instanceof Error ) return Promise.reject( opts.api );
        return Promise.resolve( ( opts.api ?? { acks: [] } ) as T );
      },
    };
    const renderer = createBroadcastAckTallyRenderer( {
      eventBus: bus, ackStore, broadcastStore: bStore, storage, api,
      timeoutMs: 5 * 60 * 1000, setTimeoutFn: timers.setTimeoutFn, clearTimeoutFn: timers.clearTimeoutFn,
      nowFn: () => now + ( opts.nowOffset ?? 0 ),
    } );
    return { bus, ackStore, bStore, renderer, root, timers, api };
  };
  const hydrateRecipients = async ( bStore: BroadcastStore ) => {
    await bStore.hydrate( { get<T>( _p: string ): Promise<T> { return Promise.resolve( { sessions: THREE } as T ); } } );
  };
  return { storage, mk, hydrateRecipients };
}

const SAVED_ACKS = { acks: [
  { session_id: "s1aaaaaa-1111", persona_name: "Mr. Radio", persona_icon: "🦉", ack_status: "completed", body_summary: "on it" },
  { session_id: "s2bbbbbb-2222", persona_name: "María", ack_status: "pending" },
] };

test( "🔴 THE TALLY SURVIVES A RELOAD — a second renderer restores the id and replays the acks", async () => {
  const { mk, hydrateRecipients } = storageBacked();

  // First page: send → track. Nothing else is persisted.
  const first = mk();
  await hydrateRecipients( first.bStore );
  first.renderer.mount( first.root ); first.renderer.recipientsChanged();
  first.renderer.track( BCAST );
  first.renderer.unmount();

  // Second page: a FRESH bus and AckStore — nothing survives but storage.
  const second = mk( { api: SAVED_ACKS } );
  await hydrateRecipients( second.bStore );
  mounted = second.renderer;
  second.renderer.mount( second.root ); second.renderer.recipientsChanged();
  assert.equal( second.renderer.trackedBroadcastId(), BCAST, "the id must be restored from storage" );

  await new Promise( r => setTimeout( r, 0 ) );   // let the floated hydrate land
  assert.equal( txt( second.root, "broadcast-ack-summary" ), "2/3 complete",
    "the persisted acks must be replayed — this is the whole point of the server half" );
  assert.equal( second.root.querySelectorAll( '[data-testid="broadcast-ack-row"]' ).length, 2 );
} );

test( "🔴 CONTROL — with NO persisted id the same second renderer shows nothing", async () => {
  // The test above would pass just as well if the renderer always rendered a tally.
  const { mk, hydrateRecipients } = storageBacked();
  const second = mk( { api: SAVED_ACKS } );
  await hydrateRecipients( second.bStore );
  mounted = second.renderer;
  second.renderer.mount( second.root ); second.renderer.recipientsChanged();
  assert.equal( second.renderer.trackedBroadcastId(), null );
  assert.equal( second.root.querySelector( '[data-testid="broadcast-ack-tally"]' ), null );
} );

test( "a DISMISSED tally does not come back on the next reload", async () => {
  const { mk, hydrateRecipients } = storageBacked();
  const first = mk();
  await hydrateRecipients( first.bStore );
  first.renderer.mount( first.root ); first.renderer.recipientsChanged();
  first.renderer.track( BCAST );
  first.renderer.dismiss();
  first.renderer.unmount();

  const second = mk( { api: SAVED_ACKS } );
  await hydrateRecipients( second.bStore );
  mounted = second.renderer;
  second.renderer.mount( second.root ); second.renderer.recipientsChanged();
  assert.equal( second.renderer.trackedBroadcastId(), null, "dismiss must mean dismissed, not hidden until you refresh" );
} );

test( "🔴 A STALE PERSISTED TALLY IS NOT RESTORED — and the entry is cleared", async () => {
  // A tally is a live artifact. Restoring last week's broadcast and announcing who has
  // not answered it would be worse than showing nothing.
  const { storage, mk, hydrateRecipients } = storageBacked();
  const first = mk();
  await hydrateRecipients( first.bStore );
  first.renderer.mount( first.root ); first.renderer.recipientsChanged();
  first.renderer.track( BCAST );
  first.renderer.unmount();

  const second = mk( { api: SAVED_ACKS, nowOffset: 11 * 60 * 1000 } );   // past the 10-minute cap
  await hydrateRecipients( second.bStore );
  mounted = second.renderer;
  second.renderer.mount( second.root ); second.renderer.recipientsChanged();
  assert.equal( second.renderer.trackedBroadcastId(), null );
  assert.equal( storage.getJSON( "broadcast:ack-tally:tracked", 1 ), null,
    "the stale entry must be cleared, not left to be re-checked forever" );
} );

test( "🔴 RESTORE DOES NOT ARM A NEW DEADLINE", async () => {
  // The 30 seconds legacy counted were 30 seconds of the USER WATCHING. A reload starts
  // a new clock on an old broadcast; arming one here would time out a tally whose seats
  // answered minutes ago and report them as having failed to.
  const { mk, hydrateRecipients } = storageBacked();
  const first = mk();
  await hydrateRecipients( first.bStore );
  first.renderer.mount( first.root ); first.renderer.recipientsChanged();
  first.renderer.track( BCAST );
  first.renderer.unmount();

  const second = mk( { api: SAVED_ACKS } );
  await hydrateRecipients( second.bStore );
  mounted = second.renderer;
  second.renderer.mount( second.root ); second.renderer.recipientsChanged();
  assert.equal( second.timers.pending(), 0, "a restored tally must not start counting down again" );
} );

test( "🔴 A FAILED REPLAY SAYS SO — an empty tally and an unloadable one must not look alike", async () => {
  const { mk, hydrateRecipients } = storageBacked();
  const first = mk();
  await hydrateRecipients( first.bStore );
  first.renderer.mount( first.root ); first.renderer.recipientsChanged();
  first.renderer.track( BCAST );
  first.renderer.unmount();

  const second = mk( { api: new Error( "offline" ) } );
  await hydrateRecipients( second.bStore );
  mounted = second.renderer;
  second.renderer.mount( second.root ); second.renderer.recipientsChanged();
  await new Promise( r => setTimeout( r, 0 ) );
  assert.equal( txt( second.root, "broadcast-ack-restore-failed" ), "could not load the saved acknowledgements",
    "0/3 with no explanation would read as 'nobody answered'" );
} );

test( "a corrupt persisted envelope is ignored rather than restored", async () => {
  const { storage, mk, hydrateRecipients } = storageBacked();
  storage.setJSON( "broadcast:ack-tally:tracked", { broadcast_id: 42, ts: "nope" }, 1 );
  const r = mk( { api: SAVED_ACKS } );
  await hydrateRecipients( r.bStore );
  mounted = r.renderer;
  r.renderer.mount( r.root );
  assert.equal( r.renderer.trackedBroadcastId(), null );
} );

test( "a tally wired with NO storage is live-only — legacy's behaviour, and still a working card", async () => {
  const { renderer, root, hydrated } = setup();
  await hydrated;
  renderer.mount( root ); renderer.recipientsChanged();
  renderer.track( BCAST );
  renderer.dismiss();
  assert.equal( renderer.trackedBroadcastId(), null, "no storage must not mean a crash" );
} );

test( "storage WITHOUT an api restores the id but replays nothing", async () => {
  // A deliberate half-wiring: the tally comes back knowing which broadcast it is, and
  // shows what the live fold holds. After a reload that is nothing — honestly zero.
  const storage = createStorageServiceForTesting();
  const bus1 = createEventBusForTesting();
  const s1   = createAckStore( { bus: bus1 } );
  const b1   = createBroadcastStore( { storage } );
  await b1.hydrate( { get<T>( _p: string ): Promise<T> { return Promise.resolve( { sessions: THREE } as T ); } } );
  const t1 = makeTimers();
  const r1 = createBroadcastAckTallyRenderer( { eventBus: bus1, ackStore: s1, broadcastStore: b1, storage,
    setTimeoutFn: t1.setTimeoutFn, clearTimeoutFn: t1.clearTimeoutFn, nowFn: () => 1_700_000_000_000 } );
  const root1 = document.createElement( "div" ); document.body.appendChild( root1 );
  r1.mount( root1 ); r1.recipientsChanged(); r1.track( BCAST ); r1.unmount();

  const bus2 = createEventBusForTesting();
  const s2   = createAckStore( { bus: bus2 } );
  const b2   = createBroadcastStore( { storage } );
  await b2.hydrate( { get<T>( _p: string ): Promise<T> { return Promise.resolve( { sessions: THREE } as T ); } } );
  const t2 = makeTimers();
  const r2 = createBroadcastAckTallyRenderer( { eventBus: bus2, ackStore: s2, broadcastStore: b2, storage,
    setTimeoutFn: t2.setTimeoutFn, clearTimeoutFn: t2.clearTimeoutFn, nowFn: () => 1_700_000_000_000 } );
  const root2 = document.createElement( "div" ); document.body.appendChild( root2 );
  mounted = r2;
  r2.mount( root2 ); r2.recipientsChanged();
  assert.equal( r2.trackedBroadcastId(), BCAST );
  assert.equal( txt( root2, "broadcast-ack-summary" ), "0/3 complete" );
} );

// ===========================================================================
// 🔴 MARÍA'S BLOCKER ON 5b569053 — AN UNKNOWN ROSTER IS NOT AN EMPTY ONE.
//
// THE DEFECT, and it was mine. `expected()` reads `broadcastStore.recipients()` live.
// On a reload the tally restores and paints BEFORE the card's first recipient fetch has
// resolved, so recipients() is [] — and `received === expected` was true at 0 === 0, so
// it took the COMPLETE branch and rendered "✅ All 0 sessions acknowledged". Then the
// acks hydrated and it jumped to "2/0". Two wrong readings in a row, and the first one
// is the worse of the two: it says the broadcast is fully answered.
//
// WHY NOTHING CAUGHT IT. Every test in this file awaited the recipient hydrate BEFORE
// mounting — a mount order that production never performs on a reload. The fixture was
// arranging the one condition the defect needed to be absent.
//
// BroadcastStore emits NO EventBus event, so the tally cannot learn this on its own.
// BroadcastCardRenderer, which owns the store and the fetch, now says so.
// ===========================================================================

function unannounced( recipients: BroadcastRecipient[] = THREE ) {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting();
  const ackStore = createAckStore( { bus } );
  const bStore   = createBroadcastStore( { storage } );
  const timers   = makeTimers();
  const root     = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createBroadcastAckTallyRenderer( {
    eventBus: bus, ackStore, broadcastStore: bStore,
    timeoutMs: 5 * 60 * 1000, setTimeoutFn: timers.setTimeoutFn, clearTimeoutFn: timers.clearTimeoutFn,
  } );
  mounted = renderer;
  const loadRecipients = async () => {
    await bStore.hydrate( { get<T>( _p: string ): Promise<T> { return Promise.resolve( { sessions: recipients } as T ); } } );
    renderer.recipientsChanged();
  };
  return { bus, ackStore, renderer, root, timers, loadRecipients };
}

test( "🔴 an UNLOADED roster never reads '✅ All 0 sessions acknowledged'", async () => {
  const { renderer, root } = unannounced();
  renderer.mount( root );
  renderer.track( BCAST );
  const text = txt( root, "broadcast-ack-summary" ) ?? "";
  assert.ok( !text.includes( "All 0" ), `an unloaded roster must not claim completion, got: ${text}` );
  assert.match( text, /loading the recipient list/, "it says it does not know yet, rather than printing a denominator" );
} );

test( "🔴 and it REPAINTS once the roster arrives", async () => {
  const { bus, ackStore, renderer, root, loadRecipients } = unannounced();
  const stop = ackStore.start();
  renderer.mount( root );
  renderer.track( BCAST );
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  await loadRecipients();
  assert.equal( txt( root, "broadcast-ack-summary" ), "1/3 complete",
    "the denominator must appear the moment the card learns it, not on the next unrelated event" );
  stop();
} );

test( "🔴 no `waiting on:` line against a roster nobody has loaded", async () => {
  // It would name nobody, or worse a stale set — a claim about seats we have not been
  // told about yet.
  const { renderer, root } = unannounced();
  renderer.mount( root );
  renderer.track( BCAST );
  assert.equal( txt( root, "broadcast-ack-pending" ), null );
} );

test( "🔴 THE DEADLINE CANNOT TIME OUT — OR DISMISS — AN UNKNOWN ROSTER", async () => {
  // Without the guard the deadline reads expected.length === 0, finds received >= 0,
  // and takes the COMPLETE branch: it would silently DISMISS a tally whose recipients
  // had merely not loaded, precisely when the network is slow.
  const { renderer, root, timers } = unannounced();
  renderer.mount( root );
  renderer.track( BCAST );
  timers.fire();
  assert.equal( renderer.trackedBroadcastId(), BCAST, "the tally must survive a deadline it cannot yet judge" );
  assert.notEqual( root.querySelector( '[data-testid="broadcast-ack-tally"]' ), null );
} );

test( "CONTROL — once the roster IS known the deadline judges normally", async () => {
  const { bus, ackStore, renderer, root, timers, loadRecipients } = unannounced();
  const stop = ackStore.start();
  renderer.mount( root );
  renderer.track( BCAST );
  await loadRecipients();
  liveAck( bus, { session_id: "s1aaaaaa-1111" } );
  timers.fire();
  assert.equal( txt( root, "broadcast-ack-summary" ), "1/3 sessions acknowledged — 2 timed out",
    "CONTROL FAILED — the deadline no longer fires at all, so the guard above proved nothing" );
  stop();
} );

test( "a FAILED recipient fetch still counts as an answer about the roster", async () => {
  // A tally waiting forever for a list that will never arrive is worse than one reading
  // zero. The card signals on its error path too.
  const { renderer, root } = unannounced();
  renderer.mount( root );
  renderer.track( BCAST );
  renderer.recipientsChanged();          // what the card does in its .catch
  assert.equal( txt( root, "broadcast-ack-summary" ), "✅ All 0 sessions acknowledged" );
} );

test( "🔴 THE LEGACY DEADLINE IS FIVE MINUTES, NOT THIRTY SECONDS", async () => {
  // broadcast-panel.js:25 — `AUTO_DISMISS_MS = 5 * 60 * 1000` "(matches AC7 ack-tracker
  // TTL)". I had written 30_000 from the constant's NAME without reading its VALUE, and
  // cited "legacy AUTO_DISMISS_MS" beside it, which made an invention look sourced.
  // Asserted here so the number has a witness rather than a comment.
  const bus      = createEventBusForTesting();
  const ackStore = createAckStore( { bus } );
  const bStore   = createBroadcastStore( { storage: createStorageServiceForTesting() } );
  const delays: number[] = [];
  const renderer = createBroadcastAckTallyRenderer( {
    eventBus: bus, ackStore, broadcastStore: bStore,
    setTimeoutFn: ( ( _cb: () => void, ms: number ): unknown => { delays.push( ms ); return 1; } ) as ( cb: () => void, ms: number ) => unknown,
    clearTimeoutFn: () => {},
  } );
  mounted = renderer;
  const root = document.createElement( "div" ); document.body.appendChild( root );
  renderer.mount( root );
  renderer.track( BCAST );
  assert.deepEqual( delays, [ 5 * 60 * 1000 ] );
} );
