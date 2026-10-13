// The legacy page sends an utterance id and ignores frames naming another.
//
// The server does not cancel a speech stream the page has moved on from, so the old
// stream's `audio_streaming_complete` or `tts_error` can arrive after the next
// request has started. Each request now sends `utterance_id`; the server echoes it
// on the stream's frames (speech.py `stream_frame`); `handleAudioMessage` drops a
// complete or error frame whose id is not the one the newest request sent.
//
// The tests enter at handleAudioMessage, the socket's own door, and at the two functions
// that send the request (playInstantTTS, playReliableTTS). Most tests record the two
// handlers behind the door, because the question is which frames reach them. The
// cut-short tests and one failed-request test run the page's own handleAudioComplete.
//
// Run: npx tsx --test src/tests/unit/notifications_js/a_late_audio_frame_for_another_utterance_is_ignored.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

interface Posted { url: string; body: Record<string, unknown> }

type AudioUI = Record<string, unknown> & {
  expectedUtteranceId : string | null;
  pcmStreamComplete?  : boolean;
  ensureValidToken?   : () => Promise<void>;
  stopTTSPlayingIndicator? : () => void;
  handleAudioMessage  : ( event: { data: string } ) => void;
  playInstantTTS      : ( text: string, voiceId?: string | null ) => Promise<void>;
  playReliableTTS     : ( text: string, voiceId?: string | null ) => Promise<void>;
  nextUtteranceId     : () => string;
};

let reached : string[] = [];
let posted  : Posted[] = [];

/** A bare instance carrying only what the audio door and the two request functions touch. */
function newUI(): AudioUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as AudioUI;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.audioSessionId     = "wise penguin";
  ui.TTS_MODE_INSTANT   = "instant";
  ui.TTS_MODE_RELIABLE  = "reliable";
  ui.currentNotificationId     = null;
  ui.pcmAudioContext           = null;
  ui.startTTSPlayingIndicator  = (): void => {};
  ui.ensureValidToken          = async (): Promise<void> => {};
  ui.getAuthHeader             = (): string => "Bearer t";
  ui.handleAudioComplete = ( envelope: Record<string, unknown> ): void => { reached.push( `complete ${ String( envelope.utterance_id ) }` ); };
  ui.handleTTSError      = ( envelope: Record<string, unknown> ): void => { reached.push( `error ${ String( envelope.utterance_id ) }` ); };
  return ui;
}

function frame( ui: AudioUI, type: string, utteranceId?: unknown ): void {
  const envelope: Record<string, unknown> = { type, text: "t", status: "s" };
  if ( utteranceId !== undefined ) envelope.utterance_id = utteranceId;
  ui.handleAudioMessage( { data: JSON.stringify( envelope ) } );
}

/** Put back the fetch every test starts with: it records the request and answers success. */
function plainFetch(): void {
  ( globalThis as Record<string, unknown> ).fetch = async ( url: string, init: { body: string } ): Promise<unknown> => {
    posted.push( { url, body: JSON.parse( init.body ) as Record<string, unknown> } );
    return { ok: true, status: 200, statusText: "OK", json: async () => ( { status: "success" } ) };
  };
}

beforeEach( () => {
  reached = [];
  posted  = [];
  plainFetch();
} );

// ---------------------------------------------------------------------------
// The two request functions send an id, new each time
// ---------------------------------------------------------------------------

test("the instant request sends an utterance_id and remembers it as the one expected", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "hello" );
  assert.equal( posted.length, 1 );
  assert.equal( posted[ 0 ]!.url, "/api/get-speech-elevenlabs" );
  assert.equal( typeof posted[ 0 ]!.body.utterance_id, "string" );
  assert.equal( posted[ 0 ]!.body.utterance_id, ui.expectedUtteranceId );
  assert.deepEqual( Object.keys( posted[ 0 ]!.body ).sort(), [ "session_id", "text", "utterance_id" ] );
});

