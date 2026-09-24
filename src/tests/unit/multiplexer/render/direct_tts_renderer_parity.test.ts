// PARITY-CLAIM: B-7
// Parity B-7 — the Direct TTS Test pane.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1):
//   - `#section-direct-tts`  notifications.html:1377-1391  input + four buttons, no display:none
//   - `setupEventListeners`  notifications.js:1775-1804 (the four buttons' wiring)
//   - `directTTSTest`     notifications.js:4240-4263
//   - `testTTS( mode )`   notifications.js:4284-4289
//   - `playTTS`'s cache arm  notifications.js:4295-4314
//   - `stopAudio`         notifications.js:5071-5136
//
// 🔴 THE ONE BEHAVIOUR THAT MUST BE CHECKED FIRST IS THE BYPASS (D4), AND IT IS
// THE ONE A WORKING-LOOKING PANE HIDES. A cache hit must play here and now, with
// no POST and no socket. A pane that quietly went through the server on every
// press would look identical, sound identical, and be measuring the server
// rather than the cache — so the miss path is given a recorder and the hit tests
// assert it stayed EMPTY. Mr. Radio 🦉's explicit ask, 2026-09-23.
//
// ⚠️ AND THE SPEC SENTENCE IS MORE ABSOLUTE THAN EITHER CLIENT IS. D4 says
// "bypassing Q&A, job completion and every WebSocket event", but both TTS doors
// stream PCM back over /ws/audio, so a cache MISS cannot avoid the socket in
// legacy either. Legacy settles it: the hit bypasses everything, the miss is an
// ordinary request. Ruled follow-legacy by Mr. Radio, 2026-09-23. Named here
// because a reviewer reading D4 alone will expect something no client does.
//
// ⚠️ D2's REFUSAL CHANNEL IS INJECTED, AND THE REASON IS A DEPENDENCY, NOT A
// PREFERENCE. Legacy refuses an empty input into `this.error`, which writes the
// debug panel AND the console — and there is no inline status element in either
// client. That panel is B-6, which is not in this branch's base, so the writers
// arrive as `logFn`/`errorFn`. Boot passes `console` today and debugSink's pair
// once B-6 merges.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/direct_tts_renderer_parity.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  createDirectTtsRenderer,
  directTtsTestText,
  DIRECT_TTS_PLACEHOLDER,
  DIRECT_TTS_EMPTY_REFUSAL,
  type DirectTtsRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render/DirectTtsRenderer";
import type { TtsMode } from "../../../../lupin_app/static/js/multiplexer/stores/AudioStore";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

// --------------------------------------------------------------------------
// Recorders. THE MISS RECORDER IS THE POINT — see the header.
// --------------------------------------------------------------------------

interface Rig {
  root      : HTMLElement;
  renderer  : DirectTtsRenderer;
  spoken    : Array<{ text: string; mode: TtsMode }>;   // the MISS path — the socket
  played    : Blob[];                                    // the HIT path — no server
  looked    : string[];                                  // what the cache was asked for
  logs      : string[];
  errors    : string[];
  halts     : number;
  stops     : number;
  input     : HTMLInputElement;
  click     : ( testid: string ) => void;
}

let mode      : TtsMode;
let cacheHit  : Blob | null;
let speakFail : boolean;
let playFail  : boolean;

function rig(): Rig {
  const spoken : Array<{ text: string; mode: TtsMode }> = [];
  const played : Blob[] = [];
  const looked : string[] = [];
  const logs   : string[] = [];
  const errors : string[] = [];
  let halts = 0;
  let stops = 0;

  const root     = document.createElement( "div" );
  const renderer = createDirectTtsRenderer( {
    audio : {
      ttsMode : () => mode,
      stop    : () => { stops += 1; },
    },
    cache : {
      checkCache : async ( text ) => { looked.push( text ); return cacheHit; },
    },
    playBlob : async ( blob ) => {
      if ( playFail ) throw new Error( "playback died" );
      played.push( blob );
    },
    speak : async ( text, m ) => {
      if ( speakFail ) throw new Error( "request died" );
      spoken.push( { text, mode: m } );
    },
    haltAll : () => { halts += 1; },
    logFn   : ( m ) => { logs.push( m ); },
    errorFn : ( m ) => { errors.push( m ); },
  } );
  renderer.mount( root );

  const input = root.querySelector<HTMLInputElement>( '[data-testid="multiplexer-direct-tts-input"]' )!;
  const click = ( testid: string ): void => {
    root.querySelector<HTMLElement>( `[data-testid="${ testid }"]` )!.click();
  };
  return { root, renderer, spoken, played, looked, logs, errors,
           get halts() { return halts; }, get stops() { return stops; }, input, click } as Rig;
}

