// Parity B-7 — the cached-blob playback path.
//
// LEGACY BEING MIRRORED, cited by symbol:
//   - `playAudioBlob`  notifications.js:5000   THE LIVE ONE — see the warning below
//   - `stopAudio`      notifications.js:5067   the `currentAudio` leg this file owns
//
// 🔴 THE LEGACY SYMBOL IS DEFINED TWICE AND THE FIRST IS DEAD. `playAudioBlob`
// appears at :4321 AND :5000 in one class body, so the later definition wins and
// :4321 never runs. They differ on the one line that decides whether anything is
// audible — :4321 assigns the Blob straight to `audio.src`, :5000 wraps it in an
// object URL. `HTMLMediaElement.src` is a DOMString, so the dead version
// stringifies a Blob to "[object Blob]", resolves it as a relative URL and fires
// `onerror`. A port taken from it would be SILENT on every cache hit, and silent
// in the worst way: legacy's hit arm `return`s, so it never falls back to the
// server, and the reject is swallowed by `playTTS`'s catch.
//
// ⚠️ LEGACY IS NOT BROKEN — it runs :5000. This is a trap for the porter, and it
// is written here rather than in a commit message because the next person to
// touch this file will grep the same name and be handed :4321 first.
//
// The object-URL round trip is therefore asserted directly, not implied.
//
// Run: npx tsx --test src/tests/unit/multiplexer/audio/direct_tts_playback_port.test.ts

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import {
  createDirectTtsPlayer,
  type DirectAudioElement,
  type DirectTtsPlayer,
} from "../../../../lupin_app/static/js/multiplexer/audio/directTtsPlayback";

// --------------------------------------------------------------------------
// A fake element that RECORDS what was asked of it, and a URL pair that records
// every mint and every revoke. Both are needed: the leak assertions below are
// about the difference between the two lists, and a recorder for only one of
// them cannot see an imbalance.
// --------------------------------------------------------------------------

interface FakeAudio extends DirectAudioElement {
  playCalls  : number;
  pauseCalls : number;
  playResult : Promise<void>;
}

let minted  : string[];
let revoked : string[];
let made    : FakeAudio[];
let seq     : number;
/**
 * What the NEXT element's `play()` returns.
 *
 * 🔴 SET BEFORE `play()` IS CALLED, NEVER AFTER. The first cut of the refused-
 * autoplay test below assigned `playResult` on the element once it existed — by
 * which time the player had already taken the resolved promise and attached its
 * `.catch()` to that one. The rejection was therefore orphaned: it surfaced as
 * an unhandledRejection and failed the FILE while the test itself printed `ok`.
 * A fake whose behaviour is configured after the code under test has read it is
 * not configuring anything.
 */
let nextPlayResult : Promise<void>;

const makeFake = ( url: string ): FakeAudio => {
  const el: FakeAudio = {
    src         : url,
    currentTime : 0,
    onended     : null,
    onerror     : null,
    playCalls   : 0,
    pauseCalls  : 0,
    playResult  : nextPlayResult,
    play() { this.playCalls += 1; return this.playResult; },
    pause() { this.pauseCalls += 1; },
  };
  made.push( el );
  return el;
};

function player( over: Partial<Parameters<typeof createDirectTtsPlayer>[0]> = {} ): DirectTtsPlayer {
  return createDirectTtsPlayer( {
    audioFactory    : makeFake,
    createObjectURL : () => { const u = `blob:mux/${ seq++ }`; minted.push( u ); return u; },
    revokeObjectURL : ( u ) => { revoked.push( u ); },
    ...over,
  } );
}

const BLOB = new Blob( [ "audio" ] );

beforeEach( () => {
  minted = []; revoked = []; made = []; seq = 0;
  nextPlayResult = Promise.resolve();
} );

// --------------------------------------------------------------------------

test( "the fakes are reached at all — positive control before any absence is read", async () => {
  // 🔴 EVERY LEAK ASSERTION BELOW READS AN EMPTY `revoked`, AND AN UNREACHED
  // RECORDER PRINTS THE SAME EMPTY ARRAY AS A CORRECT ONE.
  const p = player();
  void p.play( BLOB );
  assert.equal( minted.length, 1, "no object URL was minted — the factory is not wired" );
  assert.equal( made.length,   1, "no element was built — the audio factory is not wired" );
  assert.equal( made[ 0 ]!.playCalls, 1, "the element was never asked to play" );
} );

test( "🔴 THE BLOB GOES THROUGH createObjectURL — never assigned raw (the dead-twin defect)", () => {
  const p = player();
  void p.play( BLOB );

  assert.equal( made[ 0 ]!.src, minted[ 0 ],
    "the element's src is not the minted object URL. If a Blob is being assigned directly, this " +
    "is the notifications.js:4321 defect ported in: src is a DOMString, the Blob stringifies to " +
    `"[object Blob]", and every cache hit is silent.` );
  assert.equal( made[ 0 ]!.src.startsWith( "blob:" ), true );
} );

test( "the promise resolves when playback ENDS, not when play() is called", async () => {
  const p = player();
  let settled = false;
  const done = p.play( BLOB ).then( () => { settled = true; } );

  await Promise.resolve();
  assert.equal( settled, false, "the play resolved before the audio ended — a caller that " +
    "clears its input on resolve would clear it the instant the button was pressed" );

  made[ 0 ]!.onended!();
  await done;
  assert.equal( settled, true );
} );

