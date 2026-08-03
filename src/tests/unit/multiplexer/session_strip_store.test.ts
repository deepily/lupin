// Multiplexer WP2 (parity bridge) — SessionStripStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/session_strip_store.test.ts`.
//
// Coverage target: 100% lines + branches + functions (Lupin-wide mandate).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSessionStripStore } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type {
  LupinEvent,
  StoreSessionStripChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setup() {
  const bus    = createEventBusForTesting();
  const events: LupinEvent<StoreSessionStripChangedPayload>[] = [];
  bus.on<StoreSessionStripChangedPayload>("store_session_strip_changed", (e) => events.push(e));
  const store  = createSessionStripStore({ bus, nowFn: () => 1_000_000 });
  return { bus, store, events };
}

function emit(bus: ReturnType<typeof createEventBusForTesting>, fields: {
  type          ?: string;
  sender_id     ?: string;
  timestamp     ?: string;
  voice_persona ?: Record<string, unknown> | null;
  payload       ?: Record<string, unknown> | null;
}): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: fields },
    source  : "test",
    ts      : 0,
  });
}

const PERSONA = {
  name        : "Krishna",
  voice_id    : "vid-1",
  icon        : "🦚",
  color       : "#1DE9B6",
  assigned_at : "2026-06-10T14:28:34Z",
};

const MANAGER = { name: "Tiberius", icon: "👑", color: "#FFD700" };

// ===========================================================================
// 1-4 : voice_persona_assigned — add path
// ===========================================================================

test("voice_persona_assigned from a new sender: adds record + emits added", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  const rec = store.get("s1");
  assert.ok(rec);
  assert.equal(rec!.active, true);
  assert.equal(rec!.voice_persona.name, "Krishna");
  assert.equal(rec!.voice_persona.voice_id, "vid-1");
  assert.equal(rec!.voice_persona.icon, "🦚");
  assert.equal(rec!.voice_persona.color, "#1DE9B6");
  assert.equal(rec!.voice_persona.borrowed, false);
  assert.equal(rec!.assigned_at, Date.parse("2026-06-10T14:28:34Z"));
  assert.equal(rec!.manager_persona, undefined);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "added");
  assert.equal(events[0]!.payload.sender_id, "s1");
});

test("voice_persona_assigned with manager_persona: populates lineage", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA, payload: { manager_persona: MANAGER } });
  const rec = store.get("s1")!;
  assert.deepEqual(rec.manager_persona, { name: "Tiberius", icon: "👑", color: "#FFD700" });
});

test("voice_persona name falls back to display_name then empty; borrowed=true honored", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "dn", voice_persona: { display_name: "Rio", borrowed: true } });
  emit(bus, { type: "voice_persona_assigned", sender_id: "empty", voice_persona: { } });
  assert.equal(store.get("dn")!.voice_persona.name, "Rio");
  assert.equal(store.get("dn")!.voice_persona.borrowed, true);
  const empty = store.get("empty")!.voice_persona;
  assert.equal(empty.name, "");
  assert.equal(empty.voice_id, "");
  assert.equal(empty.icon, "");
  assert.equal(empty.color, "");
  assert.equal(empty.borrowed, false);
});

test("manager_persona fields default to empty strings when absent", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA, payload: { manager_persona: { } } });
  assert.deepEqual(store.get("s1")!.manager_persona, { name: "", icon: "", color: "" });
});

// ===========================================================================
// 5-7 : assigned_at parsing
// ===========================================================================

test("assigned_at missing → falls back to nowFn", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: { name: "X" } });
  assert.equal(store.get("s1")!.assigned_at, 1_000_000);
});

test("assigned_at unparseable → falls back to nowFn", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: { name: "X", assigned_at: "not-a-date" } });
  assert.equal(store.get("s1")!.assigned_at, 1_000_000);
});

