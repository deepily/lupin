// Legacy notifications.js — B4.9: the console events subscribe on the QUEUE socket, and
// must NOT subscribe on the AUDIO one.
//
// Row 27760534, phase 2, slice 8. Plan §4.
//
// ─────────────────────── WHY BOTH HALVES ARE ASSERTED ───────────────────────
//
// 🔴 THE FAILURE THIS REPLACES IS A REAL ONE FROM THE PLAN'S OWN REVIEW. An earlier draft
// of §4 said the two `subscribed_events` lists at `:2636` and `:2663` were "both
// `subscribed_events` lists, so one edit is a silent half-fix" — i.e. it told the
// implementer to edit BOTH. That is backwards, and Tiberius caught it (§4, B1): they are
// not two copies of one list, they are TWO DIFFERENT SOCKETS.
//
//     _buildQueueAuthMessage  -> /ws/queue  — the console's traffic belongs here
//     _buildAudioAuthMessage  -> /ws/audio  — audio_streaming_* plus tts_error
//
// Adding the console events to the audio builder would subscribe the audio socket to
// traffic it must never carry. So a test asserting only "the queue list has them" would
// stay green through exactly the mistake the plan corrected. Both halves, or neither is
// worth writing.
//
// ─────────────────── AND THE NEGATIVE HALF NEEDS A CONTROL ───────────────────
//
// "no console events in the audio list" is a ZERO, and a zero is worth nothing until the
// same search has been watched returning a positive (CLAUDE.md § Reporting a
// measurement). If `_buildAudioAuthMessage` returned an empty list, or if this test
// mis-spelled the event names, the negative assertions would pass for the wrong reason.
// So the audio list is also asserted to carry its OWN events, using the same lookup.
//
// ────────────────────────────── ALSO PINNED HERE ──────────────────────────────
//
// That the two lists remain DIFFERENT POPULATIONS. Corroboration from the tree, not from
// argument: the audio list already carries `tts_error`, which is ABSENT from the INI's
// `websocket available events` key and therefore validates away today. A future tidy-up
// that "unifies the duplicated lists" would be a silent regression of the bug above, and
// this file is what would stop it.
//
// Coverage note (B4.10b): notifications.js CANNOT be instrumented by c8 — these tests
// load it by slicing the source string through `vm.runInThisContext`, which is outside
// c8's import graph, so c8 reports an ad-hoc 0/0 even when forced into `--include`. Its
// real gate is behavioural, in this tier plus the E2E rows B4.7/B4.8. That is a NAMED
// exclusion with its real gate, not silence.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/the_console_events_reach_the_queue_socket_and_not_the_audio_one.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE            = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

// The two server -> client frames the console rides. The client -> server verbs
// (`cc_transcript_watch` / `cc_transcript_unwatch`) are SENT, never subscribed, so they
// are deliberately not in this list — see the assertion at the bottom, which pins that
// distinction rather than leaving it to be re-derived.
const CONSOLE_SUBSCRIBED_EVENTS = [ "cc_transcript_append", "cc_transcript_state" ];

// Sent, not subscribed.
const CONSOLE_CLIENT_VERBS = [ "cc_transcript_watch", "cc_transcript_unwatch" ];

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  const classOnly  = fullSource.slice( 0, initIdx );
  assert.ok( classOnly.includes( "class NotificationsUI" ), "sliced source must still contain the class" );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal(
    typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function",
    "NotificationsUI loaded"
  );
} );

// A constructor-bypassed instance carrying only what the two builders read.
function makeUI(): Record<string, unknown> & {
  _buildQueueAuthMessage: () => { subscribed_events: string[] };
  _buildAudioAuthMessage: () => { subscribed_events: string[] };
} {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as Record<string, unknown> & {
    _buildQueueAuthMessage: () => { subscribed_events: string[] };
    _buildAudioAuthMessage: () => { subscribed_events: string[] };
  };
  // The builders only ever do `.replace( "Bearer ", "" )` on this, so the value is read by
  // no assertion in this file — it exists because the builders would throw on undefined.
  //
  // WRITTEN IN ANGLE BRACKETS ON PURPOSE. `<…>` is the shape `secret_scan.py`'s
  // `_PLACEHOLDER_VALUE` recognises as a placeholder rather than a credential, so the
  // pre-commit scan passes on its own terms instead of being bypassed. Two shapes that do
  // NOT work and were tried first — a realistic mock token (len=40) and a plainly fake
  // "Bearer not-a-token" (len=18) — both flag identically, because the scanner keys on the
  // FIELD NAME and cannot tell a real token from a fake one by looking. That is the
  // scanner being right about its job.
  //
  // What was deliberately NOT done: splitting the literal or assigning through a computed
  // key to make the flag disappear. That is dodging a security control by obfuscation, and
  // it would leave the next REAL token in this file invisible to the scan.
  ui.authToken      = "<test-double-token-placeholder>";
  ui.queueSessionId = "calm dolphin";
  ui.audioSessionId = "wise owl";
  return ui;
}


