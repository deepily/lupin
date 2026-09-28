// The legacy sender card's console button — row 27760534, Rick's ruling 2026-09-28.
//
// The legacy client gets NO in-pane console. Its button opens the standalone console page in a
// new tab: `/app/console?seat=<FULL cc session id>&title=<title>`. What these cases pin:
//
//   · the button appears only on a card whose seat resolves, and only for an admin
//   · it sits IMMEDIATELY LEFT of `.persona-badge` (first in the stats group with no badge)
//   · one per card, and a repaint after the header is patched does not add a second
//   · a click calls window.open( href, "_blank" ) with the exact href, and does NOT collapse
//     the card (the header's own click handler never fires)
//   · twin sender-id prefixes are told apart by the persona name on the card
//   · the roster read is admin-only and a failed read leaves the previous roster in place
//
// The cards are built by the REAL createSenderCard and badged by the REAL
// _setPersonaBadgeOnCard, so the markup under test is the markup the page renders — a
// hand-written header would be better-formed than the real one exactly where the painter
// depends on it.
//
// ⚠️ Every assertion compares a boolean, a number or a string, never a DOM node: a failing
// assert holding a happy-dom element inspects the whole document for its message, and the
// jstest lane's RSS watchdog kills the run before the failure prints (rows f5768ee4 / 32c58572).
//
// Coverage: notifications.js is outside c8 by ruling (run-typescript-tests.sh, "DOCUMENTED
// EXEMPTION"). Its gate is behavioural: every branch of the code added for this button is
// driven by a named case below.
//
// Run: npx tsx --test src/tests/unit/notifications_js/the_legacy_sender_card_console_button_opens_the_console_page.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { buildConsolePageHref } from "../../../lupin_app/static/js/multiplexer/console/consolePageUrl";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type UI   = Record<string, any>;
type Seat = { session_id: string; project?: string | null; persona?: string | null; transcript_watchable: boolean };

let paintAll : ( container: Element, roster: Seat[], openWindow?: ( href: string, target: string ) => void ) => void;
let paintOne : ( card: Element, roster: Seat[], openWindow?: ( href: string, target: string ) => void ) => void;
let state    : { roster: Seat[] };
let BTN      : string;

// Two live seats sharing "4cecf18a" — the twin case — and one with a prefix of its own.
const TWIN_A = "4cecf18a-66f7-442f-98f3-98d61d680654";
const TWIN_B = "4cecf18a-0000-4b1c-9d2e-111111111111";
const LONER  = "449359bc-c735-4970-8fc0-e83b635c8548";

const TWIN_SENDER  = "claude.code@lupin.deepily.ai#4cecf18a";
const LONER_SENDER = "claude.code@lupin.deepily.ai#449359bc";

const RADIO = { name : "mr radio", display_name : "Mr. Radio", icon : "🦉", color : "#123456" };
const ROSA  = { name : "rosa",     display_name : "Rosa",      icon : "🌹", color : "#654321" };

function row( id: string, persona: string | null, watchable = true ): Seat {
  return { session_id : id, project : "lupin", persona, transcript_watchable : watchable };
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) +
    "\n;globalThis.NotificationsUI        = NotificationsUI;" +
    "\n;globalThis.__ccPaintAll           = ccConsolePaintSenderButtons;" +
    "\n;globalThis.__ccPaintOne           = ccConsolePaintSenderCard;" +
    "\n;globalThis.__ccConsoleState       = ccConsoleState;" +
    "\n;globalThis.__ccConsoleButtonClass = CC_CONSOLE_BUTTON_CLASS;",
    { filename : NOTIFICATIONS_JS }
  );
  const g  = globalThis as Record<string, unknown>;
  paintAll = g.__ccPaintAll           as typeof paintAll;
  paintOne = g.__ccPaintOne           as typeof paintOne;
  state    = g.__ccConsoleState       as typeof state;
  BTN      = g.__ccConsoleButtonClass as string;
  assert.equal( typeof paintAll, "function", "ccConsolePaintSenderButtons loaded" );
  assert.equal( BTN, "sender-console-btn", "the class the shared sheet styles" );
} );

const realOpen  = globalThis.window?.open;
const realFetch = globalThis.fetch;
let opened : Array<[ string, string ]>;

