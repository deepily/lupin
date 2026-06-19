// Phase 2 unit tests — BroadcastChannel wrapper.
// Run via `npx tsx --test src/tests/unit/multiplexer/broadcast.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createEventBusForTesting,
  type EventBus,
} from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createBroadcastWrapper,
  BROADCAST_WHITELIST,
  type BroadcastChannelLike,
} from "../../../lupin_app/static/js/multiplexer/shared/broadcast";
import type {
  LupinEvent,
  LupinEventType,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// In-process BroadcastChannel mock. All instances created with the same
// `name` see each other's messages (mimicking the cross-tab semantic) but
// NOT their own (per the BroadcastChannel spec).
const channelRegistry = new Map<string, Set<MockChannel>>();

class MockChannel implements BroadcastChannelLike {
  onmessage: ((evt: MessageEvent<unknown>) => void) | null = null;
  private closed = false;

  constructor(public readonly name: string) {
    let peers = channelRegistry.get(name);
    if (!peers) {
      peers = new Set();
      channelRegistry.set(name, peers);
    }
    peers.add(this);
  }

  postMessage(data: unknown): void {
    if (this.closed) return;
    const peers = channelRegistry.get(this.name);
    if (!peers) return;
    for (const peer of peers) {
      if (peer === this) continue;        // never echo to self
      if (peer.closed) continue;
      const evt = new MessageEvent("message", { data });
      peer.onmessage?.(evt);
    }
  }

  close(): void {
    this.closed = true;
    channelRegistry.get(this.name)?.delete(this);
  }
}

function makeTab() {
  const bus = createEventBusForTesting();
  const channelFactory = (name: string): BroadcastChannelLike => new MockChannel(name);
  const wrapper = createBroadcastWrapper({ bus, channelFactory });
  wrapper.start();
  return { bus, wrapper };
}

function evt<T>(
  type: LupinEventType,
  payload: T,
  source: string,
): LupinEvent<T> {
  return { type, payload, source, ts: Date.now() };
}

test("event emitted in tab A reaches tab B exactly once", () => {
  channelRegistry.clear();
  const tabA = makeTab();
  const tabB = makeTab();

  const tabBReceived: LupinEvent<unknown>[] = [];
  tabB.bus.on("auth_state_change", (e) => tabBReceived.push(e));

  tabA.bus.emit(evt("auth_state_change", { state: "ready" }, "AuthManager"));

  assert.equal(tabBReceived.length, 1);
  assert.equal(tabBReceived[0]?.payload && (tabBReceived[0]?.payload as { state: string }).state, "ready");
  assert.equal(tabBReceived[0]?.source, "broadcast", "marker present on inbound");

  tabA.wrapper.stop();
  tabB.wrapper.stop();
});

test("event from tab A does NOT echo back to tab A (loop prevention)", () => {
  channelRegistry.clear();
  const tabA = makeTab();
  const tabB = makeTab();

  const tabAReceived: LupinEvent<unknown>[] = [];
  tabA.bus.on("auth_state_change", (e) => tabAReceived.push(e));

  tabA.bus.emit(evt("auth_state_change", { state: "ready" }, "AuthManager"));

  // Local listener fires once for the local emit; broadcast must NOT echo
  // back through tab B → tab A.
  assert.equal(tabAReceived.length, 1);
  assert.equal(tabAReceived[0]?.source, "AuthManager");

  tabA.wrapper.stop();
  tabB.wrapper.stop();
});

test("non-whitelisted event is silently NOT replicated", () => {
  channelRegistry.clear();
  const tabA = makeTab();
  const tabB = makeTab();

  const tabBReceived: LupinEvent<unknown>[] = [];
  tabB.bus.on("listener_error", (e) => tabBReceived.push(e));

  // listener_error is not in the whitelist.
  tabA.bus.emit(evt("listener_error", { msg: "nope" }, "EventBus"));

  assert.equal(tabBReceived.length, 0);

  tabA.wrapper.stop();
  tabB.wrapper.stop();
});

test("inbound event with broadcast source does NOT re-broadcast outward", () => {
  channelRegistry.clear();
  const tabA = makeTab();
  const tabB = makeTab();

  // Spy on tabB's outbound by counting messages received by a third tab.
  const tabC = makeTab();
  const tabCReceived: LupinEvent<unknown>[] = [];
  tabC.bus.on("auth_state_change", (e) => tabCReceived.push(e));

  // tabA emits → tabB receives + tabC receives. Then tabB sees the inbound
  // event with source: "broadcast" — it must NOT re-emit to its peers.
  // If tabB were re-broadcasting, tabC would receive it twice.
  tabA.bus.emit(evt("auth_state_change", { state: "ready" }, "AuthManager"));

  assert.equal(tabCReceived.length, 1, "exactly one delivery; no re-broadcast loop");

  tabA.wrapper.stop();
  tabB.wrapper.stop();
  tabC.wrapper.stop();
});

test("stop() detaches from EventBus and closes channel", () => {
  channelRegistry.clear();
  const tabA = makeTab();
  const tabB = makeTab();

  const tabBReceived: LupinEvent<unknown>[] = [];
  tabB.bus.on("auth_state_change", (e) => tabBReceived.push(e));

  tabA.wrapper.stop();

  // After stop, tabA emit should NOT reach tabB.
  tabA.bus.emit(evt("auth_state_change", { state: "ready" }, "AuthManager"));
  assert.equal(tabBReceived.length, 0);

  tabB.wrapper.stop();
});

test("start() is idempotent", () => {
  channelRegistry.clear();
  const tabA = makeTab(); // already started by makeTab
  const tabB = makeTab();

  tabA.wrapper.start(); // should be a no-op
  tabA.wrapper.start();

  const tabBReceived: LupinEvent<unknown>[] = [];
  tabB.bus.on("auth_state_change", (e) => tabBReceived.push(e));

  tabA.bus.emit(evt("auth_state_change", { state: "ready" }, "AuthManager"));

  // Despite multiple start() calls, only one delivery should happen.
  assert.equal(tabBReceived.length, 1);

  tabA.wrapper.stop();
  tabB.wrapper.stop();
});

test("malformed inbound message is ignored", () => {
  channelRegistry.clear();
  const tabA = makeTab();
  const tabB = makeTab();

  const tabBReceived: LupinEvent<unknown>[] = [];
  tabB.bus.on("auth_state_change", (e) => tabBReceived.push(e));

  // Emulate a malformed cross-tab message arriving at tab B.
  const peers = channelRegistry.get("lupin");
  // Find tabA's channel and post a non-LupinEvent shape.
  for (const peer of peers ?? []) {
    if (peer !== (tabB as unknown as { wrapper: { channel: MockChannel } }).wrapper.channel) {
      peer.postMessage({ garbage: true });
      break;
    }
  }

  assert.equal(tabBReceived.length, 0);

  tabA.wrapper.stop();
  tabB.wrapper.stop();
});

test("default channel factory uses globalThis.BroadcastChannel (Node 18+ native)", () => {
  // Validate the production fallback path: when no channelFactory is passed,
  // the wrapper uses globalThis.BroadcastChannel directly. Node 22 exposes it
  // as a global so this verifies the factory wires up cleanly.
  const bus = createEventBusForTesting();
  const wrapper = createBroadcastWrapper({ bus });
  // Don't actually post — just verify start/stop work without throwing,
  // proving defaultChannelFactory was successfully invoked.
  wrapper.start();
  wrapper.stop();
});

test("BROADCAST_WHITELIST contains the documented Phase 2 + Phase 3 entries", () => {
  // Sanity: the static whitelist matches the design's enumerated set.
  const expected: LupinEventType[] = [
    "auth_state_change",
    "notification_received",
    "voice_persona_assigned",
    "voice_persona_released",
    "speakerphone_change",
  ];
  for (const t of expected) assert.ok(BROADCAST_WHITELIST.has(t), `whitelist contains ${t}`);
  assert.equal(BROADCAST_WHITELIST.size, expected.length);
});