test("the reliable request sends an utterance_id and remembers it as the one expected", async () => {
  const ui = newUI();
  await ui.playReliableTTS( "hello", "vox" );
  assert.equal( posted[ 0 ]!.url, "/api/get-speech" );
  assert.equal( posted[ 0 ]!.body.utterance_id, ui.expectedUtteranceId );
  assert.deepEqual( Object.keys( posted[ 0 ]!.body ).sort(), [ "session_id", "text", "utterance_id", "voice_id" ] );
});

test("every request gets a different id, across both doors", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "one" );
  await ui.playReliableTTS( "two" );
  await ui.playInstantTTS( "three" );
  const ids = posted.map( ( p ) => p.body.utterance_id );
  assert.equal( new Set( ids ).size, 3, JSON.stringify( ids ) );
  assert.equal( ui.expectedUtteranceId, ids[ 2 ] );
  for ( const id of ids ) assert.ok( typeof id === "string" && id.length >= 1 && id.length <= 255 );
});

test("the id is set before the request leaves, so a frame that beats the reply is judged against it", async () => {
  const ui = newUI();
  let expectedAtFetch: string | null = null;
  ( globalThis as Record<string, unknown> ).fetch = async ( _url: string, init: { body: string } ): Promise<unknown> => {
    expectedAtFetch = ui.expectedUtteranceId;
    assert.equal( ( JSON.parse( init.body ) as Record<string, unknown> ).utterance_id, expectedAtFetch );
    return { ok: true, status: 200, statusText: "OK", json: async () => ( { status: "success" } ) };
  };
  await ui.playInstantTTS( "hello" );
  assert.notEqual( expectedAtFetch, null );
});

// ---------------------------------------------------------------------------
// The socket's door drops a frame that names another utterance
// ---------------------------------------------------------------------------

test("a complete frame for an abandoned utterance does not reach the handler; the current one's does", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "A" );
  const idA = ui.expectedUtteranceId;
  await ui.playInstantTTS( "B" );
  const idB = ui.expectedUtteranceId;
  assert.notEqual( idA, idB );
  frame( ui, "audio_streaming_complete", idA );
  assert.deepEqual( reached, [], "A's late frame reached the handler while B was current" );
  frame( ui, "audio_streaming_complete", idB );
  assert.deepEqual( reached, [ `complete ${ idB }` ] );
});

test("a tts_error for an abandoned utterance does not reach the handler; the current one's does", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "A" );
  const idA = ui.expectedUtteranceId;
  await ui.playReliableTTS( "B" );
  const idB = ui.expectedUtteranceId;
  frame( ui, "tts_error", idA );
  assert.deepEqual( reached, [] );
  frame( ui, "tts_error", idB );
  assert.deepEqual( reached, [ `error ${ idB }` ] );
});

test("a frame with no id is handled as before, while an id is expected", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "A" );
  frame( ui, "audio_streaming_complete" );
  frame( ui, "tts_error" );
  assert.deepEqual( reached, [ "complete undefined", "error undefined" ] );
});

test("a frame whose utterance_id is not a string is handled as before", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "A" );
  frame( ui, "audio_streaming_complete", 7 );
  frame( ui, "tts_error", null );
  assert.deepEqual( reached, [ "complete 7", "error null" ] );
});

test("before any request, a frame with an id is handled as before", () => {
  const ui = newUI();
  frame( ui, "audio_streaming_complete", "legacy:1" );
  frame( ui, "tts_error", "legacy:1" );
  assert.deepEqual( reached, [ "complete legacy:1", "error legacy:1" ] );
});

// ---------------------------------------------------------------------------
// The real handler behind the door: a cut-short, and its control
// ---------------------------------------------------------------------------

/** An instance whose handleAudioComplete is the page's own, with only its leaves recorded. */
function newRealUI(): AudioUI {
  const ui = newUI();
  delete ( ui as Record<string, unknown> ).handleAudioComplete;
  ui.pcmStreamComplete        = false;
  ui.stopTTSPlayingIndicator  = (): void => { reached.push( "indicator stopped" ); };
  return ui;
}

