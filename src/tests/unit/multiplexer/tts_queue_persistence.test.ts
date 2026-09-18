// Parity A-1c3 (row 3dc5d3a0, 2026-09-18, Chloé 🗼) — the TTS queue survives a
// reload, with its focus-mode fields. Mirrors legacy saveTTSQueueState /
// restoreTTSQueueState (notifications.js:23045-23147, key
// `notifications_tts_queue` at :209):
//   · it saves the WAITING items and the focus fields, and removes the key when
//     there is nothing to keep (:23049-23064)
//   · it resets the paused state on restore, because a reload kills the audio
//     context (:23089-23092)
//   · it auto-exits a focus whose prompt no longer exists (:23104-23115)
//   · it starts the next item when not focused (:23139-23143)
// Legacy restores after the Action Required prompts (:596-599), so the focus
// check reads a restored Action Required store.
//
// Backend per spec ruling 3: StorageService, injected `| null`, stored as `lupin:ttsQueue`.
// A reload is not unit-reachable, so this follows action_required_persistence.test.ts:
// a writer store, then a FRESH reader store over the same backend.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createStorageServiceForTesting,
  InMemoryStorage,
  type StorageBackend,
} from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  createTtsQueueStore,
  TTS_STORAGE_KEY,
  TTS_STORAGE_SCHEMA,
  type TtsQueueStore,
} from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { AR_STORAGE_KEY, AR_STORAGE_SCHEMA } from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import { wireTtsPlayback } from "../../../lupin_app/static/js/multiplexer/wireTtsPlayback";
import type {
  AudioPlaybackState,
  StoreActionRequiredChangedPayload,
  StoreAudioStateChangePayload,
  TransportReadyPayload,
  TtsQueueItem,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

const FULLKEY = `lupin:${ TTS_STORAGE_KEY }`;

type Bus = ReturnType<typeof createEventBusForTesting>;

interface Opened {
  bus   : Bus;
  store : TtsQueueStore;
  posts : string[];
}

/** One store over `backend`; `backend` is what survives the "reload". */
function open(
  backend : StorageBackend,
  opts    : { persist?: boolean; focusItemIsLive?: (idHash: string) => boolean } = {},
): Opened {
  const bus   = createEventBusForTesting();
  const store = createTtsQueueStore({
    bus,
    nowFn           : () => 0,
    storage         : opts.persist === false ? null : createStorageServiceForTesting(bus, backend),
    focusItemIsLive : opts.focusItemIsLive,
  });
  const posts: string[] = [];
  wireTtsPlayback(bus, store, { post: (_url: string, body: unknown) => {
    posts.push((body as { text: string }).text);
    return Promise.resolve(undefined as never);
  } }, "audio-session");
  return { bus, store, posts };
}

function item(idHash: string, over: Partial<TtsQueueItem> = {}): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${ idHash }`, ...over };
}

function audio(bus: Bus, state: AudioPlaybackState): void {
  bus.emit<StoreAudioStateChangePayload>({
    type: "store_audio_state_change", payload: { state, prev: "playing" }, source: "test", ts: 0,
  });
}

function ended(bus: Bus): void {
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
}

function ready(bus: Bus, transport: string): void {
  bus.emit<TransportReadyPayload>({ type: "transport_ready", payload: { transport }, source: transport, ts: 0 });
}

function responded(bus: Bus, idHash: string): void {
  bus.emit<StoreActionRequiredChangedPayload>({
    type: "store_action_required_changed", payload: { changeKind: "responded", id_hash: idHash }, source: "test", ts: 0,
  });
}

function pendingIds(store: TtsQueueStore): string[] {
  return store.pending().map((it) => it.id_hash);
}

function saved(backend: StorageBackend): Record<string, unknown> {
  const raw = backend.getItem(FULLKEY);
  assert.ok(raw !== null, `nothing was saved under ${ FULLKEY }`);
  const envelope = JSON.parse(raw) as { schemaVersion: number; payload: Record<string, unknown> };
  assert.equal(envelope.schemaVersion, TTS_STORAGE_SCHEMA);
  return envelope.payload;
}

// A writer whose "ar" item finished speaking and entered focus, with "b" waiting.
function focusedWriter(backend: StorageBackend): Opened {
  const w = open(backend);
  w.store.enqueue(item("ar", { action_required: true }));
  w.store.enqueue(item("b"));
  audio(w.bus, "playing");
  audio(w.bus, "ended");
  ended(w.bus);
  assert.equal(w.store.focusMode(), true, "precondition: the writer is focused");
  return w;
}

// ---------------------------------------------------------------------------
// Write → fresh reader → read
// ---------------------------------------------------------------------------

test("A-1c3 the waiting items survive a reload in order; the item that was speaking does not (legacy saves ttsQueue only)", () => {
  const backend = new InMemoryStorage();
  const w = open(backend);
  w.store.enqueue(item("a"));
  w.store.enqueue(item("b"));
  w.store.enqueue(item("c"));
  assert.deepEqual((saved(backend)["pending"] as TtsQueueItem[]).map((it) => it.id_hash), [ "b", "c" ]);
  assert.equal(saved(backend)["focusModeActive"], false);

  const r = open(backend);
  assert.deepEqual(pendingIds(r.store), [ "b", "c" ]);
  assert.equal(r.store.current(), null, "nothing speaks before the audio socket is up");
});

test("A-1c3 the restored head starts when the AUDIO socket is ready, and its speech is requested once", () => {
  const backend = new InMemoryStorage();
  const w = open(backend);
  w.store.enqueue(item("a"));
  w.store.enqueue(item("b"));
  w.store.enqueue(item("c"));

  const r = open(backend);
  ready(r.bus, "QueueTransport");
  assert.equal(r.store.current(), null, "the queue socket is not the audio socket");
  assert.deepEqual(r.posts, []);

  ready(r.bus, "AudioTransport");
  assert.equal(r.store.current(), "b");
  assert.deepEqual(pendingIds(r.store), [ "c" ]);
  assert.deepEqual(r.posts, [ "say b" ]);

  ready(r.bus, "AudioTransport");   // a reconnect is not a second restore
  assert.equal(r.store.current(), "b");
  assert.deepEqual(r.posts, [ "say b" ]);
});

test("A-1c3 an item arriving before the audio socket is up waits BEHIND the restored items (FIFO)", () => {
  const backend = new InMemoryStorage();
  const w = open(backend);
  w.store.enqueue(item("a"));
  w.store.enqueue(item("b"));

  const r = open(backend);
  r.store.enqueue(item("new"));
  assert.equal(r.store.current(), null);
  assert.deepEqual(pendingIds(r.store), [ "b", "new" ]);

  ready(r.bus, "AudioTransport");
  assert.equal(r.store.current(), "b");
  assert.deepEqual(pendingIds(r.store), [ "new" ]);
});

test("A-1c3 the paused state is reset on restore: a completion after the reload advances instead of being held", () => {
  const backend = new InMemoryStorage();
  const w = open(backend);
  w.store.enqueue(item("a"));
  w.store.enqueue(item("b"));
  w.store.enqueue(item("c"));
  audio(w.bus, "playing");
  audio(w.bus, "paused");
  ended(w.bus);
  assert.equal(w.store.current(), "a", "precondition: the writer held its completion");
  assert.equal("paused" in saved(backend), false, "nothing about a pause is saved");

  const r = open(backend);
  ready(r.bus, "AudioTransport");
  audio(r.bus, "playing");
  ended(r.bus);
  assert.equal(r.store.current(), "c");
});

test("A-1c3 a live focus survives: the reader is focused and holds its waiting item until the prompt is answered", () => {
  const backend = new InMemoryStorage();
  focusedWriter(backend);
  assert.equal(saved(backend)["focusModeActive"], true);
  assert.equal(saved(backend)["focusModeNotificationId"], "ar");

  const r = open(backend, { focusItemIsLive: (id) => id === "ar" });
  assert.equal(r.store.focusMode(), true);
  assert.deepEqual(pendingIds(r.store), [ "b" ]);

  ready(r.bus, "AudioTransport");
  assert.equal(r.store.current(), null, "focus holds the roll after the reload too");

  responded(r.bus, "ar");
  assert.equal(r.store.focusMode(), false);
  assert.equal(r.store.current(), "b");
});

test("A-1c3 a STALE focus auto-exits on restore, the save is rewritten, and the waiting item starts", () => {
  const backend = new InMemoryStorage();
  focusedWriter(backend);

  const r = open(backend, { focusItemIsLive: () => false });
  assert.equal(r.store.focusMode(), false);
  assert.equal(saved(backend)["focusModeActive"], false, "the stale focus is not written back");
  assert.equal(saved(backend)["focusModeNotificationId"], null);

  ready(r.bus, "AudioTransport");
  assert.equal(r.store.current(), "b");
});

test("A-1c3 with no liveness check to ask, a restored focus is treated as stale rather than holding the queue forever", () => {
  const backend = new InMemoryStorage();
  focusedWriter(backend);
  const r = open(backend);
  assert.equal(r.store.focusMode(), false);
});

test("A-1c3 a focus with nothing waiting still survives, and an empty queue with no focus removes the key", () => {
  const backend = new InMemoryStorage();
  const w = open(backend);
  w.store.enqueue(item("ar", { action_required: true }));
  audio(w.bus, "playing");
  audio(w.bus, "ended");
  ended(w.bus);
  assert.deepEqual(saved(backend)["pending"], []);
  assert.equal(saved(backend)["focusModeActive"], true);

  w.store.clear();
  assert.equal(backend.getItem(FULLKEY), null, "legacy removes the key when there is nothing to keep (:23049-23051)");
  const r = open(backend);
  assert.equal(r.store.focusMode(), false);
  ready(r.bus, "AudioTransport");
  assert.equal(r.store.current(), null);
});

test("A-1c3 clearing the restored queue before the audio socket is up leaves nothing to start", () => {
  const backend = new InMemoryStorage();
  const w = open(backend);
  w.store.enqueue(item("a"));
  w.store.enqueue(item("b"));

  const r = open(backend);
  r.store.clear();
  r.store.enqueue(item("new"));
  assert.equal(r.store.current(), "new", "after a clear, a new arrival speaks at once as usual");
  ready(r.bus, "AudioTransport");
  assert.equal(r.store.current(), "new");
});

test("A-1c3 no storage, a corrupt save and a malformed payload each restore an empty queue without throwing", () => {
  const off = open(new InMemoryStorage(), { persist: false });
  off.store.enqueue(item("a"));
  off.store.enqueue(item("b"));
  assert.deepEqual(pendingIds(off.store), [ "b" ]);

  const corrupt = new InMemoryStorage();
  corrupt.setItem(FULLKEY, "{not json");
  assert.deepEqual(pendingIds(open(corrupt).store), []);

  const oldSchema = new InMemoryStorage();
  oldSchema.setItem(FULLKEY, JSON.stringify({ schemaVersion: 0, payload: { pending: [ item("x") ] }, ts: 0 }));
  assert.deepEqual(pendingIds(open(oldSchema).store), []);

  const malformed = new InMemoryStorage();
  malformed.setItem(FULLKEY, JSON.stringify({ schemaVersion: TTS_STORAGE_SCHEMA, payload: { pending: "b" }, ts: 0 }));
  assert.deepEqual(pendingIds(open(malformed).store), []);
});

test("A-1c3 a storage that refuses writes does not stop the queue", () => {
  const refusing: StorageBackend = Object.assign(new InMemoryStorage(), {
    setItem   : () => { throw new Error("QuotaExceededError"); },
    removeItem: () => { throw new Error("SecurityError"); },
  });
  const s = open(refusing);
  s.store.enqueue(item("a"));
  s.store.enqueue(item("b"));
  s.store.clear();
  assert.equal(s.store.current(), null);
});

// ---------------------------------------------------------------------------
// Assembled: createStores wires the focus check to the restored Action Required store
// ---------------------------------------------------------------------------

function arPrompt(idHash: string): Record<string, unknown> {
  return { id_hash: idHash, prompt: "approve?", response_type: "yes_no", questions: [],
           expires_at: null, timeout_seconds: 60, state: "pending" };
}

function assembled(backend: StorageBackend): TtsQueueStore {
  const bus = createEventBusForTesting();
  return createStores({
    eventBus : bus,
    storage  : createStorageServiceForTesting(bus, backend),
    api      : { post: async () => ({}) as never, get: async <T,>(): Promise<T> => ({} as T) },
  }).ttsQueue;
}

test("A-1c3 assembled: a focus whose prompt the Action Required store restored survives", () => {
  const backend = new InMemoryStorage();
  focusedWriter(backend);
  backend.setItem(`lupin:${ AR_STORAGE_KEY }`, JSON.stringify({
    schemaVersion: AR_STORAGE_SCHEMA, payload: { prompts: [ arPrompt("ar") ] }, ts: 0,
  }));
  assert.equal(assembled(backend).focusMode(), true);
});

test("A-1c3 assembled: a focus whose prompt the Action Required store did not restore auto-exits", () => {
  const backend = new InMemoryStorage();
  focusedWriter(backend);
  backend.setItem(`lupin:${ AR_STORAGE_KEY }`, JSON.stringify({
    schemaVersion: AR_STORAGE_SCHEMA, payload: { prompts: [ arPrompt("someone-else") ] }, ts: 0,
  }));
  const store = assembled(backend);
  assert.equal(store.focusMode(), false);
  assert.deepEqual(pendingIds(store), [ "b" ]);
});
