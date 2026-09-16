// Guard — parity A-1c2: Action Required prompts survive a reload.
//
// Legacy (notifications.js `saveActionRequiredState` / `restoreActionRequiredState`, key
// `notifications_action_required`) persists the queue in order, the active card, its pause and
// the half-answered multiple_choice stepper, and restores them on load.
//
// Rulings (operator-state spec, Mr. Radio 🦉 2026-09-16):
//   · 3 — StorageService, key `operatorState` (stored `lupin:operatorState`), injected `| null`
//   · 2 — dropped at RESTORE when the expiry passed more than 5 s ago; a queued card (no expiry)
//         is never dropped; the expiry is saved on the LOCAL clock (`expires_at − clockOffset`)
//         and compared to `nowFn()`, because the server offset is 0 after a reload
//
// A reload is not unit-reachable, so this is the module-boundary test: a writer store, a FRESH
// reader store over the same backend, and what the reader holds. The last test re-mounts a real
// renderer over the reader.
//
// 🔴 AT 59b662d5 THE STORE PERSISTED NOTHING.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createStorageServiceForTesting,
  InMemoryStorage,
  type StorageBackend,
} from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  createActionRequiredStore,
  AR_STORAGE_KEY,
  AR_STORAGE_SCHEMA,
  AR_RESTORE_GRACE_MS,
  type ActionRequiredStore,
} from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import { createActionRequiredRenderer } from "../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { QUESTIONS_PAYLOAD } from "./fixtures/actionRequiredQuestionsPayload";
import type {
  LupinEvent,
  StoreActionRequiredChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const T0      = 1_700_000_000_000;
const FULLKEY = `lupin:${ AR_STORAGE_KEY }`;

/** One store over `backend`; `backend` is what survives the "reload". */
function open( backend: StorageBackend, opts: { now?: number; persist?: boolean } = {} ) {
  const bus = createEventBusForTesting();
  const events: Array<LupinEvent<StoreActionRequiredChangedPayload>> = [];
  bus.on<StoreActionRequiredChangedPayload>( "store_action_required_changed", ( e ) => events.push( e ) );
  let now = opts.now ?? T0;
  const intervals = new Map<number, () => void>();
  let nextId = 1;
  let rejectPosts = false;
  const store = createActionRequiredStore( {
    bus,
    api             : { post: async () => { if ( rejectPosts ) throw new Error( "down" ); return {} as never; } },
    setIntervalFn   : ( cb ) => { const id = nextId++; intervals.set( id, cb ); return id; },
    clearIntervalFn : ( id ) => { intervals.delete( id as number ); },
    setTimeoutFn    : () => 0,
    clearTimeoutFn  : () => {},
    nowFn           : () => now,
    storage         : opts.persist === false ? null : createStorageServiceForTesting( bus, backend ),
  } );
  const prompt = ( id: string, over: Record<string, unknown> = {} ): void => {
    bus.emit( { type: "notification_queue_update", source: "test", ts: 0,
      payload: { notification: { id_hash: id, message: `prompt ${ id }`, response_requested: true,
                                 response_type: "open_ended", timeout_seconds: 60, ...over } } } as never );
  };
  return {
    bus, store, events, prompt,
    setNow      : ( ms: number ) => { now = ms; },
    ticking     : () => intervals.size,
    fireAll     : () => { for ( const cb of Array.from( intervals.values() ) ) cb(); },
    rejectPosts : () => { rejectPosts = true; },
    serverClock : ( offsetMs: number ) => {
      bus.emit( { type: "sys_time_update", source: "test", ts: 0, payload: { serverTime: now + offsetMs } } as never );
    },
  };
}

const ids = ( store: ActionRequiredStore ): string[] => store.list().map( ( i ) => i.id_hash );

function saved( backend: StorageBackend ): { prompts: Array<Record<string, unknown>> } {
  const raw = backend.getItem( FULLKEY );
  assert.ok( raw !== null, `nothing was saved under ${ FULLKEY }` );
  const envelope = JSON.parse( raw ) as { schemaVersion: number; payload: { prompts: Array<Record<string, unknown>> } };
  assert.equal( envelope.schemaVersion, AR_STORAGE_SCHEMA );
  return envelope.payload;
}

// ---------------------------------------------------------------------------
// Write → fresh reader → read
// ---------------------------------------------------------------------------

test( "🔴 the queue survives a reload in order: the active card keeps counting from its saved expiry, the queued card still waits", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1" );
  w.prompt( "a2", { timeout_seconds: 90 } );
  assert.deepEqual( saved( backend ).prompts.map( ( p ) => p[ "id_hash" ] ), [ "a1", "a2" ] );

  const r = open( backend, { now: T0 + 20_000 } );
  assert.deepEqual( ids( r.store ), [ "a1", "a2" ] );
  assert.equal( r.store.getById( "a1" )!.expires_at, T0 + 60_000 );
  assert.equal( r.store.getById( "a1" )!.state, "pending" );
  assert.equal( r.store.getById( "a2" )!.expires_at, null, "a queued card has not started its clock" );
  assert.equal( r.store.getById( "a2" )!.timeout_seconds, 90 );
  assert.equal( r.ticking(), 1, "only the active card counts down" );
  r.fireAll();
  assert.equal( r.events.at( -1 )!.payload.changeKind, "tick" );
  assert.equal( r.events.at( -1 )!.payload.countdownMs, 40_000 );
} );

