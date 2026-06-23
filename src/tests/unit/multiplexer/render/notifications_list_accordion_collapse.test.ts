// Multiplexer section-toolbar / accordion-collapse parity (2026-06-23, Rachel
// 🕊️) — per-accordion header-click toggle + persisted-apply-on-render +
// collapse-all/expand-all bulk, in NotificationsListRenderer.
//
// Companion to notifications_list_renderer.test.ts; targets the accordion
// surface added in this lane. Run BOTH files under one c8 process for the 100%
// gate on NotificationsListRenderer.ts.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createNotificationsListRenderer,
  type NotificationsListRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render";
import type {
  Notification,
  SenderRecord,
  ActionRequiredItem,
  StoreViewStateChangedPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});

// --- Fake ViewStateStore (records persistence) -----------------------------
interface FakeViewState {
  isAccordionCollapsed( id: string ): boolean;
  setAccordionCollapsed( id: string, collapsed: boolean ): void;
  map: Map<string, boolean>;
  setCalls: Array<[ string, boolean ]>;
}
function makeFakeViewState( seedAllCollapsed = false ): FakeViewState {
  const map = new Map<string, boolean>();
  const fake: FakeViewState = {
    map,
    setCalls: [],
    isAccordionCollapsed: ( id ) => ( seedAllCollapsed ? true : map.get( id ) === true ),
    setAccordionCollapsed: ( id, collapsed ) => { map.set( id, collapsed ); fake.setCalls.push( [ id, collapsed ] ); },
  };
  return fake;
}

function makeNotification( over: Partial<Notification> = {} ): Notification {
  return { id_hash: "n1", ts: Date.UTC( 2026, 5, 23, 14, 7 ), sender_id: "sess_42", message: "hello", action_required: false, ...over };
}
function makeSender( over: Partial<SenderRecord> = {} ): SenderRecord {
  return { sender_id: "sess_42", display_name: "Sender", last_active_ts: Date.UTC( 2026, 5, 23, 14, 7 ), unread_count: 1, conversation_mode_active: false, ...over };
}

interface Harness {
  bus       : ReturnType<typeof createEventBusForTesting>;
  notifList : Notification[];
  senderList: SenderRecord[];
  renderer  : NotificationsListRenderer;
  root      : HTMLElement;
  sCards    : HTMLElement;
  viewState : FakeViewState | undefined;
}
function setup( viewState?: FakeViewState ): Harness {
  const bus = createEventBusForTesting();
  const notifList: Notification[]  = [];
  const senderList: SenderRecord[] = [];
  const arList: ActionRequiredItem[] = [];
  const renderer = createNotificationsListRenderer( {
    eventBus: bus,
    stores  : {
      notifications  : { list: () => notifList },
      senders        : { list: () => senderList },
      actionRequired : { list: () => arList },
      viewState,
    },
    appTimezone: "UTC",
  } );
  const root = document.createElement( "section" );
  root.id = "notifications-pane";
  const arSection = document.createElement( "div" );
  arSection.id = "action-required-section";
  const sCards = document.createElement( "div" );
  sCards.id = "sender-cards-container";
  root.appendChild( arSection );
  root.appendChild( sCards );
  return { bus, notifList, senderList, renderer, root, sCards, viewState };
}

function clickBubbling( el: Element ): void {
  el.dispatchEvent( new Event( "click", { bubbles: true } ) );
}
function emitBulk( bus: Harness["bus"], collapsed: boolean ): void {
  bus.emit<StoreViewStateChangedPayload>( {
    type: "store_view_state_changed",
    payload: { changeKind: collapsed ? "collapse-all" : "expand-all" },
    source: "test", ts: 0,
  } );
}

// ===========================================================================
// 1 — Date-accordion header click toggles + persists
// ===========================================================================

test( "date-accordion header click collapses (▶) then expands (▼) + persists each", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );

  const accordion = h.sCards.querySelector( ".date-accordion" ) as HTMLElement;
  const header    = accordion.querySelector( ".date-accordion-header" ) as HTMLElement;
  const toggle    = accordion.querySelector( ".date-toggle" ) as HTMLElement;
  assert.equal( accordion.getAttribute( "data-collapsed" ), "false" );

  clickBubbling( header );
  assert.equal( accordion.getAttribute( "data-collapsed" ), "true" );
  assert.equal( toggle.textContent, "▶" );

  clickBubbling( header );
  assert.equal( accordion.getAttribute( "data-collapsed" ), "false" );
  assert.equal( toggle.textContent, "▼" );

  const id = "date::sess_42::2026-06-23";
  assert.deepEqual( vs.setCalls, [ [ id, true ], [ id, false ] ] );
  h.renderer.unmount();
} );