beforeEach( () => {
  document.body.innerHTML = "";
  state.roster = [ ];
  opened       = [ ];
  ( globalThis.window as any ).open = ( href: string, target: string ) => { opened.push( [ href, target ] ); return null; };
} );

afterEach( () => {
  ( globalThis.window as any ).open = realOpen;
  globalThis.fetch = realFetch;
} );

function newUI( isAdmin = true ): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  ui.debug             = false;
  ui.log               = (): void => {};
  ui.error             = (): void => {};
  ui.isAdmin           = isAdmin;
  ui.authToken         = "tok";
  ui.senderGroups      = new Map();
  ui.sessionNames      = { };
  ui.conversationModes = { };
  ui.senderPersonaMap  = new Map();
  ui.ccFocusState      = { enabled : false, focused_sender_id : null };
  ui.ccStripUnreadCounts        = { };
  ui._applyFocusHiddenToCard    = (): void => {};
  ui._applyCardWorkerFlag       = (): void => {};
  ui._addStripIcon              = (): void => {};
  ui._setStripIconPersonaColor  = (): void => {};
  return ui;
}

function mountList(): HTMLElement {
  const el = document.createElement( "div" );
  el.id = "notifications-list";
  document.body.appendChild( el );
  return el;
}

/** A real sender card, badged with `persona` when given. Initial-load path: no roster read. */
function card( ui: UI, senderId: string, persona: Record<string, string> | null ): Element {
  if ( persona ) ui.senderPersonaMap.set( senderId, persona );
  ui.createSenderCard( senderId, false );
  return document.querySelector( `.sender-card[data-sender-id="${ senderId }"]` ) as Element;
}

function buttons( root: ParentNode ): HTMLButtonElement[] {
  return Array.from( root.querySelectorAll<HTMLButtonElement>( `.${ BTN }` ) );
}

/** The class of the element right after the button — a string, never a node. */
function nextClass( btn: Element ): string {
  return ( btn.nextElementSibling?.className ?? "<none>" ).trim();
}

const settle = () => new Promise( ( r ) => setTimeout( r, 0 ) );

// 🔴 A FUSE ON THE OBSERVER. A painter that is not idempotent re-inserts its button on every
// repaint, the insert is a mutation, the mutation repaints — and the loop ran this file out of
// heap (2 GB, SIGABRT, no test named) on the first mutation arm, 2026-09-28. The jstest lane's
// watchdog would kill it the same way. So every observer test counts repaints through this
// fuse, which stops the loop after FUSE calls and lets a named assertion report it instead.
const FUSE = 25;
function fuse( ui: UI ): () => number {
  let calls = 0;
  const real = ui.repaintCcConsoleButtons.bind( ui );
  ui.repaintCcConsoleButtons = (): void => { calls += 1; if ( calls <= FUSE ) real(); };
  return () => calls;
}
function assertQuiet( calls: () => number ): void {
  assert.equal( calls() < FUSE, true, `the observer fed itself: ${ calls() } repaints — a repaint that changes nothing must insert nothing` );
}


// ── appears only for a resolvable seat ───────────────────────────────────────

test( "a card whose seat resolves gets one button, immediately LEFT of .persona-badge", () => {
  const ui   = newUI();
  const list = mountList();
  const c    = card( ui, LONER_SENDER, RADIO );
  paintAll( list, [ row( LONER, "Mr. Radio" ) ] );

  const btns = buttons( c );
  assert.equal( btns.length, 1 );
  assert.equal( nextClass( btns[ 0 ] ), "persona-badge", "the button's next sibling is the persona chip" );
  assert.equal( btns[ 0 ].type, "button", "a real <button>, which the header's toggle must not treat as a header click" );
  assert.equal( btns[ 0 ].dataset.seat, LONER, "the FULL seat id, never the card's 8-hex" );
} );

test( "a card whose seat is not in the roster gets no button", () => {
  const ui   = newUI();
  const list = mountList();
  card( ui, LONER_SENDER, RADIO );
  paintAll( list, [ row( "deadbeef-0000-4000-8000-000000000000", "Mr. Radio" ) ] );
  assert.equal( buttons( list ).length, 0 );
} );

