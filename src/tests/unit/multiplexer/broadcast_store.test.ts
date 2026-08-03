// Multiplexer Lane C (v0.1.9 focus-bar parity) — BroadcastStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/broadcast_store.test.ts`.
//
// Coverage target: 100% lines/branches/functions on BroadcastStore.ts. Uses the
// REAL in-memory StorageService (integration-faithful) + a stub ApiClient.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createBroadcastStore } from "../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import type {
  BroadcastStore,
  BroadcastRecipient,
  BroadcastSessionsApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import type { StorageService } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";

const SAMPLE: BroadcastRecipient[] = [
  { session_id: "s1", persona_name: "Tiberius", persona_icon: "👑", persona_color: "#fff" },
  { session_id: "s2", persona_name: "Krishna",  persona_icon: "🦚", persona_color: "#1DE9B6" },
];

function freshStore(): { store: BroadcastStore; storage: StorageService } {
  const storage = createStorageServiceForTesting();
  return { store: createBroadcastStore({ storage }), storage };
}

// A stub active-sessions ApiClient. `result` may be a value (resolve) or an
// Error (reject), letting us drive both the success + catch paths.
function stubApi(result: { sessions?: unknown } | Error): BroadcastSessionsApiClient {
  return {
    get<T>(_path: string): Promise<T> {
      if (result instanceof Error) return Promise.reject(result);
      return Promise.resolve(result as T);
    },
  };
}

test("defaults to card-open=true and an empty recipient list", () => {
  const { store } = freshStore();
  assert.equal(store.isCardOpen(), true);
  assert.deepEqual(store.recipients(), []);
});

test("setCardOpen persists across a fresh store over the same storage", () => {
  const { store, storage } = freshStore();
  store.setCardOpen(false);
  assert.equal(store.isCardOpen(), false);
  const reborn = createBroadcastStore({ storage });
  assert.equal(reborn.isCardOpen(), false);
});

test("setCardOpen(true) round-trips too", () => {
  const { store, storage } = freshStore();
  store.setCardOpen(false);
  store.setCardOpen(true);
  const reborn = createBroadcastStore({ storage });
  assert.equal(reborn.isCardOpen(), true);
});

test("corrupt / non-boolean persisted payload falls back to the default", () => {
  const storage = createStorageServiceForTesting();
  // Write a same-key envelope whose payload.open is the wrong type.
  storage.setJSON("broadcast:card-open", { open: "yes" as unknown as boolean }, 1);
  const store = createBroadcastStore({ storage });
  assert.equal(store.isCardOpen(), true);
});

test("hydrate replaces the recipient cache from the active-sessions response", async () => {
  const { store } = freshStore();
  await store.hydrate(stubApi({ sessions: SAMPLE }));
  assert.equal(store.recipients().length, 2);
  assert.equal(store.recipients()[0]?.persona_name, "Tiberius");
});

test("hydrate tolerates a missing / non-array sessions field (→ empty)", async () => {
  const { store } = freshStore();
  await store.hydrate(stubApi({}));
  assert.deepEqual(store.recipients(), []);
});

test("hydrate clears the cache AND re-raises on transport failure", async () => {
  const { store } = freshStore();
  await store.hydrate(stubApi({ sessions: SAMPLE }));
  assert.equal(store.recipients().length, 2);
  await assert.rejects(
    () => store.hydrate(stubApi(new Error("boom"))),
    /boom/,
  );
  assert.deepEqual(store.recipients(), []);
});