/** Let the handler's async chain settle — the click itself is synchronous. */
const settle = async (): Promise<void> => { for ( let i = 0; i < 8; i++ ) await Promise.resolve(); };

beforeEach( () => {
  mode = "instant"; cacheHit = null; speakFail = false; playFail = false;
} );

// --- the mounted shape ----------------------------------------------------

test( "the pane mounts a header, the input and all four buttons — the control the rest depends on", () => {
  // 🔴 EVERY TEST BELOW REACHES A CONTROL BY TESTID. If one moved, those tests
  // would throw on a null rather than assert anything — the kind of failure that
  // gets "fixed" by loosening a selector.
  const r = rig();
  assert.ok( r.root.querySelector( '[data-testid="multiplexer-direct-tts-header"]' ) );
  for ( const testid of [
    "multiplexer-direct-tts-input", "multiplexer-direct-tts-btn",
    "multiplexer-test-instant-tts-btn", "multiplexer-test-reliable-tts-btn",
    "multiplexer-stop-audio-btn",
  ] ) {
    assert.ok( r.root.querySelector( `[data-testid="${ testid }"]` ), `${ testid } did not render` );
  }
} );

test( "B7 — the header is static, carries legacy's glyph and title, and no actions", () => {
  const r = rig();
  const header = r.root.querySelector( '[data-testid="multiplexer-direct-tts-header"]' )!;
  assert.ok( ( header.textContent ?? "" ).includes( "🔧" ) );
  assert.ok( ( header.textContent ?? "" ).includes( "Direct TTS Test (Bypass Q&A)" ) );
  assert.deepEqual( Array.from( header.querySelectorAll( "button" ) ).map( ( b ) => b.className ),
    [ "toggle-button" ], "the header gained a control legacy's Direct TTS section does not have" );
} );

test( "B10 — the input placeholder is legacy's, and the five controls ship visible from the first paint", () => {
  const r = rig();
  assert.equal( r.input.placeholder, DIRECT_TTS_PLACEHOLDER );
  assert.equal( r.input.value, "" );
  // Legacy's markup has NO inline display:none here, unlike Filter Settings.
  for ( const el of Array.from( r.root.querySelectorAll( "input, button" ) ) ) {
    assert.equal( ( el as HTMLElement ).style.display, "",
      "a control ships hidden — legacy's Direct TTS markup hides nothing" );
  }
} );

test( "🔴 D1 — THERE IS NO ENTER HANDLER, and its absence is the behaviour", () => {
  // Legacy wires keydown on #qa-input and NOT on this one. An absence is what a
  // later "improvement" adds without noticing it is a divergence, so it is
  // asserted rather than left to be noticed.
  const r = rig();
  r.input.value = "speak this";
  r.input.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );

  assert.deepEqual( r.looked, [], "Enter reached the speak path — legacy's Enter does nothing here" );
  assert.deepEqual( r.spoken, [] );
} );

// --- D2, the refusal ------------------------------------------------------

test( "🔴 D2 — AN EMPTY INPUT IS REFUSED INTO THE ERROR CHANNEL, and nothing is spoken", async () => {
  const r = rig();
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.deepEqual( r.errors, [ DIRECT_TTS_EMPTY_REFUSAL ] );
  assert.deepEqual( r.looked, [], "the cache was consulted for an empty string" );
  assert.deepEqual( r.spoken, [], "an empty string was sent to the server" );
} );

test( "🔴 D2 — WHITESPACE IS EMPTY. `.trim()` is the check legacy makes", async () => {
  const r = rig();
  r.input.value = "   \t  ";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.deepEqual( r.errors, [ DIRECT_TTS_EMPTY_REFUSAL ] );
  assert.deepEqual( r.spoken, [] );
  assert.equal( r.input.value, "   \t  ",
    "a refused input was cleared — the operator's text is gone and nothing was spoken" );
} );

test( "the spoken text is TRIMMED, not sent with its padding", async () => {
  const r = rig();
  r.input.value = "  hello  ";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.deepEqual( r.looked, [ "hello" ] );
  assert.deepEqual( r.spoken, [ { text: "hello", mode: "instant" } ] );
} );

// --- D4, THE BYPASS -------------------------------------------------------