test( "🔴 a paused card comes back paused, frozen, and a resume adds the paused span", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1" );
  w.setNow( T0 + 10_000 );
  assert.equal( w.store.togglePause( "a1" ), true );

  const r = open( backend, { now: T0 + 40_000 } );
  assert.equal( r.store.getById( "a1" )!.paused_at, T0 + 10_000 );
  assert.equal( r.ticking(), 0, "a restored pause must not restart the countdown" );
  assert.equal( r.store.togglePause( "a1" ), false );
  assert.equal( r.store.getById( "a1" )!.expires_at, T0 + 90_000 );
  assert.equal( r.store.getById( "a1" )!.total_paused_ms, 30_000 );
  assert.equal( r.events.at( -1 )!.payload.countdownMs, 50_000, "the remainder frozen at the pause" );
} );

test( "🔴 the half-answered stepper survives: the saved position and answers come back", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1", { response_type: "multiple_choice", response_options: QUESTIONS_PAYLOAD.multiple_choice.response_options } );
  const step = { index: 1, answers: { Database: "PostgreSQL" } };
  w.store.recordStep( "a1", step );
  assert.deepEqual( saved( backend ).prompts[ 0 ]![ "step" ], step );
  assert.equal( w.events.length, 1, "recording a step emits nothing — a repaint would drop the operator's focus" );

  const r = open( backend );
  assert.deepEqual( r.store.getById( "a1" )!.step, step );
  r.store.recordStep( "nope", step ); // an unknown card is ignored
  assert.deepEqual( ids( r.store ), [ "a1" ] );
} );

test( "🔴 the expiry is saved on the LOCAL clock, so a reload with no server offset yet does not drop a live card", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.serverClock( 3_600_000 );   // the server runs an hour ahead
  w.prompt( "a1" );
  w.setNow( T0 + 5_000 );
  w.store.togglePause( "a1" );
  assert.equal( w.store.getById( "a1" )!.expires_at, T0 + 3_600_000 + 60_000 );
  assert.equal( saved( backend ).prompts[ 0 ]![ "expires_at" ], T0 + 60_000 );
  assert.equal( saved( backend ).prompts[ 0 ]![ "paused_at" ], T0 + 5_000 );

  const r = open( backend, { now: T0 + 30_000 } );
  assert.deepEqual( ids( r.store ), [ "a1" ] );
  assert.equal( r.store.getById( "a1" )!.expires_at, T0 + 60_000 );
} );

test( "🔴 restore drops a card expired more than the grace ago and promotes the next with a fresh countdown", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1" );
  w.prompt( "a2" );

  const r = open( backend, { now: T0 + 60_000 + AR_RESTORE_GRACE_MS } );
  assert.deepEqual( ids( r.store ), [ "a2" ] );
  assert.equal( r.store.getById( "a2" )!.expires_at, T0 + 60_000 + AR_RESTORE_GRACE_MS + 60_000 );
  assert.equal( r.ticking(), 1 );
  assert.deepEqual( saved( backend ).prompts.map( ( p ) => p[ "id_hash" ] ), [ "a2" ], "the dropped card is gone from storage too" );
} );

test( "restore keeps a card expired within the grace, and its first tick expires it", () => {
  const backend = new InMemoryStorage();
  open( backend ).prompt( "a1" );
  const r = open( backend, { now: T0 + 60_000 + AR_RESTORE_GRACE_MS - 1 } );
  assert.deepEqual( ids( r.store ), [ "a1" ] );
  r.fireAll();
  assert.equal( r.store.getById( "a1" )!.state, "expired" );
} );