// ===========================================================================
// 2 — Sender-card header click toggles + persists
// ===========================================================================

test( "sender-card header click collapses the card + persists (sender:: id)", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );

  const card   = h.sCards.querySelector( ".sender-card" ) as HTMLElement;
  const header = card.querySelector( ".sender-card-header" ) as HTMLElement;
  const toggle = card.querySelector( ".sender-toggle" ) as HTMLElement;
  // Click the project-name span (a non-interactive header region).
  const label  = header.querySelector( ".sender-project-name" ) as HTMLElement;

  clickBubbling( label );
  assert.equal( card.getAttribute( "data-collapsed" ), "true" );
  assert.equal( toggle.textContent, "▶" );
  assert.deepEqual( vs.setCalls, [ [ "sender::sess_42", true ] ] );
  h.renderer.unmount();
} );

// ===========================================================================
// 3 — Clicking an interactive control in the header does NOT collapse
// ===========================================================================

test( "sender-card header: click on the delete button does NOT toggle collapse", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );

  const card      = h.sCards.querySelector( ".sender-card" ) as HTMLElement;
  const deleteBtn = card.querySelector( ".sender-delete-btn" ) as HTMLElement;
  // Initial render already applied the persisted (expanded) state → "false".
  assert.equal( card.getAttribute( "data-collapsed" ), "false" );
  clickBubbling( deleteBtn );
  // Delete-button click is owned by its own handler → collapse state unchanged.
  assert.equal( card.getAttribute( "data-collapsed" ), "false" );
  assert.deepEqual( vs.setCalls, [] );
  h.renderer.unmount();
} );

// ===========================================================================
// 4 — Persisted collapse re-applies on render
// ===========================================================================

test( "render re-applies persisted collapse: a seeded-collapsed store paints data-collapsed=true", () => {
  const vs = makeFakeViewState( true );   // everything collapsed
  const h = setup( vs );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );   // initial render → reapplyAccordionCollapse

  const card      = h.sCards.querySelector( ".sender-card" ) as HTMLElement;
  const accordion = h.sCards.querySelector( ".date-accordion" ) as HTMLElement;
  assert.equal( card.getAttribute( "data-collapsed" ), "true" );
  assert.equal( accordion.getAttribute( "data-collapsed" ), "true" );
  assert.equal( ( card.querySelector( ".sender-toggle" ) as HTMLElement ).textContent, "▶" );
  h.renderer.unmount();
} );

// ===========================================================================
// 5 — Collapse-all / expand-all bulk (toolbar-driven)
// ===========================================================================

test( "collapse-all then expand-all flips every accordion + persists each", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );

  const card      = h.sCards.querySelector( ".sender-card" ) as HTMLElement;
  const accordion = h.sCards.querySelector( ".date-accordion" ) as HTMLElement;

  emitBulk( h.bus, true );
  assert.equal( card.getAttribute( "data-collapsed" ), "true" );
  assert.equal( accordion.getAttribute( "data-collapsed" ), "true" );

  emitBulk( h.bus, false );
  assert.equal( card.getAttribute( "data-collapsed" ), "false" );
  assert.equal( accordion.getAttribute( "data-collapsed" ), "false" );

  // Persisted both levels both directions.
  assert.ok( vs.setCalls.some( ( [ id, c ] ) => id === "sender::sess_42" && c === true ) );
  assert.ok( vs.setCalls.some( ( [ id, c ] ) => id === "date::sess_42::2026-06-23" && c === false ) );
  h.renderer.unmount();
} );

// ===========================================================================
// 6 — No store wired: clicks + bulk still toggle the DOM (no persist, no throw)
// ===========================================================================

test( "no viewState store: header click toggles DOM without persisting", () => {
  const h = setup( undefined );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );
  const accordion = h.sCards.querySelector( ".date-accordion" ) as HTMLElement;
  clickBubbling( accordion.querySelector( ".date-accordion-header" ) as HTMLElement );
  assert.equal( accordion.getAttribute( "data-collapsed" ), "true" );
  h.renderer.unmount();
} );