test("assigned_at parseable → parsed ms", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: { name: "X", assigned_at: "2026-01-02T03:04:05Z" } });
  assert.equal(store.get("s1")!.assigned_at, Date.parse("2026-01-02T03:04:05Z"));
});

// ===========================================================================
// 8-11 : re-assignment (update path)
// ===========================================================================

test("re-assign existing sender: emits updated, keeps original assigned_at, refreshes persona", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  const firstAssignedAt = store.get("s1")!.assigned_at;
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: { name: "Rio", color: "#fff", assigned_at: "2027-01-01T00:00:00Z" } });
  const rec = store.get("s1")!;
  assert.equal(rec.voice_persona.name, "Rio");
  assert.equal(rec.voice_persona.color, "#fff");
  assert.equal(rec.assigned_at, firstAssignedAt);   // anchor preserved
  assert.equal(rec.active, true);
  assert.equal(events.length, 2);
  assert.equal(events[1]!.payload.changeKind, "updated");
});

test("re-assign reactivates a released session", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  emit(bus, { type: "voice_persona_released", sender_id: "s1" });
  assert.equal(store.get("s1")!.active, false);
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  assert.equal(store.get("s1")!.active, true);
});

test("re-assign adds a manager that was previously absent", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  assert.equal(store.get("s1")!.manager_persona, undefined);
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA, payload: { manager_persona: MANAGER } });
  assert.deepEqual(store.get("s1")!.manager_persona, MANAGER);
});

test("re-assign clears a manager that was previously present", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA, payload: { manager_persona: MANAGER } });
  assert.deepEqual(store.get("s1")!.manager_persona, MANAGER);
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  assert.equal(store.get("s1")!.manager_persona, undefined);
});

// ===========================================================================
// 12-14 : voice_persona_released
// ===========================================================================

test("release flips active false + emits updated (persona retained for display)", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  emit(bus, { type: "voice_persona_released", sender_id: "s1" });
  const rec = store.get("s1")!;
  assert.equal(rec.active, false);
  assert.equal(rec.voice_persona.name, "Krishna");   // retained
  assert.equal(events[1]!.payload.changeKind, "updated");
});

test("release on already-inactive session: no spurious emit", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  emit(bus, { type: "voice_persona_released", sender_id: "s1" });
  const count = events.length;
  emit(bus, { type: "voice_persona_released", sender_id: "s1" });
  assert.equal(events.length, count);
});

test("release on unknown sender: no-op", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_released", sender_id: "ghost" });
  assert.equal(store.get("ghost"), undefined);
  assert.equal(events.length, 0);
});

// ===========================================================================
// 15-16 : session_reaped
// ===========================================================================

test("reap removes the session + emits removed", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  emit(bus, { type: "session_reaped", sender_id: "s1" });
  assert.equal(store.get("s1"), undefined);
  assert.equal(events[1]!.payload.changeKind, "removed");
});

test("reap on unknown sender: no-op", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "session_reaped", sender_id: "ghost" });
  assert.equal(events.length, 0);
});

// ===========================================================================
// 17-22 : ignore / guard branches
// ===========================================================================

test("missing notification branch: ignored", () => {
  const { bus, store } = setup();
  bus.emit({ type: "notification_queue_update", payload: {}, source: "test", ts: 0 });
  assert.equal(store.list().length, 0);
});

test("missing sender_id: ignored", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", voice_persona: PERSONA });
  assert.equal(store.list().length, 0);
});

test("type not in strip set (regular notification): ignored", () => {
  const { bus, store } = setup();
  emit(bus, { type: "task", sender_id: "s1" });
  assert.equal(store.list().length, 0);
});

test("conversation-mode events are ignored by the strip store", () => {
  const { bus, store } = setup();
  emit(bus, { type: "speakerphone_changed", sender_id: "s1", payload: { on: true } });
  assert.equal(store.list().length, 0);
});