test( "restore never drops a queued card on expiry grounds, however old the save", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1" );
  w.prompt( "a2" );
  const r = open( backend, { now: T0 + 86_400_000 } );
  assert.deepEqual( ids( r.store ), [ "a2" ] );
} );

test( "a submitting or failed card is saved as still owed and comes back answerable", async () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1" );
  w.rejectPosts();
  await assert.rejects( w.store.respondAndAwait( "a1", "yes" ) );
  assert.equal( w.store.getById( "a1" )!.state, "failed" );
  assert.equal( saved( backend ).prompts[ 0 ]![ "state" ], "pending" );
  assert.equal( open( backend ).store.getById( "a1" )!.state, "pending" );
} );

test( "a finished card leaves the snapshot, and the last one clears the key", async () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  w.prompt( "a1" );
  w.prompt( "a2" );
  await w.store.respondAndAwait( "a1", "yes" );
  assert.deepEqual( saved( backend ).prompts.map( ( p ) => p[ "id_hash" ] ), [ "a2" ] );
  w.bus.emit( { type: "notification_responded", source: "test", ts: 0, payload: { id_hash: "a2" } } as never );
  assert.equal( backend.getItem( FULLKEY ), null );
} );

test( "with no storage the store persists and restores nothing", () => {
  const backend = new InMemoryStorage();
  const w = open( backend, { persist: false } );
  w.prompt( "a1" );
  w.store.recordStep( "a1", { index: 0, answers: {} } );
  assert.equal( backend.length, 0 );
  open( backend ).prompt( "a9" );
  assert.deepEqual( ids( open( backend, { persist: false } ).store ), [] );
} );

test( "an unreadable save restores nothing and does not throw: wrong schema, or no prompt list", () => {
  const backend = new InMemoryStorage();
  backend.setItem( FULLKEY, JSON.stringify( { schemaVersion: AR_STORAGE_SCHEMA + 1, payload: { prompts: [] }, ts: 0 } ) );
  assert.deepEqual( ids( open( backend ).store ), [] );
  backend.setItem( FULLKEY, JSON.stringify( { schemaVersion: AR_STORAGE_SCHEMA, payload: { nope: 1 }, ts: 0 } ) );
  assert.deepEqual( ids( open( backend ).store ), [] );
} );

test( "a storage write that throws does not stop the operator answering", async () => {
  const backend = new InMemoryStorage();
  backend.setItem = () => { throw new Error( "QuotaExceededError" ); };
  const w = open( backend );
  w.prompt( "a1" );
  await w.store.respondAndAwait( "a1", "yes" );
  assert.equal( w.store.getById( "a1" )!.state, "responded" );
} );

// ---------------------------------------------------------------------------
// Integration: re-mount a real renderer over the reader
// ---------------------------------------------------------------------------

test( "🔴 re-mount: a fresh store and renderer paint the paused card on the question the operator had reached", () => {
  const backend = new InMemoryStorage();
  const w = open( backend );
  const wr = createActionRequiredRenderer( { eventBus: w.bus, stores: { actionRequired: w.store } } );
  const wroot = document.createElement( "div" );
  document.body.appendChild( wroot );
  wr.mount( wroot );
  w.prompt( "a1", { response_type: "multiple_choice", response_options: QUESTIONS_PAYLOAD.multiple_choice.response_options } );
  w.prompt( "a2" );
  wroot.querySelector<HTMLInputElement>( 'input[value="PostgreSQL"]' )!.checked = true;
  wroot.querySelector<HTMLButtonElement>( ".action-required-btn-next" )!.click();
  wroot.querySelector<HTMLButtonElement>( ".action-required-pause-btn" )!.click();
  wr.unmount();
  wroot.remove();

  const r = open( backend, { now: T0 + 30_000 } );
  const rr = createActionRequiredRenderer( { eventBus: r.bus, stores: { actionRequired: r.store } } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  rr.mount( root );
  const card = root.querySelector<HTMLElement>( '.action-required-active-slot [data-id-hash="a1"]' );
  assert.ok( card, "the active card was not restored into the slot" );
  assert.equal( card.classList.contains( "paused" ), true );
  assert.equal( root.querySelector( ".action-required-question-indicator" )!.textContent, "Question 2 of 2" );
  root.querySelector<HTMLButtonElement>( ".action-required-btn-back" )!.click();
  assert.equal( root.querySelector<HTMLInputElement>( 'input[value="PostgreSQL"]' )!.checked, true );
  assert.equal( root.querySelectorAll( ".action-required-minimized" ).length, 1, "the queued card is back in the queue" );
  rr.unmount();
} );