test( "a seat with no live transcript gets no button", () => {
  const ui   = newUI();
  const list = mountList();
  card( ui, LONER_SENDER, RADIO );
  paintAll( list, [ row( LONER, "Mr. Radio", false ) ] );
  assert.equal( buttons( list ).length, 0 );
} );

test( "a card whose sender id is not <who>@<host>#<hex> gets no button", () => {
  const ui   = newUI();
  const list = mountList();
  card( ui, "notification.proxy@lupin.deepily.ai", null );
  paintAll( list, [ row( LONER, null ) ] );
  assert.equal( buttons( list ).length, 0 );
} );

test( "a seat that stops resolving loses its button on the next paint", () => {
  const ui   = newUI();
  const list = mountList();
  card( ui, LONER_SENDER, RADIO );
  paintAll( list, [ row( LONER, "Mr. Radio" ) ] );
  assert.equal( buttons( list ).length, 1, "precondition: painted" );
  paintAll( list, [ ] );
  assert.equal( buttons( list ).length, 0 );
} );

test( "a non-admin never gets a button, whatever the roster holds", () => {
  const ui   = newUI( false );
  mountList();
  card( ui, LONER_SENDER, RADIO );
  state.roster = [ row( LONER, "Mr. Radio" ) ];
  ui.repaintCcConsoleButtons();
  assert.equal( buttons( document ).length, 0 );

  // The positive control: the same roster, the same card, an admin — painted.
  ui.isAdmin = true;
  ui.repaintCcConsoleButtons();
  assert.equal( buttons( document ).length, 1, "the harness can paint, so the zero above is the admin gate" );
} );

test( "repaint without the list on the page is a no-op, not a throw", () => {
  const ui = newUI();
  ui.repaintCcConsoleButtons();
  assert.equal( buttons( document ).length, 0 );
} );


// ── placement when there is no badge yet, and after it arrives ───────────────

test( "with no badge yet, the button is first in the stats group; the late badge puts it back LEFT", async () => {
  const ui   = newUI();
  const list = mountList();
  const c    = card( ui, LONER_SENDER, null );
  state.roster = [ row( LONER, "Mr. Radio" ) ];
  const calls  = fuse( ui );
  ui.startCcConsoleButtonObserver();

  const group = c.querySelector( ".sender-stats-group" ) as Element;
  assert.equal( group.firstElementChild?.classList.contains( BTN ), true, "first in the stats group, where the chip will land" );

  // The persona arrives later: the real patch inserts the badge FIRST in the stats group,
  // i.e. to the button's right-hand side of nothing — before it. The observer repaints.
  ui._setPersonaBadgeOnCard( LONER_SENDER, RADIO );
  await settle();
  assertQuiet( calls );

  const btns = buttons( c );
  assert.equal( btns.length, 1, "still exactly one" );
  assert.equal( nextClass( btns[ 0 ] ), "persona-badge", "moved back in front of the chip" );
  ui.ccConsoleButtonObserver.disconnect();
  void list;
} );

test( "a header with no stats group takes the button at its end", () => {
  const list = mountList();
  list.innerHTML =
    `<div class="sender-card" data-sender-id="${ LONER_SENDER }">` +
    `<div class="sender-card-header"><span class="sender-project-name">LUPIN</span></div></div>`;
  paintAll( list, [ row( LONER, null ) ] );
  const header = list.querySelector( ".sender-card-header" ) as Element;
  assert.equal( header.lastElementChild?.classList.contains( BTN ), true );
} );

test( "a card with no header is skipped", () => {
  const list = mountList();
  list.innerHTML = `<div class="sender-card" data-sender-id="${ LONER_SENDER }"></div>`;
  paintAll( list, [ row( LONER, null ) ] );
  assert.equal( buttons( list ).length, 0 );
} );


// ── one per card, idempotent across re-renders ───────────────────────────────

test( "painting twice adds nothing and touches nothing", () => {
  const ui   = newUI();
  const list = mountList();
  const c    = card( ui, LONER_SENDER, RADIO );
  const roster = [ row( LONER, "Mr. Radio" ) ];
  paintAll( list, roster );
  const first = buttons( c )[ 0 ];
  paintAll( list, roster );
  assert.equal( buttons( c ).length, 1 );
  assert.equal( buttons( c )[ 0 ] === first, true, "the same element survived: an idle repaint does not re-create it" );
} );

