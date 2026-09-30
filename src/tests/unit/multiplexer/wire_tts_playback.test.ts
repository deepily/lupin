// Multiplexer 4f14d38f — wireTtsPlayback unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/wire_tts_playback.test.ts`.
//
// The TTS playback request-initiation wire: on store_tts_queue_changed, when the
// active item rolls to a NEW notification, POST { text, session_id } to
// /api/get-speech-elevenlabs (the mux's OWN sessionId = the PCM routing key).
// Covers the re-request guard (new-id-only, same-id no-refire, drain reset,
// re-enqueue refire), the ttsText nullish path, and fire-and-forget rejection.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { wireTtsPlayback } from "../../../lupin_app/static/js/multiplexer/wireTtsPlayback";
import type { TtsQueueItem, StoreTtsQueueChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const SESSION = "wise-penguin-1";

function item( id: string, over: Partial<TtsQueueItem> = {} ): TtsQueueItem {
  return { id_hash: id, ttsText: `say ${id}`, addedAt: 0, ...over };
}

function makeActiveReader() {
  let active: TtsQueueItem | null = null;
  return {
    reader: { activeItem: (): TtsQueueItem | null => active },
    setActive( it: TtsQueueItem | null ): void { active = it; },
  };
}

interface PostCall { path: string; body: unknown; }

function makePoster( mode: "resolve" | "reject" = "resolve" ) {
  const calls: PostCall[] = [];
  return {
    calls,
    poster: {
      post<T>( path: string, body: unknown ): Promise<T> {
        calls.push( { path, body } );
        return mode === "reject"
          ? Promise.reject( new Error( "boom" ) )
          : Promise.resolve( undefined as T );
      },
    },
  };
}

// Parity B-1 — the mode reader the wire picks its door from. `instant` is the
// default everything below assumes; the two `reliable` cases pass their own.
function modeReader( mode: "instant" | "reliable" = "instant" ) {
  return { ttsMode: () => mode };
}

// The wire reads ttsQueue.activeItem() (not the payload) — a well-formed payload
// keeps the event honest; activeId only drives readability here.
function emitChange( bus: ReturnType<typeof createEventBusForTesting>, activeId: string | null ): void {
  bus.emit<StoreTtsQueueChangedPayload>( {
    type    : "store_tts_queue_changed",
    payload : { activeNotificationId: activeId, pending: [] },
    source  : "test",
    ts      : 0,
  } );
}

test("new active id (null→A): POSTs { text, session_id } exactly once to the elevenlabs endpoint", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  assert.equal( api.calls.length, 1 );
  assert.equal( api.calls[0]!.path, "/api/get-speech-elevenlabs" );
  assert.deepEqual( api.calls[0]!.body, { text: "say A", session_id: SESSION } );
});

test("advance A→B: a new active id fires a second POST for B", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  q.setActive( item( "B" ) ); emitChange( bus, "B" );
  assert.equal( api.calls.length, 2 );
  assert.deepEqual( api.calls[1]!.body, { text: "say B", session_id: SESSION } );
});

test("same active id re-emit (pending churn while A still plays): does NOT re-request", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  emitChange( bus, "A" );   // e.g. a new pending item appended while A is still the head
  assert.equal( api.calls.length, 1, "same active id must not re-POST" );
});

test("drain A→null: no POST on the null roll", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  q.setActive( null );        emitChange( bus, null );
  assert.equal( api.calls.length, 1, "the final null roll makes no request" );
});

test("re-enqueue same id after a drain (A→null→A): re-requests (guard was reset)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  q.setActive( null );        emitChange( bus, null );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  assert.equal( api.calls.length, 2, "same id after a drain must re-request" );
});

test("undefined ttsText: POSTs text \"\" (nullish-coalesce guard)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A", { ttsText: undefined } ) );
  emitChange( bus, "A" );
  assert.deepEqual( api.calls[0]!.body, { text: "", session_id: SESSION } );
});

test("POST rejection is swallowed (fire-and-forget) — the event handler does not throw", async () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster( "reject" );
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) );
  assert.doesNotThrow( () => emitChange( bus, "A" ) );
  assert.equal( api.calls.length, 1 );
  // Flush microtasks so the .catch runs (coverage) with no unhandled rejection.
  await Promise.resolve();
});

test("unsubscriber detaches the seam — no POST after it runs", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  const off = wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  off();
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  assert.equal( api.calls.length, 0 );
});

test("766bb609: an item carrying voice_id includes it in the POST body (persona voice)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A", { voice_id: "vox-tiberius" } ) );
  emitChange( bus, "A" );
  assert.deepEqual( api.calls[0]!.body, { text: "say A", session_id: SESSION, voice_id: "vox-tiberius" } );
});

test("766bb609: an item WITHOUT voice_id OMITS the key entirely (byte-identical to legacy null-voice body)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) );   // no voice_id
  emitChange( bus, "A" );
  assert.deepEqual( api.calls[0]!.body, { text: "say A", session_id: SESSION } );
  // The key must be ABSENT (not present-with-undefined) so the request is
  // byte-identical to the pre-766bb609 body → server default voice.
  assert.equal( Object.prototype.hasOwnProperty.call( api.calls[0]!.body, "voice_id" ), false );
});

