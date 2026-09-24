// B-1 review finding (María 🌸, 2026-09-23) — the "answer is spoken" fix is wired ONLY in
// `stores/index.ts`, and that file is `/* c8 ignore */` from its first line to its last.
//
// 🔴 MEASURED, NOT ARGUED. Deleting `ttsQueue : ttsQueue` from the `createQaStore` call in
// stores/index.ts left 150 tests passing across every file that names `createStores` or
// `tts_job_request` — tts_queue_persistence, tts_failure_releases_slot, tts_error_frame_releases_slot,
// action_required_tts_deferral, stores_integration, notifications_list_renderer and qa_store.
// The store's OWN suite cannot catch it: it constructs QaStore directly and passes a stub
// enqueuer, so it proves the store speaks when handed a queue and says nothing about whether
// the assembled app hands it one. The pane would have gone back to answering in silence and
// the whole suite would have stayed green.
//
// ⚠️ AND THE BARREL'S c8-ignore IS WHY NO COVERAGE NUMBER WOULD HAVE SHOWN IT EITHER. The
// wiring is three closures in a file the mandate does not measure, so "100% on QaStore.ts"
// and "the answer is spoken in production" are independent facts. This file is the second one.
//
// These enter at the assembled `createStores`, not at the class: the defect is a missing
// argument at the construction site, and a test that supplies the argument itself cannot see it.
//
// Legacy: notifications.js handleJobCompletion writes the line AND calls playTTS with
// getVoiceIdForSender(sender_id) — notifications.js:4035-4041.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_assembled_qa_store_speaks_its_answer.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import { QA_EMPTY_RESPONSE } from "../../../lupin_app/static/js/multiplexer/stores/QaStore";
import type { TtsJobRequestPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

// createStores wants one object satisfying five client interfaces. Nothing here reaches the
// network: the Q&A path under test is bus-driven end to end.
const API = {
  get  : async <T>() => ( {} as T ),
  post : async <T>() => ( {} as T ),
  patch: async <T>() => ( {} as T ),
};

function assembled() {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the five-interface intersection; every call here is stubbed.
  const stores  = createStores( { eventBus: bus, storage, api: API as any } );
  return { bus, stores };
}

/** The server frame a finished job arrives on. */
function jobCompleted( bus: Bus, payload: TtsJobRequestPayload ): void {
  bus.emit( { type: "tts_job_request", payload, source: "test", ts: 0 } );
}

/** Give `sender_id` a persona voice the way the server does — a live assignment frame. */
function assignVoice( bus: Bus, senderId: string, voiceId: string ): void {
  bus.emit( {
    type    : "notification_queue_update",
    payload : { notification: {
      type          : "voice_persona_assigned",
      sender_id     : senderId,
      timestamp     : "2026-09-23T20:00:00Z",
      voice_persona : { name: "Rio", voice_id: voiceId, icon: "🎤", color: "#28a745" },
    } },
    source : "test",
    ts     : 0,
  } );
}

test( "positive control: the instrument can see an empty queue, and the frame is one this app routes", () => {
  const { bus, stores } = assembled();
  assert.equal( stores.ttsQueue.current(), null, "the queue is not empty before the frame" );
  assert.equal( stores.qa.responseText(), QA_EMPTY_RESPONSE, "the response pane does not start on its placeholder" );
  jobCompleted( bus, { text: "anything", id: "probe" } );
  assert.notEqual( stores.qa.responseText(), QA_EMPTY_RESPONSE,
    "the frame reached QaStore at all — if this fails, nothing below means anything" );
} );

test( "the assembled app SPEAKS a finished job's answer, it does not only write it", () => {
  const { bus, stores } = assembled();
  jobCompleted( bus, { text: "The answer is 42", id: "j1" } );

  // The written half — the half that already worked before the review finding.
  assert.equal( stores.qa.responseText(), "Job completed: The answer is 42" );

  // The spoken half — the wiring this file exists for.
  const spoken = stores.ttsQueue.activeItem();
  assert.notEqual( spoken, null, "the answer reached the response pane but NOT the TTS queue — the pane answers in silence" );
  assert.equal( spoken!.ttsText, "The answer is 42" );
  assert.equal( spoken!.id_hash, "qa-j1" );
} );

test( "it speaks in the sender's OWN persona voice, resolved through the assembled SenderStore", () => {
  const { bus, stores } = assembled();
  assignVoice( bus, "rio@x", "voice-rio" );
  jobCompleted( bus, { text: "Done", id: "j2", sender_id: "rio@x" } );

  const spoken = stores.ttsQueue.activeItem();
  assert.notEqual( spoken, null, "nothing was enqueued" );
  assert.equal( spoken!.voice_id, "voice-rio",
    "the voiceFor closure is not reading the assembled SenderStore — the answer speaks in the wrong voice" );
} );

test( "an unknown sender omits the voice key rather than inventing one — the server's default voice", () => {
  const { bus, stores } = assembled();
  jobCompleted( bus, { text: "Done", id: "j3", sender_id: "nobody@x" } );

  const spoken = stores.ttsQueue.activeItem();
  assert.notEqual( spoken, null, "nothing was enqueued" );
  assert.equal( "voice_id" in spoken!, false,
    "an absent persona must OMIT voice_id; sending undefined or empty is not legacy's null-voice_id case" );
} );

test( "a job with no text still speaks — the queue never takes an empty utterance", () => {
  const { bus, stores } = assembled();
  jobCompleted( bus, { text: "", id: "j4" } );

  assert.equal( stores.qa.responseText(), "Job completed: No text provided" );
  const spoken = stores.ttsQueue.activeItem();
  assert.notEqual( spoken, null, "an empty-text job was written but not spoken" );
  assert.equal( spoken!.ttsText, "Job completed", "the spoken fallback differs from the written one, by design" );
} );

test( "two finished jobs QUEUE — the second waits, it does not overlap or replace the first", () => {
  const { bus, stores } = assembled();
  jobCompleted( bus, { text: "First", id: "j5" } );
  jobCompleted( bus, { text: "Second", id: "j6" } );

  // The deliberate divergence from legacy's immediate POST (Mr. Radio 🦉's ruling, 2026-09-23):
  // ordering beats immediacy, because overlapping audio is worse than a short delay.
  assert.equal( stores.ttsQueue.activeItem()!.ttsText, "First", "the second answer displaced the first" );
  assert.deepEqual( stores.ttsQueue.pending().map( ( i ) => i.ttsText ), [ "Second" ],
    "the second answer did not queue behind the first" );
} );