test( "🔴 D4 — A CACHE HIT PLAYS THE BLOB AND NEVER REACHES THE SERVER", async () => {
  // Mr. Radio 🦉's explicit ask. `spoken` is the miss path — the POST that
  // streams PCM back over /ws/audio. It must stay EMPTY on a hit, or the pane is
  // measuring the server while looking like it is measuring the cache.
  const blob = new Blob( [ "cached" ] );
  cacheHit = blob;
  const r = rig();
  r.input.value = "already spoken";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.deepEqual( r.played, [ blob ], "the cached blob was not played" );
  assert.deepEqual( r.spoken, [],
    "🔴 A CACHE HIT WENT BACK THROUGH THE SERVER. D4's whole point is the bypass: the hit must " +
    "play here and now, with no POST and no /ws/audio round trip." );
} );

test( "🔴 D4 — A CACHE MISS FALLS THROUGH TO THE SERVER, in the mode the store reports", async () => {
  // The other half. A pane that never reached the server would pass the test
  // above forever while being able to speak only what it had already spoken.
  cacheHit = null;
  mode = "reliable";
  const r = rig();
  r.input.value = "never spoken";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.deepEqual( r.played, [], "a miss played a blob it does not have" );
  assert.deepEqual( r.spoken, [ { text: "never spoken", mode: "reliable" } ] );
} );

test( "🔴 D3 — THE MODE COMES FROM THE STORE AND IS READ AT PRESS TIME", async () => {
  // Read at wire time would pin the first value forever, and reading `#tts-mode`
  // from the DOM would make this pane depend on whether the Q&A pane is mounted.
  const r = rig();
  r.input.value = "one";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();
  mode = "reliable";
  r.input.value = "two";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.deepEqual( r.spoken.map( ( s ) => s.mode ), [ "instant", "reliable" ] );
} );

// --- D5, the ordering -----------------------------------------------------

test( "🔴 D5 — THE INPUT IS CLEARED ONLY AFTER THE PLAY RESOLVES", async () => {
  // The ordering is driven through the real handler and read at two moments:
  // the click is synchronous, the play is not. Before the awaits settle the
  // value must still be there; after, gone.
  const r = rig();
  r.input.value = "hello";
  r.click( "multiplexer-direct-tts-btn" );

  assert.equal( r.input.value, "hello",
    "the input was cleared synchronously on press — a play that then fails loses the " +
    "operator's text to a failure they did not cause" );
  // Positive control for the GAP itself. `looked` is NOT usable here: an async
  // function runs synchronously up to its first await, and `checkCache` has no
  // await before its recorder, so the cache is already consulted by the time the
  // click returns — measured 2026-09-23, and it failed this control on the first
  // run. `spoken` is the honest marker: nothing has been sent yet, so the value
  // read above was genuinely read MID-FLIGHT and not after everything finished.
  assert.deepEqual( r.spoken, [],
    "positive control: the whole play already completed synchronously, so the assertion above " +
    "is not observing the gap it claims to" );

  await settle();

  assert.equal( r.input.value, "" );
  assert.deepEqual( r.spoken, [ { text: "hello", mode: "instant" } ],
    "the clear happened without anything being spoken" );
} );

test( "🔴 D5 — A FAILED PLAY STILL CLEARS, because legacy's catch is INSIDE playTTS", async () => {
  // Legacy's `directTTSTest` awaits `playTTS`, which swallows its own failure and
  // returns normally — so the clear runs. Matching that matters: the alternative
  // reading (clear only on success) is the one a reader would guess.
  speakFail = true;
  const r = rig();
  r.input.value = "doomed";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.equal( r.input.value, "" );
  assert.ok( r.errors.some( ( e ) => e.includes( "TTS playback failed" ) ),
    "a failed play was not reported anywhere — there is no status element, so the log is the only channel" );
} );

test( "a failed cache-hit playback is reported and swallowed, not thrown at the page", async () => {
  cacheHit  = new Blob( [ "x" ] );
  playFail  = true;
  const r = rig();
  r.input.value = "cached but broken";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.ok( r.errors.some( ( e ) => e.includes( "TTS playback failed in instant mode" ) ) );
  assert.deepEqual( r.spoken, [],
    "a failed HIT fell through to the server — legacy's hit arm returns, it does not retry" );
} );

// --- D6 / D7, the test buttons --------------------------------------------

