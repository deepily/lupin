// Phase 3 unit tests — ConnectionStateMachine.
// Verifies the full state × event transition matrix from the design,
// the 100ms grace guard, attempts counter discipline, EventBus emissions
// (connection_state_change / connection_reconnecting / connection_offline /
// connection_online with `payload.transport` per AC#7 source mapping), and
// the backoffDelayMs full-jitter formula.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  backoffDelayMs,
  createConnectionStateMachine,
} from "../../../lupin_app/static/js/multiplexer/transport/ConnectionStateMachine";
import type {
  ConnectionLifecyclePayload,
  ConnectionReconnectingPayload,
  ConnectionState,
  ConnectionStateChangePayload,
  LupinEvent,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

function makeHarness(graceMs?: number) {
  const bus = createEventBusForTesting();
  const stateChanges: LupinEvent<ConnectionStateChangePayload>[] = [];
  const reconnecting: LupinEvent<ConnectionReconnectingPayload>[] = [];
  const offlines    : LupinEvent<ConnectionLifecyclePayload>[] = [];
  const onlines     : LupinEvent<ConnectionLifecyclePayload>[] = [];

  bus.on<ConnectionStateChangePayload>("connection_state_change", (e) => stateChanges.push(e));
  bus.on<ConnectionReconnectingPayload>("connection_reconnecting", (e) => reconnecting.push(e));
  bus.on<ConnectionLifecyclePayload>("connection_offline", (e) => offlines.push(e));
  bus.on<ConnectionLifecyclePayload>("connection_online", (e) => onlines.push(e));

  const csm = createConnectionStateMachine({
    bus,
    transportName : "QueueTransport",
    ...(graceMs !== undefined ? { graceMs } : {}),
  });

  return { bus, csm, stateChanges, reconnecting, offlines, onlines };
}

test("initial state is `connecting`", () => {
  const h = makeHarness();
  assert.equal(h.csm.state, "connecting");
  assert.equal(h.csm.attempts, 0);
});

test("connecting + socket_open → connected; attempts stays 0", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_open" });
  assert.equal(h.csm.state, "connected");
  assert.equal(h.csm.attempts, 0);
});

test("connecting + socket_close → backoff; attempts incremented", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  assert.equal(h.csm.state, "backoff");
  assert.equal(h.csm.attempts, 1);
});

test("connected + socket_close < graceMs → reconnecting (fluke)", () => {
  // Big grace window so `Date.now() - connectedAtMs < graceMs` is true.
  const h = makeHarness(5_000);
  h.csm.send({ type: "socket_open" });
  h.csm.send({ type: "socket_close" });
  assert.equal(h.csm.state, "reconnecting");
  // Fluke path does NOT increment attempts.
  assert.equal(h.csm.attempts, 0);
});

test("connected + socket_close ≥ graceMs → backoff (genuine)", async () => {
  // Tiny grace so the close is treated as genuine immediately.
  const h = makeHarness(1);
  h.csm.send({ type: "socket_open" });
  // Wait a few ms so Date.now() - connectedAtMs >= graceMs.
  await new Promise((r) => setTimeout(r, 5));
  h.csm.send({ type: "socket_close" });
  assert.equal(h.csm.state, "backoff");
  assert.equal(h.csm.attempts, 1);
});

test("reconnecting + socket_open → connected; attempts reset to 0", () => {
  const h = makeHarness(5_000);
  h.csm.send({ type: "socket_open" });
  h.csm.send({ type: "socket_close" });  // → reconnecting
  // Manually drive to backoff first to bump attempts visibly.
  h.csm.send({ type: "socket_close" });  // reconnecting + socket_close → backoff
  assert.ok(h.csm.attempts >= 1);
  h.csm.send({ type: "backoff_expire" }); // → reconnecting
  h.csm.send({ type: "socket_open" });    // → connected; resets
  assert.equal(h.csm.state, "connected");
  assert.equal(h.csm.attempts, 0);
});

test("backoff + backoff_expire → reconnecting", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });   // connecting → backoff
  h.csm.send({ type: "backoff_expire" }); // backoff → reconnecting
  assert.equal(h.csm.state, "reconnecting");
});

test("backoff + page_visible → reconnecting (fast-forward)", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  h.csm.send({ type: "page_visible" });
  assert.equal(h.csm.state, "reconnecting");
});

test("backoff + network_online → reconnecting (fast-forward)", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  h.csm.send({ type: "network_online" });
  assert.equal(h.csm.state, "reconnecting");
});

test("backoff + network_offline → offline; emits connection_offline", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  h.csm.send({ type: "network_offline" });
  assert.equal(h.csm.state, "offline");
  assert.equal(h.offlines.length, 1);
  assert.equal(h.offlines[0]?.payload.transport, "QueueTransport");
});

test("offline + network_online → reconnecting; emits connection_online", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  h.csm.send({ type: "network_offline" });   // → offline
  h.csm.send({ type: "network_online" });    // → reconnecting
  assert.equal(h.csm.state, "reconnecting");
  assert.equal(h.onlines.length, 1);
  assert.equal(h.onlines[0]?.payload.transport, "QueueTransport");
});

test("backoff + max_attempts_reached → failed; restart returns to connecting", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  h.csm.send({ type: "max_attempts_reached" });
  assert.equal(h.csm.state, "failed");
  h.csm.send({ type: "restart" });
  assert.equal(h.csm.state, "connecting");
});

test("connection_reconnecting event fires on entry to reconnecting state", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });    // → backoff
  assert.equal(h.reconnecting.length, 0);
  h.csm.send({ type: "backoff_expire" }); // → reconnecting
  assert.equal(h.reconnecting.length, 1);
  assert.equal(h.reconnecting[0]?.payload.transport, "QueueTransport");
  // Source per AC#7: emitter is "ConnectionStateMachine"; per-transport
  // identification lives in `payload.transport`.
  assert.equal(h.reconnecting[0]?.source, "ConnectionStateMachine");
});