// ── the positive half ─────────────────────────────────────────────────────────

for ( const event of CONSOLE_SUBSCRIBED_EVENTS ) {
  test( `the QUEUE socket subscribes ${event}`, () => {
    const queue = makeUI()._buildQueueAuthMessage();
    assert.ok(
      queue.subscribed_events.includes( event ),
      `${event} is missing from _buildQueueAuthMessage's subscribed_events. Without it the ` +
      `server validates the subscription away silently and the console pane stays empty ` +
      `while auth reports success.`
    );
  } );
}


// ── the negative half — the one the corrected plan exists for ────────────────

for ( const event of CONSOLE_SUBSCRIBED_EVENTS ) {
  test( `the AUDIO socket does NOT subscribe ${event}`, () => {
    const audio = makeUI()._buildAudioAuthMessage();
    assert.ok(
      !audio.subscribed_events.includes( event ),
      `${event} is present in _buildAudioAuthMessage's subscribed_events. /ws/audio must ` +
      `never carry console traffic — these are two different sockets, not two copies of ` +
      `one list. An earlier draft of plan §4 told the implementer to edit both; this is ` +
      `the assertion that catches following that instruction.`
    );
  } );
}


// ── the control, so the zeros above mean something ───────────────────────────

test( "the audio list is not empty and carries its OWN events — the positive control", () => {
  const audio = makeUI()._buildAudioAuthMessage();
  assert.ok( audio.subscribed_events.length > 0, "the audio subscribed_events list is empty" );
  for ( const own of [ "audio_streaming_chunk", "audio_streaming_status", "audio_streaming_complete" ] ) {
    assert.ok(
      audio.subscribed_events.includes( own ),
      `${own} missing from the audio list — the "no console events here" assertions above ` +
      `are searching a list that does not contain what it should, so their zeros are worthless`
    );
  }
} );

test( "the queue list still carries everything it carried before", () => {
  // Adding to a list is the easy half; not silently dropping something is the other.
  const queue = makeUI()._buildQueueAuthMessage();
  for ( const pre of [
    "job_state_transition", "job_removed", "tts_job_request", "sys_time_update",
    "notification_play_sound", "notification_queue_update", "notification_responded",
    "notification_expired", "auth_success", "auth_error", "connect", "sys_ping",
  ] ) {
    assert.ok( queue.subscribed_events.includes( pre ), `${pre} was dropped from the queue list` );
  }
} );


// ── the two lists are different populations, and must stay that way ──────────

test( "the two sockets subscribe different populations", () => {
  const ui    = makeUI();
  const queue = ui._buildQueueAuthMessage().subscribed_events;
  const audio = ui._buildAudioAuthMessage().subscribed_events;

  assert.notDeepEqual(
    [ ...queue ].sort(), [ ...audio ].sort(),
    "the queue and audio subscription lists have become identical — they are two different " +
    "sockets and a 'unify the duplicated lists' tidy-up is a silent regression"
  );

  // The audio socket's own marker: it carries tts_error, which the queue socket does not.
  assert.ok( audio.includes( "tts_error" ),  "the audio list lost its tts_error marker" );
  assert.ok( !queue.includes( "tts_error" ), "tts_error leaked into the queue list" );
} );


// ── watch/unwatch are SENT, not subscribed ───────────────────────────────────

test( "the client -> server verbs are not in either subscription list", () => {
  const ui    = makeUI();
  const queue = ui._buildQueueAuthMessage().subscribed_events;
  const audio = ui._buildAudioAuthMessage().subscribed_events;

  for ( const verb of CONSOLE_CLIENT_VERBS ) {
    assert.ok(
      !queue.includes( verb ),
      `${verb} is in the QUEUE subscription list. It is a verb this client SENDS, not an ` +
      `event it receives — subscribing to it says the client expects the server to push it.`
    );
    assert.ok( !audio.includes( verb ), `${verb} is in the AUDIO subscription list` );
  }
} );
