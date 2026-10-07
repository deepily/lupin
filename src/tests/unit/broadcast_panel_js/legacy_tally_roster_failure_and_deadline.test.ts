// Legacy broadcast-panel.js — the ack tally's two roster/deadline questions from row a08dfa48 (Rachel, 2026-10-07).
// Run via `npx tsx --test src/tests/unit/broadcast_panel_js/legacy_tally_roster_failure_and_deadline.test.ts`.
//
// The multiplexer tally had two defects: a failed active-sessions fetch printed "All 0 sessions acknowledged",
// and a roster that landed after the deadline never timed out. The legacy panel is a different design (it
// snapshots the roster when the POST returns, and arms its deadline from an ack), so each question is asked
// the legacy way, through the real DOM and the real send path, and each test asserts the CORRECT behaviour.
// A test that goes red is a defect that is real here too.
//
// HOW IT LOADS: broadcast-panel.js is an IIFE with no exports, so the whole file is run through
// vm.runInThisContext once per test, against a fresh DOM and a fake authedFetch. The real bytes are under test.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE               = dirname( fileURLToPath( import.meta.url ) );
const BROADCAST_PANEL_JS = resolve( HERE, "../../../lupin_app/static/js/broadcast-panel.js" );

const SESSIONS = [
  { session_id: "s1aaaaaa-1111", persona_name: "Rio",    persona_icon: "⚡", persona_color: "#111" },
  { session_id: "s2bbbbbb-2222", persona_name: "Sam",    persona_icon: "🎙️", persona_color: "#222" },
];

type Timer = { cb: () => void; ms: number };
let timers: Timer[] = [];
const realSetTimeout = globalThis.setTimeout;
let release: ( v: Response ) => void = () => {};
let activeSessionsFails = false;

function jsonResponse( body: unknown ): Response {
  return { ok: true, status: 200, json: async () => body, headers: { get: () => null } } as unknown as Response;
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => {
  timers = [];
  activeSessionsFails = false;
  document.body.innerHTML = `
    <div id="broadcast-recipients-row"><span id="broadcast-recipients-label">To:</span><button id="broadcast-recipients-refresh">↻</button></div>
    <textarea id="broadcast-textarea"></textarea>
    <div id="broadcast-preview"></div>
    <button id="broadcast-send-button"></button>
    <div id="broadcast-submit-status"></div>
    <div id="broadcast-aggregate-panel"></div>`;
  ( window as unknown as Record<string, unknown> ).notificationsUI = {
    authedFetch: ( url: string, opts?: { method?: string } ): Promise<Response> => {
      if ( url.endsWith( "/active-sessions" ) ) {
        return activeSessionsFails ? Promise.reject( new Error( "network down" ) ) : Promise.resolve( jsonResponse( { sessions: SESSIONS } ) );
      }
      if ( opts?.method === "POST" ) return new Promise<Response>( ( r ) => { release = r; } );
      return Promise.reject( new Error( "unexpected url " + url ) );
    },
  };
  // Capture the panel's timers; everything else still gets a real timer.
  ( globalThis as unknown as { setTimeout: unknown } ).setTimeout = ( cb: () => void, ms?: number ) => {
    if ( ms !== undefined && ms >= 60_000 ) { timers.push( { cb, ms } ); return timers.length; }
    return realSetTimeout( cb, ms );
  };
  vm.runInThisContext( readFileSync( BROADCAST_PANEL_JS, "utf8" ), { filename: BROADCAST_PANEL_JS } );
} );

afterEach( () => {
  ( globalThis as unknown as { setTimeout: unknown } ).setTimeout = realSetTimeout;
  document.body.replaceChildren();
} );

const tick = () => new Promise( ( r ) => realSetTimeout( r, 0 ) );
const summary = () => document.getElementById( "broadcast-aggregate-summary" )?.textContent ?? "";

/** Roster loaded, a message typed, the send confirmed; the POST is left pending. */
async function sendWithPostPending(): Promise<void> {
  await tick();                                                       // the initial roster fetch has landed
  const ta = document.getElementById( "broadcast-textarea" ) as HTMLTextAreaElement;
  ta.value = "hello fleet";
  ta.dispatchEvent( new Event( "input" ) );
  ( document.getElementById( "broadcast-send-button" ) as HTMLButtonElement ).click();
  ( document.querySelector( ".btn-confirm" ) as HTMLButtonElement ).click();   // POST is now in flight
  await tick();
}

test( "control: with the roster loaded, a send shows the tally against the 2 recipients", async () => {
  await sendWithPostPending();
  release( jsonResponse( { broadcast_id: "bbbbbbbb-1111-4222-8333-444444444444", recipients: 2 } ) );
  await tick();
  assert.equal( summary(), "0/2 complete" );
} );

test( "a roster refresh that fails while the POST is in flight must not make the tally read 'All 0 sessions acknowledged'", async () => {
  await sendWithPostPending();
  activeSessionsFails = true;
  ( document.getElementById( "broadcast-recipients-refresh" ) as HTMLButtonElement ).click();   // the fetch fails, the cache empties
  await tick();
  release( jsonResponse( { broadcast_id: "bbbbbbbb-1111-4222-8333-444444444444", recipients: 2 } ) );
  await tick();
  assert.notEqual( summary(), "", "the tally rendered a summary line" );
  assert.doesNotMatch( summary(), /All 0 session/, `the server sent to 2 sessions; a failed roster read must not print a complete tally; got: ${ summary() }` );
} );

test( "a broadcast nobody acknowledges still times out: the deadline is armed when the tally starts", async () => {
  await sendWithPostPending();
  release( jsonResponse( { broadcast_id: "bbbbbbbb-1111-4222-8333-444444444444", recipients: 2 } ) );
  await tick();
  assert.equal( timers.filter( ( t ) => t.ms === 5 * 60 * 1000 ).length, 1, "one 5-minute deadline must be armed by the send; no ack has arrived to arm it" );
} );

test( "control for the timer capture: the first ack DOES arm the 5-minute deadline", async () => {
  await sendWithPostPending();
  release( jsonResponse( { broadcast_id: "bbbbbbbb-1111-4222-8333-444444444444", recipients: 2 } ) );
  await tick();
  ( window as unknown as { broadcastPanel: { handleAck( n: unknown ): void } } ).broadcastPanel.handleAck( {
    payload: { broadcast_id: "bbbbbbbb-1111-4222-8333-444444444444", session_id: "s1aaaaaa-1111", persona_name: "Rio", status: "ok", body_summary: "got it" },
  } );
  assert.equal( timers.filter( ( t ) => t.ms === 5 * 60 * 1000 ).length, 1, "the capture sees the timer the ack arms" );
} );
