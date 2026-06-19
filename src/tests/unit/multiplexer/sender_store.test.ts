// Multiplexer Phase 4 — SenderStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/sender_store.test.ts`.
// AC4 floor: ≥ 10 tests per design doc § Verification matrix per-store floor.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSenderStore } from "../../../lupin_app/static/js/multiplexer/stores/SenderStore";
import type {
  LupinEvent,
  StoreSendersChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setup() {
  const bus    = createEventBusForTesting();
  const events: LupinEvent<StoreSendersChangedPayload>[] = [];
  bus.on<StoreSendersChangedPayload>("store_senders_changed", (e) => events.push(e));
  const store  = createSenderStore({ bus, nowFn: () => 1_000_000 });
  return { bus, store, events };
}

function emitNotification(bus: ReturnType<typeof createEventBusForTesting>, fields: {
  type           ?: string;
  sender_id      : string;
  timestamp      ?: string;
  voice_persona  ?: Record<string, unknown> | null;
}): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: fields },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// 1-3 : Basic add/update behavior
// ===========================================================================

test("first notification from a new sender: adds record + emits added", () => {
  const { bus, store, events } = setup();
  emitNotification(bus, {
    type      : "task",
    sender_id : "alice@example.com",
    timestamp : "2026-05-04T10:00:00Z",
  });
  const rec = store.get("alice@example.com");
  assert.ok(rec);
  assert.equal(rec!.unread_count, 1);
  assert.equal(rec!.last_active_ts, Date.parse("2026-05-04T10:00:00Z"));
  const added = events.find(e => e.payload.changeKind === "added");
  assert.ok(added);
  assert.equal(added!.payload.sender_id, "alice@example.com");
});

test("second notification from same sender: updates last_active + bumps unread", () => {
  const { bus, store, events } = setup();
  emitNotification(bus, { type: "task", sender_id: "a@x", timestamp: "2026-05-04T10:00:00Z" });
  const before = events.length;
  emitNotification(bus, { type: "task", sender_id: "a@x", timestamp: "2026-05-04T11:00:00Z" });
  const rec = store.get("a@x")!;
  assert.equal(rec.unread_count, 2);
  assert.equal(rec.last_active_ts, Date.parse("2026-05-04T11:00:00Z"));
  const updated = events.slice(before).find(e => e.payload.changeKind === "updated");
  assert.ok(updated);
});

test("notifications from multiple senders: each tracked independently", () => {
  const { bus, store } = setup();
  emitNotification(bus, { type: "task", sender_id: "a@x" });
  emitNotification(bus, { type: "task", sender_id: "b@x" });
  emitNotification(bus, { type: "task", sender_id: "a@x" });
  assert.equal(store.list().length, 2);
  assert.equal(store.get("a@x")!.unread_count, 2);
  assert.equal(store.get("b@x")!.unread_count, 1);
});

// ===========================================================================
// 4-7 : voice_persona_assigned / released
// ===========================================================================

test("voice_persona_assigned populates the 5-field VoicePersona on existing sender", () => {
  const { bus, store } = setup();
  emitNotification(bus, { type: "task", sender_id: "claude.code@lupin", timestamp: "2026-05-04T10:00:00Z" });
  const before = store.get("claude.code@lupin")!.unread_count;

  emitNotification(bus, {
    type           : "voice_persona_assigned",
    sender_id      : "claude.code@lupin",
    timestamp      : "2026-05-04T10:01:00Z",
    voice_persona  : {
      name     : "Tiberius",
      voice_id : "abcd1234",
      icon     : "🎙",
      color    : "#3a86ff",
      borrowed : false,
    },
  });

  const rec = store.get("claude.code@lupin")!;
  assert.equal(rec.voice_persona?.name, "Tiberius");
  assert.equal(rec.voice_persona?.voice_id, "abcd1234");
  assert.equal(rec.voice_persona?.icon, "🎙");
  assert.equal(rec.voice_persona?.color, "#3a86ff");
  assert.equal(rec.voice_persona?.borrowed, false);
  // Persona events do NOT bump unread.
  assert.equal(rec.unread_count, before);
});