test("connection_state_change fires for every transition with prev/next", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_open" });    // connecting → connected
  h.csm.send({ type: "socket_close" });   // connected → reconnecting/backoff (depends on timing)
  // At least 2 transitions emitted.
  assert.ok(h.stateChanges.length >= 2);
  const first = h.stateChanges[0]!.payload;
  assert.equal(first.prev, "connecting");
  assert.equal(first.state, "connected");
  // All payloads carry transport identifier.
  for (const evt of h.stateChanges) {
    assert.equal(evt.payload.transport, "QueueTransport");
    assert.equal(evt.source, "ConnectionStateMachine");
  }
});

test("subscribe() listener fires on transitions; unsub stops notifications", () => {
  const h = makeHarness();
  const seen: ConnectionState[] = [];
  const unsub = h.csm.subscribe((next) => seen.push(next));

  h.csm.send({ type: "socket_open" });
  unsub();
  h.csm.send({ type: "socket_close" });

  assert.equal(seen.length, 1, "only one transition observed before unsub");
  assert.equal(seen[0], "connected");
});

test("stop() releases the underlying actor; subsequent send() is a no-op", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_open" });
  h.csm.stop();
  // Sending after stop must not throw — XState v5 ignores events on a
  // stopped actor.
  h.csm.send({ type: "socket_close" });
  // State remains as it was before stop.
  assert.equal(h.csm.state, "connected");
});

test("backoffDelayMs returns an integer in [0, min(1000 * 2^n, 30000)]", () => {
  for (const attempt of [0, 1, 2, 3, 5, 10]) {
    for (let i = 0; i < 50; i++) {
      const d = backoffDelayMs(attempt);
      assert.ok(Number.isInteger(d), `attempt=${attempt}: not integer (${d})`);
      assert.ok(d >= 0,             `attempt=${attempt}: below 0 (${d})`);
      const cap = Math.min(1000 * Math.pow(2, attempt), 30_000);
      assert.ok(d <= cap,           `attempt=${attempt}: above cap ${cap} (${d})`);
    }
  }
});

test("graceMs override is honored", async () => {
  // graceMs of 50ms; wait > 50ms before close → backoff path (not reconnecting).
  const h = makeHarness(50);
  h.csm.send({ type: "socket_open" });
  await new Promise((r) => setTimeout(r, 75));
  h.csm.send({ type: "socket_close" });
  assert.equal(h.csm.state, "backoff");
});

test("listener errors do not propagate (consumer-side errors swallowed)", () => {
  const h = makeHarness();
  h.csm.subscribe(() => {
    throw new Error("listener boom");
  });
  // This should not propagate.
  h.csm.send({ type: "socket_open" });
  assert.equal(h.csm.state, "connected");
});

test("matrix: connecting + page_hidden / page_visible / network_online stay connecting", () => {
  const h = makeHarness();
  h.csm.send({ type: "page_hidden" });
  assert.equal(h.csm.state, "connecting");
  h.csm.send({ type: "page_visible" });
  assert.equal(h.csm.state, "connecting");
  h.csm.send({ type: "network_online" });
  assert.equal(h.csm.state, "connecting");
});

test("matrix: connecting + network_offline → offline", () => {
  const h = makeHarness();
  h.csm.send({ type: "network_offline" });
  assert.equal(h.csm.state, "offline");
});

test("matrix: connected + network_offline → offline", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_open" });
  h.csm.send({ type: "network_offline" });
  assert.equal(h.csm.state, "offline");
});

test("matrix: failed + page_visible / network_online stay failed (must restart)", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });
  h.csm.send({ type: "max_attempts_reached" });
  assert.equal(h.csm.state, "failed");
  h.csm.send({ type: "page_visible" });
  assert.equal(h.csm.state, "failed");
  h.csm.send({ type: "network_online" });
  assert.equal(h.csm.state, "failed");
});

// --- permanent_failure (reconnect-parity fix 4450995d) ----------------------

test("connecting + permanent_failure → failed; payload carries reason/code", () => {
  const h = makeHarness();
  h.csm.send({ type: "permanent_failure", reason: "auth-permanent", code: 4001 });
  assert.equal(h.csm.state, "failed");
  // The failed transition surfaces reason/code so the consumer can route.
  const failedEvt = h.stateChanges.find((e) => e.payload.state === "failed");
  assert.ok(failedEvt, "emitted a failed transition");
  assert.equal(failedEvt?.payload.reason, "auth-permanent");
  assert.equal(failedEvt?.payload.code, 4001);
});

test("connected + permanent_failure → failed (mid-session displaced)", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_open" });   // → connected
  h.csm.send({ type: "permanent_failure", reason: "auth-permanent", code: 4002 });
  assert.equal(h.csm.state, "failed");
  const failedEvt = h.stateChanges.find((e) => e.payload.state === "failed");
  assert.equal(failedEvt?.payload.code, 4002);
});

test("backoff + permanent_failure → failed", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_close" });  // connecting → backoff
  h.csm.send({ type: "permanent_failure", reason: "auth-permanent", code: 4003 });
  assert.equal(h.csm.state, "failed");
});

test("non-failed transitions carry NO reason/code", () => {
  const h = makeHarness();
  h.csm.send({ type: "socket_open" });   // → connected (no reason/code)
  const connectedEvt = h.stateChanges.find((e) => e.payload.state === "connected");
  assert.equal(connectedEvt?.payload.reason, undefined);
  assert.equal(connectedEvt?.payload.code, undefined);
});