test("B is not cut short: A's late complete frame leaves B's stream open in the real handler", async () => {
  const ui = newRealUI();
  await ui.playInstantTTS( "A" );
  const idA = ui.expectedUtteranceId;
  await ui.playInstantTTS( "B" );
  frame( ui, "audio_streaming_complete", idA );
  assert.equal( ui.pcmStreamComplete, false, "A's late frame marked B's stream complete" );
  frame( ui, "audio_streaming_complete", ui.expectedUtteranceId );
  assert.equal( ui.pcmStreamComplete, true, "B's own frame did not end B's stream" );
});

test("control: the same late frame without an id does cut B short in the real handler", async () => {
  const ui = newRealUI();
  await ui.playInstantTTS( "A" );
  await ui.playInstantTTS( "B" );
  frame( ui, "audio_streaming_complete" );
  assert.equal( ui.pcmStreamComplete, true );
});

// ---------------------------------------------------------------------------
// A request that fails gives its id back
// ---------------------------------------------------------------------------

type Reply = { ok: boolean; status: number; statusText: string; json: () => Promise<unknown> };

function replyOnce( reply: Reply ): void {
  const inner = ( globalThis as Record<string, unknown> ).fetch as ( url: string, init: { body: string } ) => Promise<unknown>;
  let used = false;
  ( globalThis as Record<string, unknown> ).fetch = async ( url: string, init: { body: string } ): Promise<unknown> => {
    await inner( url, init );
    if ( used ) return { ok: true, status: 200, statusText: "OK", json: async () => ( { status: "success" } ) };
    used = true;
    return reply;
  };
}

const HTTP_500: Reply = { ok: false, status: 500, statusText: "Server Error", json: async () => ( {} ) };

test("a failed instant request while A plays: A's complete frame still ends A in the real handler", async () => {
  const ui = newRealUI();
  await ui.playInstantTTS( "A" );
  const idA = ui.expectedUtteranceId;
  replyOnce( HTTP_500 );
  await assert.rejects( ui.playInstantTTS( "B" ), /HTTP 500/ );
  assert.equal( posted.length, 2, "the failed request did leave, with an id of its own" );
  assert.notEqual( posted[ 1 ]!.body.utterance_id, idA );
  assert.equal( ui.expectedUtteranceId, idA, "the failed request's id stayed the expected one" );
  frame( ui, "audio_streaming_complete", idA );
  assert.equal( ui.pcmStreamComplete, true, "A's own complete frame was dropped: the card would pulse forever" );
});

test("a failed reliable request gives its id back, for an HTTP error and for a not-success reply", async () => {
  for ( const reply of [ HTTP_500, { ok: true, status: 200, statusText: "OK", json: async () => ( { status: "error", message: "no" } ) } ] ) {
    const ui = newUI();
    await ui.playInstantTTS( "A" );
    const idA = ui.expectedUtteranceId;
    replyOnce( reply );
    await assert.rejects( ui.playReliableTTS( "B" ) );
    assert.equal( ui.expectedUtteranceId, idA );
    reached = [];
    frame( ui, "audio_streaming_complete", idA );
    assert.deepEqual( reached, [ `complete ${ idA }` ] );
  }
});

test("the first request of a page fails: no id is expected, a frame naming a stream is dropped, a bare one passes", async () => {
  const ui = newUI();
  replyOnce( HTTP_500 );
  await assert.rejects( ui.playInstantTTS( "A" ) );
  const idA = posted[ 0 ]!.body.utterance_id;
  assert.equal( ui.expectedUtteranceId, null );
  frame( ui, "audio_streaming_complete", idA );
  frame( ui, "tts_error", "some other stream" );
  assert.deepEqual( reached, [] );
  frame( ui, "audio_streaming_complete" );
  assert.deepEqual( reached, [ "complete undefined" ] );
});

