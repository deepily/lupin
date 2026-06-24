// Multiplexer cold-load hydration (2026-06-11) — SenderStore.hydrate unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/sender_store_hydrate.test.ts`.
//
// Design: src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md
// (§2 step 1: never-regress merge, single "hydrated" emission).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSenderStore } from "../../../lupin_app/static/js/multiplexer/stores/SenderStore";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type {
  LupinEvent,
  StoreSendersChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

const NOW_MS = Date.parse("2026-06-11T22:00:00Z");

function setup() {
  const bus    = createEventBusForTesting();
  const events: LupinEvent<StoreSendersChangedPayload>[] = [];
  bus.on<StoreSendersChangedPayload>("store_senders_changed", (e) => events.push(e));
  const store  = createSenderStore({ bus, nowFn: () => NOW_MS });
  return { bus, store, events };
}

function makeRec(over: Partial<ServerSenderHydrationRecord> = {}): ServerSenderHydrationRecord {
  return {
    sender_id     : "ext-sender",
    last_activity : "2026-06-11T21:00:00Z",
    count         : 3,
    new_count     : 2,
    voice_persona : null,
    ...over,
  };
}

function emitLiveNotification(bus: ReturnType<typeof createEventBusForTesting>, senderId: string, iso: string): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { type: "task", sender_id: senderId, timestamp: iso, message: "m" } },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// Seeding new senders
// ===========================================================================

test("hydrate seeds a new sender: parsed activity, new_count as unread, conv-mode off, persona-less stays persona-less", () => {
  const { store } = setup();
  store.hydrate([makeRec()]);
  const rec = store.get("ext-sender")!;
  assert.equal(rec.last_active_ts, Date.parse("2026-06-11T21:00:00Z"));
  assert.equal(rec.unread_count, 2);
  assert.equal(rec.conversation_mode_active, false);
  assert.equal(rec.display_name, "ext-sender");
  assert.equal(rec.voice_persona, undefined);
});

test("hydrate normalizes a server persona onto a new sender", () => {
  const { store } = setup();
  store.hydrate([makeRec({
    sender_id     : "cc-sender",
    voice_persona : { name: "Rachel", voice_id: "v1", icon: "🕊️", color: "#CE93D8", borrowed: true },
  })]);
  const rec = store.get("cc-sender")!;
  assert.deepEqual(rec.voice_persona, { name: "Rachel", voice_id: "v1", icon: "🕊️", color: "#CE93D8", borrowed: true });
});

test("released personas and missing sender_ids are skipped", () => {
  const { store } = setup();
  store.hydrate([
    makeRec({ sender_id: "released-one", voice_persona: { name: "X", released: true } }),
    makeRec({ sender_id: undefined }),
  ]);
  assert.equal(store.get("released-one")!.voice_persona, undefined);
  assert.equal(store.list().length, 1);
});

test("missing/unparseable last_activity seeds 0; missing/negative new_count seeds 0", () => {
  const { store } = setup();
  store.hydrate([
    makeRec({ sender_id: "no-activity", last_activity: undefined, new_count: undefined }),
    makeRec({ sender_id: "bad-activity", last_activity: "garbage", new_count: -3 }),
  ]);
  assert.equal(store.get("no-activity")!.last_active_ts, 0);
  assert.equal(store.get("no-activity")!.unread_count, 0);
  assert.equal(store.get("bad-activity")!.last_active_ts, 0);
  assert.equal(store.get("bad-activity")!.unread_count, 0);
});

// ===========================================================================
// Never-regress merge (live event arrived before the snapshot resolved)
// ===========================================================================

test("merge never regresses: newer live activity + higher live unread are kept", () => {
  const { bus, store } = setup();
  emitLiveNotification(bus, "ext-sender", "2026-06-11T21:30:00Z");
  emitLiveNotification(bus, "ext-sender", "2026-06-11T21:31:00Z");
  emitLiveNotification(bus, "ext-sender", "2026-06-11T21:32:00Z");   // unread now 3
  store.hydrate([makeRec({ new_count: 2, last_activity: "2026-06-11T21:00:00Z" })]);
  const rec = store.get("ext-sender")!;
  assert.equal(rec.last_active_ts, Date.parse("2026-06-11T21:32:00Z"));
  assert.equal(rec.unread_count, 3);
});

