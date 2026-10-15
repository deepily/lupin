// Keep place: a card that is spoken must not move the view (row 45f29f42, review finding 1).
//
// Speaking a notification expands what hides it and then scrolls it into view. With Keep place on the
// expansion still happens, because the reader asked to hear the card, but the scroll does not.
//
// happy-dom does no layout, so each target is pinned below the fold; without that the helper resolves
// without scrolling and every "did not scroll" assertion would pass for the wrong reason.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/keep_place_spoken_card_does_not_scroll.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsListRenderer } from "../../../../lupin_app/static/js/multiplexer/render";
import { createActionRequiredRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import { KEEP_PLACE_KEY, keepPlaceIsOn } from "../../../../lupin_app/static/js/multiplexer/render/keepPlace";
import type { ActionRequiredItem, Notification, SenderRecord } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => {
  ( globalThis as { marked?: unknown } ).marked       = { parse: ( s: string ) => `<p>${s}</p>` };
  ( globalThis as { DOMPurify?: unknown } ).DOMPurify = { sanitize: ( s: string ) => s };
  localStorage.clear();
} );
afterEach( () => { localStorage.clear(); } );

const TS = Date.UTC( 2026, 4, 5, 14, 7 );

function offscreen( el: HTMLElement ): void {
  el.getBoundingClientRect = () => ( {
    top: window.innerHeight + 100, bottom: window.innerHeight + 400,
    left: 0, right: 0, width: 0, height: 300, x: 0, y: 0, toJSON: () => ( {} ),
  } ) as DOMRect;
}

/** Speak n1 in a collapsed card; return the scroll count and whether the card opened. */
function speakInHistory(): { scrolls: number; expanded: boolean } {
  const bus    = createEventBusForTesting();
  let current: string | null = null;
  const notifs : Notification[] = [ { id_hash: "n1", ts: TS, sender_id: "sess_42", message: "hi", action_required: false } ];
  const senders: SenderRecord[] = [ { sender_id: "sess_42", display_name: "S", last_active_ts: TS, unread_count: 1, conversation_mode_active: false } ];
  const viewState = {
    isAccordionCollapsed: () => false, setAccordionCollapsed: () => {}, isSectionVisible: () => true,
    setSectionVisible: () => {}, hasSectionPreference: () => false, getHiddenSectionIds: () => [] as string[],
  };
  const renderer = createNotificationsListRenderer( {
    eventBus: bus,
    stores  : { notifications: { list: () => notifs }, senders: { list: () => senders }, ttsQueue: { current: () => current }, viewState },
    appTimezone: "UTC",
  } );
  const root = document.createElement( "section" );
  const ar   = document.createElement( "div" );
  ar.id      = "action-required-section";
  const mount = document.createElement( "div" );
  mount.id    = "sender-cards-container";
  root.append( ar, mount );
  renderer.mount( root );
  let scrolls = 0;
  const bubble = mount.querySelector<HTMLElement>( '.sender-message[data-id-hash="n1"]' ) as HTMLElement;
  offscreen( bubble );
  bubble.scrollIntoView = () => { scrolls += 1; };
  const card = mount.querySelector<HTMLElement>( ".sender-card" ) as HTMLElement;
  card.setAttribute( "data-collapsed", "true" );
  current = "n1";
  bus.emit( { type: "store_tts_queue_changed", payload: undefined, source: "test", ts: 0 } );
  const expanded = card.getAttribute( "data-collapsed" ) === "false";
  renderer.unmount();
  return { scrolls, expanded };
}

test( "instrument check: with Keep place off a spoken card scrolls into view", () => {
  const r = speakInHistory();
  assert.equal( r.scrolls, 1 );
  assert.equal( r.expanded, true );
} );

test( "🔴 with Keep place on, a spoken card is expanded but the view does not move", () => {
  localStorage.setItem( KEEP_PLACE_KEY, "true" );
  const r = speakInHistory();
  assert.equal( r.expanded, true, "the card stayed shut, so the reader could not see what was spoken" );
  assert.equal( r.scrolls, 0, "the spoken card moved the view while Keep place was on" );
} );

function item( id: string ): ActionRequiredItem {
  return { id_hash: id, prompt: "Proceed?", response_type: "yes_no", questions: [], expires_at: Date.now() + 30_000, timeout_seconds: 30, state: "pending" };
}

/** Emit one change for an action-required card and count the scrolls it caused. */
function actionRequiredScrolls( changeKind: "added" | "activated" ): number {
  document.body.replaceChildren();
  const bus   = createEventBusForTesting();
  const items = new Map<string, ActionRequiredItem>( [ [ "a1", item( "a1" ) ] ] );
  const root  = document.createElement( "div" );
  root.id     = "action-required-section";
  document.body.appendChild( root );
  let scrolls = 0;
  offscreen( root );
  root.scrollIntoView = () => { scrolls += 1; };
  const renderer = createActionRequiredRenderer( {
    eventBus: bus,
    stores  : { actionRequired: { list: () => Array.from( items.values() ), getById: ( id ) => items.get( id ), respondAndAwait: async () => {} } },
  } );
  renderer.mount( root );
  bus.emit( { type: "store_action_required_changed", payload: { changeKind, id_hash: "a1" }, source: "test", ts: 0 } );
  renderer.unmount();
  return scrolls;
}

for ( const kind of [ "added", "activated" ] as const ) {
  test( `instrument check: with Keep place off an action-required card scrolls on ${kind}`, () => {
    assert.equal( actionRequiredScrolls( kind ), 1 );
  } );
  test( `🔴 with Keep place on, an action-required card does not move the view on ${kind}`, () => {
    localStorage.setItem( KEEP_PLACE_KEY, "true" );
    assert.equal( actionRequiredScrolls( kind ), 0 );
  } );
}

test( "keepPlaceIsOn is true only for the stored word true", () => {
  assert.equal( keepPlaceIsOn(), false );
  localStorage.setItem( KEEP_PLACE_KEY, "yes" );
  assert.equal( keepPlaceIsOn(), false );
  localStorage.setItem( KEEP_PLACE_KEY, "true" );
  assert.equal( keepPlaceIsOn(), true );
} );

test( "keepPlaceIsOn is false where reading localStorage throws or no storage exists", () => {
  const saved = Object.getOwnPropertyDescriptor( globalThis, "localStorage" ) as PropertyDescriptor;
  try {
    Object.defineProperty( globalThis, "localStorage", { configurable: true, get: () => { throw new Error( "blocked" ); } } );
    assert.equal( keepPlaceIsOn(), false );
    Object.defineProperty( globalThis, "localStorage", { configurable: true, get: () => undefined } );
    assert.equal( keepPlaceIsOn(), false );
  } finally {
    Object.defineProperty( globalThis, "localStorage", saved );
  }
} );