test( "🔴 the object URL is revoked on END — a leak pins the blob for the page's lifetime", async () => {
  const p = player();
  const done = p.play( BLOB );
  made[ 0 ]!.onended!();
  await done;

  assert.deepEqual( revoked, minted, "the minted URL was not revoked when playback ended" );
  assert.equal( p.isPlaying(), false, "the slot still holds an element that has finished" );
} );

test( "the object URL is revoked on ERROR too, and the caller still resolves", async () => {
  // An error that rejected would surface as an unhandled rejection in the pane,
  // which has no status element to report it in. Legacy resolves here as well.
  const p = player();
  const done = p.play( BLOB );
  made[ 0 ]!.onerror!();
  await done;

  assert.deepEqual( revoked, minted );
  assert.equal( p.isPlaying(), false );
} );

test( "🔴 END AND ERROR TOGETHER RELEASE ONCE — not twice, and the caller resolves once", async () => {
  // They are mutually exclusive in practice and not by contract. Revoking twice
  // is harmless; resolving twice is not, and a double release would clear the
  // slot out from under a NEW element.
  //
  // 🔴 THE HANDLER IS CAPTURED BEFORE IT FIRES, AND THAT IS THE REAL SHAPE, NOT
  // A TRICK TO REACH A LINE. Releasing nulls `onended`/`onerror`, so a second
  // call cannot arrive through the element's own properties — but an event
  // already dispatched carries its listener with it, and `ended` and `error` in
  // one task is exactly how that arrives. Reading the property afterwards finds
  // `null` and would quietly test nothing.
  const p = player();
  let resolutions = 0;
  const done = p.play( BLOB ).then( () => { resolutions += 1; } );
  const captured = made[ 0 ]!.onended!;
  assert.notEqual( captured, null, "positive control: no handler was attached to capture" );

  captured();
  await done;
  captured();                         // the same listener, dispatched twice
  await Promise.resolve();

  assert.equal( resolutions, 1, "the caller resolved twice" );
  assert.equal( revoked.length, 1, `the URL was revoked ${ revoked.length } times` );
} );

test( "🔴 A REFUSED AUTOPLAY RESOLVES, and does NOT release — legacy's own choice", async () => {
  // Legacy: "Auto-play prevented for cached audio, but audio is ready" → resolve.
  // Reporting it as a failure would blame the TTS path for a browser policy, and
  // releasing the URL would make the audio unplayable if the user then allows it.
  const p = player();
  nextPlayResult = Promise.reject( new Error( "NotAllowedError" ) );
  const done = p.play( BLOB );
  // The player attaches its own `.catch()` inside play(); drive the microtasks.
  for ( let i = 0; i < 4; i++ ) await Promise.resolve();

  assert.equal( made[ 0 ]!.playCalls, 1,
    "positive control: the refused promise was never taken, so nothing was refused" );

  assert.deepEqual( revoked, [], "a refused autoplay released the URL — the audio is now dead " +
    "even if the operator allows playback" );
  assert.equal( p.isPlaying(), true, "the element was dropped, so stop() can no longer reach it" );

  made[ 0 ]!.onended!();
  await done;
  assert.deepEqual( revoked, minted );
} );

// --- stop -----------------------------------------------------------------

test( "🔴 stop() pauses, rewinds and releases — legacy's `currentAudio` leg of D8", () => {
  const p = player();
  void p.play( BLOB );
  made[ 0 ]!.currentTime = 12;

  p.stop();

  assert.equal( made[ 0 ]!.pauseCalls, 1, "stop() did not pause — the audio keeps playing" );
  assert.equal( made[ 0 ]!.currentTime, 0, "stop() did not rewind, so a re-play resumes mid-word" );
  assert.deepEqual( revoked, minted );
  assert.equal( p.isPlaying(), false );
} );

test( "stop() on an idle player is a no-op, not a throw", () => {
  const p = player();
  p.stop();
  p.stop();
  assert.equal( p.isPlaying(), false );
  assert.deepEqual( revoked, [] );
} );

test( "🔴 A SECOND PLAY STOPS THE FIRST — two blobs never overlap", async () => {
  // There is ONE slot. Without this, the first element stays audible AND
  // unreachable: stop() would only ever find the second.
  const p = player();
  void p.play( BLOB );
  void p.play( new Blob( [ "second" ] ) );

  assert.equal( made.length, 2 );
  assert.equal( made[ 0 ]!.pauseCalls, 1, "the first element was left playing" );
  assert.deepEqual( revoked, [ minted[ 0 ] ], "the first URL leaked" );
  assert.equal( p.isPlaying(), true );
} );

test( "🔴 A STOPPED ELEMENT'S LATE onended DOES NOT WIPE THE NEW ONE'S HANDLE", async () => {
  // The ordering that makes this reachable is ordinary: stop() detaches the
  // handlers, but a listener already queued can still run. If it cleared the
  // slot unconditionally, the NEW element would be unreachable by stop() — it
  // would play to the end with the Stop button doing nothing.
  const p = player();
  void p.play( BLOB );
  const first = made[ 0 ]!;
  void p.play( new Blob( [ "second" ] ) );

  assert.equal( first.onended, null, "stop() left the old element's handler attached" );
  assert.equal( p.isPlaying(), true, "the new element's handle was cleared by the old one" );

  p.stop();
  assert.equal( made[ 1 ]!.pauseCalls, 1, "stop() could not reach the second element" );
} );
