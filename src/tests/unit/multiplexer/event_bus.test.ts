// Phase 2 unit tests — EventBus.
// Run via `npx tsx --test src/tests/unit/multiplexer/event_bus.test.ts`.
// Coverage gate: ≥ 90% per Phase 2 AC#4 (verified via `c8`).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type {
  LupinEvent,
  LupinEventType,
  ListenerErrorPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

function evt<T>(type: LupinEventType, payload: T): LupinEvent<T> {
  return { type, payload, source: "test", ts: 1234 };
}

test("on/emit delivers events to subscribers", () => {
  const bus = createEventBusForTesting();
  const received: Array<LupinEvent<{ n: number }>> = [];
  bus.on<{ n: number }>("auth_state_change", (e) => received.push(e));

  bus.emit(evt("auth_state_change", { n: 1 }));
  bus.emit(evt("auth_state_change", { n: 2 }));

  assert.equal(received.length, 2);
  assert.equal(received[0]?.payload.n, 1);
  assert.equal(received[1]?.payload.n, 2);
  assert.equal(received[0]?.source, "test");
  assert.equal(received[0]?.ts, 1234);
});

test("emit only delivers to listeners of the matching type", () => {
  const bus = createEventBusForTesting();
  const auth: LupinEvent<unknown>[] = [];
  const storage: LupinEvent<unknown>[] = [];
  bus.on("auth_state_change", (e) => auth.push(e));
  bus.on("storage_corrupt", (e) => storage.push(e));

  bus.emit(evt("auth_state_change", { state: "ready" }));

  assert.equal(auth.length, 1);
  assert.equal(storage.length, 0);
});

test("on returns an unsubscribe function that detaches the listener", () => {
  const bus = createEventBusForTesting();
  const received: LupinEvent<unknown>[] = [];
  const unsubscribe = bus.on("auth_state_change", (e) => received.push(e));

  bus.emit(evt("auth_state_change", { state: "ready" }));
  unsubscribe();
  bus.emit(evt("auth_state_change", { state: "expired" }));

  assert.equal(received.length, 1);
});

test("off removes a previously registered listener", () => {
  const bus = createEventBusForTesting();
  const received: LupinEvent<unknown>[] = [];
  const listener = (e: LupinEvent<unknown>): void => {
    received.push(e);
  };
  bus.on("refresh_started", listener);

  bus.emit(evt("refresh_started", { reason: "expired" }));
  bus.off("refresh_started", listener);
  bus.emit(evt("refresh_started", { reason: "invalidated" }));

  assert.equal(received.length, 1);
});

test("off on an unknown type or listener is a no-op", () => {
  const bus = createEventBusForTesting();
  const noop = (): void => {
    /* no-op */
  };
  // No throw expected.
  bus.off("auth_state_change", noop);
  bus.on("auth_state_change", noop);
  // Removing a different listener for the same type — no-op.
  bus.off("auth_state_change", () => {
    /* different ref */
  });
});

test("listener throwing does NOT break sibling listeners", () => {
  const bus = createEventBusForTesting();
  const sibling: LupinEvent<unknown>[] = [];
  bus.on("auth_state_change", () => {
    throw new Error("first listener boom");
  });
  bus.on("auth_state_change", (e) => sibling.push(e));

  bus.emit(evt("auth_state_change", { state: "ready" }));

  assert.equal(sibling.length, 1, "sibling listener still received the event");
});

test("listener throwing emits a listener_error event referencing the original", () => {
  const bus = createEventBusForTesting();
  const errors: LupinEvent<ListenerErrorPayload>[] = [];
  bus.on<ListenerErrorPayload>("listener_error", (e) => errors.push(e));
  bus.on("auth_state_change", () => {
    throw new Error("kaboom");
  });

  const original = evt("auth_state_change", { state: "ready" as const });
  bus.emit(original);

  assert.equal(errors.length, 1);
  assert.equal(errors[0]?.payload.originalEvent.type, "auth_state_change");
  assert.match(errors[0]?.payload.error ?? "", /kaboom/);
  assert.equal(errors[0]?.source, "EventBus");
});

test("listener throwing a non-Error (string) — coerced via String(err) into the listener_error payload", () => {
  // Exercises the `: String(err)` arm of `err instanceof Error ? err.message : String(err)`
  // in handleListenerError().
  const bus = createEventBusForTesting();
  const errors: LupinEvent<ListenerErrorPayload>[] = [];
  bus.on<ListenerErrorPayload>("listener_error", (e) => errors.push(e));
  bus.on("auth_state_change", () => {
    /* eslint-disable-next-line @typescript-eslint/no-throw-literal */
    throw "raw-string-payload";
  });
  bus.emit(evt("auth_state_change", { state: "ready" as const }));
  assert.equal(errors.length, 1);
  assert.equal(errors[0]?.payload.error, "raw-string-payload");
});

test("listener_error listeners that themselves throw do NOT recurse", () => {
  const bus = createEventBusForTesting();
  // A listener_error subscriber that itself throws would otherwise emit another
  // listener_error → infinite recursion.
  bus.on("listener_error", () => {
    throw new Error("error-handler boom");
  });
  bus.on("auth_state_change", () => {
    throw new Error("origin boom");
  });

  // Should NOT stack-overflow.
  bus.emit(evt("auth_state_change", { state: "ready" as const }));
  assert.ok(true, "emit returned without recursive blow-up");
});

test("event envelope shape is preserved end-to-end", () => {
  const bus = createEventBusForTesting();
  let observed: LupinEvent<unknown> | null = null;
  bus.on("storage_corrupt", (e) => {
    observed = e;
  });

  const original: LupinEvent<{ key: string }> = {
    type    : "storage_corrupt",
    payload : { key: "lupin:foo" },
    source  : "StorageService",
    ts      : 999,
  };
  bus.emit(original);

  // Cast safely — the listener actually fired so observed is populated.
  const got = observed as unknown as LupinEvent<{ key: string }> | null;
  assert.ok(got, "listener was invoked");
  assert.equal(got?.type, "storage_corrupt");
  assert.equal(got?.payload.key, "lupin:foo");
  assert.equal(got?.source, "StorageService");
  assert.equal(got?.ts, 999);
});
