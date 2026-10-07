// Row 232df5c1 — ActionRequiredStore reads connection_state_change without looking at
// payload.transport. This drives the REAL store off TWO REAL state machines (QueueTransport
// and AudioTransport) on one real bus, so the payloads are the ones production emits.
// Run: npx tsx --test src/tests/unit/multiplexer/action_required_two_transports.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createConnectionStateMachine } from "../../../lupin_app/static/js/multiplexer/transport/ConnectionStateMachine";
import {
  createActionRequiredStore,
  type ActionRequiredApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";

function makeFakeIntervals() {
  let nextId = 1;
  const map = new Map<number, () => void>();
  return {
    setIntervalFn   : ((cb: () => void): unknown => { const id = nextId++; map.set(id, cb); return id; }) as (cb: () => void, ms: number) => unknown,
    clearIntervalFn : ((id: unknown): void => { map.delete(id as number); }) as (id: unknown) => void,
    pending         : (): number => map.size,
  };
}

function setup() {
  const bus       = createEventBusForTesting();
  const intervals = makeFakeIntervals();
  const api: ActionRequiredApiClient = { post: async () => ({ ok: true }) };
  createActionRequiredStore({
    bus,
    api,
    setIntervalFn   : intervals.setIntervalFn,
    clearIntervalFn : intervals.clearIntervalFn,
    setTimeoutFn    : ((): unknown => 0) as (cb: () => void, ms: number) => unknown,
    clearTimeoutFn  : ((): void => {}) as (id: unknown) => void,
    nowFn           : () => 1_000_000,
  });
  const queue = createConnectionStateMachine({ bus, transportName: "QueueTransport" });
  const audio = createConnectionStateMachine({ bus, transportName: "AudioTransport" });
  // One pending card with a countdown, so there is an interval to freeze and thaw.
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: {
      id_hash: "ar1", message: "Proceed?", response_requested: true, response_type: "yes_no",
      response_options: ["yes", "no"], response_default: "no", timeout_seconds: 30,
      timestamp: new Date(1_000_000).toISOString(),
    } },
    source  : "test",
    ts      : 0,
  });
  // Both sockets come up, then the audio socket loses its connection once.
  queue.send({ type: "socket_open" });
  audio.send({ type: "socket_open" });
  return { bus, intervals, queue, audio };
}

// An audio socket drop that is NOT a network outage: two closes reach backoff, then the socket
// returns. Only connection_state_change carries it, with no connection_offline / connection_online.
function dropAndRestoreAudio(audio: ReturnType<typeof setup>["audio"]): void {
  audio.send({ type: "socket_close" });   // inside the grace window: reconnecting
  audio.send({ type: "socket_close" });   // a second close: backoff
  assert.equal(audio.state, "backoff", "precondition: the audio transport is in backoff");
  audio.send({ type: "backoff_expire" });
  audio.send({ type: "socket_open" });
  assert.equal(audio.state, "connected", "precondition: the audio transport reconnected");
}

test("queue FAILED, audio socket reconnects: the card must stay frozen while the queue socket is down", () => {
  const h = setup();
  assert.equal(h.intervals.pending(), 1, "precondition: the card is counting down");

  h.queue.send({ type: "permanent_failure", reason: "auth-permanent", code: 4001 });
  assert.equal(h.queue.state, "failed", "precondition: the queue transport is failed");
  assert.equal(h.intervals.pending(), 0, "precondition: failed froze the card");

  dropAndRestoreAudio(h.audio);

  assert.equal(h.queue.state, "failed", "the queue transport is still failed");
  assert.equal(h.intervals.pending(), 0, "the card was thawed by the AUDIO reconnect while the queue socket is failed");
});

test("CONTROL: queue backoff then the QUEUE reconnects: the card thaws (the harness can see a thaw)", () => {
  const h = setup();
  h.queue.send({ type: "socket_close" });   // a close inside the grace window is a fluke: reconnecting
  h.queue.send({ type: "socket_close" });   // a second close from reconnecting is a genuine drop: backoff
  assert.equal(h.queue.state, "backoff", "precondition: the queue transport is in backoff");
  assert.equal(h.intervals.pending(), 0, "precondition: the card is frozen");

  h.queue.send({ type: "backoff_expire" });
  h.queue.send({ type: "socket_open" });
  assert.equal(h.queue.state, "connected", "precondition: the queue transport reconnected");
  assert.equal(h.intervals.pending(), 1, "the queue's own reconnect thaws the card");
});

test("audio socket drops while the queue is connected: the countdown should keep running", () => {
  const h = setup();
  h.audio.send({ type: "socket_close" });
  h.audio.send({ type: "socket_close" });
  assert.equal(h.audio.state, "backoff", "precondition: audio is in backoff");
  assert.equal(h.queue.state, "connected", "precondition: queue is connected");
  assert.equal(h.intervals.pending(), 1, "an audio-only drop froze a card whose queue socket is fine");
});

test("queue FAILED, audio goes offline and back (connection_offline / connection_online path): the card must stay frozen", () => {
  const h = setup();
  h.queue.send({ type: "permanent_failure", reason: "auth-permanent", code: 4001 });
  assert.equal(h.intervals.pending(), 0, "precondition: failed froze the card");

  h.audio.send({ type: "network_offline" });
  h.audio.send({ type: "network_online" });
  h.audio.send({ type: "socket_open" });
  assert.equal(h.audio.state, "connected", "precondition: the audio transport is back");
  assert.equal(h.intervals.pending(), 0, "connection_online from the AUDIO transport thawed a card while the queue socket is failed");
});
