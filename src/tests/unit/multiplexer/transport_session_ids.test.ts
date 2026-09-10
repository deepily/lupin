// Row d2b1b59a, FINDING 5 — the multiplexer's queue and audio sockets must not
// share a session id.
//
// Measured 2026-09-10: the multiplexer opened /ws/queue and /ws/audio under ONE
// id, the server keeps one socket + one subscription list per id, and the audio
// socket's registration overwrote the queue's. Every notification to the tab —
// the P0 petition asks and every ordinary ask — was declined "not subscribed".
// Write-up: src/rnd/2026.09.10-multiplexer-misses-petition-ask.md
//
// These tests drive the REAL StorageService over an in-memory backend, so a
// persisted id is read back through the same accessor boot reads on reload.
//
// Run: npx tsx --test src/tests/unit/multiplexer/transport_session_ids.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createStorageServiceForTesting,
  InMemoryStorage,
} from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  resolveTransportSessionIds,
  MAX_AUDIO_ID_ATTEMPTS,
} from "../../../lupin_app/static/js/multiplexer/shared/transportSessionIds";

function makeStorage() {
  return createStorageServiceForTesting(createEventBusForTesting(), new InMemoryStorage());
}

// A generator that hands out a fixed script of ids and counts its calls.
function scripted(ids: string[]) {
  const gen = { calls: 0, next: (): string => "" };
  gen.next = () => {
    const id = ids[Math.min(gen.calls, ids.length - 1)] as string;
    gen.calls++;
    return id;
  };
  return gen;
}

test("a fresh tab gets two DIFFERENT ids, and both are persisted", () => {
  const storage = makeStorage();
  const gen     = scripted(["calm dolphin", "wise owl"]);

  const ids = resolveTransportSessionIds(storage, gen.next);

  assert.equal(ids.queueSessionId, "calm dolphin");
  assert.equal(ids.audioSessionId, "wise owl");
  assert.notEqual(ids.queueSessionId, ids.audioSessionId);
  assert.equal(storage.getSessionId(), "calm dolphin");
  assert.equal(storage.getAudioSessionId(), "wise owl");
});

test("a reload reuses both stored ids without generating", () => {
  const storage = makeStorage();
  resolveTransportSessionIds(storage, scripted(["calm dolphin", "wise owl"]).next);

  const gen = scripted(["bold tiger"]);
  const ids = resolveTransportSessionIds(storage, gen.next);

  assert.deepEqual(ids, { queueSessionId: "calm dolphin", audioSessionId: "wise owl" });
  assert.equal(gen.calls, 0);
});

test("a tab from before the fix keeps its queue id and gains a distinct audio id", () => {
  // Pre-fix storage held ONE id, used for both sockets.
  const storage = makeStorage();
  storage.setSessionId("calm dolphin");
  const gen = scripted(["wise owl"]);

  const ids = resolveTransportSessionIds(storage, gen.next);

  assert.deepEqual(ids, { queueSessionId: "calm dolphin", audioSessionId: "wise owl" });
  assert.equal(storage.getAudioSessionId(), "wise owl");
  assert.equal(gen.calls, 1);
});

test("a stored audio id EQUAL to the queue id is replaced, not reused", () => {
  const storage = makeStorage();
  storage.setSessionId("calm dolphin");
  storage.setAudioSessionId("calm dolphin");
  const gen = scripted(["wise owl"]);

  const ids = resolveTransportSessionIds(storage, gen.next);

  assert.equal(ids.audioSessionId, "wise owl");
  assert.equal(storage.getAudioSessionId(), "wise owl");
});

test("a stored audio id that already differs is reused", () => {
  const storage = makeStorage();
  storage.setSessionId("calm dolphin");
  storage.setAudioSessionId("wise owl");
  const gen = scripted(["bold tiger"]);

  const ids = resolveTransportSessionIds(storage, gen.next);

  assert.equal(ids.audioSessionId, "wise owl");
  assert.equal(gen.calls, 0);
});

test("a generator that repeats the queue id is drawn again until it differs", () => {
  // 100 combinations means a collision is ordinary: the first draw can land on
  // the queue id, and taking it would reproduce the shared-id defect.
  const storage = makeStorage();
  const gen     = scripted(["calm dolphin", "calm dolphin", "calm dolphin", "wise owl"]);

  const ids = resolveTransportSessionIds(storage, gen.next);

  assert.deepEqual(ids, { queueSessionId: "calm dolphin", audioSessionId: "wise owl" });
  assert.equal(gen.calls, 4);
});

test("a generator that can only return the queue id fails loud instead of sharing it", () => {
  const storage = makeStorage();
  const gen     = scripted(["calm dolphin"]);

  assert.throws(
    () => resolveTransportSessionIds(storage, gen.next),
    /could not draw an audio session id distinct from the queue id "calm dolphin" in 32 attempts/,
  );
  assert.equal(MAX_AUDIO_ID_ATTEMPTS, 32);
  assert.equal(gen.calls, 1 + MAX_AUDIO_ID_ATTEMPTS);
  assert.equal(storage.getAudioSessionId(), null, "nothing shared was persisted");
});
