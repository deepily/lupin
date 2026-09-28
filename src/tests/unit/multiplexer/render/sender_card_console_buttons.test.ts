// Row 27760534 — SenderCardConsoleButtons: the live-console button in each sender card's
// title bar, immediately LEFT of the persona chip (Rick's placement ruling, 2026-09-28).
//
// Cards are built by the REAL template (renderSenderCard), so the header shape these tests
// read is the one the list renderer actually emits, not a hand-written copy of it.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { renderSenderCard } from "../../../../lupin_app/static/js/multiplexer/render/templates/senderCard";
import {
  createSenderCardConsoleButtons,
  SENDER_CONSOLE_BUTTON_CLASS,
  type SenderCardConsoleAffordance,
} from "../../../../lupin_app/static/js/multiplexer/render/SenderCardConsoleButtons";
import type { SenderRecord, VoicePersona } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => {
  document.body.replaceChildren();
  ( globalThis as { marked?: { parse: ( s: string ) => string } } ).marked       = { parse: ( s: string ) => `<p>${ s }</p>` };
  ( globalThis as { DOMPurify?: { sanitize: ( s: string ) => string } } ).DOMPurify = { sanitize: ( s: string ) => s };
} );

function persona( name: string, icon: string ): VoicePersona {
  return { name, voice_id: `vid_${ name }`, icon, color: "#ab1234", borrowed: false };
}

function sender( senderId: string, vp: VoicePersona | undefined ): SenderRecord {
  return {
    sender_id                : senderId,
    display_name             : senderId,
    last_active_ts           : Date.UTC( 2026, 8, 28, 16, 0 ),
    unread_count             : 0,
    conversation_mode_active : false,
    ...( vp === undefined ? {} : { voice_persona: vp } ),
  };
}

function card( senderId: string, vp: VoicePersona | undefined ): HTMLElement {
  return renderSenderCard( sender( senderId, vp ), [], { appTimezone: "UTC" } );
}

interface Harness {
  container : HTMLElement;
  opened    : Array<[ string, string ]>;
  resolved  : Array<[ string, string | null ]>;
  seats     : Map<string, string>;
  bus       : ReturnType<typeof createEventBusForTesting>;
  buttons   : ReturnType<typeof createSenderCardConsoleButtons>;
}

// The affordance resolves by (senderId, personaName) — the persona name is how the real
// roster breaks a tie between twin sender-id prefixes, so the fake keys on BOTH.
function harness( ...cards: HTMLElement[] ): Harness {
  const container = document.createElement( "div" );
  container.id    = "sender-cards-container";
  for ( const c of cards ) container.appendChild( c );
  document.body.appendChild( container );

  const opened   : Array<[ string, string ]>         = [];
  const resolved : Array<[ string, string | null ]>  = [];
  const seats    = new Map<string, string>();
  const affordance: SenderCardConsoleAffordance = {
    resolve : ( senderId, personaName ) => {
      resolved.push( [ senderId, personaName ] );
      return seats.get( `${ senderId }|${ personaName }` ) ?? null;
    },
    open    : ( ccSessionId, title ) => { opened.push( [ ccSessionId, title ] ); },
  };
  const bus     = createEventBusForTesting();
  const buttons = createSenderCardConsoleButtons( { eventBus: bus, affordance } );
  return { container, opened, resolved, seats, bus, buttons };
}

function rosterChanged( h: Harness ): void {
  h.bus.emit( { type: "store_session_transcript_roster_changed", payload: {}, source: "test", ts: 0 } );
}

const tick = () => new Promise<void>( ( r ) => setTimeout( r, 0 ) );

function buttonsIn( el: ParentNode ): HTMLButtonElement[] {
  return Array.from( el.querySelectorAll<HTMLButtonElement>( `.${ SENDER_CONSOLE_BUTTON_CLASS }` ) );
}

// ---------------------------------------------------------------------------

test( "a card whose seat resolves gets one button, immediately LEFT of the persona chip", () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "e14bd712-full" );
  h.buttons.mount( h.container );

  const btns = buttonsIn( h.container );
  assert.equal( btns.length, 1 );
  const btn   = btns[ 0 ]!;
  const badge = h.container.querySelector( ".sender-persona-badge" );
  assert.ok( badge !== null, "fixture: the real template emits a persona chip" );
  assert.equal( btn.nextElementSibling, badge, "the button sits immediately before the chip" );
  assert.equal( btn.tagName, "BUTTON" );
  assert.equal( btn.type, "button" );
  assert.equal( btn.dataset[ "seat" ], "e14bd712-full" );
  assert.equal( btn.dataset[ "testid" ], "multiplexer-sender-console" );
  assert.deepEqual( h.resolved, [ [ "claude.code@lupin.deepily.ai#e14bd712", "Mr. Radio" ] ],
    "the persona NAME is read from the chip and handed to the resolver" );
} );

test( "a card whose seat does not resolve gets no button", () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#aaaa1111", persona( "Rio", "🎸" ) ) );
  h.buttons.mount( h.container );
  assert.equal( buttonsIn( h.container ).length, 0 );
} );