test( "🔴 D6 / D7 — THE TEST TEXT IS BUILT FROM THE MODE VALUE, not two literals", async () => {
  // Legacy concatenates `mode`, so the two buttons cannot drift apart. Two
  // hard-coded strings would pass a per-button test and diverge the day a third
  // mode appears.
  assert.equal( directTtsTestText( "instant" ),
    "This is a test of the text-to-speech system in instant mode." );
  assert.equal( directTtsTestText( "reliable" ),
    "This is a test of the text-to-speech system in reliable mode." );

  const r = rig();
  r.click( "multiplexer-test-instant-tts-btn" );
  await settle();
  r.click( "multiplexer-test-reliable-tts-btn" );
  await settle();

  assert.deepEqual( r.spoken, [
    { text: directTtsTestText( "instant" ),  mode: "instant" },
    { text: directTtsTestText( "reliable" ), mode: "reliable" },
  ] );
} );

test( "the test buttons speak their OWN mode, not the store's", async () => {
  // Legacy passes the mode as the argument: `testTTS( TTS_MODE_INSTANT )`. A
  // button that deferred to the select would make "Test Reliable TTS" speak in
  // instant mode whenever the select said instant — which is every default load.
  mode = "instant";
  const r = rig();
  r.click( "multiplexer-test-reliable-tts-btn" );
  await settle();

  assert.deepEqual( r.spoken, [ { text: directTtsTestText( "reliable" ), mode: "reliable" } ] );
} );

test( "the test buttons go through the cache too — legacy checks before every play", async () => {
  const blob = new Blob( [ "cached test" ] );
  cacheHit = blob;
  const r = rig();
  r.click( "multiplexer-test-instant-tts-btn" );
  await settle();

  assert.deepEqual( r.looked, [ directTtsTestText( "instant" ) ] );
  assert.deepEqual( r.played, [ blob ] );
  assert.deepEqual( r.spoken, [] );
} );

test( "a test button does NOT touch the input — it has nothing to clear", async () => {
  const r = rig();
  r.input.value = "typed but not sent";
  r.click( "multiplexer-test-instant-tts-btn" );
  await settle();
  assert.equal( r.input.value, "typed but not sent" );
} );

// --- D8, the stop ---------------------------------------------------------

test( "🔴 D8 — STOP HALTS BOTH THE STORE AND EVERYTHING ELSE, and speaks to neither path", () => {
  const r = rig();
  r.click( "multiplexer-stop-audio-btn" );

  assert.equal( r.stops, 1, "AudioStore.stop() was not called — the Web Audio sources keep playing" );
  assert.equal( r.halts, 1, "the rest of the teardown was not called" );
  assert.deepEqual( r.spoken, [] );
  assert.deepEqual( r.played, [] );
} );

test( "stop is idempotent — a second press is another full halt, not a throw", () => {
  const r = rig();
  r.click( "multiplexer-stop-audio-btn" );
  r.click( "multiplexer-stop-audio-btn" );
  assert.equal( r.stops, 2 );
  assert.equal( r.halts, 2 );
} );

// --- D9, the wiring -------------------------------------------------------

test( "🔴 D9 — UNMOUNT REMOVES THE LISTENERS, so a remounted pane does not fire twice", async () => {
  // Legacy wires unguarded and never unmounts, so it cannot hit this. A client
  // that owns its subtree can: the buttons are rebuilt on remount, but a handler
  // left on a retained node would double every press.
  const r = rig();
  const stopBtn = r.root.querySelector<HTMLElement>( '[data-testid="multiplexer-stop-audio-btn"]' )!;
  r.renderer.unmount();

  assert.equal( r.root.children.length, 0, "unmount left the pane's subtree in the page" );
  stopBtn.click();                       // the detached node, still reachable by the old handle
  assert.equal( r.stops, 0, "a detached button still reaches the store — the listener survived unmount" );
} );

test( "mounting twice is refused rather than silently building a second subtree", () => {
  const r = rig();
  assert.throws( () => r.renderer.mount( r.root ), /already mounted/ );
} );

test( "a remount works, and the new controls are live", async () => {
  const r = rig();
  r.renderer.unmount();
  const root2 = document.createElement( "div" );
  r.renderer.mount( root2 );

  root2.querySelector<HTMLElement>( '[data-testid="multiplexer-stop-audio-btn"]' )!.click();
  assert.equal( r.stops, 1 );
  r.renderer.unmount();
} );

// --- the log ---------------------------------------------------------------

test( "the press is logged with the text and the mode, as legacy logs it", async () => {
  const r = rig();
  r.input.value = "hello";
  r.click( "multiplexer-direct-tts-btn" );
  await settle();

  assert.ok( r.logs.some( ( l ) => l.includes( "hello" ) && l.includes( "instant" ) ),
    "the direct-TTS press left no trace in the only channel this pane has" );
} );