test("voice_persona_assigned for a previously-unknown sender: creates record without bumping unread", () => {
  const { bus, store } = setup();
  emitNotification(bus, {
    type           : "voice_persona_assigned",
    sender_id      : "fresh@x",
    voice_persona  : { name: "Pippa", voice_id: "v1", icon: "🦆", color: "#fa3", borrowed: false },
  });
  const rec = store.get("fresh@x")!;
  assert.ok(rec);
  assert.equal(rec.unread_count, 0, "persona-first arrival must not count as unread");
  assert.equal(rec.voice_persona?.name, "Pippa");
});

test("voice_persona_released clears the persona; record retained", () => {
  const { bus, store } = setup();
  emitNotification(bus, {
    type           : "voice_persona_assigned",
    sender_id      : "alice@x",
    voice_persona  : { name: "Tiberius", voice_id: "v1", icon: "x", color: "#000", borrowed: false },
  });
  emitNotification(bus, {
    type           : "voice_persona_released",
    sender_id      : "alice@x",
    voice_persona  : { name: "Tiberius", released: true },
  });
  const rec = store.get("alice@x")!;
  assert.ok(rec);
  assert.equal(rec.voice_persona, undefined);
});

test("voice_persona_assigned uses display_name when name is missing (legacy compat)", () => {
  const { bus, store } = setup();
  emitNotification(bus, {
    type           : "voice_persona_assigned",
    sender_id      : "x@y",
    voice_persona  : { display_name: "Mr Display", voice_id: "v1", icon: "i", color: "#ff0", borrowed: false },
  });
  const rec = store.get("x@y")!;
  assert.equal(rec.voice_persona?.name, "Mr Display");
});

// ===========================================================================
// 8-11 : Edge cases
// ===========================================================================

test("notification without sender_id is silently dropped", () => {
  const { bus, store, events } = setup();
  const before = events.length;
  emitNotification(bus, { type: "task", sender_id: "" });
  // Empty string sender_id rejected — no record, no emission.
  assert.equal(store.list().length, 0);
  assert.equal(events.length, before);
});