test("merge fills forward: snapshot newer than live raises activity + unread", () => {
  const { bus, store } = setup();
  emitLiveNotification(bus, "ext-sender", "2026-06-11T20:00:00Z");   // unread 1
  store.hydrate([makeRec({ new_count: 5, last_activity: "2026-06-11T21:45:00Z" })]);
  const rec = store.get("ext-sender")!;
  assert.equal(rec.last_active_ts, Date.parse("2026-06-11T21:45:00Z"));
  assert.equal(rec.unread_count, 5);
});

test("merge never clobbers a live-assigned persona", () => {
  const { bus, store } = setup();
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: {
      type          : "voice_persona_assigned",
      sender_id     : "cc-sender",
      timestamp     : "2026-06-11T21:00:00Z",
      voice_persona : { name: "Tiberius", voice_id: "vt", icon: "👑", color: "#3F51B5" },
    } },
    source : "test",
    ts     : 0,
  });
  store.hydrate([makeRec({
    sender_id     : "cc-sender",
    voice_persona : { name: "Stale", voice_id: "vs", icon: "❓", color: "#000000" },
  })]);
  assert.equal(store.get("cc-sender")!.voice_persona!.name, "Tiberius");
});

test("merge fills a persona onto an existing persona-less record", () => {
  const { bus, store } = setup();
  emitLiveNotification(bus, "cc-sender", "2026-06-11T21:00:00Z");
  assert.equal(store.get("cc-sender")!.voice_persona, undefined);
  store.hydrate([makeRec({
    sender_id     : "cc-sender",
    voice_persona : { name: "Rachel", voice_id: "v1", icon: "🕊️", color: "#CE93D8" },
  })]);
  assert.equal(store.get("cc-sender")!.voice_persona!.name, "Rachel");
});

// ===========================================================================
// Emission contract
// ===========================================================================

test("hydrate emits exactly ONE store_senders_changed{hydrated} with no sender_id, regardless of record count", () => {
  const { store, events } = setup();
  store.hydrate([makeRec({ sender_id: "a" }), makeRec({ sender_id: "b" }), makeRec({ sender_id: "c" })]);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
  assert.equal(events[0]!.payload.sender_id, undefined);
  assert.equal(events[0]!.source, "SenderStore");
});

test("hydrate of an empty snapshot still emits the single hydrated change", () => {
  const { store, events } = setup();
  store.hydrate([]);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
});

// ===========================================================================
// Worker-badge silencing — is_worker from rec.manager_persona (Rick 2026-06-24)
// Cold-load rows carry the manager lineage at `rec.manager_persona` (same field
// SessionStripStore hydrates from). Fill-forward only: set is_worker when the
// snapshot says "managed"; never clobber a live-set true back to false.
// ===========================================================================

test("hydrate sets is_worker=true when the snapshot row carries manager_persona", () => {
  const { store } = setup();
  store.hydrate([makeRec({
    sender_id       : "worker-cold",
    manager_persona : { name: "Tiberius", icon: "👑", color: "#3F51B5" },
  })]);
  assert.equal(store.get("worker-cold")!.is_worker, true);
});

test("hydrate leaves is_worker unset for a row with no manager_persona (root session)", () => {
  const { store } = setup();
  store.hydrate([makeRec({ sender_id: "root-cold" })]);
  assert.equal(store.get("root-cold")!.is_worker, undefined);
});

test("hydrate leaves is_worker unset when manager_persona is explicitly null", () => {
  const { store } = setup();
  store.hydrate([makeRec({ sender_id: "null-cold", manager_persona: null })]);
  assert.equal(store.get("null-cold")!.is_worker, undefined);
});

test("hydrate fills is_worker forward — never clobbers a live-set worker back to false", () => {
  const { bus, store } = setup();
  // Live voice_persona_assigned arrives FIRST with a manager → is_worker true.
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: {
      type          : "voice_persona_assigned",
      sender_id     : "race@x",
      timestamp     : "2026-06-11T21:00:00Z",
      voice_persona : { name: "Rio", voice_id: "v1", icon: "🎤", color: "#28a745" },
      payload       : { manager_persona: { name: "Tiberius", icon: "👑", color: "#3F51B5" } },
    } },
    source : "test",
    ts     : 0,
  });
  assert.equal(store.get("race@x")!.is_worker, true, "precondition: live-set worker");
  // A stale snapshot WITHOUT manager_persona must NOT regress the flag.
  store.hydrate([makeRec({ sender_id: "race@x" })]);
  assert.equal(store.get("race@x")!.is_worker, true, "fill-forward: stale snapshot does not clear it");
});
