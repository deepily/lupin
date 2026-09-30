// Guard — parity A-2 #2f (Phase 2 A3 R5): the Action Required card's ⏸️ pause / resume.
//
// Legacy (notifications.js `pauseActionRequired` / `resumeActionRequired` / `togglePause`):
//   · a ⏸️ button in every card header, title "Pause timer and audio (P)"
//   · pause freezes the countdown, pauses TTS, turns the button into ▶️ "Resume timer and
//     audio (P)", marks the button, timer and card `.paused`, and shows
//     "⏸️ Paused – 5-minute grace period added" under the header
//   · resume adds the paused time to the expiry, restarts the countdown and resumes TTS
// The P key is A-2 #2h; reload persistence of the pause is A-1c2.
//
// 🔴 AT 067a1559 NONE OF THIS EXISTED: the store's only freeze was the offline/backoff one,
// and the card had no pause control.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredStore,
  type ActionRequiredAudioControl,
} from "../../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import {
  createActionRequiredRenderer,
  AR_PAUSE_TITLE,
  AR_RESUME_TITLE,
  AR_PAUSED_MESSAGE,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type {
  LupinEvent,
  StoreActionRequiredChangedPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const T0 = 1_700_000_000_000;

function harness( audioPlaying = true ) {
  const bus = createEventBusForTesting();
  const events: Array<LupinEvent<StoreActionRequiredChangedPayload>> = [];
  bus.on<StoreActionRequiredChangedPayload>( "store_action_required_changed", ( e ) => events.push( e ) );
  let now = T0;
  const intervals = new Map<number, () => void>();
  let nextId = 1;
  const audio = { playing: audioPlaying, pauses: 0, resumes: 0 };
  const audioControl: ActionRequiredAudioControl = {
    isPlaying : () => audio.playing,
    pause     : () => { audio.pauses += 1; audio.playing = false; },
    resume    : () => { audio.resumes += 1; audio.playing = true; },
  };
  const store = createActionRequiredStore( {
    bus,
    api             : { post: async () => ( {} as never ) },
    setIntervalFn   : ( cb ) => { const id = nextId++; intervals.set( id, cb ); return id; },
    clearIntervalFn : ( id ) => { intervals.delete( id as number ); },
    setTimeoutFn    : () => 0,
    clearTimeoutFn  : () => {},
    nowFn           : () => now,
    audioControl,
  } );
  const prompt = ( id: string, timeout = 60 ): void => {
    bus.emit( { type: "notification_queue_update", source: "test", ts: 0,
      payload: { notification: { id_hash: id, message: `prompt ${ id }`, response_requested: true,
                                 response_type: "open_ended", timeout_seconds: timeout } } } as never );
  };
  return {
    bus, store, events, audio,
    prompt,
    setNow   : ( n: number ) => { now = n; },
    ticking  : () => intervals.size,
    fireAll  : () => { for ( const cb of Array.from( intervals.values() ) ) cb(); },
    kinds    : () => events.map( ( e ) => e.payload.changeKind ),
  };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

test( "🔴 store: pausing the active card stops its countdown and pauses playing audio", () => {
  const h = harness();
  h.prompt( "a1" );
  assert.equal( h.ticking(), 1, "positive control: the active card counts down" );
  h.setNow( T0 + 10_000 );

  assert.equal( h.store.togglePause( "a1" ), true );
  assert.equal( h.ticking(), 0, "the countdown kept running through a pause" );
  assert.equal( h.store.getById( "a1" )!.paused_at, T0 + 10_000 );
  assert.equal( h.audio.pauses, 1 );
  const paused = h.events.at( -1 )!.payload;
  assert.equal( paused.changeKind, "paused" );
  assert.equal( paused.countdownMs, 50_000, "the frozen remaining time rides the event" );
} );

test( "store: resuming adds the paused time to the expiry, restarts the countdown and resumes the audio it paused", () => {
  const h = harness();
  h.prompt( "a1" );
  const expires = h.store.getById( "a1" )!.expires_at!;
  h.setNow( T0 + 10_000 );
  h.store.togglePause( "a1" );
  h.setNow( T0 + 40_000 );

  assert.equal( h.store.togglePause( "a1" ), false );
  const item = h.store.getById( "a1" )!;
  assert.equal( item.expires_at, expires + 30_000 );
  assert.equal( item.total_paused_ms, 30_000 );
  assert.equal( item.paused_at, null );
  assert.equal( h.ticking(), 1 );
  assert.equal( h.audio.resumes, 1 );
  assert.equal( h.events.at( -1 )!.payload.changeKind, "resumed" );
  assert.equal( h.events.at( -1 )!.payload.countdownMs, 50_000, "the countdown resumes where it froze" );

  // A second cycle accumulates.
  h.store.togglePause( "a1" );
  h.setNow( T0 + 45_000 );
  h.store.togglePause( "a1" );
  assert.equal( h.store.getById( "a1" )!.total_paused_ms, 35_000 );
} );

test( "store: audio that was not playing is neither paused nor resumed", () => {
  const h = harness( false );
  h.prompt( "a1" );
  h.store.togglePause( "a1" );
  h.store.togglePause( "a1" );
  assert.deepEqual( [ h.audio.pauses, h.audio.resumes ], [ 0, 0 ] );
} );

test( "store: only the active, pending, counting card can be paused", () => {
  const h = harness();
  h.prompt( "a1" );
  h.prompt( "q2" );                                  // queued behind a1
  const before = h.events.length;
  assert.equal( h.store.togglePause( "q2" ), false, "a queued card has no countdown to pause" );
  assert.equal( h.store.togglePause( "nope" ), false );
  assert.equal( h.events.length, before, "a refused toggle emits nothing" );
  assert.equal( h.audio.pauses, 0 );
} );

test( "store: a reconnect does not restart a paused card's countdown", () => {
  const h = harness();
  h.prompt( "a1" );
  h.store.togglePause( "a1" );
  h.bus.emit( { type: "connection_state_change", source: "test", ts: 0, payload: { state: "offline" } } as never );
  h.bus.emit( { type: "connection_state_change", source: "test", ts: 0, payload: { state: "connected" } } as never );
  assert.equal( h.ticking(), 0, "the thaw restarted a countdown the operator paused" );
  h.store.togglePause( "a1" );
  assert.equal( h.ticking(), 1 );
} );

test( "store: a card that is not paused keeps its countdown through an offline freeze and thaw", () => {
  const h = harness();
  h.prompt( "a1" );
  h.bus.emit( { type: "connection_state_change", source: "test", ts: 0, payload: { state: "offline" } } as never );
  assert.equal( h.ticking(), 0 );
  h.bus.emit( { type: "connection_state_change", source: "test", ts: 0, payload: { state: "connected" } } as never );
  assert.equal( h.ticking(), 1 );
} );

// ---------------------------------------------------------------------------
// Renderer, over the real store
// ---------------------------------------------------------------------------

function mounted( audioPlaying = true ) {
  const h = harness( audioPlaying );
  const renderer = createActionRequiredRenderer( { eventBus: h.bus, stores: { actionRequired: h.store } } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  renderer.mount( root );
  return { ...h, root, renderer };
}

const q = <T extends Element>( root: ParentNode, sel: string ): T => {
  const el = root.querySelector<T>( sel );
  assert.ok( el, `not rendered: ${ sel }` );
  return el;
};

test( "🔴 renderer: the active card carries a ⏸️ button that pauses and resumes it", () => {
  const m = mounted();
  m.prompt( "a1" );
  const btn = q<HTMLButtonElement>( m.root, ".action-required-header .action-required-pause-btn" );
  assert.equal( btn.textContent, "⏸️" );
  assert.equal( btn.title, AR_PAUSE_TITLE );
  assert.equal( btn.type, "button" );

  btn.click();
  assert.equal( m.store.getById( "a1" )!.paused_at !== null, true, "the click did not reach the store" );
  const pausedBtn = q<HTMLButtonElement>( m.root, ".action-required-pause-btn" );
  assert.equal( pausedBtn.textContent, "▶️" );
  assert.equal( pausedBtn.title, AR_RESUME_TITLE );
  assert.ok( pausedBtn.classList.contains( "paused" ) );
  assert.ok( q( m.root, ".action-required-countdown" ).classList.contains( "paused" ) );
  assert.ok( q( m.root, ".action-required-widget" ).classList.contains( "paused" ) );
  const msg = q<HTMLElement>( m.root, ".grace-period-message" );
  assert.equal( msg.textContent, AR_PAUSED_MESSAGE );
  // ⚠️ Nodes are compared as BOOLEANS: a failing assert.equal on two happy-dom nodes renders
  // their circular parent chain into the diff and the run dies of memory instead of reporting.
  assert.equal( msg.previousElementSibling === q( m.root, ".action-required-header" ), true, "the message sits under the header" );

  pausedBtn.click();
  assert.equal( m.store.getById( "a1" )!.paused_at, null );
  const again = q<HTMLButtonElement>( m.root, ".action-required-pause-btn" );
  assert.equal( again.textContent, "⏸️" );
  assert.equal( again.title, AR_PAUSE_TITLE );
  assert.equal( again.classList.contains( "paused" ), false );
  assert.equal( q( m.root, ".action-required-countdown" ).classList.contains( "paused" ), false );
  assert.equal( q( m.root, ".action-required-widget" ).classList.contains( "paused" ), false );
  assert.equal( m.root.querySelector( ".grace-period-message" ) === null, true );
  m.renderer.unmount();
} );

test( "renderer: pausing does not rebuild the card, so a half-typed answer survives", () => {
  const m = mounted();
  m.prompt( "a1" );
  const widget = q<HTMLElement>( m.root, ".action-required-widget" );
  const input  = q<HTMLInputElement>( widget, "input" );
  input.value = "half an answer";
  q<HTMLButtonElement>( m.root, ".action-required-pause-btn" ).click();
  assert.equal( q( m.root, ".action-required-widget" ) === widget, true, "the pause rebuilt the active card" );
  assert.equal( input.value, "half an answer" );
  m.renderer.unmount();
} );

test( "renderer: a paused card rebuilt for another reason still shows paused, with the frozen time", () => {
  const m = mounted();
  m.prompt( "a1" );
  m.setNow( T0 + 15_000 );
  q<HTMLButtonElement>( m.root, ".action-required-pause-btn" ).click();
  m.renderer.forceRenderForTesting();
  assert.equal( q<HTMLButtonElement>( m.root, ".action-required-pause-btn" ).textContent, "▶️" );
  assert.ok( m.root.querySelector( ".grace-period-message" ) );
  assert.match( q( m.root, ".action-required-countdown" ).textContent ?? "", /0:45|00:45/ );
  m.renderer.unmount();
} );

test( "renderer: a paused/resumed event for a card not in the slot changes nothing", () => {
  const m = mounted();
  m.prompt( "a1" );
  const before = m.root.innerHTML;
  m.bus.emit( { type: "store_action_required_changed", source: "test", ts: 0,
                payload: { changeKind: "paused", id_hash: "elsewhere" } } );
  assert.equal( m.root.innerHTML, before );
  m.renderer.unmount();
} );

test( "renderer: a repeated paused event keeps ONE message, an event without a countdown reads 00:00, and a card with no header only toggles its class", () => {
  const m = mounted();
  m.prompt( "a1" );
  const emit = ( changeKind: "paused" | "resumed", countdownMs?: number ): void => {
    const payload: StoreActionRequiredChangedPayload = { changeKind, id_hash: "a1" };
    if ( countdownMs !== undefined ) payload.countdownMs = countdownMs;
    m.bus.emit( { type: "store_action_required_changed", source: "test", ts: 0, payload } );
  };
  emit( "paused", 12_000 );
  emit( "paused" );
  assert.equal( m.root.querySelectorAll( ".grace-period-message" ).length, 1 );
  assert.match( q( m.root, ".action-required-countdown" ).textContent ?? "", /00:00/ );

  const widget = q<HTMLElement>( m.root, ".action-required-widget" );
  q( widget, ".action-required-header" ).remove();
  q( widget, ".grace-period-message" ).remove();
  emit( "paused", 5_000 );
  assert.ok( widget.classList.contains( "paused" ) );
  assert.equal( widget.querySelector( ".grace-period-message" ) === null, true, "no header, nowhere to put the message" );
  m.renderer.unmount();
} );
