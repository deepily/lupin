// Guard — parity A-2 #2e (Phase 2 A3 R4): the Action Required card's draining progress bar.
//
// Legacy (notifications.js `renderActionRequiredNotification` / `startCountdownTimer` /
// `updatePausedTimerDisplay`):
//   · a `.action-required-progress-bar` holding `.action-required-progress-fill` at width 100%,
//     below the message and above the response controls
//   · every second the fill's width is the remaining share of the timeout, and it carries
//     `.warning` at ≤ 50% and `.danger` at ≤ 25%
//   · a pause marks the fill `.paused`; a resume clears it
//
// 🔴 AT d3cd00aa THE CARD HAD A COUNTDOWN AND NO BAR.

import { test, before, mock } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createActionRequiredStore } from "../../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import {
  createActionRequiredRenderer,
  arProgressPercent,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const T0 = 1_700_000_000_000;

function mounted() {
  const bus = createEventBusForTesting();
  let now = T0;
  const intervals = new Map<number, () => void>();
  let nextId = 1;
  const store = createActionRequiredStore( {
    bus,
    api             : { post: async () => ( {} as never ) },
    setIntervalFn   : ( cb ) => { const id = nextId++; intervals.set( id, cb ); return id; },
    clearIntervalFn : ( id ) => { intervals.delete( id as number ); },
    setTimeoutFn    : () => 0,
    clearTimeoutFn  : () => {},
    nowFn           : () => now,
    audioControl    : { isPlaying: () => false, pause: () => {}, resume: () => {} },
  } );
  const renderer = createActionRequiredRenderer( { eventBus: bus, stores: { actionRequired: store } } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  renderer.mount( root );
  const prompt = ( id: string, timeout = 60, responseType = "open_ended" ): void => {
    bus.emit( { type: "notification_queue_update", source: "test", ts: 0,
      payload: { notification: { id_hash: id, message: `prompt ${ id }`, response_requested: true,
                                 response_type: responseType, timeout_seconds: timeout } } } as never );
  };
  return {
    store, root, renderer, prompt,
    at      : ( ms: number ) => { now = T0 + ms; for ( const cb of Array.from( intervals.values() ) ) cb(); },
    setNow  : ( ms: number ) => { now = T0 + ms; },
  };
}

const q = <T extends Element>( root: ParentNode, sel: string ): T => {
  const el = root.querySelector<T>( sel );
  assert.ok( el, `not rendered: ${ sel }` );
  return el;
};

const fillOf = ( root: ParentNode ): HTMLElement =>
  q<HTMLElement>( root, ".action-required-progress-bar > .action-required-progress-fill" );

test( "🔴 renderer: the active card carries a full progress bar between its prompt and its controls", () => {
  // The card is built against the wall clock, so the wall clock is pinned to the store's.
  mock.timers.enable( { apis: [ "Date" ], now: T0 } );
  try {
    for ( const type of [ "yes_no", "open_ended", "open_ended_batch", "multiple_choice" ] ) {
      const m = mounted();
      m.prompt( "a1", 60, type );
      const bar  = q<HTMLElement>( m.root, ".action-required-widget .action-required-progress-bar" );
      const fill = fillOf( m.root );
      assert.equal( fill.style.width, "100%", type );
      assert.equal( fill.classList.contains( "warning" ) || fill.classList.contains( "danger" ), false, type );
      // ⚠️ Nodes are compared as BOOLEANS: a failing assert.equal on two happy-dom nodes renders
      // their circular parent chain into the diff and the run dies of memory instead of reporting.
      assert.equal( bar.previousElementSibling === q( m.root, ".action-required-prompt" ), true, `${ type }: the bar follows the prompt` );
      m.renderer.unmount();
    }
  } finally {
    mock.timers.reset();
  }
} );

test( "🔴 renderer: each tick drains the bar and colours it warning at half, danger at a quarter", () => {
  const m = mounted();
  m.prompt( "a1", 60 );
  m.at( 12_000 );
  assert.equal( fillOf( m.root ).style.width, "80%" );
  assert.equal( fillOf( m.root ).className, "action-required-progress-fill" );
  m.at( 30_000 );
  assert.equal( fillOf( m.root ).style.width, "50%" );
  assert.equal( fillOf( m.root ).classList.contains( "warning" ), true );
  m.at( 45_000 );
  assert.equal( fillOf( m.root ).style.width, "25%" );
  assert.equal( fillOf( m.root ).classList.contains( "danger" ), true );
  assert.equal( fillOf( m.root ).classList.contains( "warning" ), false, "danger replaces warning" );
  m.renderer.unmount();
} );

test( "🔴 renderer: a pause marks the fill paused in place and a resume clears it", () => {
  const m = mounted();
  m.prompt( "a1", 60 );
  m.at( 30_000 );
  q<HTMLButtonElement>( m.root, ".action-required-pause-btn" ).click();
  assert.equal( fillOf( m.root ).classList.contains( "paused" ), true );
  assert.equal( fillOf( m.root ).style.width, "50%", "the pause keeps the frozen share" );
  m.setNow( 90_000 );
  q<HTMLButtonElement>( m.root, ".action-required-pause-btn" ).click();
  assert.equal( fillOf( m.root ).classList.contains( "paused" ), false );
  assert.equal( fillOf( m.root ).style.width, "50%", "the resume adds the paused span back" );
  m.renderer.unmount();
} );

test( "renderer: a paused card rebuilt for another reason shows its frozen share, colour and pause", () => {
  const m = mounted();
  m.prompt( "a1", 60 );
  m.at( 48_000 );
  q<HTMLButtonElement>( m.root, ".action-required-pause-btn" ).click();
  m.setNow( 200_000 );
  m.prompt( "b2", 60 ); // a queued arrival repaints the slot
  const fill = fillOf( m.root.querySelector( '[data-id-hash="a1"]' )! );
  assert.equal( fill.style.width, "20%" );
  assert.equal( fill.classList.contains( "danger" ), true );
  assert.equal( fill.classList.contains( "paused" ), true );
  m.renderer.unmount();
} );

test( "arProgressPercent: the remaining share of the timeout, clamped to 0..100, and 0 with no timeout", () => {
  assert.equal( arProgressPercent( 30_000, 60_000 ), 50 );
  assert.equal( arProgressPercent( 90_000, 60_000 ), 100 );
  assert.equal( arProgressPercent( -1, 60_000 ), 0 );
  assert.equal( arProgressPercent( 5_000, 0 ), 0 );
} );