test("missing type: ignored", () => {
  const { bus, store } = setup();
  emit(bus, { sender_id: "s1", voice_persona: PERSONA });
  assert.equal(store.list().length, 0);
});

test("assigned with null persona: ignored", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: null });
  assert.equal(store.get("s1"), undefined);
});

test("assigned with released:true persona: ignored", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: { name: "X", released: true } });
  assert.equal(store.get("s1"), undefined);
});

test("assigned with payload present but manager_persona null: no lineage", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA, payload: { manager_persona: null } });
  assert.equal(store.get("s1")!.manager_persona, undefined);
});

// ===========================================================================
// 23 : list()
// ===========================================================================

test("list() returns every tracked session", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "a", voice_persona: PERSONA });
  emit(bus, { type: "voice_persona_assigned", sender_id: "b", voice_persona: PERSONA });
  assert.equal(store.list().length, 2);
  const ids = store.list().map(s => s.sender_id).sort();
  assert.deepEqual(ids, ["a", "b"]);
});

// ===========================================================================
// WP9 — hydrate() cold-reload bulk load
// ===========================================================================

test("hydrate creates sessions from records + emits a single id-less 'hydrated'", () => {
  const { store, events } = setup();
  store.hydrate([
    { sender_id: "s1", voice_persona: PERSONA, manager_persona: MANAGER },
    { sender_id: "s2", voice_persona: { name: "Rio", color: "#fff", assigned_at: "2026-06-10T10:00:00Z" } },
  ]);
  assert.equal(store.list().length, 2);
  const s1 = store.get("s1")!;
  assert.equal(s1.active, true);
  assert.equal(s1.voice_persona.name, "Krishna");
  assert.deepEqual(s1.manager_persona, MANAGER);
  assert.equal(s1.assigned_at, Date.parse("2026-06-10T14:28:34Z"));
  assert.equal(store.get("s2")!.manager_persona, undefined);
  // exactly one emission, changeKind hydrated, no sender_id
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
  assert.equal(events[0]!.payload.sender_id, undefined);
});

test("hydrate skips records without a persona, without a sender_id, or released", () => {
  const { store, events } = setup();
  store.hydrate([
    { sender_id: "no-persona" },
    { sender_id: "null-persona", voice_persona: null },
    { voice_persona: PERSONA },                                  // no sender_id
    { sender_id: "released", voice_persona: { name: "X", released: true } },
    { sender_id: "good", voice_persona: PERSONA },
  ]);
  assert.equal(store.list().length, 1);
  assert.ok(store.get("good"));
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
});

test("hydrate merges idempotently with sessions already present from live events", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  const firstAssignedAt = store.get("s1")!.assigned_at;
  store.hydrate([
    { sender_id: "s1", voice_persona: { name: "Rio", color: "#222", assigned_at: "2027-01-01T00:00:00Z" }, manager_persona: MANAGER },
    { sender_id: "s2", voice_persona: PERSONA },
  ]);
  assert.equal(store.list().length, 2);            // no duplicate s1
  const s1 = store.get("s1")!;
  assert.equal(s1.voice_persona.name, "Rio");      // refreshed
  assert.deepEqual(s1.manager_persona, MANAGER);   // lineage added
  assert.equal(s1.assigned_at, firstAssignedAt);   // chronological anchor preserved
});

test("hydrate with an empty snapshot emits 'hydrated' and tracks nothing", () => {
  const { store, events } = setup();
  store.hydrate([]);
  assert.equal(store.list().length, 0);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
});

// ===========================================================================
// reconcile() — reconnect-path prune (bug 0b2783ef, option 1)
//
// The additive `hydrate` never removes; a stale reaped card (whose live
// `session_reaped` was missed while the WS was down) therefore survives every
// reconnect re-hydrate and clears only on a full page refresh. `reconcile` is
// hydrate PLUS a prune of the sessions the snapshot AUTHORITATIVELY reports as
// persona-less (present-with-null/released persona) — leaving sessions ABSENT
// from the snapshot (a live-assigned-not-yet-persisted session) untouched, so
// the additive/live-event safety is preserved. Confined to the reconnect path;
// cold-boot `hydrate` stays additive.
// ===========================================================================

