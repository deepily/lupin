// Row aa13fdd7 — 0% MEANS SILENT on the legacy client too.
//
// Rick, ruling on af01bd4b (2026-09-26): "The only thing that is an issue is that
// playback occurs when it is NOT enabled." The slider's label is the promise —
// notifications.html:491, "0% = silent; 100% = full message."
//
// 🔴 THE GATE EXISTED AND MOST CALLERS WALKED PAST IT. Measured 2026-09-27:
// `_computeTTSPreview` has exactly two references in notifications.js — its own
// definition and one call, from `addToTTSQueue`. So the queued notification paths
// honoured the slider and every DIRECT caller of `playTTS` did not. The live one was
// `handleJobCompletion` (:4035-4041), which calls playTTS straight through, so a
// finished job spoke at 0%. It need not be the user's own job: the `tts_job_request`
// frame arrives for any sender.
//
// ⚠️ THE CEILING MATTERS AS MUCH AS THE FLOOR. Five callers are a key the user
// pressed asking to hear something — Direct TTS Test, testTTS, job replay, and the
// two notification-card play/replay controls. Silencing those at 0% would be a new
// defect traded for an old one: a control that reports success and makes no sound,
// and a divergence from the multiplexer, which keeps its Direct TTS pane audible via
// the matching `user_initiated` item flag. So there are cases here for speech that
// must SURVIVE, not only speech that must stop.
//
// ENTERED AT handleJobCompletion, NOT AT playTTS, for the automatic case — that is
// the layer the incident entered at, and a test that calls playTTS itself cannot see
// a caller that passes the wrong argument.
//
// Run: npx tsx --test src/tests/unit/notifications_js/tts_silent_when_the_slider_is_at_zero.test.ts

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

// A slider position, named so the assertions read as settings rather than numbers.
const SILENT  = 0;
const AUDIBLE = 0.25;

/** One dispatch to a real TTS door, recorded instead of performed. */
interface Spoken { door: "instant" | "reliable"; text: string; voiceId: string | null }

type TtsUI = Record<string, unknown> & {
  ttsPreviewFraction : number;
  playTTS            : ( text: string, mode: string, voiceId?: string | null, userInitiated?: boolean ) => Promise<void>;
  handleJobCompletion: ( envelope: Record<string, unknown> ) => void;
};

let spoken: Spoken[] = [];

/**
 * A bare instance carrying only what the speech path touches.
 *
 * The two DOORS are stubbed, not the gate: `playInstantTTS` / `playReliableTTS` are
 * where audio actually leaves, so recording them measures "did this utterance
 * dispatch", which is the question, and it needs no network or AudioContext.
 */
function newUI( fraction: number ): TtsUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as TtsUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.ttsPreviewFraction = fraction;
  // Cache OFF: a cache hit is a third door and would answer a different question.
  ui.audioCacheInitialized = false;
  ui.TTS_MODE_INSTANT      = "instant";
  ui.playInstantTTS  = async ( text: string, voiceId: string | null = null ): Promise<void> => {
    spoken.push( { door: "instant", text, voiceId } );
  };
  ui.playReliableTTS = async ( text: string, voiceId: string | null = null ): Promise<void> => {
    spoken.push( { door: "reliable", text, voiceId } );
  };
  // handleJobCompletion's own collaborators, stubbed to no-ops: this file asks about
  // SPEECH, and each of these has its own guard elsewhere.
  ui.processedEvents           = new Set<string>();
  ui.maxProcessedEvents        = 100;
  ui.updateElement             = (): void => {};
  ui.updateMetricsTTT          = (): void => {};
  ui.storeJobCompletionForReplay = async (): Promise<void> => {};
  ui.getVoiceIdForSender       = (): string | null => null;
  return ui;
}

/** The `#tts-mode` select handleJobCompletion reads its door from. */
function buildDOM(): void {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.innerHTML = `<select id="tts-mode"><option value="instant" selected>instant</option></select>`;
  document.body.appendChild( host );
}

beforeEach( () => {
  spoken = [];
  buildDOM();
} );

// ---------------------------------------------------------------------------
// The floor — automatic speech stops at 0%.
// ---------------------------------------------------------------------------

test( "at 0% a finished job says nothing", async () => {
  const ui = newUI( SILENT );
  ui.handleJobCompletion( {
    type      : "tts_job_request",
    timestamp : "2026-09-27T16:00:00Z",
    text      : "the answer nobody asked to hear",
    sender_id : "some-other-client",
  } );
  // handleJobCompletion does not await playTTS, so let the microtask queue drain
  // before asking — otherwise this passes on timing rather than on the gate.
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual( spoken, [],
    "this is the path that was live: handleJobCompletion calls playTTS directly and so " +
    "never met the addToTTSQueue gate, and the frame arrives for ANY sender's job" );
} );