test("a network failure, not only an HTTP error, gives the id back", async () => {
  for ( const door of [ "playInstantTTS", "playReliableTTS" ] as const ) {
    plainFetch();
    const ui = newUI();
    await ui.playInstantTTS( "A" );
    const idA = ui.expectedUtteranceId;
    ( globalThis as Record<string, unknown> ).fetch = async (): Promise<unknown> => { throw new Error( "network down" ); };
    await assert.rejects( ui[ door ]( "B" ), /network down/ );
    assert.equal( ui.expectedUtteranceId, idA, door );
    assert.equal( ( ui.pendingUtteranceIds as Set<string> ).size, 0, `${ door }: a failed request is still counted as waiting` );
  }
});

/** A fetch whose replies the test settles by hand, in any order. */
function heldFetch(): Array<{ ok: () => void; fail: ( reason: Error ) => void }> {
  const held: Array<{ ok: () => void; fail: ( reason: Error ) => void }> = [];
  ( globalThis as Record<string, unknown> ).fetch = ( _url: string, init: { body: string } ): Promise<unknown> => {
    posted.push( { url: _url, body: JSON.parse( init.body ) as Record<string, unknown> } );
    return new Promise( ( resolve, reject ) => {
      held.push( {
        ok   : (): void => resolve( { ok: true, status: 200, statusText: "OK", json: async () => ( { status: "success" } ) } ),
        fail : reject,
      } );
    } );
  };
  return held;
}

const tick = (): Promise<void> => new Promise( ( r ) => setImmediate( r ) );

test("two requests fail while A plays, in either order: A's complete frame still ends A", async () => {
  for ( const order of [ [ 0, 1 ], [ 1, 0 ] ] ) {
    plainFetch();
    const ui = newRealUI();
    await ui.playInstantTTS( "A" );
    const idA  = ui.expectedUtteranceId;
    const held = heldFetch();
    const b = assert.rejects( ui.playInstantTTS( "B" ), /down/ ); await tick();
    const c = assert.rejects( ui.playInstantTTS( "C" ), /down/ ); await tick();
    assert.equal( held.length, 2 );
    for ( const which of order ) { held[ which ]!.fail( new Error( "down" ) ); await tick(); }
    await b; await c;
    assert.equal( ui.expectedUtteranceId, idA, `order ${ JSON.stringify( order ) }: a dead id stayed expected` );
    frame( ui, "audio_streaming_complete", idA );
    assert.equal( ui.pcmStreamComplete, true, `order ${ JSON.stringify( order ) }` );
  }
});

test("A is stopped, then B fails: A's late frames do not play A's leftovers or raise its error", async () => {
  for ( const door of [ "playInstantTTS", "playReliableTTS" ] as const ) {
    const ui = newUI();
    ui.stopTTSPlayingIndicator = (): void => {};
    await ui.playInstantTTS( "A" );
    const idA = ui.expectedUtteranceId;
    ( ui as unknown as { stopAudio: () => void } ).stopAudio();
    assert.equal( ui.expectedUtteranceId, null, "a stopped stream stayed expected" );
    replyOnce( HTTP_500 );
    await assert.rejects( ui[ door ]( "B" ) );
    assert.equal( ui.expectedUtteranceId, null, door );
    frame( ui, "audio_streaming_complete", idA );
    frame( ui, "tts_error", idA );
    assert.deepEqual( reached, [], door );
  }
});

test("a stop while a request waits for its reply keeps that request's id expected", async () => {
  const ui = newUI();
  ui.stopTTSPlayingIndicator = (): void => {};
  await ui.playInstantTTS( "A" );
  const held = heldFetch();
  const b = ui.playInstantTTS( "B" ); await tick();
  const idB = ui.expectedUtteranceId;
  ( ui as unknown as { stopAudio: () => void } ).stopAudio();
  assert.equal( ui.expectedUtteranceId, idB );
  held[ 0 ]!.ok(); await b;
  frame( ui, "audio_streaming_complete", idB );
  assert.deepEqual( reached, [ `complete ${ idB }` ] );
  ( ui as unknown as { stopAudio: () => void } ).stopAudio();
  assert.equal( ui.expectedUtteranceId, null, "an answered request survived a later stop" );
});