// ---------------------------------------------------------------------------
// Parity B-1 — the reliable door.
//
// Legacy picks between two endpoints on every playback by reading #tts-mode
// (notifications.js playTTS → playInstantTTS /api/get-speech-elevenlabs, or
// playReliableTTS /api/get-speech). The multiplexer shipped the instant door only,
// which would have made the select's `reliable` option a painted-but-dead control.
// The BODY is the same on both doors, so these assert the URL and that the body did
// not change with it.
// ---------------------------------------------------------------------------

test("B-1: reliable mode POSTs the OpenAI batch door, with the same body", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader( "reliable" ) );
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  assert.equal( api.calls.length, 1 );
  assert.equal( api.calls[0]!.path, "/api/get-speech" );
  assert.deepEqual( api.calls[0]!.body, { text: "say A", session_id: SESSION } );
});

test("B-1: the mode is read at REQUEST time — a change between two items moves the door", () => {
  // Captured at wire time, a mid-session switch would keep knocking on the old door
  // for the rest of the page's life. Legacy re-reads its select per playback for the
  // same reason.
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  let mode: "instant" | "reliable" = "instant";
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, { ttsMode: () => mode } );

  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  mode = "reliable";
  q.setActive( item( "B" ) );
  emitChange( bus, "B" );

  assert.deepEqual( api.calls.map( ( c ) => c.path ), [ "/api/get-speech-elevenlabs", "/api/get-speech" ] );
});

// ---------------------------------------------------------------------------
// Parity B-1b — the TTFA clock's start.
//
// Legacy stamps `metricsTTSStartTime` immediately BEFORE the fetch, in BOTH
// playInstantTTS and playReliableTTS, with the comment "Start timing BEFORE the
// fetch for accurate TTFA measurement". Stamping after would fold the request's own
// latency into the metric that exists to isolate audio generation from it.
// ---------------------------------------------------------------------------

test("B-1b: the observer is notified BEFORE the POST, once per requested item", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const order: string[] = [];
  const api = {
    post<T>(): Promise<T> { order.push( "post" ); return Promise.resolve( undefined as T ); },
  };
  wireTtsPlayback( bus, q.reader, api, SESSION, modeReader(), {
    noteTtsRequested: () => { order.push( "stamp" ); },
  } );

  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  assert.deepEqual( order, [ "stamp", "post" ] );
});

test("B-1b: a same-id re-emit does NOT re-stamp — the guard covers both", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  let stamps = 0;
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader(), {
    noteTtsRequested: () => { stamps += 1; },
  } );

  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  emitChange( bus, "A" );
  assert.equal( stamps, 1 );
  assert.equal( api.calls.length, 1 );
});

test("B-1b: a null active rolls the guard and stamps nothing", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  let stamps = 0;
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader(), {
    noteTtsRequested: () => { stamps += 1; },
  } );

  q.setActive( null );
  emitChange( bus, null );
  assert.equal( stamps, 0 );
  assert.equal( api.calls.length, 0 );
});

test("B-1b: the observer is OPTIONAL — omitting it still requests", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader() );
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  assert.equal( api.calls.length, 1 );
});

// ===========================================================================
// Parity B-7 — the per-item mode override (María 🌸's review of cfe8a348).
//
// 🔴 THE DEFECT THIS CLOSES: the wire read ONLY the page-wide select, so an
// utterance that must be spoken in a specific mode could not say so. Direct
// TTS's "Test Reliable TTS" button therefore posted to the INSTANT door on any
// default page — and reported success, because the POST itself was fine. The
// button tested the wrong door and said so convincingly.
//
// Legacy has no such gap: `testTTS( mode )` hands the mode to
// `playTTS( text, mode )`, which branches on the ARGUMENT and never consults
// `#tts-mode` (notifications.js:4310-4314).
// ===========================================================================

test("🔴 an item's own tts_mode picks the door, overriding the page-wide select", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  // The select says instant — the state of any default page.
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader( "instant" ) );
  q.setActive( item( "A", { tts_mode: "reliable" } ) );
  emitChange( bus, "A" );

  assert.equal( api.calls.length, 1 );
  assert.equal( api.calls[ 0 ]!.path, "/api/get-speech",
    "the item asked for `reliable` and the wire posted to the instant door anyway — " +
    "Test Reliable TTS is testing the wrong endpoint and reporting success" );
});

test("🔴 and the converse — an item's `instant` wins over a `reliable` select", () => {
  // The mirror arm. One direction alone is satisfied by a wire that simply
  // hard-coded the other door.
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader( "reliable" ) );
  q.setActive( item( "A", { tts_mode: "instant" } ) );
  emitChange( bus, "A" );

  assert.equal( api.calls[ 0 ]!.path, "/api/get-speech-elevenlabs" );
});

test("an item with NO tts_mode still follows the page-wide select — every other caller", () => {
  // The override must not become a requirement: notifications carry no mode and
  // must keep tracking the select, which is the behaviour B-1 shipped.
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader( "reliable" ) );
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );

  assert.equal( api.calls[ 0 ]!.path, "/api/get-speech",
    "an item with no mode of its own stopped following the page-wide select" );
});

test("tts_mode does NOT leak into the request body — it chooses the door, it is not a field", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION, modeReader( "instant" ) );
  q.setActive( item( "A", { tts_mode: "reliable" } ) );
  emitChange( bus, "A" );

  assert.deepEqual( api.calls[ 0 ]!.body, { text: "say A", session_id: SESSION },
    "tts_mode reached the POST body — the server's contract is { text, session_id, voice_id? } " +
    "and the mode is expressed by WHICH endpoint is called" );
});
