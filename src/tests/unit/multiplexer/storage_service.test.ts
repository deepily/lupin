// Phase 2 unit tests — StorageService.
// Run via `npx tsx --test src/tests/unit/multiplexer/storage_service.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createEventBusForTesting,
  type EventBus,
} from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createStorageServiceForTesting,
  InMemoryStorage,
  type StorageBackend,
} from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type {
  LupinEvent,
  StorageCorruptPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

interface Harness {
  bus     : EventBus;
  backend : InMemoryStorage;
  storage : ReturnType<typeof createStorageServiceForTesting>;
  corruptEvents: LupinEvent<StorageCorruptPayload>[];
}

function makeHarness(): Harness {
  const bus = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting(bus, backend);
  const corruptEvents: LupinEvent<StorageCorruptPayload>[] = [];
  bus.on<StorageCorruptPayload>("storage_corrupt", (e) => corruptEvents.push(e));
  return { bus, backend, storage, corruptEvents };
}

test("setJSON/getJSON round-trips a typed payload", () => {
  const h = makeHarness();
  h.storage.setJSON<{ a: number; b: string }>("foo", { a: 1, b: "two" }, 1);
  const got = h.storage.getJSON<{ a: number; b: string }>("foo", 1);
  assert.deepEqual(got, { a: 1, b: "two" });
});

test("getJSON returns null for missing key without emitting storage_corrupt", () => {
  const h = makeHarness();
  const got = h.storage.getJSON<{ x: number }>("missing", 1);
  assert.equal(got, null);
  assert.equal(h.corruptEvents.length, 0);
});

test("getJSON returns null + emits storage_corrupt on JSON.parse failure (synchronous)", () => {
  const h = makeHarness();
  // Deliberately corrupt the underlying record (simulates external tampering).
  (h.backend as StorageBackend).setItem("lupin:bad", "{not json");
  const got = h.storage.getJSON<{ x: number }>("bad", 1);
  // Synchronous-emission contract: the event MUST already be visible to
  // listeners by the time getJSON returns.
  assert.equal(got, null);
  assert.equal(h.corruptEvents.length, 1);
  assert.equal(h.corruptEvents[0]?.payload.key, "lupin:bad");
  assert.match(h.corruptEvents[0]?.payload.error ?? "", /JSON|Unexpected/i);
  assert.equal(h.corruptEvents[0]?.source, "StorageService");
});

test("getJSON returns null + emits storage_corrupt on schema mismatch", () => {
  const h = makeHarness();
  h.storage.setJSON<{ a: number }>("schema-v1", { a: 1 }, 1);
  const got = h.storage.getJSON<{ a: number }>("schema-v1", 2); // different version
  assert.equal(got, null);
  assert.equal(h.corruptEvents.length, 1);
  assert.match(h.corruptEvents[0]?.payload.error ?? "", /schema/i);
});

test("getJSON returns null + emits storage_corrupt on malformed envelope", () => {
  const h = makeHarness();
  // Plain JSON object without the schemaVersion/payload/ts envelope.
  h.backend.setItem("lupin:plain", JSON.stringify({ a: 1 }));
  const got = h.storage.getJSON<{ a: number }>("plain", 1);
  assert.equal(got, null);
  assert.equal(h.corruptEvents.length, 1);
  assert.match(h.corruptEvents[0]?.payload.error ?? "", /envelope/i);
});

test("storage_corrupt observers attached before getJSON receive the event in the same call (no race)", () => {
  const h = makeHarness();
  let observedDuringNullReturn = false;
  h.bus.on<StorageCorruptPayload>("storage_corrupt", () => {
    observedDuringNullReturn = true;
  });
  h.backend.setItem("lupin:bad", "not json");

  const got = h.storage.getJSON<{ x: number }>("bad", 1);
  // By the time getJSON returns, the listener must already have fired.
  assert.equal(got, null);
  assert.equal(observedDuringNullReturn, true);
});

test("remove deletes the lupin-prefixed entry", () => {
  const h = makeHarness();
  h.storage.setJSON<number>("foo", 42, 1);
  assert.equal(h.backend.getItem("lupin:foo") !== null, true);
  h.storage.remove("foo");
  assert.equal(h.backend.getItem("lupin:foo"), null);
});

test("keys() returns un-prefixed keys, isolating lupin namespace", () => {
  const h = makeHarness();
  // Mix lupin: keys with foreign keys to confirm namespace isolation.
  h.storage.setJSON<number>("a", 1, 1);
  h.storage.setJSON<number>("b", 2, 1);
  h.backend.setItem("other:zzz", "ignored");

  const ks = h.storage.keys();
  assert.deepEqual(ks.sort(), ["a", "b"]);
});

test("keys(prefix) filters by un-prefixed sub-prefix", () => {
  const h = makeHarness();
  h.storage.setJSON<number>("foo:1", 1, 1);
  h.storage.setJSON<number>("foo:2", 2, 1);
  h.storage.setJSON<number>("bar:1", 3, 1);

  const ks = h.storage.keys("foo:");
  assert.deepEqual(ks.sort(), ["foo:1", "foo:2"]);
});

test("getSessionId returns null when not set", () => {
  const h = makeHarness();
  assert.equal(h.storage.getSessionId(), null);
});

test("setSessionId/getSessionId round-trip", () => {
  const h = makeHarness();
  h.storage.setSessionId("wise penguin");
  assert.equal(h.storage.getSessionId(), "wise penguin");
});

test("setSessionId persists generatedAt internally", () => {
  const h = makeHarness();
  const before = Date.now();
  h.storage.setSessionId("wise penguin");
  const after = Date.now();

  // The session ID accessor strips the envelope, but the raw payload is still
  // the SessionIdEnvelope with generatedAt.
  const raw = h.backend.getItem("lupin:session_id");
  assert.ok(raw, "session id row exists");
  const parsed = JSON.parse(raw ?? "{}") as { payload: { generatedAt: number } };
  assert.ok(parsed.payload.generatedAt >= before);
  assert.ok(parsed.payload.generatedAt <= after);
});

test("session id corruption returns null without throwing", () => {
  const h = makeHarness();
  h.backend.setItem("lupin:session_id", "not json");
  assert.equal(h.storage.getSessionId(), null);
  assert.equal(h.corruptEvents.length, 1);
});

// ---------------------------------------------------------------------------
// Coverage backfill — defensive guard branches
// ---------------------------------------------------------------------------

test("getJSON: a literal `null` payload (typeof object && === null) is treated as malformed", () => {
  // Exercises the `v === null` arm of `isEnvelope` (line ~127). JSON.parse("null")
  // returns null, which has typeof "object" but is null — should fall into the
  // malformed-envelope branch.
  const h = makeHarness();
  h.backend.setItem("lupin:foo", "null");
  const got = h.storage.getJSON<unknown>("foo", 1);
  assert.equal(got, null);
  assert.equal(h.corruptEvents.length, 1, "null payload triggered storage_corrupt");
  assert.match(h.corruptEvents[0]!.payload.error, /malformed envelope/);
});

test("createStorageServiceForTesting falls back to a default InMemoryStorage when no backend is provided", () => {
  // Exercises the `backend ?? new InMemoryStorage()` fallback. Calling without
  // a backend MUST still produce a working service.
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  storage.setJSON<number>("k", 7, 1);
  assert.equal(storage.getJSON<number>("k", 1), 7, "default-backed storage round-trips");
});

test("keys() with a backend whose key(i) returns null for some in-range index — null entries skipped", () => {
  // Exercises `if (k === null) continue;` in keys(). InMemoryStorage's key()
  // always returns a string for in-range indices, so we use a custom backend
  // that intentionally returns null for one index.
  const bus = createEventBusForTesting();
  const customBackend: StorageBackend = {
    getItem: () => null,
    setItem: () => { /* noop */ },
    removeItem: () => { /* noop */ },
    key: ( i: number ) => i === 0 ? null : ( i === 1 ? "lupin:visible" : null ),
    length: 2,
  };
  const storage = createStorageServiceForTesting(bus, customBackend);
  // i=0 → null (skipped via continue)
  // i=1 → "lupin:visible" (kept)
  const ks = storage.keys();
  assert.deepEqual(ks, ["visible"]);
});

test("InMemoryStorage.key(): negative index returns null", () => {
  const m = new InMemoryStorage();
  m.setItem("a", "1");
  assert.equal(m.key(-1), null);
});

test("InMemoryStorage.key(): out-of-range positive index returns null", () => {
  const m = new InMemoryStorage();
  m.setItem("a", "1");
  // size=1; index 5 >= size → null.
  assert.equal(m.key(5), null);
});

test("InMemoryStorage.key(): in-range index returns the matching key", () => {
  const m = new InMemoryStorage();
  m.setItem("first", "1");
  m.setItem("second", "2");
  assert.equal(m.key(0), "first");
  assert.equal(m.key(1), "second");
});