test("a stream's second ending frame is dropped, and the utterances before it are forgotten", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "A" );
  const idA = ui.expectedUtteranceId;
  await ui.playInstantTTS( "B" );
  const idB = ui.expectedUtteranceId;
  frame( ui, "audio_streaming_complete", idB );
  frame( ui, "tts_error", idB );
  frame( ui, "audio_streaming_complete", idA );
  assert.deepEqual( reached, [ `complete ${ idB }` ] );
  assert.equal( ui.expectedUtteranceId, null );
  await ui.playInstantTTS( "C" );
  replyOnce( HTTP_500 );
  await assert.rejects( ui.playInstantTTS( "D" ) );
  assert.equal( ui.expectedUtteranceId, posted[ 2 ]!.body.utterance_id, "a failure after C restored something other than C" );
});

test("a request that fails before an id is minted leaves the expected id alone", async () => {
  for ( const door of [ "playInstantTTS", "playReliableTTS" ] as const ) {
    const ui = newUI();
    posted = [];
    await ui.playInstantTTS( "A" );
    const idA = ui.expectedUtteranceId;
    ui.ensureValidToken = async (): Promise<void> => { throw new Error( "no token" ); };
    await assert.rejects( ui[ door ]( "B" ), /no token/ );
    assert.equal( ui.expectedUtteranceId, idA );
    assert.equal( posted.length, 1, "no request left" );
  }
});

test("a request that fails after a later one started does not take the later one's id away", async () => {
  const ui = newUI();
  await ui.playInstantTTS( "A" );
  let failB: ( reason: Error ) => void = (): void => {};
  const plain = ( globalThis as Record<string, unknown> ).fetch as ( url: string, init: { body: string } ) => Promise<unknown>;
  let calls = 0;
  ( globalThis as Record<string, unknown> ).fetch = async ( url: string, init: { body: string } ): Promise<unknown> => {
    calls += 1;
    if ( calls > 1 ) return plain( url, init );
    await plain( url, init );
    return new Promise( ( _resolve, reject ) => { failB = reject; } );
  };
  const pendingB = ui.playInstantTTS( "B" );
  await new Promise( ( r ) => setImmediate( r ) );
  await ui.playInstantTTS( "C" );
  const idC = ui.expectedUtteranceId;
  failB( new Error( "network down" ) );
  await assert.rejects( pendingB, /network down/ );
  assert.equal( ui.expectedUtteranceId, idC );
});

// ---------------------------------------------------------------------------
// The id carries a prefix drawn once per page load
// ---------------------------------------------------------------------------

test("two page loads mint different ids for the same count; one page keeps one prefix", () => {
  const realRandom = Math.random;
  try {
    Math.random = (): number => 0.123456789;
    const first = newUI();
    const a1 = first.nextUtteranceId();
    Math.random = (): number => 0.987654321;
    const a2 = first.nextUtteranceId();
    const second = newUI();
    const b1 = second.nextUtteranceId();
    const prefix = ( id: string ): string => id.split( ":" )[ 1 ]!;
    assert.match( a1, /^legacy:[a-z0-9]{1,8}:1$/ );
    assert.match( b1, /^legacy:[a-z0-9]{1,8}:1$/ );
    assert.equal( prefix( a1 ), prefix( a2 ), "one page changed its prefix between requests" );
    assert.notEqual( a1, b1, "a reloaded page repeated the id of the page before it" );
    Math.random = (): number => 0;
    assert.equal( newUI().nextUtteranceId(), "legacy:0:1", "a draw with no digits left an empty prefix" );
  } finally {
    Math.random = realRandom;
  }
});

test("an answered request, from either door, is forgotten by the next stop", async () => {
  for ( const door of [ "playInstantTTS", "playReliableTTS" ] as const ) {
    const ui = newUI();
    ui.stopTTSPlayingIndicator = (): void => {};
    await ui[ door ]( "A" );
    const idA = ui.expectedUtteranceId;
    assert.notEqual( idA, null );
    ( ui as unknown as { stopAudio: () => void } ).stopAudio();
    assert.equal( ui.expectedUtteranceId, null, door );
    frame( ui, "audio_streaming_complete", idA );
    assert.deepEqual( reached, [], door );
  }
});