test( "after the header's badge is re-rendered, the observer's repaint leaves exactly one button", async () => {
  const ui   = newUI();
  mountList();
  const c    = card( ui, LONER_SENDER, RADIO );
  state.roster = [ row( LONER, "Mr. Radio" ) ];
  const calls  = fuse( ui );
  ui.startCcConsoleButtonObserver();
  ui.startCcConsoleButtonObserver();   // a second start is a no-op, not a second observer
  assert.equal( buttons( c ).length, 1, "precondition: painted on start" );

  // The real in-place patch: the badge is REPLACED via outerHTML, several times over.
  ui._setPersonaBadgeOnCard( LONER_SENDER, RADIO );
  ui._setPersonaBadgeOnCard( LONER_SENDER, RADIO );
  await settle();
  assertQuiet( calls );
  const btns = buttons( c );
  assert.equal( btns.length, 1, "one per card after the header is re-rendered" );
  assert.equal( nextClass( btns[ 0 ] ), "persona-badge" );
  ui.ccConsoleButtonObserver.disconnect();
} );

test( "a persona renamed in place re-titles the tab the button opens", async () => {
  const ui   = newUI();
  mountList();
  const c    = card( ui, LONER_SENDER, RADIO );
  state.roster = [ row( LONER, null ) ];
  const calls  = fuse( ui );
  ui.startCcConsoleButtonObserver();

  ui._setPersonaBadgeOnCard( LONER_SENDER, ROSA );
  await settle();
  assertQuiet( calls );
  const btns = buttons( c );
  assert.equal( btns.length, 1 );
  btns[ 0 ].click();
  assert.equal( opened[ 0 ][ 0 ], buildConsolePageHref( LONER, "🌹 Rosa — console" ) );
  ui.ccConsoleButtonObserver.disconnect();
} );

test( "starting the observer with no list on the page does nothing", () => {
  const ui = newUI();
  ui.startCcConsoleButtonObserver();
  assert.equal( ui.ccConsoleButtonObserver ?? null, null );
} );


// ── the click ────────────────────────────────────────────────────────────────

test( "a click opens the console page in a new tab with the exact href, and does not collapse the card", () => {
  const ui   = newUI();
  const list = mountList();
  const c    = card( ui, LONER_SENDER, RADIO );
  let toggles = 0;
  ui.toggleSenderCard = (): void => { toggles += 1; };
  const header = c.querySelector( ".sender-card-header" ) as HTMLElement;
  header.addEventListener( "click", () => { toggles += 1; } );
  paintAll( list, [ row( LONER, "Mr. Radio" ) ] );

  buttons( c )[ 0 ].click();

  // Pinned to a LITERAL on one side, so the comparison is not two copies of one builder.
  const literal = "/app/console?seat=449359bc-c735-4970-8fc0-e83b635c8548" +
                  "&title=%F0%9F%A6%89%20Mr.%20Radio%20%E2%80%94%20console";
  assert.equal( opened.length, 1 );
  assert.equal( opened[ 0 ][ 0 ], literal );
  assert.equal( opened[ 0 ][ 1 ], "_blank" );
  assert.equal( literal, buildConsolePageHref( LONER, "🦉 Mr. Radio — console" ), "the multiplexer builds the same href" );
  assert.equal( toggles, 0, "the header's click handler fired, so the card would have collapsed" );

  // The positive control for the counter: a header click does count.
  header.click();
  assert.equal( toggles > 0, true, "the header listener is live, so the zero above means something" );
} );

test( "an injected opener receives the click instead of window.open", () => {
  const ui   = newUI();
  const list = mountList();
  const c    = card( ui, LONER_SENDER, null );
  const got : Array<[ string, string ]> = [ ];
  paintOne( c, [ row( LONER, null ) ], ( href, target ) => { got.push( [ href, target ] ); } );
  buttons( c )[ 0 ].click();
  assert.equal( opened.length, 0 );
  assert.equal( got.length, 1 );
  // No badge: the title falls back to the sender id, as the multiplexer's `name ?? senderId`.
  assert.equal( got[ 0 ][ 0 ], buildConsolePageHref( LONER, `${ LONER_SENDER } — console` ) );
  void list;
} );