test( "twin sender-id prefixes: each card gets ITS seat, told apart by persona name", () => {
  const h = harness(
    card( "claude.code@lupin.deepily.ai#abcd1234", persona( "Rio", "🎸" ) ),
    card( "claude.code@lupin.deepily.ai#abcd1234x", persona( "Krishna", "🪷" ) ),
  );
  h.seats.set( "claude.code@lupin.deepily.ai#abcd1234|Rio",       "seat-rio" );
  h.seats.set( "claude.code@lupin.deepily.ai#abcd1234x|Krishna",  "seat-krishna" );
  h.buttons.mount( h.container );

  const seats = buttonsIn( h.container ).map( ( b ) => b.dataset[ "seat" ] );
  assert.deepEqual( seats, [ "seat-rio", "seat-krishna" ] );
} );

test( "clicking the button opens the console with the chip's icon and name, and does not collapse the card", () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "e14bd712-full" );
  h.buttons.mount( h.container );

  // The list renderer collapses a card from a click on its header; a click that reaches
  // the header would be that collapse. The button must stop it there.
  let headerClicks = 0;
  h.container.querySelector( ".sender-card-header" )!.addEventListener( "click", () => { headerClicks += 1; } );

  buttonsIn( h.container )[ 0 ]!.click();
  assert.deepEqual( h.opened, [ [ "e14bd712-full", "🦉 Mr. Radio — console" ] ] );
  assert.equal( headerClicks, 0, "the click never reached the header's collapse handler" );
} );

test( "a card with no persona chip gets the button at the end of its title bar, titled by sender id", () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#0000beef", undefined ) );
  assert.equal( h.container.querySelector( ".sender-persona-badge" ), null, "fixture: no chip without a persona" );
  h.seats.set( "claude.code@lupin.deepily.ai#0000beef|null", "seat-anon" );
  h.buttons.mount( h.container );

  const header = h.container.querySelector( ".sender-card-header" )!;
  const btn    = buttonsIn( h.container )[ 0 ]!;
  assert.equal( header.lastElementChild, btn );
  btn.click();
  assert.deepEqual( h.opened, [ [ "seat-anon", "claude.code@lupin.deepily.ai#0000beef — console" ] ] );
} );

test( "a card re-rendered from cache loses the button, and the observer paints it back", async () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "e14bd712-full" );
  h.buttons.mount( h.container );
  assert.equal( buttonsIn( h.container ).length, 1 );

  // What the list renderer does when a card's inputs move: swap the card wholesale.
  const fresh = card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) );
  h.container.firstElementChild!.replaceWith( fresh );
  assert.equal( buttonsIn( h.container ).length, 0, "the swap dropped the button" );

  await tick();
  const btns = buttonsIn( h.container );
  assert.equal( btns.length, 1, "the observer repainted it" );
  assert.ok( fresh.contains( btns[ 0 ]! ), "on the NEW card" );
} );

test( "a repaint that changes nothing inserts nothing (it cannot feed its own observer)", async () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "e14bd712-full" );
  h.buttons.mount( h.container );
  const first = buttonsIn( h.container )[ 0 ];

  h.buttons.forceRenderForTesting();
  await tick();
  assert.equal( buttonsIn( h.container )[ 0 ], first, "the same node survives an idle repaint" );
  const calls = h.resolved.length;
  await tick();
  assert.equal( h.resolved.length, calls, "no repaint loop: the idle repaint triggered no further paint" );
} );

test( "a roster change moves the button: a new seat replaces it, a lost seat removes it", () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  h.buttons.mount( h.container );
  assert.equal( buttonsIn( h.container ).length, 0 );

  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "seat-one" );
  rosterChanged( h );
  assert.equal( buttonsIn( h.container )[ 0 ]!.dataset[ "seat" ], "seat-one" );

  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "seat-two" );
  rosterChanged( h );
  const btns = buttonsIn( h.container );
  assert.equal( btns.length, 1, "replaced, not duplicated" );
  assert.equal( btns[ 0 ]!.dataset[ "seat" ], "seat-two" );

  h.seats.clear();
  rosterChanged( h );
  assert.equal( buttonsIn( h.container ).length, 0 );
} );

test( "a card without a title bar is skipped", () => {
  const bare = document.createElement( "div" );
  bare.className = "sender-card";
  bare.setAttribute( "data-sender-id", "claude.code@lupin.deepily.ai#e14bd712" );
  const h = harness( bare );
  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|null", "seat" );
  h.buttons.mount( h.container );
  assert.equal( buttonsIn( h.container ).length, 0 );
  assert.equal( h.resolved.length, 0, "no header, no resolve" );
} );

test( "unmount removes every button, stops listening, and a second mount throws", async () => {
  const h = harness( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  h.seats.set( "claude.code@lupin.deepily.ai#e14bd712|Mr. Radio", "e14bd712-full" );
  h.buttons.mount( h.container );
  assert.throws( () => h.buttons.mount( h.container ), /already mounted/ );

  h.buttons.unmount();
  assert.equal( buttonsIn( h.container ).length, 0 );
  const calls = h.resolved.length;
  rosterChanged( h );
  h.container.firstElementChild!.replaceWith( card( "claude.code@lupin.deepily.ai#e14bd712", persona( "Mr. Radio", "🦉" ) ) );
  await tick();
  assert.equal( h.resolved.length, calls, "neither the bus nor the observer paints after unmount" );
  assert.equal( buttonsIn( h.container ).length, 0 );
} );
