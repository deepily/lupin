// Multiplexer Lane E WP15 — MissedStore unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createMissedStore,
  coerceCount,
  DISMISS_ENDPOINT,
  type MissedApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/MissedStore";
import type {
  LupinEventType,
  StoreMissedChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

let nowSeq = 1000;
const nowFn = (): number => nowSeq++;

interface ApiCtx {
  api      : MissedApiClient;
  calls    : Array<{ path: string; body: unknown }>;
  setResp  : (count: unknown) => void;
  setReject: (b: boolean) => void;
}

function makeApi(initial: unknown = 0): ApiCtx {
  const calls: Array<{ path: string; body: unknown }> = [];
  let respCount: unknown = initial;
  let reject = false;
  const api: MissedApiClient = {
    post: async <T,>(path: string, body: unknown): Promise<T> => {
      calls.push({ path, body });
      if (reject) throw new Error("network down");
      return { undelivered_count: respCount } as T;
    },
  };
  return {
    api,
    calls,
    setResp: (c) => { respCount = c; },
    setReject: (b) => { reject = b; },
  };
}

function makeBus(): { bus: ReturnType<typeof createEventBusForTesting>; events: StoreMissedChangedPayload[] } {
  const bus = createEventBusForTesting();
  const events: StoreMissedChangedPayload[] = [];
  bus.on<StoreMissedChangedPayload>("store_missed_changed", (e) => events.push(e.payload));
  return { bus, events };
}

function emitAuthSuccess(bus: ReturnType<typeof createEventBusForTesting>, payload: unknown): void {
  bus.emit({
    type    : "auth_success" as LupinEventType,
    payload,
    source  : "test",
    ts      : 0,
  });
}

// ---------------------------------------------------------------------------
// coerceCount
// ---------------------------------------------------------------------------

test("coerceCount: positive numbers floor to non-negative integers", () => {
  assert.equal(coerceCount(5), 5);
  assert.equal(coerceCount(3.9), 3);
  assert.equal(coerceCount("7"), 7);
});

test("coerceCount: zero / negative / non-finite / non-numeric → 0", () => {
  assert.equal(coerceCount(0), 0);
  assert.equal(coerceCount(-4), 0);
  assert.equal(coerceCount(NaN), 0);
  assert.equal(coerceCount(Infinity), 0);
  assert.equal(coerceCount(undefined), 0);
  assert.equal(coerceCount("nope"), 0);
});

// ---------------------------------------------------------------------------
// auth_success surfacing
// ---------------------------------------------------------------------------

test("initial count is 0", () => {
  const { bus } = makeBus();
  const { api } = makeApi();
  const store = createMissedStore({ bus, api, nowFn });
  assert.equal(store.count(), 0);
});

test("auth_success with undelivered_count sets count + emits store_missed_changed", () => {
  const { bus, events } = makeBus();
  const { api } = makeApi();
  const store = createMissedStore({ bus, api, nowFn });
  emitAuthSuccess(bus, { undelivered_count: 4 });
  assert.equal(store.count(), 4);
  assert.deepEqual(events, [{ count: 4 }]);
});

test("auth_success with zero count emits {count:0} (renderer stays hidden)", () => {
  const { bus, events } = makeBus();
  const { api } = makeApi();
  const store = createMissedStore({ bus, api, nowFn });
  emitAuthSuccess(bus, { undelivered_count: 0 });
  assert.equal(store.count(), 0);
  assert.deepEqual(events, [{ count: 0 }]);
});

test("auth_success with undefined payload coerces to 0", () => {
  const { bus, events } = makeBus();
  const { api } = makeApi();
  const store = createMissedStore({ bus, api, nowFn });
  emitAuthSuccess(bus, undefined);
  assert.equal(store.count(), 0);
  assert.deepEqual(events, [{ count: 0 }]);
});

// ---------------------------------------------------------------------------
// reset()
// ---------------------------------------------------------------------------

test("reset() with zero count is a no-op (returns 0, no POST)", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  const store = createMissedStore({ bus, api: ctx.api, nowFn });
  const result = await store.reset();
  assert.equal(result, 0);
  assert.equal(ctx.calls.length, 0);
});

test("reset() POSTs the dismiss endpoint and adopts the post-dismiss count", async () => {
  const { bus, events } = makeBus();
  const ctx = makeApi(0); // server returns 0 remaining after dismiss
  const store = createMissedStore({ bus, api: ctx.api, nowFn });
  emitAuthSuccess(bus, { undelivered_count: 6 });
  events.length = 0;

  const result = await store.reset();
  assert.equal(result, 0);
  assert.equal(store.count(), 0);
  assert.equal(ctx.calls.length, 1);
  assert.equal(ctx.calls[0]!.path, DISMISS_ENDPOINT);
  assert.deepEqual(ctx.calls[0]!.body, {});
  assert.deepEqual(events, [{ count: 0 }]);
});

test("reset() adopts a non-zero remaining count when the server reports one", async () => {
  const { bus } = makeBus();
  const ctx = makeApi(2); // partial dismiss leaves 2
  const store = createMissedStore({ bus, api: ctx.api, nowFn });
  emitAuthSuccess(bus, { undelivered_count: 5 });
  const result = await store.reset();
  assert.equal(result, 2);
  assert.equal(store.count(), 2);
});

test("reset() rejects on POST failure and leaves the count unchanged", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setReject(true);
  const store = createMissedStore({ bus, api: ctx.api, nowFn });
  emitAuthSuccess(bus, { undelivered_count: 3 });
  await assert.rejects(() => store.reset(), /network down/);
  assert.equal(store.count(), 3);
});
