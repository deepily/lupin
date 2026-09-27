// Row aa13fdd7 — 0% MEANS SILENT, on every AUTOMATIC speech path.
//
// Rick, ruling on af01bd4b (2026-09-26): "The only thing that is an issue is that
// playback occurs when it is NOT enabled." The slider's own label is the promise —
// notifications.html:491, "0% = silent; 100% = full message."
//
// 🔴 WHAT WAS ACTUALLY BROKEN, MEASURED 2026-09-27 AND NOT INFERRED. Fixed-string
// `git grep -F '.enqueue('` over the 161 non-test .ts files under
// static/js/multiplexer/ returns exactly three production call sites into
// TtsQueueStore — wireTtsIntent.ts (notification arrivals), stores/QaStore.ts
// (job-completion answers) and boot.ts (the Direct TTS pane). Only the FIRST read
// the slider. TtsQueueStore.enqueue itself read no setting at all, and
// wireTtsPlayback is the single POST to /api/get-speech* in this client, so every
// sound this client makes through the server traces back through that one
// unguarded method.
//
// The live consequence was the job-completion answer. QaStore's own docstring notes
// a `tts_job_request` frame can arrive "with no submit behind it (another client's
// job, a cold reload)" — so with the slider at 0%, ANY client finishing a job made
// this one talk.
//
// ⚠️ AN EXPLICIT BUTTON PRESS IS NOT AUTOMATIC SPEECH, AND THAT IS A PARITY FACT,
// NOT A CONVENIENCE. Legacy's gate lives inside `addToTTSQueue` (the only caller of
// `_computeTTSPreview`, notifications.js:22307), while Speak Now and the two Test
// TTS buttons call `playTTS` directly (:4259, :4288) and never pass through it. So
// legacy's buttons sound at 0% and the multiplexer's must too, or the two clients
// diverge and a control reports success while making no noise. `user_initiated`
// carries that opt-out, and its ABSENCE gates — a new automatic path is silent at
// 0% without having to remember this flag.
//
// THE TWO ALTITUDES BELOW ARE BOTH NEEDED, and the sibling guard
// `the_assembled_qa_store_speaks_its_answer.test.ts` is why. A store-level test
// hands the store its own `liveFraction` and so cannot see a construction site that
// forgets to pass one; `stores/index.ts` is `/* c8 ignore */` end to end, so no
// coverage number would show it either. The assembled cases enter at `createStores`
// for exactly that reason. The boot cases are a source parse, the idiom the sibling
// `boot_wires_*` guards use, because importing boot runs page bootstrap.
//
// Run: npx tsx --test src/tests/unit/multiplexer/tts_silent_when_the_slider_is_at_zero.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import type { TtsJobRequestPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const NOW = 1_700_000_000_000;

// A slider position, named so the assertions read as settings rather than numbers.
const SILENT = 0;
const AUDIBLE = 0.25;

// ---------------------------------------------------------------------------
// Altitude 1 — the store's own gate.
// ---------------------------------------------------------------------------

function queueAt( fraction: number ) {
  const bus = createEventBusForTesting();
  return createTtsQueueStore( { bus, nowFn: () => NOW, liveFraction: () => fraction } );
}

test( "at 0% an automatic utterance is dropped, not queued", () => {
  const tts = queueAt( SILENT );
  tts.enqueue( { id_hash: "auto-1", ttsText: "a notification nobody asked to hear" } );
  assert.equal( tts.current(), null,
    "the slider is at 0% and this item had no user_initiated flag, so it must not have " +
    "become the active utterance — an active item is what makes wireTtsPlayback POST" );
  assert.equal( tts.itemQueueLength(), 0, "nor may it sit in the pending tail waiting to speak" );
  assert.equal( tts.isPlaying(), false );
} );

test( "at 0% a user-initiated utterance still speaks", () => {
  const tts = queueAt( SILENT );
  tts.enqueue( { id_hash: "direct-tts-1", ttsText: "Speak Now", user_initiated: true } );
  assert.equal( tts.current(), "direct-tts-1",
    "the user pressed a button asking to hear this; legacy's Speak Now sounds at 0% " +
    "because its gate is in addToTTSQueue and playTTS bypasses it, and so must this" );
} );

test( "above 0% an automatic utterance speaks as before", () => {
  const tts = queueAt( AUDIBLE );
  tts.enqueue( { id_hash: "auto-2", ttsText: "an ordinary arrival" } );
  assert.equal( tts.current(), "auto-2",
    "the gate must fire on 0% ALONE — if this reddens, the gate is silencing speech " +
    "the user did ask for" );
} );

test( "the gate is re-read per utterance, so moving the slider takes effect without a reload", () => {
  const bus = createEventBusForTesting();
  let fraction = SILENT;
  const tts = createTtsQueueStore( { bus, nowFn: () => NOW, liveFraction: () => fraction } );

  tts.enqueue( { id_hash: "while-silent", ttsText: "dropped" } );
  assert.equal( tts.current(), null, "silent at enqueue time" );

  fraction = AUDIBLE;
  tts.enqueue( { id_hash: "after-the-move", ttsText: "spoken" } );
  assert.equal( tts.current(), "after-the-move",
    "the fraction must be READ at each enqueue, never captured at construction — the " +
    "shared legacy key means the user can move it on the other client at any moment" );
} );