test( "no viewState store: collapse-all still flips DOM without persisting", () => {
  const h = setup( undefined );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );
  const card = h.sCards.querySelector( ".sender-card" ) as HTMLElement;
  emitBulk( h.bus, true );
  assert.equal( card.getAttribute( "data-collapsed" ), "true" );
  h.renderer.unmount();
} );

// ===========================================================================
// 7 — Edge branches in dateAccordionId + forEachAccordion id-guards
// ===========================================================================

test( "date-accordion with NO sender-card ancestor: click toggles DOM, no persist (dateAccordionId null)", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.renderer.mount( h.root );
  // Inject a detached accordion (no .sender-card parent) directly in the mount.
  const acc = document.createElement( "div" );
  acc.className = "date-accordion";
  acc.setAttribute( "data-date-key", "2026-06-23" );
  acc.innerHTML = `<div class="date-accordion-header"><span class="date-toggle">▼</span></div>`;
  h.sCards.appendChild( acc );
  clickBubbling( acc.querySelector( ".date-accordion-header" ) as HTMLElement );
  assert.equal( acc.getAttribute( "data-collapsed" ), "true" );   // DOM flipped
  assert.deepEqual( vs.setCalls, [] );                            // id null → no persist
  h.renderer.unmount();
} );

test( "date-accordion inside a sender-card MISSING data-date-key: id null → no persist", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.renderer.mount( h.root );
  const card = document.createElement( "div" );
  card.className = "sender-card";
  card.setAttribute( "data-sender-id", "sX" );
  card.innerHTML = `<div class="date-accordion"><div class="date-accordion-header"><span class="date-toggle">▼</span></div></div>`;
  h.sCards.appendChild( card );
  clickBubbling( card.querySelector( ".date-accordion-header" ) as HTMLElement );
  assert.equal( ( card.querySelector( ".date-accordion" ) as HTMLElement ).getAttribute( "data-collapsed" ), "true" );
  assert.deepEqual( vs.setCalls, [] );   // senderId defined but dateKey undefined → null
  h.renderer.unmount();
} );

test( "sender-card MISSING data-sender-id: header click toggles DOM, no persist", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.renderer.mount( h.root );
  const card = document.createElement( "div" );
  card.className = "sender-card";
  card.innerHTML = `<div class="sender-card-header"><span class="sender-toggle">▼</span></div><div class="sender-card-dates"></div>`;
  h.sCards.appendChild( card );
  clickBubbling( card.querySelector( ".sender-toggle" ) as HTMLElement );
  assert.equal( card.getAttribute( "data-collapsed" ), "true" );
  assert.deepEqual( vs.setCalls, [] );
  h.renderer.unmount();
} );

test( "bulk over malformed injected cards: id-guards skip persist for both levels", () => {
  const vs = makeFakeViewState();
  const h = setup( vs );
  h.notifList.push( makeNotification() );
  h.senderList.push( makeSender() );
  h.renderer.mount( h.root );
  // Append a malformed card: no data-sender-id, accordion no data-date-key.
  const bad = document.createElement( "div" );
  bad.className = "sender-card";
  bad.innerHTML = `<div class="sender-card-header"><span class="sender-toggle">▼</span></div>`
    + `<div class="sender-card-dates"><div class="date-accordion"><div class="date-accordion-header"><span class="date-toggle">▼</span></div></div></div>`;
  h.sCards.appendChild( bad );
  vs.setCalls.length = 0;
  emitBulk( h.bus, true );
  // The malformed card (no data-sender-id) is SKIPPED by forEachAccordion's
  // id-guard → never flipped, never persisted...
  assert.equal( bad.getAttribute( "data-collapsed" ), null );
  assert.equal( ( bad.querySelector( ".date-accordion" ) as HTMLElement ).getAttribute( "data-collapsed" ), null );
  // ...and only the REAL card/accordion ids were persisted.
  assert.deepEqual(
    vs.setCalls.map( ( [ id ] ) => id ).sort(),
    [ "date::sess_42::2026-06-23", "sender::sess_42" ],
  );
  h.renderer.unmount();
} );