test("reconcile upserts persona-carrying records exactly like hydrate", () => {
  const { store, events } = setup();
  store.reconcile([
    { sender_id: "s1", voice_persona: PERSONA, manager_persona: MANAGER },
    { sender_id: "s2", voice_persona: { name: "Rio", color: "#fff", assigned_at: "2026-06-10T10:00:00Z" } },
  ]);
  assert.equal(store.list().length, 2);
  assert.deepEqual(store.get("s1")!.manager_persona, MANAGER);
  assert.equal(store.get("s2")!.voice_persona.name, "Rio");
  assert.equal(events[events.length - 1]!.payload.changeKind, "hydrated");
});

test("reconcile PRUNES a session the snapshot INCLUDES with null persona (missed reap)", () => {
  const { bus, store, events } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA, payload: { manager_persona: MANAGER } });
  const before = events.length;
  store.reconcile([{ sender_id: "s1", voice_persona: null }]);   // server: s1 has no persona now (reaped)
  assert.equal(store.get("s1"), undefined);                      // stale M-badged card pruned
  const emitted = events.slice(before).map(e => e.payload.changeKind);
  assert.ok(emitted.includes("removed"));                        // focus-auto-exit parity with live reap
  const removed = events.slice(before).find(e => e.payload.changeKind === "removed")!;
  assert.equal(removed.payload.sender_id, "s1");
  assert.equal(events[events.length - 1]!.payload.changeKind, "hydrated");
});

test("reconcile PRUNES a released-but-alive session that is null in the snapshot (matches refresh)", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  emit(bus, { type: "voice_persona_released", sender_id: "s1" });   // active=false, icon retained
  assert.equal(store.get("s1")!.active, false);
  store.reconcile([{ sender_id: "s1", voice_persona: null }]);
  assert.equal(store.get("s1"), undefined);                        // pruned — reconnect now matches refresh
});

test("reconcile does NOT prune a session ABSENT from the snapshot (live-assigned, not yet persisted)", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  store.reconcile([]);                                             // snapshot doesn't mention s1 yet
  assert.ok(store.get("s1"));                                      // additive/live-event safety preserved
});

test("reconcile keeps a session present WITH a persona (upsert, not prune)", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  store.reconcile([{ sender_id: "s1", voice_persona: { name: "Rio", color: "#222", assigned_at: "2027-01-01T00:00:00Z" } }]);
  assert.ok(store.get("s1"));
  assert.equal(store.get("s1")!.voice_persona.name, "Rio");       // refreshed, not pruned
});

test("reconcile emits no 'removed' for a null-persona sender that was never tracked", () => {
  const { store, events } = setup();
  store.reconcile([{ sender_id: "ghost", voice_persona: null }]);  // not in store
  const kinds = events.map(e => e.payload.changeKind);
  assert.ok(!kinds.includes("removed"));                           // no spurious removed
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
});

test("reconcile with a released:true persona prunes a tracked session (released leg of the null branch)", () => {
  const { bus, store } = setup();
  emit(bus, { type: "voice_persona_assigned", sender_id: "s1", voice_persona: PERSONA });
  store.reconcile([{ sender_id: "s1", voice_persona: { name: "X", released: true } }]);
  assert.equal(store.get("s1"), undefined);
});

test("reconcile skips a record without a sender_id", () => {
  const { store, events } = setup();
  store.reconcile([{ voice_persona: null }]);                      // no sender_id → skipped entirely
  assert.equal(store.list().length, 0);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
});

test("reconcile with an empty snapshot emits 'hydrated' and prunes nothing", () => {
  const { store, events } = setup();
  store.reconcile([]);
  assert.equal(store.list().length, 0);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "hydrated");
});
