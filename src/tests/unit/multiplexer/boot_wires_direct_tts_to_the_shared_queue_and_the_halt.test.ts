// Parity B-7 — what boot hands the Direct TTS pane.
//
// 🔴 THIS IS THE ONLY GUARD THAT CAN SEE `haltAll`'s CONTENTS. The pane takes it
// as a function and its own tests assert only that pressing Stop CALLS it —
// correctly, because the pane must not know what halting means. The composition
// lives in boot, boot is excluded from the coverage gate by Rick's 2026-07-21
// ruling, and importing it executes page bootstrap against a live DOM. So the
// source is read, exactly as the sibling `boot_wires_*` guards do.
//
// ⚠️ WHAT A SOURCE-PARSE CAN AND CANNOT SAY. It can say the call is written; it
// cannot say it runs, or runs in that order. It is a guard against DELETION and
// against a refactor that quietly drops a leg — which is the failure this row
// actually risks, because a missing halt leg is inaudible in a test and audible
// only to whoever is still hearing speech after pressing Stop.
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_wires_direct_tts_to_the_shared_queue_and_the_halt.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const BOOT_PATH = join(
  process.env.LUPIN_ROOT ?? process.cwd(),
  "src/lupin_app/static/js/multiplexer/boot.ts",
);
// Comments stripped: this file's own prose names every symbol it asserts, and a
// match inside a comment is the defect the B-6 link guard was caught by.
const BOOT_CODE = readFileSync( BOOT_PATH, "utf8" )
  .split( "\n" )
  .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
  .join( "\n" );

/** The `createDirectTtsRenderer({ … })` argument, braces balanced. */
function directTtsCall(): string {
  const start = BOOT_CODE.indexOf( "createDirectTtsRenderer(" );
  assert.notEqual( start, -1,
    "boot does not call createDirectTtsRenderer — the pane is not mounted, and every " +
    "assertion below would pass over an empty string" );
  let depth = 0;
  for ( let i = start; i < BOOT_CODE.length; i++ ) {
    const ch = BOOT_CODE[ i ];
    if ( ch === "(" ) depth += 1;
    if ( ch === ")" ) {
      depth -= 1;
      if ( depth === 0 ) return BOOT_CODE.slice( start, i + 1 );
    }
  }
  assert.fail( "createDirectTtsRenderer's call is unbalanced — the slice ran to end-of-file" );
}

test( "the parse finds a real call — the control every assertion below rests on", () => {
  const call = directTtsCall();
  assert.ok( call.length > 200, `the extracted call is only ${ call.length } chars` );
  assert.ok( call.includes( "haltAll" ), "the extracted slice does not even contain haltAll" );
} );

test( "🔴 D8 — THE HALT STOPS THE BLOB PLAYER, AND MUST NOT CLEAR THE QUEUE", () => {
  // 🔴 THIS TEST USED TO ASSERT THE OPPOSITE, AND THE OPPOSITE WAS A DEFECT.
  // The first cut called `stores.ttsQueue.clear()` in the halt, so pressing Stop
  // on a TTS TEST silently discarded every notification waiting to be spoken —
  // work that had nothing to do with this pane. Caught by María 🌸 in review of
  // cfe8a348, not by this file, which was asserting the defect was present.
  //
  // The multiplexer's own transport already settles it: TtsChromeRenderer wires
  // `onStop` to `stores.audio.stop()` and `onClearAll` to
  // `stores.ttsQueue.clear()`. Two buttons, two verbs. Stop is not Clear-All.
  const call = directTtsCall();
  assert.ok( /directTtsPlayer\.stop\(\)/.test( call ),
    "the halt no longer stops the blob player — a cached hit keeps playing through Stop" );

  const halt = /haltAll\s*:\s*\(\)\s*=>\s*\{([\s\S]*?)\n\s*\},/.exec( call );
  assert.notEqual( halt, null, "positive control: haltAll's body could not be isolated" );
  assert.ok( /directTtsPlayer\.stop\(\)/.test( halt![ 1 ]! ),
    "positive control: the isolated body is not haltAll's" );
  assert.equal( /ttsQueue\.clear\(\)/.test( halt![ 1 ]! ), false,
    "Stop clears the whole speech queue again. That discards every notification waiting to be " +
    "spoken because someone pressed Stop on a TTS test. Clear-All is a different control." );
} );