test( "at 0% an automatic playTTS dispatches to neither door", async () => {
  const ui = newUI( SILENT );
  await ui.playTTS( "unrequested speech", "instant" );
  assert.deepEqual( spoken, [],
    "the default for userInitiated must be false, so a caller that knows nothing about " +
    "the argument is gated rather than accidentally exempt" );
} );

// ---------------------------------------------------------------------------
// The ceiling — a button press still sounds, and nothing above 0% is touched.
// ---------------------------------------------------------------------------

test( "at 0% a user-initiated utterance still speaks", async () => {
  const ui = newUI( SILENT );
  await ui.playTTS( "Speak Now", "instant", null, true );
  assert.equal( spoken.length, 1, "the user pressed a button asking to hear this" );
  assert.equal( spoken[ 0 ]?.text, "Speak Now" );
} );

// ⚠️ THE CENSUS BELOW IS NOT ENOUGH ON ITS OWN, AND THIS IS WHY THIS CASE EXISTS.
// Measured 2026-09-27: stripping the `, null, true` from all five button call sites
// reddens ONLY the census test, because every other ceiling case calls playTTS with
// the flag itself and so tests the MECHANISM rather than the CALLERS. This case
// drives a real button path end to end, so the five exemptions are guarded by
// behaviour and not only by a source count.
test( "at 0% the Test TTS button still speaks — driven through its own handler", async () => {
  const ui = newUI( SILENT );
  await ( ui as unknown as { testTTS: ( m: string ) => Promise<void> } ).testTTS( "instant" );
  assert.equal( spoken.length, 1,
    "testTTS is a button. Legacy has always sounded at 0% here because its gate lives in " +
    "addToTTSQueue and this path never entered it; silencing it would be a new defect " +
    "traded for an old one, and a divergence from the multiplexer's Direct TTS pane" );
  assert.match( spoken[ 0 ]?.text ?? "", /test of the text-to-speech system/ );
} );

test( "above 0% a finished job is spoken, as it always was", async () => {
  const ui = newUI( AUDIBLE );
  ui.handleJobCompletion( {
    type      : "tts_job_request",
    timestamp : "2026-09-27T16:01:00Z",
    text      : "an answer the user wants read out",
  } );
  await Promise.resolve();
  await Promise.resolve();
  assert.equal( spoken.length, 1,
    "with the slider up the job answer must still speak — this is what proves the test " +
    "above measured the GATE and not a job-completion path broken some other way" );
  assert.equal( spoken[ 0 ]?.text, "an answer the user wants read out" );
} );

test( "above 0% the door is still chosen by the mode, not flattened by the gate", async () => {
  const ui = newUI( AUDIBLE );
  await ui.playTTS( "reliable please", "reliable" );
  assert.equal( spoken[ 0 ]?.door, "reliable",
    "the gate must not disturb the instant/reliable branch beneath it" );
} );

// ---------------------------------------------------------------------------
// The call sites — a source parse, because the split between automatic and
// user-initiated is a fact about WHO CALLS, which no single behaviour test sees.
// ---------------------------------------------------------------------------

const SOURCE = readFileSync( NOTIFICATIONS_JS, "utf8" )
  .split( "\n" )
  .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
  .join( "\n" );

test( "every playTTS call site is deliberately on one side of the gate", () => {
  const calls = SOURCE.split( "\n" ).filter( ( l ) => l.includes( "this.playTTS(" ) );
  assert.equal( calls.length, 7,
    `expected 7 playTTS call sites, found ${calls.length} — a NEW one has appeared and ` +
    "nobody has decided which side of the gate it belongs on, which is exactly the " +
    "decision this row was filed about" );
  const userInitiated = calls.filter( ( l ) => /,\s*true\s*\)/.test( l ) );
  assert.equal( userInitiated.length, 5,
    "5 call sites are a button press: Direct TTS Test, testTTS, job replay, and the two " +
    "notification-card play/replay controls" );
  const automatic = calls.filter( ( l ) => !/,\s*true\s*\)/.test( l ) );
  assert.equal( automatic.length, 2,
    "2 are automatic and must stay gated: handleJobCompletion, and the TTS queue's own " +
    "playback (already gated upstream by the addToTTSQueue skip, so this is suspenders)" );
  assert.ok( automatic.some( ( l ) => l.includes( "actualText || \"Job completed\"" ) ),
    "handleJobCompletion's call must be one of the gated two — it is the defect this row named" );
} );

test( "the gate reads the same field the slider writes", () => {
  assert.match( SOURCE, /if \( this\.ttsPreviewFraction === 0 && !userInitiated \)/,
    "the gate must key on ttsPreviewFraction, the field the slider and the shared " +
    "localStorage key both drive — a separate flag would be a second setting nobody moves" );
} );
