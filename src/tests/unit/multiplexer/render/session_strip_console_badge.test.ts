// The session strip's live-console badge — row 27760534, plan §4, slice 7 (ruling Q10: the
// console opens from the seat's chip). 100% lines/branches/functions per the coverage mandate.
//
// Asserted through the REAL roster resolver with the twin-prefix fixture (B4.4c): two seats
// share their first 8 hex characters, so a badge that resolved on the prefix alone would
// open the wrong seat — and these tests would see which one it opened.
import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSessionStripRenderer, STRIP_CONSOLE_CLASS } from "../../../../lupin_app/static/js/multiplexer/render/SessionStripRenderer";
import { resolveTranscriptSeat, type TranscriptRosterRow } from "../../../../lupin_app/static/js/multiplexer/stores/SessionTranscriptRoster";
import type { StripSession } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); });
beforeEach(() => { document.body.replaceChildren(); globalThis.localStorage?.clear(); });

const RADIO = "e14bd712-700e-46ce-88ea-8db62604ceb4";
const TWIN  = "e14bd712-0000-4000-8000-000000000001";

function session( senderId: string, name: string, assigned: number ): StripSession {
  return { sender_id : senderId, voice_persona : { name, voice_id : "v", icon : "🦉", color : "#fff", borrowed : false }, assigned_at : assigned, active : true };
}

const S_RADIO = session( "claude.code@lupin#e14bd712", "mr radio", 1 );
const S_SAM   = session( "claude.code@lupin#e14bd712", "sam", 2 );   // same chip key width, different seat
const S_GONE  = session( "claude.code@lupin#deadbeef", "ghost", 3 );

function makeRoot(): HTMLElement {
  const root = document.createElement( "main" );
  root.innerHTML = `<div id="cc-session-strip"><div id="cc-strip-icons"></div>
    <button id="cc-strip-toggle"></button><button id="cc-hide-inactive-toggle"></button></div>`;
  document.body.appendChild( root );
  return root;
}

function setup( sessions: StripSession[], rows: TranscriptRosterRow[], withConsole = true ) {
  const bus    = createEventBusForTesting();
  let roster   = rows;
  const opened : string[] = [];
  const renderer = createSessionStripRenderer( {
    eventBus : bus,
    stores   : { strip : { list : () => sessions } },
    storage  : null,
    console  : withConsole ? {
      canOpen : ( s ) => resolveTranscriptSeat( { senderId : s.sender_id, personaName : s.voice_persona.name }, roster ) !== null,
      open    : ( s ) => { opened.push( resolveTranscriptSeat( { senderId : s.sender_id, personaName : s.voice_persona.name }, roster ) as string ); },
    } : undefined,
  } );
  const root = makeRoot();
  renderer.mount( root );
  return {
    bus, renderer, opened, root,
    setRoster : ( next: TranscriptRosterRow[] ) => {
      roster = next;
      bus.emit( { type : "store_session_transcript_roster_changed", payload : {}, source : "test", ts : 0 } );
    },
  };
}

const icons  = () => Array.from( document.querySelectorAll<HTMLElement>( ".cc-strip-icon" ) );
const badges = () => Array.from( document.querySelectorAll<HTMLElement>( `.${ STRIP_CONSOLE_CLASS }` ) );
const click  = ( el: Element ) => el.dispatchEvent( new MouseEvent( "click", { bubbles : true } ) );

test( "a chip whose seat resolves carries the badge; one that outlived its seat does not", () => {
  const h = setup( [ session( "claude.code@lupin#e14bd712", "mr radio", 1 ), S_GONE ],
    [ { session_id : RADIO, persona : "mr radio", project : "lupin", transcript_watchable : true } ] );
  const [ radio, gone ] = icons();
  assert.ok( radio!.querySelector( `.${ STRIP_CONSOLE_CLASS }` ) );
  assert.equal( gone!.querySelector( `.${ STRIP_CONSOLE_CLASS }` ), null );
  assert.equal( badges()[ 0 ]!.getAttribute( "role" ), "button" );
  assert.equal( badges()[ 0 ]!.tagName, "SPAN", "the icon is a <button>; a button may not contain one" );
  h.renderer.unmount();
} );

test( "B4.4c: clicking the badge opens the chip's OWN seat, by full id, and leaves focus alone", () => {
  // The strip keys icons on sender_id, so the twin-prefix pair is modelled as two strips.
  const rows: TranscriptRosterRow[] = [
    { session_id : RADIO, persona : "mr radio", project : "lupin", transcript_watchable : true },
    { session_id : TWIN,  persona : "sam",      project : "lupin", transcript_watchable : true },
  ];
  const a = setup( [ S_RADIO ], rows );
  click( badges()[ 0 ]! );
  assert.deepEqual( a.opened, [ RADIO ] );
  assert.equal( icons()[ 0 ]!.hasAttribute( "data-focused" ), false, "the badge is not a focus click" );
  a.renderer.unmount();
  document.body.replaceChildren();

  const b = setup( [ S_SAM ], rows );
  click( badges()[ 0 ]! );
  assert.deepEqual( b.opened, [ TWIN ], "a prefix-only resolver would have opened RADIO" );
  b.renderer.unmount();
} );

test( "a roster read adds and removes badges without any strip change", () => {
  const h = setup( [ S_RADIO ], [] );
  assert.equal( badges().length, 0 );
  h.setRoster( [ { session_id : RADIO, persona : "mr radio", project : "lupin", transcript_watchable : true } ] );
  assert.equal( badges().length, 1 );
  h.renderer.forceRenderForTesting();
  assert.equal( badges().length, 1, "re-painting does not add a second badge" );
  h.setRoster( [] );
  assert.equal( badges().length, 0 );
  h.renderer.unmount();
} );

test( "with no console affordance, no chip ever carries a badge, and a click still focuses", () => {
  const h = setup( [ S_RADIO ], [ { session_id : RADIO, persona : "mr radio", project : "lupin", transcript_watchable : true } ], false );
  assert.equal( badges().length, 0 );
  click( icons()[ 0 ]! );
  assert.equal( icons()[ 0 ]!.getAttribute( "data-focused" ), "true" );
  h.renderer.unmount();
} );