// ── twin prefixes ────────────────────────────────────────────────────────────

test( "twin prefixes are told apart by the persona name on each card", () => {
  const list = mountList();
  // Two cards cannot share one sender id in the list, so the twins arrive as the same 8-hex
  // on two cards painted separately — which is exactly the tie the persona name must break.
  const roster = [ row( TWIN_A, "Mr. Radio" ), row( TWIN_B, "Rosa" ) ];

  const uiA = newUI();
  const a   = card( uiA, TWIN_SENDER, RADIO );
  paintAll( list, roster );
  assert.equal( buttons( a )[ 0 ]?.dataset.seat, TWIN_A, "Mr. Radio's card opens Mr. Radio's seat" );

  document.body.innerHTML = "";
  const list2 = mountList();
  const uiB   = newUI();
  const b     = card( uiB, TWIN_SENDER, ROSA );
  paintAll( list2, roster );
  assert.equal( buttons( b )[ 0 ]?.dataset.seat, TWIN_B, "Rosa's card opens Rosa's seat" );
} );

test( "twins with no persona name on the card get no button — never a guess", () => {
  const ui   = newUI();
  const list = mountList();
  card( ui, TWIN_SENDER, null );
  paintAll( list, [ row( TWIN_A, "Mr. Radio" ), row( TWIN_B, "Rosa" ) ] );
  assert.equal( buttons( list ).length, 0 );
} );


// ── the roster read ──────────────────────────────────────────────────────────

function stubFetch( reply: () => Promise<unknown> ): string[] {
  const urls: string[] = [ ];
  globalThis.fetch = ( async ( url: string ) => { urls.push( url ); return reply(); } ) as typeof fetch;
  return urls;
}

test( "an admin's roster read fills the roster and paints the cards", async () => {
  const ui   = newUI();
  mountList();
  card( ui, LONER_SENDER, RADIO );
  const urls = stubFetch( async () => ( { ok : true, json : async () => ( { status : "ok", seats : [ row( LONER, "Mr. Radio" ) ] } ) } ) );
  await ui.refreshCcConsoleRoster();
  assert.deepEqual( urls, [ "/api/cc-transcript-roster" ] );
  assert.equal( state.roster.length, 1 );
  assert.equal( buttons( document ).length, 1 );
} );

test( "a body with no seats (an unreachable arbiter) empties the roster", async () => {
  const ui = newUI();
  state.roster = [ row( LONER, null ) ];
  stubFetch( async () => ( { ok : true, json : async () => ( { status : "unreachable" } ) } ) );
  await ui.refreshCcConsoleRoster();
  assert.equal( state.roster.length, 0 );
} );

test( "a non-admin never reads the roster", async () => {
  const ui   = newUI( false );
  const urls = stubFetch( async () => { throw new Error( "must not be called" ); } );
  await ui.refreshCcConsoleRoster();
  assert.equal( urls.length, 0 );
} );

test( "a refused read keeps the previous roster", async () => {
  const ui = newUI();
  state.roster = [ row( LONER, null ) ];
  const warn = console.warn;
  console.warn = (): void => {};
  try {
    stubFetch( async () => ( { ok : false, status : 403, json : async () => ( { } ) } ) );
    await ui.refreshCcConsoleRoster();
    assert.equal( state.roster.length, 1, "refused" );

    stubFetch( async () => { throw new Error( "network down" ); } );
    await ui.refreshCcConsoleRoster();
    assert.equal( state.roster.length, 1, "failed" );
  } finally {
    console.warn = warn;
  }
} );

test( "a CC card created at runtime re-reads the roster; one from initial load does not", async () => {
  const ui   = newUI();
  mountList();
  const urls = stubFetch( async () => ( { ok : true, json : async () => ( { seats : [ ] } ) } ) );
  ui.createSenderCard( LONER_SENDER, false );
  assert.equal( urls.length, 0, "initial load: the read authentication started covers it" );
  ui.createSenderCard( TWIN_SENDER, true );
  await settle();
  assert.equal( urls.length, 1, "runtime: a new seat usually means a new roster row" );
} );
