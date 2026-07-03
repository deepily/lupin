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
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
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
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  q.setActive( item( "B" ) ); emitChange( bus, "B" );
  assert.equal( api.calls.length, 2 );
  assert.deepEqual( api.calls[1]!.body, { text: "say B", session_id: SESSION } );
});

test("same active id re-emit (pending churn while A still plays): does NOT re-request", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  emitChange( bus, "A" );   // e.g. a new pending item appended while A is still the head
  assert.equal( api.calls.length, 1, "same active id must not re-POST" );
});

test("drain A→null: no POST on the null roll", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  q.setActive( null );        emitChange( bus, null );
  assert.equal( api.calls.length, 1, "the final null roll makes no request" );
});

test("re-enqueue same id after a drain (A→null→A): re-requests (guard was reset)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  q.setActive( null );        emitChange( bus, null );
  q.setActive( item( "A" ) ); emitChange( bus, "A" );
  assert.equal( api.calls.length, 2, "same id after a drain must re-request" );
});

test("undefined ttsText: POSTs text \"\" (nullish-coalesce guard)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A", { ttsText: undefined } ) );
  emitChange( bus, "A" );
  assert.deepEqual( api.calls[0]!.body, { text: "", session_id: SESSION } );
});

test("POST rejection is swallowed (fire-and-forget) — the event handler does not throw", async () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster( "reject" );
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
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
  const off = wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  off();
  q.setActive( item( "A" ) );
  emitChange( bus, "A" );
  assert.equal( api.calls.length, 0 );
});

test("766bb609: an item carrying voice_id includes it in the POST body (persona voice)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A", { voice_id: "vox-tiberius" } ) );
  emitChange( bus, "A" );
  assert.deepEqual( api.calls[0]!.body, { text: "say A", session_id: SESSION, voice_id: "vox-tiberius" } );
});

test("766bb609: an item WITHOUT voice_id OMITS the key entirely (byte-identical to legacy null-voice body)", () => {
  const bus = createEventBusForTesting();
  const q   = makeActiveReader();
  const api = makePoster();
  wireTtsPlayback( bus, q.reader, api.poster, SESSION );
  q.setActive( item( "A" ) );   // no voice_id
  emitChange( bus, "A" );
  assert.deepEqual( api.calls[0]!.body, { text: "say A", session_id: SESSION } );
  // The key must be ABSENT (not present-with-undefined) so the request is
  // byte-identical to the pre-766bb609 body → server default voice.
  assert.equal( Object.prototype.hasOwnProperty.call( api.calls[0]!.body, "voice_id" ), false );
});