test( "🔴 THE MODE RIDES THE ITEM — otherwise Test Reliable speaks through the instant door", () => {
  // The second blocker from the same review. wireTtsPlayback reads the
  // page-wide select, so an utterance that must be spoken in a SPECIFIC mode has
  // to carry it. Legacy's `playTTS( text, mode )` branches on its argument and
  // never consults `#tts-mode`, which is why its two test buttons really do test
  // two doors. Without this the button posted to the wrong door and reported
  // success, because the POST itself was fine.
  const call = directTtsCall();
  assert.ok( /speak\s*:\s*async\s*\(\s*text\s*,\s*mode\s*\)/.test( call ),
    "boot's speak() dropped its mode parameter — the pane passes one and nothing carries it" );
  assert.ok( /tts_mode\s*:\s*mode/.test( call ),
    "the enqueued item no longer carries tts_mode — every Direct TTS utterance goes through " +
    "whatever door the page-wide select happens to name" );
} );

test( "🔴 THE STORE'S OWN stop() IS THE THIRD LEG, and it is passed as `audio`", () => {
  // The pane calls `audio.stop()` itself, so this asserts boot handed it the
  // real store rather than a stub that satisfies the type.
  const call = directTtsCall();
  assert.ok( /audio\s*:\s*stores\.audio\b/.test( call ),
    "boot no longer passes stores.audio — the Web Audio sources and the gapless scheduler " +
    "are never halted, and the mode comes from somewhere else" );
} );

test( "🔴 THE MISS PATH GOES THROUGH THE SHARED QUEUE — B-7 owns no door of its own", () => {
  // One door, one place the mode is read. A second POST site here would be a
  // second place to keep the instant/reliable branch in step with B-1's.
  const call = directTtsCall();
  assert.ok( /stores\.ttsQueue\.enqueue\(/.test( call ),
    "the cache-miss path no longer enqueues onto the shared TtsQueueStore" );
  assert.equal( /apiClient\.post\(|fetch\(/.test( call ), false,
    "the Direct TTS pane posts directly — that is a second door, and the instant/reliable " +
    "branch now lives in two places" );
} );

test( "🔴 THE CACHE IS CONSULTED, AND IT IS THE REAL TtsAudioCache", () => {
  const call = directTtsCall();
  assert.ok( /cache\s*:\s*directTtsCache\b/.test( call ) );
  assert.ok( /new TtsAudioCache\(/.test( BOOT_CODE ),
    "boot no longer builds a TtsAudioCache — D4's bypass has nothing to look in, so every " +
    "press is a miss and the pane silently becomes a slower Q&A" );
  assert.ok( /directTtsCache\.initialize\(\)/.test( BOOT_CODE ),
    "the cache is never initialized — checkCache answers from the memory tier only, so a hit " +
    "can never survive a reload and the feature looks like it works in one session" );
} );

test( "🔴 D2's WRITERS ARE THE DEBUG SINK, now that B-6 is merged", () => {
  // Legacy refuses an empty input into `this.error`, which writes the debug
  // panel AND the console. While B-6 was unmerged this passed bare `console`
  // calls with legacy's prefixes copied by hand; now it passes debugSink's own
  // writers, which OWN those prefixes. An unwired refusal is invisible, because
  // there is no inline status element in either client.
  const call = directTtsCall();
  assert.ok( /logFn\s*:\s*debugLog\b/.test( call ),
    "boot no longer passes debugSink's log — a Direct TTS press leaves no trace in the panel" );
  assert.ok( /errorFn\s*:\s*debugError\b/.test( call ),
    "boot no longer passes debugSink's error — an empty input is refused into nothing, and " +
    "there is no inline status element to notice it" );

  // ⚠️ AND THE PREFIXES MUST NOT BE RE-ADDED HERE. debugSink writes
  // `[Notifications] ` and `[Notifications ERROR] ` itself; a hand-copy at this
  // call site would double them in the console and still send the panel an
  // unprefixed line, which is the state this commit removed.
  assert.equal( /\[Notifications/.test( call ), false,
    "boot re-added legacy's console prefix at the call site — debugSink already writes it, so " +
    "the console line would read `[Notifications] [Notifications] …`" );
  assert.ok( /from "\.\/shared\/debugSink"/.test( BOOT_CODE ),
    "boot does not import debugSink at all" );
} );