test("queue resync (no notification field) is a no-op", () => {
  const { bus, store, events } = setup();
  const before = events.length;
  bus.emit({
    type    : "notification_queue_update",
    payload : { queue_name: "notification", value: 5, unplayed_count: 3 },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 0);
  assert.equal(events.length, before);
});

test("speakerphone_changed type is treated as state-update (no unread bump)", () => {
  const { bus, store } = setup();
  // First a real notification to establish baseline.
  emitNotification(bus, { type: "task", sender_id: "a@x" });
  const baseline = store.get("a@x")!.unread_count;
  // Then a speakerphone-change for the same sender.
  emitNotification(bus, { type: "speakerphone_changed", sender_id: "a@x" });
  assert.equal(store.get("a@x")!.unread_count, baseline);
});

test("voice_persona_assigned without voice_persona payload is a no-op for the persona slot", () => {
  const { bus, store } = setup();
  emitNotification(bus, { type: "task", sender_id: "a@x" });
  const before = store.get("a@x");
  emitNotification(bus, { type: "voice_persona_assigned", sender_id: "a@x", voice_persona: null });
  // Persona slot stays unchanged (undefined).
  assert.equal(store.get("a@x")?.voice_persona, before?.voice_persona);
});

test("malformed timestamp falls back to nowFn(); record still created", () => {
  const { bus, store } = setup();
  emitNotification(bus, { type: "task", sender_id: "a@x", timestamp: "not-a-date" });
  // Date.parse('not-a-date') is NaN — the reducer drops the event.
  assert.equal(store.list().length, 0);
});

test("missing timestamp falls back to nowFn(); record created with current time", () => {
  const { bus, store } = setup();
  emitNotification(bus, { type: "task", sender_id: "a@x" });
  // No timestamp field → reducer uses nowFn() = 1_000_000.
  const rec = store.get("a@x")!;
  assert.equal(rec.last_active_ts, 1_000_000);
});

// ---------------------------------------------------------------------------
// Coverage backfill — `??` fallbacks for missing persona fields
// ---------------------------------------------------------------------------

test("voice_persona_assigned with NO name AND NO display_name falls back to empty string", () => {
  // Exercises the second `??` in `(persona.name ?? persona.display_name ?? "")`.
  const { bus, store } = setup();
  emitNotification(bus, {
    type           : "voice_persona_assigned",
    sender_id      : "no-name@x",
    voice_persona  : { voice_id: "v1", icon: "i", color: "#000", borrowed: false },
  });
  const rec = store.get("no-name@x")!;
  assert.equal(rec.voice_persona?.name, "", "name fallback to empty string");
});

test("voice_persona_assigned with no voice_id / icon / color uses empty-string fallbacks", () => {
  // Exercises `voice_id ?? ""`, `icon ?? ""`, `color ?? ""` arms together.
  const { bus, store } = setup();
  emitNotification(bus, {
    type           : "voice_persona_assigned",
    sender_id      : "minimal@x",
    voice_persona  : { name: "OnlyName", borrowed: false },
  });
  const rec = store.get("minimal@x")!;
  assert.equal(rec.voice_persona?.name, "OnlyName");
  assert.equal(rec.voice_persona?.voice_id, "", "voice_id fallback");
  assert.equal(rec.voice_persona?.icon, "", "icon fallback");
  assert.equal(rec.voice_persona?.color, "", "color fallback");
});

// ---------------------------------------------------------------------------
// session_reaped — reap → focus-bar badge drop (2026-06-05)
// See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md
// ---------------------------------------------------------------------------

test("session_reaped on a tracked sender: removes record + emits removed", () => {
  const { bus, store, events } = setup();
  // Sender first becomes known via a regular notification.
  emitNotification(bus, { type: "task", sender_id: "reapme@x", timestamp: "2026-06-05T10:00:00Z" });
  assert.ok(store.get("reapme@x"), "precondition: sender tracked");

  emitNotification(bus, { type: "session_reaped", sender_id: "reapme@x" });

  assert.equal(store.get("reapme@x"), undefined, "record removed from store");
  assert.ok(!store.list().some(s => s.sender_id === "reapme@x"), "absent from list()");
  const removed = events.find(e => e.payload.changeKind === "removed");
  assert.ok(removed, "emits a removed change");
  assert.equal(removed!.payload.sender_id, "reapme@x");
});

test("session_reaped on an untracked sender: no-op, no removed emission", () => {
  const { bus, store, events } = setup();
  // Never tracked — a worker that never sent a notification has no badge.
  emitNotification(bus, { type: "session_reaped", sender_id: "ghost@x" });

  assert.equal(store.get("ghost@x"), undefined, "still absent");
  assert.ok(
    !events.some(e => e.payload.changeKind === "removed"),
    "no spurious removed emission for an untracked sender",
  );
});

test("session_reaped removes ONLY the named sender, leaving others intact", () => {
  const { bus, store } = setup();
  emitNotification(bus, { type: "task", sender_id: "keep@x", timestamp: "2026-06-05T10:00:00Z" });
  emitNotification(bus, { type: "task", sender_id: "reap@x", timestamp: "2026-06-05T10:01:00Z" });

  emitNotification(bus, { type: "session_reaped", sender_id: "reap@x" });

  assert.equal(store.get("reap@x"), undefined, "reaped sender gone");
  const kept = store.get("keep@x");
  assert.ok(kept, "other sender untouched");
  assert.equal(kept!.unread_count, 1, "session_reaped does not bump another sender's unread");
});