// ---------------------------------------------------------------------------
// Altitude 2 — the assembled app. These are the cases a store-level test cannot
// reach: they fail if createStores forgets to forward the reader.
// ---------------------------------------------------------------------------

// createStores wants one object satisfying five client interfaces. Nothing here
// reaches the network — the job-completion path under test is bus-driven end to end.
const API = {
  get   : async <T>() => ( {} as T ),
  post  : async <T>() => ( {} as T ),
  patch : async <T>() => ( {} as T ),
};

function assembledAt( fraction: number ) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  const stores  = createStores( {
    eventBus        : bus,
    storage,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the five-interface intersection; every call here is stubbed.
    api             : API as any,
    ttsLiveFraction : () => fraction,
  } );
  return { bus, stores };
}

/** The server frame a finished job arrives on (legacy handleJobCompletion's input). */
function jobCompleted( bus: ReturnType<typeof createEventBusForTesting>, payload: TtsJobRequestPayload ): void {
  bus.emit( { type: "tts_job_request", payload, source: "test", ts: 0 } );
}

test( "assembled: at 0% a finished job writes its answer to the pane and says nothing", () => {
  const { bus, stores } = assembledAt( SILENT );
  jobCompleted( bus, { text: "the answer nobody asked to hear", job_id: "job-1" } as TtsJobRequestPayload );

  assert.equal( stores.ttsQueue.current(), null,
    "this is the path that was live: QaStore.speak read no setting, and the frame can " +
    "arrive from ANOTHER client's job, so at 0% a peer's finished job made this client talk" );
  assert.equal( stores.ttsQueue.itemQueueLength(), 0 );
  assert.match( stores.qa.responseText(), /the answer nobody asked to hear/,
    "silencing the AUDIO must not silence the PANE — the written answer is not speech, " +
    "and legacy writes it before it ever calls playTTS (notifications.js:4040)" );
} );

test( "assembled: above 0% the same frame is spoken", () => {
  const { bus, stores } = assembledAt( AUDIBLE );
  jobCompleted( bus, { text: "an answer the user wants read out", job_id: "job-2" } as TtsJobRequestPayload );
  assert.equal( stores.ttsQueue.current(), "qa-job-2",
    "with the slider up, the job answer must still speak — this is the case that proves " +
    "the previous test measured the GATE and not a broken job-completion path" );
} );

// ---------------------------------------------------------------------------
// Altitude 3 — boot's wiring. A source parse: importing boot runs page bootstrap
// against a live DOM, and boot is outside the coverage gate (Rick, 2026-07-21).
// It can say the call is WRITTEN; it cannot say it runs. That is the failure this
// row risks — a refactor quietly dropping the argument, which is inaudible in a
// test and audible only to whoever is still hearing speech at 0%.
// ---------------------------------------------------------------------------

const BOOT_PATH = join(
  process.env.LUPIN_ROOT ?? process.cwd(),
  "src/lupin_app/static/js/multiplexer/boot.ts",
);
// Comments stripped: this file's own prose names every symbol it asserts, and a
// match inside a comment is a guard passing on its own documentation.
const BOOT_CODE = readFileSync( BOOT_PATH, "utf8" )
  .split( "\n" )
  .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
  .join( "\n" );

test( "boot hands createStores a live-fraction reader", () => {
  assert.match( BOOT_CODE, /ttsLiveFraction\s*:\s*readLiveTtsFraction/,
    "without this argument createStores builds an UNGATED queue and every case above " +
    "still passes, because they supply the reader themselves" );
  assert.match( BOOT_CODE, /const readLiveTtsFraction\s*=\s*\(\)\s*:\s*number\s*=>\s*resolveLiveFraction\(/,
    "and the reader must be resolveLiveFraction, the function whose first source is the " +
    "LEGACY shared key — that is what lets a change on the legacy page silence this client" );
} );

test( "boot marks the Direct TTS pane's utterance user-initiated", () => {
  const start = BOOT_CODE.indexOf( "createDirectTtsRenderer(" );
  assert.notEqual( start, -1,
    "boot does not mount the Direct TTS pane — the assertion below would pass over an empty string" );
  const paneCall = BOOT_CODE.slice( start, BOOT_CODE.indexOf( "haltAll", start ) );
  assert.match( paneCall, /user_initiated\s*:\s*true/,
    "the pane's three buttons would go dead at 0% without this — a control that reports " +
    "success and makes no sound, and a divergence from legacy, whose Speak Now sounds at 0%" );
} );

test( "the live-fraction expression exists in exactly one place", () => {
  const readers = BOOT_CODE.split( "resolveLiveFraction(" ).length - 1;
  assert.equal( readers, 1,
    `boot calls resolveLiveFraction ${readers} times; it must be 1. Two copies are two ` +
    "places deciding one rule, and they agree only until someone edits one of them" );
} );
